import assert from "node:assert/strict";
import { test } from "node:test";
import { TabNavigation, parseEntry, type TabEntry } from "./navigation.ts";

function host(initial: unknown = null, channels = false) {
  const entries: unknown[] = [initial];
  let index = 0;
  const listeners = new Set<() => void>();
  const browser = {
    history: {
      get state() {
        return entries[index];
      },
      pushState(value: unknown) {
        entries.splice(++index);
        entries.push(value);
      },
      replaceState(value: unknown) {
        entries[index] = value;
      },
    },
    addEventListener(_event: string, listener: () => void) {
      listeners.add(listener);
    },
    removeEventListener(_event: string, listener: () => void) {
      listeners.delete(listener);
    },
    BroadcastChannel: channels ? BroadcastChannel : undefined,
  };
  return {
    browser: browser as unknown as Window & typeof globalThis,
    back() {
      if (index > 0) {
        index--;
        listeners.forEach((listener) => listener());
      }
    },
    forward() {
      if (index + 1 < entries.length) {
        index++;
        listeners.forEach((listener) => listener());
      }
    },
  };
}

test("fresh tabs start new, and history traversal and refresh preserve destinations", async () => {
  const page = host();
  let shown: TabEntry | undefined;
  const nav = new TabNavigation(page.browser, (entry) => {
    shown = entry;
  });
  await nav.initialize();
  assert.equal(shown?.destination.kind, "new");
  nav.go({ kind: "interview", id: "a" });
  nav.go({ kind: "interview", id: "b" });
  page.back();
  assert.deepEqual(shown?.destination, { kind: "interview", id: "a" });
  page.forward();
  assert.deepEqual(shown?.destination, { kind: "interview", id: "b" });
  nav.dispose();
  const refreshed = new TabNavigation(page.browser, (entry) => {
    shown = entry;
  });
  await refreshed.initialize();
  assert.deepEqual(shown?.destination, { kind: "interview", id: "b" });
  refreshed.dispose();
  const fresh = new TabNavigation(host().browser, () => {});
  assert.equal(fresh.current.destination.kind, "new");
  fresh.dispose();
});

test("start replaces its own opening entry and a late start leaves the current view alone", async () => {
  const page = host();
  const nav = new TabNavigation(page.browser, () => {});
  await nav.initialize();
  nav.go({ kind: "interview", id: "a" });
  nav.go({ kind: "new" });
  nav.started(nav.current.entry, "b");
  page.back();
  assert.deepEqual(nav.current.destination, { kind: "interview", id: "a" });
  nav.go({ kind: "new" });
  const origin = nav.current.entry;
  nav.go({ kind: "interview", id: "a" });
  nav.started(origin, "c");
  assert.deepEqual(nav.current.destination, { kind: "interview", id: "a" });
  page.back();
  assert.deepEqual(nav.current.destination, { kind: "interview", id: "c" });
  nav.dispose();
});

test("duplicate tabs reset their copied history while closed tabs restore it", async () => {
  const sourcePage = host(null, true);
  const source = new TabNavigation(sourcePage.browser, () => {});
  await source.initialize();
  source.go({ kind: "interview", id: "a" });
  const copied = structuredClone(source.current);
  const duplicate = new TabNavigation(host(copied, true).browser, () => {});
  await duplicate.initialize();
  assert.equal(duplicate.current.destination.kind, "new");
  assert.notEqual(duplicate.current.token, source.current.token);
  assert.deepEqual(source.current.destination, { kind: "interview", id: "a" });
  source.dispose();
  duplicate.dispose();
  const restored = new TabNavigation(host(copied, true).browser, () => {});
  await restored.initialize();
  assert.deepEqual(restored.current.destination, {
    kind: "interview",
    id: "a",
  });
  restored.dispose();
});

test("invalid history starts new and missing Interview IDs remain explicit destinations", () => {
  assert.equal(
    parseEntry({ metis: 1, destination: { kind: "interview" } }),
    undefined,
  );
  const nav = new TabNavigation(host({ obsolete: "a" }).browser, () => {});
  assert.equal(nav.current.destination.kind, "new");
  nav.go({ kind: "interview", id: "missing" });
  assert.deepEqual(nav.current.destination, {
    kind: "interview",
    id: "missing",
  });
  nav.dispose();
});
