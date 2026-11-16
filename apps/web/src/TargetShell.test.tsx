import assert from "node:assert/strict";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { Router } from "wouter";
import { ComparePage } from "./ExperimentPages";
import {
  LoginPage,
  LoginSessionProvider,
  startsAtFirstPage,
} from "./LoginGate";
import { at, control, tab, text } from "./markup.test-helper";
import { ProfileToolbar } from "./ProfileToolbar";
import { ExperimentsTab, TargetTabs } from "./TargetPage";
import { TargetRail } from "./TargetRail";

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
  assert.match(markup, /role="radiogroup" aria-label="Colour theme"/);
  assert.doesNotMatch(markup, /aria-current/);
});

test("the rail has no user and no logout control when login is off", () => {
  const markup = rail(null);

  assert.doesNotMatch(markup, /Log out/);
});

test("the rail names the current user and offers logout in a login session", () => {
  const user = {
    id: "3f6c2a9d5b7e4c1e8a0f2d4b6c8e0a1c",
    username: "curious-otter",
    created_at: "2026-11-14T08:30:00Z",
  };

  const markup = renderToStaticMarkup(
    <LoginSessionProvider value={{ user, logout: () => {} }}>
      {
        <Router ssrPath="/">
          <TargetRail
            targets={[]}
            problems={[]}
            selectedId={null}
            activeIds={new Set()}
            onNew={() => {}}
            onDelete={() => {}}
          />
        </Router>
      }
    </LoginSessionProvider>,
  );

  assert.match(text(markup), /curious-otter/);
  assert.match(markup, /<button[^>]*aria-label="Log out"/);
});

test("the login page asks for a username and a password", () => {
  const markup = renderToStaticMarkup(<LoginPage onLogin={() => {}} />);
  const inputs = [...markup.matchAll(/<input[^>]*>/g)].map(([input]) => input);

  assert.match(markup, /<h1[^>]*>Log in<\/h1>/);
  assert.equal(inputs.length, 2);
  assert.match(inputs[0] ?? "", /type="text"/);
  assert.match(inputs[0] ?? "", /autoComplete="username"/);
  assert.match(inputs[0] ?? "", /name="username"/);
  assert.match(inputs[1] ?? "", /type="password"/);
  assert.match(inputs[1] ?? "", /autoComplete="current-password"/);
  assert.match(markup, /<button[^>]*type="submit"[^>]*>Log in<\/button>/);
  assert.doesNotMatch(markup, /role="alert"/);
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

test("an empty Experiments tab says so", () => {
  assert.match(
    at("/targets/a/experiments", <ExperimentsTab />),
    /No experiments yet\./,
  );
});

test("the comparison links back to its Target", () => {
  const markup = at(
    "/targets/a/compare",
    <ComparePage targetId="a" targetTitle="Bank bot" />,
  );

  assert.match(control(markup, "Bank bot"), /href="\/targets\/a\/experiments"/);
  assert.match(markup, /Compare experiments/);
});
