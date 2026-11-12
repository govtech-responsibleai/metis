import assert from "node:assert/strict";
import { test } from "node:test";
import type { ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { Router } from "wouter";
import { ExperimentsTab, TargetTabs } from "./TargetPage";
import { TargetRail } from "./TargetRail";

function at(path: string, node: ReactNode): string {
  return renderToStaticMarkup(<Router ssrPath={path}>{node}</Router>);
}

function tab(markup: string, label: string): string {
  const found = [
    ...markup.matchAll(/<(a|button)[^>]*role="tab"[^>]*>(.*?)<\/\1>/g),
  ].find(([, , inner]) => inner === label);
  assert.ok(found, `no ${label} tab`);
  return found[0];
}

const text = (markup: string) => markup.replace(/<[^>]+>/g, "");

// The opening tag of the first link or button whose text starts with `label`. A Target row
// also shows its time.
function control(markup: string, label: string): string {
  const found = [...markup.matchAll(/(<(a|button)\b[^>]*>)(.*?)<\/\2>/g)].find(
    ([, , , inner]) => text(inner ?? "").startsWith(label),
  );
  assert.ok(found, `no ${label} control`);
  return found[1] ?? "";
}

const runButton = (markup: string) => control(markup, "Run");

const rail = (selected: Parameters<typeof TargetRail>[0]["selected"]) =>
  at(
    "/",
    <TargetRail
      targets={[
        { id: "a", title: "Bank bot", updated: Date.now() },
        { id: "b", title: "Shop bot", updated: Date.now() },
      ]}
      problems={[]}
      selected={selected}
      activeIds={new Set(["a"])}
      onNew={() => {}}
      onDelete={() => {}}
    />,
  );

test("the rail links New target, each Target, and All experiments", () => {
  const markup = rail(null);

  assert.match(control(markup, "New target"), /^<a[^>]*href="\/targets\/new"/);
  assert.match(control(markup, "Bank bot"), /^<a[^>]*href="\/targets\/a"/);
  assert.match(control(markup, "Shop bot"), /^<a[^>]*href="\/targets\/b"/);
  assert.match(
    control(markup, "All experiments"),
    /^<a[^>]*href="\/experiments"/,
  );
  assert.match(markup, /role="radiogroup" aria-label="Colour theme"/);
  assert.doesNotMatch(markup, /aria-current/);
});

test("All experiments shows no count", () => {
  control(rail(null), "All experiments");
});

test("the rail marks the selected Target or All experiments", () => {
  const target = rail({ kind: "target", id: "b" });
  assert.match(control(target, "Shop bot"), /aria-current="page"/);
  assert.doesNotMatch(control(target, "Bank bot"), /aria-current/);
  const experiments = rail({ kind: "experiments" });
  assert.match(control(experiments, "All experiments"), /aria-current="page"/);
  assert.doesNotMatch(control(experiments, "Shop bot"), /aria-current/);
});

test("a Target that is sending cannot be deleted", () => {
  const markup = rail(null);

  assert.match(markup, /aria-label="Delete Bank bot"[^>]*disabled=""/);
  assert.doesNotMatch(markup, /aria-label="Delete Shop bot"[^>]*disabled=""/);
});

test("Experiments and Run stay off until the Interview is done", () => {
  const markup = at(
    "/targets/a/specification",
    <TargetTabs
      targetId="a"
      tab="specification"
      done={false}
      onRun={() => {}}
    />,
  );

  assert.match(
    tab(markup, "Specification"),
    /href="\/targets\/a\/specification"/,
  );
  assert.match(tab(markup, "Specification"), /aria-selected="true"/);
  assert.match(tab(markup, "Experiments"), /disabled=""/);
  assert.match(
    tab(markup, "Experiments"),
    /title="Finish the Interview first"/,
  );
  assert.match(runButton(markup), /disabled=""/);
  assert.match(runButton(markup), /title="Finish the Interview first"/);
});

test("a done Interview turns on Experiments and Run", () => {
  const markup = at(
    "/targets/a/experiments",
    <TargetTabs targetId="a" tab="experiments" done onRun={() => {}} />,
  );

  assert.match(tab(markup, "Experiments"), /href="\/targets\/a\/experiments"/);
  assert.match(tab(markup, "Experiments"), /aria-selected="true"/);
  assert.match(tab(markup, "Specification"), /aria-selected="false"/);
  assert.doesNotMatch(runButton(markup), /disabled=""/);
});

test("a new Target shows its Specification tab with Experiments and Run off", () => {
  const markup = at(
    "/targets/new",
    <TargetTabs
      targetId={null}
      tab="specification"
      done={false}
      onRun={() => {}}
    />,
  );

  assert.match(tab(markup, "Specification"), /href="\/targets\/new"/);
  assert.match(tab(markup, "Experiments"), /disabled=""/);
  assert.match(runButton(markup), /disabled=""/);
});

test("an empty Experiments tab offers Run", () => {
  const markup = at("/", <ExperimentsTab onRun={() => {}} />);

  assert.match(markup, /No experiments yet\./);
  assert.match(runButton(markup), /^<button/);
});
