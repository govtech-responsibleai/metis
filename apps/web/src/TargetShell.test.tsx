import assert from "node:assert/strict";
import { test } from "node:test";
import { isValidElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { Router } from "wouter";
import { ComparePage } from "./ExperimentPages";
import {
  joinFailure,
  LoginPage,
  LoginSessionProvider,
  startsAtFirstPage,
} from "./LoginGate";
import { TransportError } from "./transport/api";
import { at, control, tab, text } from "./markup.test-helper";
import { ProfileToolbar } from "./ProfileToolbar";
import type { ListLoad, RowLoad } from "./ExperimentList";
import { ExperimentsTabView, TargetTabs } from "./TargetPage";
import {
  AccountMenuList,
  AppearanceRow,
  CollapsedRail,
  TargetRail,
} from "./TargetRail";
import { THEME_STORAGE_KEY, useThemeChoice } from "./theme";

const startButton = (markup: string) => control(markup, "Start an experiment");

const rail = (selectedId: string | null) =>
  at(
    "/",
    <TargetRail
      targets={[
        { id: "a", title: "Bank bot", updated: Date.now() },
        { id: "b", title: "Shop bot", updated: Date.now() },
      ]}
      problems={[]}
      selectedId={selectedId}
      activeIds={new Set(["a"])}
      onNew={() => {}}
      onDelete={() => {}}
    />,
  );

test("the rail links New target and each Target", () => {
  const markup = rail(null);

  assert.match(control(markup, "New target"), /^<a[^>]*href="\/targets\/new"/);
  assert.match(control(markup, "Bank bot"), /^<a[^>]*href="\/targets\/a"/);
  assert.match(control(markup, "Shop bot"), /^<a[^>]*href="\/targets\/b"/);
  assert.doesNotMatch(markup, /aria-current/);
});

test("with login off, the rail foot has the colour theme and no account menu", () => {
  const markup = rail(null);

  assert.match(markup, /role="radiogroup" aria-label="Colour theme"/);
  assert.deepEqual(
    [...markup.matchAll(/role="radio"[^>]*aria-label="(\w+)"/g)].map(
      ([, label]) => label,
    ),
    ["System", "Light", "Dark"],
  );
  assert.doesNotMatch(markup, /aria-haspopup="menu"/);
  assert.doesNotMatch(markup, /Log out/);
});

const otter = {
  id: "3f6c2a9d5b7e4c1e8a0f2d4b6c8e0a1c",
  username: "curious-otter",
  created_at: "2026-11-14T08:30:00Z",
  admin: false,
};

test("the rail shows the avatar and the name of the current user on a closed account menu button", () => {
  const markup = renderToStaticMarkup(
    <LoginSessionProvider value={{ user: otter, logout: () => {} }}>
      <Router ssrPath="/">
        <TargetRail
          targets={[]}
          problems={[]}
          selectedId={null}
          activeIds={new Set()}
          onNew={() => {}}
          onDelete={() => {}}
        />
        <CollapsedRail onExpand={() => {}} />
      </Router>
    </LoginSessionProvider>,
  );
  const [open, compact] = [
    ...markup.matchAll(
      /<button[^>]*aria-haspopup="menu"[^>]*>(.*?)<\/button>/g,
    ),
  ];

  assert.match(open?.[0] ?? "", /aria-expanded="false"/);
  assert.match(text(open?.[1] ?? ""), /^COcurious-otter$/);
  assert.equal(text(compact?.[1] ?? ""), "CO");
  assert.match(open?.[1] ?? "", /lucide-chevrons-up-down/);
  assert.match(
    compact?.[0] ?? "",
    /aria-label="Account menu of curious-otter"/,
  );
  assert.doesNotMatch(markup, /role="menu"/);
  assert.doesNotMatch(markup, /Log out/);
  assert.doesNotMatch(markup, /role="radio/);
});

test("the account menu shows the avatar and the username, then Manage accounts for an admin, Appearance, and Log out", () => {
  const menu = (admin: boolean) => {
    const markup = at(
      "/",
      <AccountMenuList
        session={{ user: { ...otter, admin }, logout: () => {} }}
        theme="dark"
        onTheme={() => {}}
        onClose={() => {}}
      />,
    );
    const rows = [
      ...markup.matchAll(
        /<(a|button)[^>]*role="menuitem"[^>]*>(.*?)<\/\1>|role="group" aria-label="(Appearance)"/g,
      ),
    ].map(([item, , inner, group]) => ({
      item,
      label: group ?? text(inner ?? ""),
    }));
    return { markup, rows };
  };

  const participant = menu(false);
  assert.match(
    participant.markup,
    /^<div[^>]*><p[^>]*><span[^>]*>CO<\/span><span[^>]*>curious-otter<\/span><\/p><div[^>]*role="menu"/,
  );
  assert.deepEqual(
    participant.rows.map(({ label }) => label),
    ["Appearance", "Log out"],
  );
  const options = [
    ...participant.markup.matchAll(/<button[^>]*role="menuitemradio"[^>]*>/g),
  ].map(([option]) => option);
  assert.deepEqual(
    options.map((option) => /aria-label="(\w+)"/.exec(option)?.[1]),
    ["System", "Light", "Dark"],
  );
  assert.deepEqual(
    options.map((option) => /aria-checked="(\w+)"/.exec(option)?.[1]),
    ["false", "false", "true"],
  );

  const admin = menu(true);
  assert.deepEqual(
    admin.rows.map(({ label }) => label),
    ["Manage accounts", "Appearance", "Log out"],
  );
  assert.match(admin.rows[0]?.item ?? "", /href="\/admin"/);
});

// The element of `node` that matches `found`, with each function component called to give its
// elements. It works only for components that use no hooks.
function elementIn(
  node: ReactNode,
  found: (props: Record<string, unknown>) => boolean,
): ReactElement<Record<string, unknown>> | undefined {
  if (Array.isArray(node)) {
    for (const child of node) {
      const match = elementIn(child as ReactNode, found);
      if (match) return match;
    }
    return undefined;
  }
  if (!isValidElement<Record<string, unknown>>(node)) return undefined;
  if (typeof node.type === "function") {
    return elementIn(
      (node.type as (props: unknown) => ReactNode)(node.props),
      found,
    );
  }
  if (found(node.props)) return node;
  return elementIn(node.props.children as ReactNode, found);
}

test("picking a theme in the account menu stores the theme choice", () => {
  const stored = new Map<string, string>();
  Object.assign(globalThis, {
    window: {
      localStorage: {
        getItem: (key: string) => stored.get(key) ?? null,
        setItem: (key: string, value: string) => stored.set(key, value),
        removeItem: (key: string) => stored.delete(key),
      },
    },
  });
  try {
    let row: ReactNode = null;
    function Menu() {
      const [choice, setChoice] = useThemeChoice();
      row = <AppearanceRow choice={choice} onChoose={setChoice} />;
      return null;
    }
    renderToStaticMarkup(<Menu />);
    const pick = (label: string) =>
      (
        elementIn(row, (props) => props["aria-label"] === label)?.props
          .onClick as () => void
      )();

    pick("Dark");
    assert.equal(stored.get(THEME_STORAGE_KEY), "dark");
    pick("Light");
    assert.equal(stored.get(THEME_STORAGE_KEY), "light");
    pick("System");
    assert.equal(stored.has(THEME_STORAGE_KEY), false);
  } finally {
    Reflect.deleteProperty(globalThis, "window");
  }
});

test("the login page asks for a username and a password", () => {
  const markup = renderToStaticMarkup(<LoginPage onLogin={() => {}} />);
  const inputs = [...markup.matchAll(/<input[^>]*>/g)].map(([input]) => input);

  assert.match(markup, /<h1[^>]*>Log in<\/h1>/);
  assert.equal(inputs.length, 3);
  assert.match(inputs[0] ?? "", /type="text"/);
  assert.match(inputs[0] ?? "", /autoComplete="username"/);
  assert.match(inputs[0] ?? "", /name="username"/);
  assert.match(inputs[1] ?? "", /type="password"/);
  assert.match(inputs[1] ?? "", /autoComplete="current-password"/);
  assert.match(markup, /<button[^>]*type="submit"[^>]*>Log in<\/button>/);
  assert.match(markup, /<button[^>]*aria-label="Show password"/);
  assert.doesNotMatch(markup, /role="alert"/);
});

test("the login page has a workshop join with a hidden token box", () => {
  const markup = renderToStaticMarkup(<LoginPage onLogin={() => {}} />);
  const token = [...markup.matchAll(/<input[^>]*>/g)][2]?.[0] ?? "";

  assert.match(markup, /<h2[^>]*>Joining a workshop\?<\/h2>/);
  assert.match(text(markup), /Enter the join token to create an account\./);
  assert.match(token, /aria-label="Workshop token"/);
  assert.match(token, /type="password"/);
  assert.match(token, /autoComplete="off"/);
  assert.match(markup, /<button[^>]*aria-label="Show token"/);
  assert.match(markup, /<button[^>]*type="submit"[^>]*>Join<\/button>/);
});

test("a failed join says that the join token is not correct", () => {
  assert.equal(
    joinFailure(new TransportError("x", { status: 401 })),
    "The join token is not correct. Try again.",
  );
  assert.equal(
    joinFailure(new TransportError("Couldn't reach the METIS API.")),
    "Couldn't reach the METIS API.",
  );
});

test("a login of a different user account starts at the first page", () => {
  assert.equal(startsAtFirstPage("alice", "bob"), true);
  assert.equal(startsAtFirstPage("alice", "alice"), false);
  assert.equal(startsAtFirstPage(null, "alice"), false);
});

test("the login page shows why a login failed", () => {
  const markup = renderToStaticMarkup(
    <LoginPage
      onLogin={() => {}}
      error="The username or the password is not correct."
    />,
  );

  assert.match(
    markup,
    /<p role="alert"[^>]*>The username or the password is not correct.<\/p>/,
  );
  assert.match(markup, /aria-invalid="true"/);
});

test("the rail marks the selected Target", () => {
  const target = rail("b");
  assert.match(control(target, "Shop bot"), /aria-current="page"/);
  assert.doesNotMatch(control(target, "Bank bot"), /aria-current/);
});

test("a Target that is sending cannot be deleted", () => {
  const markup = rail(null);

  assert.match(markup, /aria-label="Delete Bank bot"[^>]*disabled=""/);
  assert.doesNotMatch(markup, /aria-label="Delete Shop bot"[^>]*disabled=""/);
});

test("Experiments and the start button stay off until the Interview is done", () => {
  const markup = at(
    "/targets/a/specification",
    <TargetTabs
      targetId="a"
      tab="specification"
      done={false}
      onStartExperiment={() => {}}
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
  assert.match(startButton(markup), /disabled=""/);
  assert.match(startButton(markup), /title="Finish the Interview first"/);
});

test("a done Interview turns on Experiments and the start button", () => {
  const markup = at(
    "/targets/a/experiments",
    <TargetTabs
      targetId="a"
      tab="experiments"
      done
      onStartExperiment={() => {}}
    />,
  );

  assert.match(tab(markup, "Experiments"), /href="\/targets\/a\/experiments"/);
  assert.match(tab(markup, "Experiments"), /aria-selected="true"/);
  assert.match(tab(markup, "Specification"), /aria-selected="false"/);
  assert.doesNotMatch(startButton(markup), /disabled=""/);
});

test("a new Target shows its Specification tab with Experiments and the start button off", () => {
  const markup = at(
    "/targets/new",
    <TargetTabs
      targetId={null}
      tab="specification"
      done={false}
      onStartExperiment={() => {}}
    />,
  );

  assert.match(tab(markup, "Specification"), /href="\/targets\/new"/);
  assert.match(tab(markup, "Experiments"), /disabled=""/);
  assert.match(startButton(markup), /disabled=""/);
});

const toolbar = (done: boolean) =>
  renderToStaticMarkup(
    <ProfileToolbar
      mode="document"
      onMode={() => {}}
      done={done}
      busy={false}
      onDownload={() => {}}
    />,
  );

test("the Profile toolbar offers Download and the Document and YAML views", () => {
  const markup = toolbar(true);

  assert.match(markup, /role="radiogroup" aria-label="View"/);
  assert.match(control(markup, "Document"), /aria-checked="true"/);
  assert.match(control(markup, "YAML"), /aria-checked="false"/);
  assert.doesNotMatch(control(markup, "YAML"), /disabled=""/);
  assert.doesNotMatch(control(markup, "Download"), /disabled=""/);
});

test("the YAML view and Download wait for the end of the Interview", () => {
  const markup = toolbar(false);

  assert.match(control(markup, "YAML"), /disabled=""/);
  assert.match(control(markup, "YAML"), /title="Finish the Interview first"/);
  assert.match(control(markup, "Download"), /disabled=""/);
  assert.match(
    control(markup, "Download"),
    /title="Finish the Interview first"/,
  );
  assert.doesNotMatch(control(markup, "Document"), /disabled=""/);
});

const experimentsTab = (load: ListLoad) =>
  at("/targets/a/experiments", <ExperimentsTabView load={load} />);

const YEAR = new Date().getFullYear();
const local = (day: number, hour: number, minute: number, second = 0) =>
  new Date(YEAR, 0, day, hour, minute, second).toISOString();

const row = (experimentId: string, startedAt: string, load: RowLoad) => ({
  record: {
    experiment_id: experimentId,
    target_id: "a",
    started_at: startedAt,
    step: "simulate" as const,
  },
  load,
});

test("an empty Experiments tab says so", () => {
  assert.match(
    experimentsTab({ status: "ready", rows: [] }),
    /No experiments yet\./,
  );
});

test("the Experiments tab is a table of the newest start first, and each row links to its view", () => {
  const markup = experimentsTab({
    status: "ready",
    rows: [
      row("exp-stopped", local(5, 12, 0), {
        status: "ready",
        state: {
          kind: "stopped",
          progress: null,
          reason: "Timed out",
          resume: "resume-simulate",
        },
        updatedAt: local(5, 12, 4, 30),
      }),
      row("exp-failed", local(3, 9, 15), { status: "failed" }),
      row("exp-live", local(5, 14, 32, 5), {
        status: "ready",
        state: {
          kind: "simulating",
          stopping: false,
          progress: { phase: "simulating", ended: 5, total: 16 },
        },
        updatedAt: local(5, 14, 40, 9),
      }),
    ],
  });
  const headers = [...markup.matchAll(/<th\b([^>]*)>(.*?)<\/th>/g)].map(
    ([, attributes, inner]) => ({
      label: text(inner ?? ""),
      sort: /aria-sort="(\w+)"/.exec(attributes ?? "")?.[1],
      button: /<button/.test(inner ?? ""),
    }),
  );
  const rows = [
    ...(/<tbody>(.*)<\/tbody>/.exec(markup)?.[1] ?? "").matchAll(
      /<tr\b[^>]*>(.*?)<\/tr>/g,
    ),
  ].map(([, inner]) =>
    [...(inner ?? "").matchAll(/<td\b[^>]*>(.*?)<\/td>/g)].map(([, cell]) =>
      text(cell ?? ""),
    ),
  );

  assert.deepEqual(headers.slice(0, 5), [
    { label: "Experiment ID", sort: undefined, button: true },
    { label: "Started", sort: "descending", button: true },
    { label: "Last updated", sort: undefined, button: true },
    { label: "Status", sort: undefined, button: true },
    { label: "Progress", sort: undefined, button: false },
  ]);
  assert.deepEqual(rows, [
    [
      "exp-live",
      "5 Jan, 14:32:05",
      "5 Jan, 14:40:09",
      "Simulating",
      "5 of 16 simulated",
      "",
    ],
    ["exp-stopped", "5 Jan, 12:00:00", "5 Jan, 12:04:30", "Stopped", "", ""],
    ["exp-failed", "3 Jan, 09:15:00", "", "Status unavailable", "", ""],
  ]);
  const link = control(markup, "exp-live");
  assert.match(link, /href="\/targets\/a\/experiments\/exp-live"/);
  assert.match(link, /title="exp-live"/);
  assert.match(
    markup,
    new RegExp(
      `<time dateTime="${local(5, 14, 32, 5)}" title="(just now|\\d+ (min|h|d) ago)"`,
    ),
  );
});

test("the Experiments tab says when the list does not load", () => {
  const markup = experimentsTab({
    status: "failed",
    message: "Couldn't reach the METIS API.",
  });

  assert.match(markup, /role="alert"/);
  assert.match(text(markup), /Couldn&#x27;t reach the METIS API\./);
});

test("the comparison links back to its Target", () => {
  const markup = at(
    "/targets/a/compare",
    <ComparePage targetId="a" targetTitle="Bank bot" />,
  );

  assert.match(control(markup, "Bank bot"), /href="\/targets\/a\/experiments"/);
  assert.match(markup, /Compare experiments/);
});
