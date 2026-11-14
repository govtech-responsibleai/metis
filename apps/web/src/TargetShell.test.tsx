import assert from "node:assert/strict";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { ComparePage } from "./ExperimentPages";
import { at, control, tab } from "./markup.test-helper";
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

test("an empty Experiments tab says so and links to the comparison", () => {
  const markup = at("/targets/a/experiments", <ExperimentsTab targetId="a" />);

  assert.match(markup, /No experiments yet\./);
  assert.match(control(markup, "Compare"), /href="\/targets\/a\/compare"/);
});

test("the comparison links back to its Target", () => {
  const markup = at(
    "/targets/a/compare",
    <ComparePage targetId="a" targetTitle="Bank bot" />,
  );

  assert.match(control(markup, "Bank bot"), /href="\/targets\/a\/experiments"/);
  assert.match(markup, /Compare experiments/);
});
