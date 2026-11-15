// The Report tab of an experiment. It has the sections of report.html from `metis insights report`
// and the same layout: the score, the results for each Feature, Behaviour and Criterion as a list
// or a tree with a panel for one Criterion, and the results for each test case.
// `report.css` has the rules. Every number comes from `reportPage` in `report.ts`. A test case of
// the results table opens the trial drawer (`CaseDrawer.tsx`).

import { ArrowDown, ChevronRight, Download } from "lucide-react";
import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { CaseDrawer } from "./CaseDrawer";
import { saveFile } from "./download";
import type {
  BehaviourRate,
  CaseCell,
  CaseTable,
  CriterionResult,
  FeatureResult,
  ReportLoad,
  ReportPage,
  Passing,
  ScoreFacts,
  UnmappedResult,
} from "./report";
import { OUTCOME, RateText, Tip } from "./ReportParts";
import { paths } from "./routes";
import { api } from "./transport/api";
import { Button, cn, Mono } from "./ui";

const QUIET = "text-sm text-muted-foreground";

const isLow = (rate: BehaviourRate) => rate.kind === "measured" && rate.low;

function Caret() {
  return (
    <span className="car">
      <ChevronRight size={12} aria-hidden />
    </span>
  );
}

function Counts({ criterion }: { criterion: CriterionResult }) {
  return (
    <span className="counts n">
      <span>
        {criterion.passed} of {criterion.graded} graded results passed
      </span>
      {criterion.skipped > 0 && <span>{criterion.skipped} skipped</span>}
      {criterion.errored > 0 && (
        <span className="e">{criterion.errored} errored</span>
      )}
    </span>
  );
}

function Score({ score }: { score: ScoreFacts }) {
  const none = <span className="n">No result</span>;
  const count = (fact: Passing | null) =>
    fact ? (
      <b>
        {fact.passing}/{fact.graded}
      </b>
    ) : (
      none
    );
  return (
    <section className="score" aria-label="Score">
      <div>
        <div className="label">
          Average pass rate{" "}
          <Tip>
            The average of the feature scores below. Each score is the average
            of the level under it. A criterion's score is its passed results ÷
            its graded results. Skipped and errored results are not counted. The
            default pass-rate target is {score.target}%. Scores below it are
            shown in red.
          </Tip>
        </div>
        <RateText rate={score.passRate} className="big" />
      </div>
      <div className="facts">
        <div>
          <span>Passing behaviours</span>
          {count(score.behaviours)}
        </div>
        <div>
          <span>Passing test cases</span>
          {count(score.testCases)}
        </div>
        <div>
          <span>Report date</span>
          {score.date ? <b>{score.date}</b> : none}
        </div>
      </div>
    </section>
  );
}

type SpecView = "list" | "tree";

// What the user opened and picked in the specification results.
export interface SpecState {
  view: SpecView;
  closedFeatures: ReadonlySet<string>;
  openBehaviours: ReadonlySet<string>;
  // The id of the picked Criterion.
  selected: string | null;
  // The id of the test case that the results table marks.
  shownCase: string | null;
  // The id of the test case that the trial drawer shows.
  openCase: string | null;
}

// The report starts on the tree. Features start open and Behaviours start closed.
export const SPEC_START: SpecState = {
  view: "tree",
  closedFeatures: new Set(),
  openBehaviours: new Set(),
  selected: null,
  shownCase: null,
  openCase: null,
};

export interface SpecActions {
  show: (view: SpecView) => void;
  toggleFeature: (id: string) => void;
  toggleBehaviour: (id: string) => void;
  select: (criterionId: string) => void;
  // Mark one test case of the picked Criterion in the results table.
  showCase: (taskId: string) => void;
  openCase: (taskId: string) => void;
  closeCase: () => void;
}

function toggled(set: ReadonlySet<string>, id: string): ReadonlySet<string> {
  const next = new Set(set);
  if (!next.delete(id)) next.add(id);
  return next;
}

function SpecList({
  features,
  state,
  actions,
}: {
  features: FeatureResult[];
  state: SpecState;
  actions: SpecActions;
}) {
  return (
    <div className="listwrap quiet-scrollbar">
      {features.map((feature) => {
        const open = !state.closedFeatures.has(feature.id);
        return (
          <div key={feature.id}>
            <button
              type="button"
              className={cn("feat", open && "open")}
              aria-expanded={open}
              onClick={() => actions.toggleFeature(feature.id)}
            >
              <span>
                <Caret />
                {feature.name}
              </span>
              <RateText rate={feature.rate} className="score-val" />
            </button>
            {open &&
              feature.behaviours.map((behaviour) => {
                const shown = state.openBehaviours.has(behaviour.id);
                return (
                  <div key={behaviour.id}>
                    <button
                      type="button"
                      className={cn("row b", shown && "open")}
                      aria-expanded={shown}
                      title={behaviour.label}
                      onClick={() => actions.toggleBehaviour(behaviour.id)}
                    >
                      {behaviour.criteria.length > 0 ? <Caret /> : <span />}
                      <span className="name">{behaviour.label}</span>
                      <RateText rate={behaviour.rate} className="score-val" />
                    </button>
                    {shown &&
                      behaviour.criteria.map((criterion) => (
                        <button
                          key={criterion.id}
                          type="button"
                          className={cn(
                            "row c",
                            state.selected === criterion.id && "sel",
                          )}
                          aria-pressed={state.selected === criterion.id}
                          title={criterion.name}
                          onClick={() => actions.select(criterion.id)}
                        >
                          <span />
                          <span className="name">{criterion.name}</span>
                          <RateText
                            rate={criterion.rate}
                            className="score-val"
                          />
                        </button>
                      ))}
                  </div>
                );
              })}
          </div>
        );
      })}
    </div>
  );
}

// The geometry of the tree of report.html: one column for each level, and a parent at the middle
// of its children.
const BOX = { width: 210, height: 48, gap: 12 };
const COLUMN = [6, 256, 506, 756] as const;
const TREE_TOP = 34;
const LEVELS = ["Target", "Feature", "Behaviour", "Criterion"];

interface TreeNode {
  key: string;
  x: number;
  y: number;
  name: string;
  rate: BehaviourRate;
  // Null for a node with no click of its own.
  onPick: (() => void) | null;
  // Null for a node with nothing under it.
  toggle: { open: boolean; onToggle: () => void } | null;
  // The id that puts the node on the path of the picked Criterion.
  id: string | null;
}

interface TreeLink {
  from: [number, number];
  to: [number, number];
  toId: string;
}

function treeLayout(
  page: ReportPage,
  state: SpecState,
  actions: SpecActions,
): { nodes: TreeNode[]; links: TreeLink[]; height: number } {
  const step = BOX.height + BOX.gap;
  const nodes: TreeNode[] = [];
  const links: TreeLink[] = [];
  const middle = (ys: number[], y: number) =>
    ys.length > 0 ? ((ys[0] ?? 0) + (ys[ys.length - 1] ?? 0)) / 2 : y - step;
  const link = (level: 0 | 1 | 2, y: number, childY: number, toId: string) =>
    links.push({
      from: [COLUMN[level] + BOX.width, y],
      to: [COLUMN[level + 1] ?? 0, childY],
      toId,
    });
  let y = TREE_TOP;
  const featureYs: number[] = [];
  for (const feature of page.specification) {
    const open = !state.closedFeatures.has(feature.id);
    const behaviourYs: number[] = [];
    for (const behaviour of open ? feature.behaviours : []) {
      const shown = state.openBehaviours.has(behaviour.id);
      const criterionYs: number[] = [];
      for (const criterion of shown ? behaviour.criteria : []) {
        criterionYs.push(y);
        nodes.push({
          key: `c ${behaviour.id} ${criterion.id}`,
          x: COLUMN[3],
          y,
          name: criterion.name,
          rate: criterion.rate,
          onPick: () => actions.select(criterion.id),
          toggle: null,
          id: criterion.id,
        });
        y += step;
      }
      if (criterionYs.length === 0) y += step;
      const behaviourY = middle(criterionYs, y);
      behaviourYs.push(behaviourY);
      const onToggle = () => actions.toggleBehaviour(behaviour.id);
      nodes.push({
        key: `b ${behaviour.id}`,
        x: COLUMN[2],
        y: behaviourY,
        name: behaviour.label,
        rate: behaviour.rate,
        onPick: onToggle,
        toggle:
          behaviour.criteria.length > 0 ? { open: shown, onToggle } : null,
        id: behaviour.id,
      });
      criterionYs.forEach((criterionY, index) =>
        link(2, behaviourY, criterionY, behaviour.criteria[index]?.id ?? ""),
      );
    }
    if (behaviourYs.length === 0) y += step;
    const featureY = middle(behaviourYs, y);
    featureYs.push(featureY);
    nodes.push({
      key: `f ${feature.id}`,
      x: COLUMN[1],
      y: featureY,
      name: feature.name,
      rate: feature.rate,
      onPick: null,
      toggle:
        feature.behaviours.length > 0
          ? { open, onToggle: () => actions.toggleFeature(feature.id) }
          : null,
      id: feature.id,
    });
    behaviourYs.forEach((behaviourY, index) =>
      link(1, featureY, behaviourY, feature.behaviours[index]?.id ?? ""),
    );
    y += 10;
  }
  const targetY = featureYs.length > 0 ? middle(featureYs, TREE_TOP) : TREE_TOP;
  nodes.push({
    key: "target",
    x: COLUMN[0],
    y: targetY,
    name: page.target,
    rate: page.score.passRate,
    onPick: null,
    toggle: null,
    id: null,
  });
  featureYs.forEach((featureY, index) =>
    link(0, targetY, featureY, page.specification[index]?.id ?? ""),
  );
  return { nodes, links, height: y };
}

// The picked Criterion with the Behaviour and the Feature that own it.
function picked(features: FeatureResult[], selected: string | null) {
  for (const feature of features)
    for (const behaviour of feature.behaviours)
      for (const criterion of behaviour.criteria)
        if (criterion.id === selected) return { feature, behaviour, criterion };
  return null;
}

const onKey = (act: () => void) => (event: KeyboardEvent) => {
  if (event.key !== "Enter" && event.key !== " ") return;
  event.preventDefault();
  event.stopPropagation();
  act();
};

const fit = (name: string) =>
  name.length > 24 ? `${name.slice(0, 23)}…` : name;

function SpecTree({
  page,
  state,
  actions,
}: {
  page: ReportPage;
  state: SpecState;
  actions: SpecActions;
}) {
  const { nodes, links, height } = treeLayout(page, state, actions);
  const path = picked(page.specification, state.selected);
  const onPath = new Set(
    path ? [path.criterion.id, path.behaviour.id, path.feature.id] : [],
  );
  const half = BOX.height / 2;
  return (
    <div className="treewrap quiet-scrollbar">
      <svg
        width={COLUMN[3] + BOX.width + 16}
        height={height}
        aria-label="Specification tree"
      >
        {LEVELS.map((level, index) => (
          <text
            key={level}
            className="tree-level"
            x={(COLUMN[index] ?? 0) + 4}
            y={16}
          >
            {level.toUpperCase()}
          </text>
        ))}
        {links.map(({ from: [x1, y1], to: [x2, y2], toId }) => (
          <path
            key={`${x2} ${y2}`}
            className={cn("tree-link", onPath.has(toId) && "lit")}
            d={`M${x1} ${y1 + half} C ${x1 + 20} ${y1 + half}, ${x2 - 20} ${y2 + half}, ${x2} ${y2 + half}`}
          />
        ))}
        {nodes.map((node) => (
          <g
            key={node.key}
            className={cn(
              "tree-node",
              node.id !== null && onPath.has(node.id) && "lit",
              node.id !== null && node.id === state.selected && "picked",
            )}
            transform={`translate(${node.x},${node.y})`}
            {...(node.onPick && {
              role: "button",
              tabIndex: 0,
              onClick: node.onPick,
              onKeyDown: onKey(node.onPick),
            })}
          >
            <title>{node.name}</title>
            <rect
              className="tree-box"
              width={BOX.width}
              height={BOX.height}
              rx={8}
            />
            <circle
              className={cn(
                "tree-dot",
                node.rate.kind !== "measured" && "none",
                isLow(node.rate) && "low",
              )}
              cx={14}
              cy={16}
              r={4}
            />
            <text className="tree-name" x={26} y={20}>
              {fit(node.name)}
            </text>
            <text
              className={cn("tree-rate", isLow(node.rate) && "low")}
              x={26}
              y={36}
            >
              {node.rate.kind === "measured"
                ? `${node.rate.percent}%`
                : node.rate.kind === "not-measured"
                  ? "Not measured"
                  : "Not graded"}
            </text>
            {node.toggle && (
              <g
                className={cn("tree-toggle", node.toggle.open && "open")}
                transform={`translate(${BOX.width},${half})`}
                role="button"
                tabIndex={0}
                aria-label={node.toggle.open ? "Close" : "Open"}
                onClick={(event) => {
                  event.stopPropagation();
                  node.toggle?.onToggle();
                }}
                onKeyDown={onKey(node.toggle.onToggle)}
              >
                <circle r={8} />
                <path d={node.toggle.open ? "M-4 0H4" : "M-4 0H4M0 -4V4"} />
              </g>
            )}
          </g>
        ))}
      </svg>
    </div>
  );
}

function CriterionPanel({
  path,
  showCase,
}: {
  path: ReturnType<typeof picked>;
  showCase: (taskId: string) => void;
}) {
  if (!path)
    return (
      <div className="empty">
        <b>Pick a criterion</b>
        <span>Open a behaviour, then click one of its criteria.</span>
      </div>
    );
  const { behaviour, criterion } = path;
  return (
    <>
      <div className="parent">
        <div className="n">Behaviour</div>
        <div className="parent-row">
          <b>{behaviour.label}</b>
          <RateText rate={behaviour.rate} className="score-val" />
        </div>
        <p className="n">{behaviour.statement}</p>
      </div>
      <div className="n">Criterion</div>
      <h3>{criterion.name}</h3>
      <div className="rate-line">
        <RateText rate={criterion.rate} className="big" />
        <Counts criterion={criterion} />
      </div>
      <p className="desc">{criterion.description}</p>
      <dl className="kv">
        <dt>Grader</dt>
        <dd>{criterion.graderName}</dd>
        <dt>Judge model</dt>
        <dd className="parts">
          {criterion.judgeModels.length > 0
            ? criterion.judgeModels.map((model) => (
                <span key={model}>{model}</span>
              ))
            : "None"}
        </dd>
        <dt>Pass mark</dt>
        <dd>
          {criterion.passMark === null
            ? "None"
            : `Score ≥ ${criterion.passMark.toFixed(2)}`}
        </dd>
        <dt>Mean score</dt>
        <dd className="mono">
          {criterion.meanScore === null
            ? "No result"
            : criterion.meanScore.toFixed(2)}
        </dd>
        <dt>Criterion ID</dt>
        <dd className="mono id">{criterion.id}</dd>
      </dl>
      <b>By test case</b>
      <p className="n by-case">
        Click a test case to see it in the results table.
      </p>
      {criterion.cases.map((testCase) => (
        <button
          key={testCase.taskId}
          type="button"
          className="tc"
          title="Show this test case in the results table"
          onClick={() => showCase(testCase.taskId)}
        >
          <span>
            <b>{testCase.taskId}</b>
            <span className="n">{testCase.persona}</span>
            <span className="n">{testCase.scenario}</span>
          </span>
          <span className="sq">
            {testCase.trials.map((trial) => (
              <i
                key={trial.index}
                className={cn("q", trial.outcome)}
                title={`Trial ${trial.index}: ${OUTCOME[trial.outcome]}`}
              />
            ))}
          </span>
          <RateText rate={testCase.rate} className="score-val" />
          <ArrowDown size={14} aria-hidden className="arrow" />
        </button>
      ))}
    </>
  );
}

const LIST_ICON = (
  <svg
    viewBox="0 0 18 18"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    aria-hidden
  >
    <circle cx="3" cy="4" r="1.2" fill="currentColor" />
    <path d="M7 4h9" />
    <circle cx="3" cy="9" r="1.2" fill="currentColor" />
    <path d="M7 9h9" />
    <circle cx="3" cy="14" r="1.2" fill="currentColor" />
    <path d="M7 14h9" />
  </svg>
);

const TREE_ICON = (
  <svg
    viewBox="0 0 18 18"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.6"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden
  >
    <rect x="1.5" y="7" width="4" height="4" rx="1" />
    <rect x="12.5" y="1.5" width="4" height="4" rx="1" />
    <rect x="12.5" y="12.5" width="4" height="4" rx="1" />
    <path d="M5.5 9H9v-5.5h3.5M9 9v5.5h3.5" />
  </svg>
);

function SpecificationResults({
  page,
  state,
  actions,
}: {
  page: ReportPage;
  state: SpecState;
  actions: SpecActions;
}) {
  const viewButton = (id: SpecView, label: string, icon: ReactNode) => (
    <button
      type="button"
      aria-pressed={state.view === id}
      onClick={() => actions.show(id)}
    >
      {icon}
      {label}
    </button>
  );
  const path = picked(page.specification, state.selected);
  return (
    <section aria-labelledby="spec-title">
      <div className="sechead">
        <h2 id="spec-title">Specification results</h2>
        <Tip>
          <b>Every score here is an average.</b> A criterion's score is its
          passed results ÷ its graded results, over all test cases. A behaviour
          is the average of its criteria. A feature is the average of its
          behaviours. Skipped and errored results are not counted.
        </Tip>
        <div className="seg" role="group" aria-label="View">
          {viewButton("tree", "Tree", TREE_ICON)}
          {viewButton("list", "List", LIST_ICON)}
        </div>
      </div>
      <div className={cn("inv", path && "picked")}>
        <div className="specview">
          {state.view === "list" ? (
            <SpecList
              features={page.specification}
              state={state}
              actions={actions}
            />
          ) : (
            <SpecTree page={page} state={state} actions={actions} />
          )}
        </div>
        <aside className="panel quiet-scrollbar">
          <CriterionPanel path={path} showCase={actions.showCase} />
        </aside>
      </div>
    </section>
  );
}

// The two stops of the pass rate scale next to a rate, and how far the rate is between them.
function scaleStyle(percent: number): CSSProperties {
  const position = Math.max(0, Math.min(100, percent)) / 25;
  const stop = Math.min(3, Math.floor(position));
  return {
    "--lo": `var(--rate-${stop * 25})`,
    "--hi": `var(--rate-${(stop + 1) * 25})`,
    "--t": `${Math.round((position - stop) * 100)}%`,
  } as CSSProperties;
}

function Cell({
  cell,
  name,
  hit,
}: {
  cell: CaseCell | null;
  name: string;
  // The cell of the marked test case in the column of the picked Criterion.
  hit: boolean;
}) {
  if (!cell) return <td className="cell" />;
  const counts = [
    `${cell.passed} passed`,
    `${cell.failed} failed`,
    ...(cell.skipped > 0 ? [`${cell.skipped} skipped`] : []),
    ...(cell.errored > 0 ? [`${cell.errored} errored`] : []),
  ].join(", ");
  const range = cell.interval
    ? `${cell.interval.lower} to ${cell.interval.upper}%`
    : null;
  if (cell.rate.kind !== "measured")
    return (
      <td
        className={cn("cell none", hit && "hit")}
        aria-label={`${name}: ${counts}`}
      >
        No result
      </td>
    );
  return (
    <td
      className={cn("cell scaled", hit && "hit")}
      style={scaleStyle(cell.rate.percent)}
      aria-label={`${name}: ${counts}${range ? `. 95% range: ${range}` : ""}`}
    >
      <span className={cn("rate", cell.rate.low && "low")}>
        {cell.rate.percent}%
      </span>
      {range && <span className="ci">({range})</span>}
    </td>
  );
}

function CaseResults({
  table,
  marked,
  shownCase,
  openCase,
}: {
  table: CaseTable;
  // The id of the picked Criterion. Its column has the accent colour.
  marked: string | null;
  // The id of the marked test case. Its row has the accent colour.
  shownCase: string | null;
  openCase: (taskId: string) => void;
}) {
  const columns = table.groups.flatMap((group) => group.columns);
  return (
    <section aria-labelledby="results-title">
      <div className="sechead">
        <h2 id="results-title">Results by test case</h2>
        <Tip>
          One row is one test case: one persona in one scenario, run one or more
          times. A cell is the criterion's pass rate over that test case's
          graded results. The numbers in brackets are its 95% confidence
          interval. A wide interval means there are too few trials to be sure.
          Click a test case to see each trial and its conversation.
        </Tip>
      </div>
      <div className="tsum">
        <span>Click a test case to see its trials.</span>
        <span className="totals">
          <span>{table.skipped} skipped</span>
          <span>{table.errored} errored</span>
        </span>
      </div>
      {columns.length === 0 || table.rows.length === 0 ? (
        <p className="n">No test case has a grader result.</p>
      ) : (
        <div className="results-scroll quiet-scrollbar">
          <table className="rt">
            <thead>
              <tr>
                <th className="stick id fg" rowSpan={2} scope="col">
                  ID
                </th>
                <th className="stick first fg" rowSpan={2} scope="col">
                  Persona
                </th>
                <th className="stick second fg" rowSpan={2} scope="col">
                  Scenario
                </th>
                {table.groups.map((group) => (
                  <th
                    key={group.featureId}
                    className="fg"
                    colSpan={group.columns.length}
                    scope="colgroup"
                    title={group.name}
                  >
                    <span>{group.name}</span>
                  </th>
                ))}
              </tr>
              <tr>
                {columns.map((column) => (
                  <th
                    key={column.criterionId}
                    className={cn(
                      "crit",
                      column.criterionId === marked && "mark",
                    )}
                    scope="col"
                    title={column.label}
                    data-marked={column.criterionId === marked || undefined}
                  >
                    <span>{column.label}</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((row) => (
                // The button of the Persona cell is the control. A click on any part of the row
                // comes to the row and does the same.
                <tr
                  key={row.taskId}
                  className={row.taskId === shownCase ? "mark" : undefined}
                  onClick={() => openCase(row.taskId)}
                >
                  <td className="stick id" title={row.taskId}>
                    {row.taskId}
                  </td>
                  <th className="stick first" scope="row">
                    <button
                      type="button"
                      className="case-toggle"
                      aria-label={`${row.taskId}: ${row.persona}, ${row.scenario}`}
                    >
                      <span className="case-name" title={row.persona}>
                        {row.persona}
                      </span>
                    </button>
                  </th>
                  <td className="stick second">
                    <span className="case-open">
                      <span>
                        <span className="case-name" title={row.scenario}>
                          {row.scenario}
                        </span>
                        {(row.skipped > 0 || row.errored > 0) && (
                          <span className="probs">
                            {row.skipped > 0 && (
                              <span>{row.skipped} skipped</span>
                            )}
                            {row.errored > 0 && (
                              <span className="e">{row.errored} errored</span>
                            )}
                          </span>
                        )}
                      </span>
                      <ChevronRight size={16} aria-hidden />
                    </span>
                  </td>
                  {row.cells.map((cell, index) => (
                    <Cell
                      key={columns[index]?.criterionId ?? index}
                      cell={cell}
                      name={columns[index]?.label ?? ""}
                      hit={
                        row.taskId === shownCase &&
                        columns[index]?.criterionId === marked
                      }
                    />
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function UnmappedResults({ results }: { results: UnmappedResult[] }) {
  if (results.length === 0) return null;
  return (
    <section className="unmapped" aria-labelledby="unmapped-title">
      <h2 id="unmapped-title">Results without a matching criterion</h2>
      <p className="n">
        These results match no Task and Criterion in the specification. They are
        not part of any score.
      </p>
      {results.map((group, index) => (
        <div key={index} className="um">
          <div className="um-head">
            <span>{group.criterionId}</span>
            <span>{group.grader}</span>
          </div>
          <p className="n">{group.why}</p>
          {group.items.map((item, itemIndex) => (
            <div key={itemIndex} className="um-item">
              <div className="um-where">
                <span className={cn("pill", item.outcome)}>
                  {OUTCOME[item.outcome]}
                </span>
                <span>{item.taskId}</span>
                <span>trial {item.trialIndex}</span>
                {item.resultNumber !== null && (
                  <span>result {item.resultNumber}</span>
                )}
              </div>
              <div>{item.reason}</div>
              <details>
                <summary className="n">
                  Recorded grader settings <Caret />
                </summary>
                <pre>{item.settings}</pre>
              </details>
            </div>
          ))}
        </div>
      ))}
    </section>
  );
}

// The sections for one state of the specification results. It has no hook, so a test can render
// each state.
export function ReportSections({
  page,
  state,
  actions,
  caseHref,
}: {
  page: ReportPage;
  state: SpecState;
  actions: SpecActions;
  caseHref: (taskId: string) => string;
}) {
  const opened = page.cases.rows.find((row) => row.taskId === state.openCase);
  return (
    <div className="report">
      <Score score={page.score} />
      <SpecificationResults page={page} state={state} actions={actions} />
      <CaseResults
        table={page.cases}
        marked={state.selected}
        shownCase={state.shownCase}
        openCase={actions.openCase}
      />
      <UnmappedResults results={page.unmapped} />
      {opened && (
        <CaseDrawer
          key={opened.taskId}
          row={opened}
          columns={page.cases.groups.flatMap((group) => group.columns)}
          target={page.score.target}
          targetName={page.target}
          marked={state.selected}
          trialsHref={caseHref(opened.taskId)}
          onClose={actions.closeCase}
        />
      )}
    </div>
  );
}

function ReadyReport({
  page,
  caseHref,
}: {
  page: ReportPage;
  caseHref: (taskId: string) => string;
}) {
  const [state, setState] = useState(SPEC_START);
  const root = useRef<HTMLDivElement>(null);
  // Each click on a test case of the panel moves the page, also a second click on the same one.
  const [shows, setShows] = useState(0);
  useEffect(() => {
    if (shows === 0) return;
    const row = root.current?.querySelector<HTMLElement>(".rt tr.mark");
    if (!row) return;
    row.scrollIntoView({ behavior: "smooth", block: "center" });
    const box = row.closest<HTMLElement>(".results-scroll");
    const column = box?.querySelector<HTMLElement>("th[data-marked]");
    if (!box || !column) return;
    const sticky = [
      ...box.querySelectorAll<HTMLElement>("thead .stick"),
    ].reduce((width, cell) => width + cell.offsetWidth, 0);
    box.scrollTo({
      left: Math.max(0, column.offsetLeft - sticky - 2 * column.offsetWidth),
      behavior: "smooth",
    });
  }, [shows]);
  // The Criterion boxes are the last column of the tree. When the tree is wider than its area,
  // this brings them into view after the user opens a Behaviour or picks a Criterion.
  useEffect(() => {
    if (state.openBehaviours.size === 0 && state.selected === null) return;
    const tree = root.current?.querySelector<HTMLElement>(".treewrap");
    tree?.scrollTo({ left: tree.scrollWidth, behavior: "smooth" });
  }, [state.openBehaviours, state.selected, state.view]);
  const actions: SpecActions = {
    show: (view) => setState((now) => ({ ...now, view })),
    toggleFeature: (id) =>
      setState((now) => ({
        ...now,
        closedFeatures: toggled(now.closedFeatures, id),
      })),
    toggleBehaviour: (id) =>
      setState((now) => ({
        ...now,
        openBehaviours: toggled(now.openBehaviours, id),
      })),
    select: (selected) =>
      setState((now) => ({ ...now, selected, shownCase: null })),
    showCase: (shownCase) => {
      setState((now) => ({ ...now, shownCase }));
      setShows((count) => count + 1);
    },
    openCase: (openCase) =>
      setState((now) => ({ ...now, openCase, shownCase: null })),
    closeCase: () => setState((now) => ({ ...now, openCase: null })),
  };
  return (
    <div ref={root} className="contents">
      <ReportSections
        page={page}
        state={state}
        actions={actions}
        caseHref={caseHref}
      />
    </div>
  );
}

// The state of a download is separate from the report load: a failed download does not change
// what the browser knows about the report.
export function DownloadReport({ experimentId }: { experimentId: string }) {
  const [state, setState] = useState<"idle" | "busy" | { failure: string }>(
    "idle",
  );
  const download = async () => {
    setState("busy");
    try {
      saveFile(await api.reportPage(experimentId));
      setState("idle");
    } catch (error) {
      setState({
        failure:
          error instanceof Error ? error.message : "The download failed.",
      });
    }
  };
  return (
    <div className="flex items-center gap-3">
      {typeof state === "object" && (
        <span role="alert" className="text-sm text-destructive">
          {state.failure}
        </span>
      )}
      <Button
        disabled={state === "busy"}
        title="The same report.html that the CLI writes"
        onClick={() => void download()}
      >
        <Download size={13} strokeWidth={2} aria-hidden />
        report.html
      </Button>
    </div>
  );
}

export function ReportTab({
  targetId,
  experimentId,
  load,
  onReload,
}: {
  targetId: string;
  experimentId: string;
  load: ReportLoad;
  onReload: () => void;
}) {
  switch (load.status) {
    case "loading":
      return (
        <p role="status" className={QUIET}>
          Loading the report
        </p>
      );
    case "not-evaluated":
      return (
        <div className={cn("flex flex-col gap-1", QUIET)}>
          <p className="text-foreground">This experiment has no results yet.</p>
          <p>
            Run <Mono>metis engine evaluate</Mono> on the experiment, then open
            this page again.
          </p>
        </div>
      );
    case "not-found":
      return <p className={QUIET}>No experiment has this name.</p>;
    case "failed":
      return (
        <div className="flex flex-col items-start gap-3">
          <p role="alert" className="text-sm text-destructive">
            {load.message}
          </p>
          {load.retryable && <Button onClick={onReload}>Try again</Button>}
        </div>
      );
    case "ready":
      return (
        <ReadyReport
          page={load.page}
          caseHref={(taskId) => paths.testCase(targetId, experimentId, taskId)}
        />
      );
  }
}
