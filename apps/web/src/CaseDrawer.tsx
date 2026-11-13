// The drawer for one test case of the Report tab, as in report.html: the pass rate and its 95%
// range for each Criterion, the trials, and for one trial its conversation and what the Graders
// returned. `report.css` has the rules.

import { ChevronRight, ChevronsRight } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "wouter";
import type {
  CaseCell,
  CaseColumn,
  CaseRow,
  GraderResult,
  Outcome,
  TrialCriterion,
  TrialDetail,
} from "./report";
import { OUTCOME, RateText, Tip } from "./ReportParts";
import { cn, Modal } from "./ui";

const ENDING: Record<string, string> = {
  succeeded: "Reached its goal",
  abandoned: "Stopped",
  error: "Error",
  timedOut: "Timed out",
};

const SOURCE: Record<string, string> = {
  target: "Target",
  userAgent: "User agent",
  evaluationRunner: "Evaluation runner",
};

type Status = "ok" | "stop" | "bad" | "time";

const STATUS: Record<string, Status> = {
  succeeded: "ok",
  abandoned: "stop",
  error: "bad",
  timedOut: "time",
};

const STATUS_MARK: Record<Status, ReactNode> = {
  ok: <path d="M5.5 9.2l2.3 2.3 4.7-4.9" strokeLinejoin="round" />,
  bad: <path d="M6.2 6.2l5.6 5.6M11.8 6.2l-5.6 5.6" />,
  stop: <path d="M6 9h6" />,
  time: <path d="M9 5.5V9l2.5 1.8" />,
};

// The order of the outcome tabs of a trial.
const TABS: Outcome[] = ["failed", "passed", "errored", "skipped"];

const ERRORED_NOTE =
  "The grader could not score these criteria. This says nothing about the target.";

const ending = (trial: TrialDetail) => ENDING[trial.category] ?? trial.category;

function StatusIcon({ trial }: { trial: TrialDetail }) {
  const status = STATUS[trial.category] ?? "stop";
  const label = ending(trial) || "Unknown";
  return (
    <svg
      className={cn("st", status)}
      viewBox="0 0 18 18"
      width="18"
      height="18"
      role="img"
      aria-label={label}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
    >
      <title>{label}</title>
      <circle cx="9" cy="9" r="7.5" />
      {STATUS_MARK[status]}
    </svg>
  );
}

// One Criterion that has a result for the test case.
interface Shown {
  column: CaseColumn;
  cell: CaseCell;
}

function RangeAxis({ target }: { target: number }) {
  return (
    <div className="ci-row ci-axis">
      <span />
      <span />
      <div className="ci-wide ticks">
        {[0, 25, 50, 75, 100]
          .filter((value) => Math.abs(value - target) > 8)
          .map((value) => (
            <span
              key={value}
              className={
                value === 0 ? "first" : value === 100 ? "last" : undefined
              }
              style={{ left: `${value}%` }}
            >
              {value}%
            </span>
          ))}
        <span className="tg-label" style={{ left: `${target}%` }}>
          {target}% target
        </span>
      </div>
      <span />
      <span />
    </div>
  );
}

function RangeRow({
  shown: { column, cell },
  target,
  marked,
}: {
  shown: Shown;
  target: number;
  marked: boolean;
}) {
  const { interval, rate } = cell;
  return (
    <div className={cn("ci-row", marked && "mark")}>
      <span className="ci-name" title={column.label}>
        {column.label}
      </span>
      <RateText rate={rate} className="ci-rate mono" />
      {interval && rate.kind === "measured" ? (
        <div className="ci-wide">
          <span className="ci-track" />
          <span
            className="ci-rng"
            style={{
              left: `${interval.lower}%`,
              width: `${interval.upper - interval.lower}%`,
            }}
          />
          <span className="ci-tg" style={{ left: `${target}%` }} />
          <span className="ci-pt" style={{ left: `${rate.percent}%` }} />
        </div>
      ) : (
        <div className="ci-wide none" />
      )}
      <span className="ci-num mono">
        {interval ? `${interval.lower} to ${interval.upper}%` : "No result"}
      </span>
      <span className="ci-n">
        {cell.passed} of {cell.passed + cell.failed} passed
      </span>
    </div>
  );
}

function TrialTable({
  trials,
  shown,
  picked,
  marked,
  onTrial,
}: {
  trials: TrialDetail[];
  shown: Shown[];
  picked: TrialDetail | undefined;
  marked: string | null;
  onTrial: (index: number) => void;
}) {
  return (
    <div className="dt-scroll quiet-scrollbar">
      <table className="dt">
        <thead>
          <tr>
            <th className="st-col" />
            <th className="sum-col" scope="col">
              Trial
            </th>
            {shown.map(({ column }) => (
              <th
                key={column.criterionId}
                className={cn("cc", column.criterionId === marked && "mark")}
                scope="col"
                title={column.label}
              >
                <span>{column.label}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {trials.map((trial) => {
            const first =
              trial.turns[0]?.user ?? "No conversation was recorded.";
            const on = trial === picked;
            return (
              <tr
                key={trial.index}
                className={cn("trow", on && "on")}
                onClick={() => onTrial(trial.index)}
              >
                <td className="st-col">
                  <StatusIcon trial={trial} />
                </td>
                <td className="sum-col">
                  <button
                    type="button"
                    aria-pressed={on}
                    aria-label={`Show trial ${trial.index}`}
                  >
                    Trial {trial.index}
                  </button>
                  <span className="first" title={first}>
                    {first}
                  </span>
                  <span className="n end">
                    {trial.category === "succeeded" ? (
                      <>
                        <span>Reached its goal</span>
                        {trial.turns.length > 0 && (
                          <span>
                            {trial.turns.length}{" "}
                            {trial.turns.length === 1 ? "turn" : "turns"}
                          </span>
                        )}
                      </>
                    ) : (
                      <>
                        <span className="cut">
                          {ending(trial)}: {trial.message}
                        </span>
                        {trial.attempt > 1 && (
                          <span>Retried, attempt {trial.attempt}</span>
                        )}
                      </>
                    )}
                  </span>
                </td>
                {shown.map(({ column }) => {
                  const outcome = trial.criteria.find(
                    (criterion) => criterion.criterionId === column.criterionId,
                  )?.outcome;
                  return (
                    <td
                      key={column.criterionId}
                      className={cn(
                        "pc",
                        column.criterionId === marked && "mark",
                      )}
                    >
                      {outcome && (
                        <span className={cn("pill", outcome)}>
                          {OUTCOME[outcome]}
                        </span>
                      )}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Conversation({
  trial,
  targetName,
}: {
  trial: TrialDetail;
  targetName: string;
}) {
  if (trial.turns.length === 0)
    return (
      <div className="chat">
        <p className="n">
          No conversation was recorded for this trial.
          {trial.conversationProblem && ` ${trial.conversationProblem}.`}
        </p>
      </div>
    );
  return (
    <div className="chat">
      {trial.turns.map((turn) => (
        <div key={turn.turn} className="exchange">
          <span className="tn">Turn {turn.turn}</span>
          <div className="say user">
            <b>User</b>
            <p>{turn.user ?? "No user message recorded"}</p>
          </div>
          <div className="say agent">
            <b>{targetName}</b>
            <p>{turn.target ?? "No reply recorded"}</p>
          </div>
          {turn.errors.map((error, index) => (
            <div key={index} className="terr">
              Error: {error}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

// The bars have the numbers, so the reason below them only says what they mean.
function Measurements({ result }: { result: GraderResult }) {
  const scored = result.score !== null;
  return (
    <div className="measures">
      <div className="mnums">
        {scored ? (
          <span>
            Score <b className="mono">{result.score?.toFixed(2)}</b>
          </span>
        ) : (
          <span className="n">No score</span>
        )}
        {/* The pass mark applies to the score only, so a result with no score shows none. */}
        {scored && result.passMark !== null && (
          <span>
            Pass mark <b className="mono">≥ {result.passMark.toFixed(2)}</b>
          </span>
        )}
      </div>
      {result.measurements.map(({ name, value }) => (
        <div key={name} className="mrow">
          <span className="mname">{name}</span>
          <span className="mbar">
            <span className="ci-track" />
            <span
              className="ci-rng"
              style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }}
            />
          </span>
          <span className="mval mono">{value.toFixed(2)}</span>
        </div>
      ))}
    </div>
  );
}

function GraderOutput({ criterion }: { criterion: TrialCriterion }) {
  if (criterion.results.length === 0)
    return (
      <p className="why n">The grader returned no result for this trial.</p>
    );
  const many = criterion.results.length > 1;
  return (
    <>
      {criterion.results.map((result, index) => {
        const label = many && (
          <span className="why-label">Result {index + 1}: </span>
        );
        if (result.measurements.length > 0)
          return (
            <div key={index} className="why">
              {label}
              <Measurements result={result} />
              {result.reason && <p className="n mnote">{result.reason}</p>}
            </div>
          );
        if (result.reason)
          return (
            <p key={index} className="why">
              {label}
              {result.reason}
            </p>
          );
        return (
          <div key={index} className="why">
            {label}
            <pre className="raw">
              {JSON.stringify(
                {
                  outcome: result.outcome,
                  ...(result.score !== null && { score: result.score }),
                },
                null,
                1,
              )}
            </pre>
          </div>
        );
      })}
    </>
  );
}

function Verdicts({
  trial,
  tab,
  marked,
  onTab,
}: {
  trial: TrialDetail;
  // The outcome tab that the user picked. Null shows the default tab.
  tab: Outcome | null;
  marked: string | null;
  onTab: (outcome: Outcome) => void;
}) {
  const present = TABS.filter((outcome) =>
    trial.criteria.some((criterion) => criterion.outcome === outcome),
  );
  if (present.length === 0)
    return <p className="n">No grader result was recorded for this trial.</p>;
  // The default tab has the picked Criterion, or it is the first tab.
  const pick =
    tab ??
    trial.criteria.find((criterion) => criterion.criterionId === marked)
      ?.outcome ??
    present[0]!;
  return (
    <div className="verdicts">
      <h4>What the graders returned</h4>
      <div className="vtabs" role="group" aria-label="Outcome">
        {present.map((outcome) => (
          <button
            key={outcome}
            type="button"
            className={cn("vtab", outcome, outcome === pick && "on")}
            aria-pressed={outcome === pick}
            onClick={() => onTab(outcome)}
          >
            {OUTCOME[outcome]}
          </button>
        ))}
      </div>
      {pick === "errored" && <p className="n vlead">{ERRORED_NOTE}</p>}
      {trial.criteria
        .filter((criterion) => criterion.outcome === pick)
        .map((criterion) => (
          <div
            key={criterion.criterionId}
            className={cn(
              "why-row",
              criterion.criterionId === marked && "mark",
            )}
          >
            <div className="why-head">
              <b>{criterion.name}</b>
            </div>
            <GraderOutput criterion={criterion} />
          </div>
        ))}
    </div>
  );
}

function TrialSection({
  trial,
  targetName,
  tab,
  marked,
  onTab,
}: {
  trial: TrialDetail;
  targetName: string;
  tab: Outcome | null;
  marked: string | null;
  onTab: (outcome: Outcome) => void;
}) {
  return (
    <div className="trial-detail">
      <h4 className="td-title">Trial {trial.index}</h4>
      {trial.category !== "succeeded" && (
        <div className="endnote">
          <b>Ended early.</b> {ending(trial)}:{" "}
          {trial.message.replace(/\.\s*$/, "")}. Source:{" "}
          {SOURCE[trial.failureSource] ?? "Not recorded"}.
          {trial.attempt > 1 && (
            <span className="n"> Retried, attempt {trial.attempt}.</span>
          )}
        </div>
      )}
      <div className="split">
        <Conversation trial={trial} targetName={targetName} />
        <Verdicts trial={trial} tab={tab} marked={marked} onTab={onTab} />
      </div>
    </div>
  );
}

export interface DrawerState {
  // The index of the shown trial. Null shows the first trial.
  trial: number | null;
  // The outcome tab of the shown trial. Null shows the default tab.
  tab: Outcome | null;
}

export const DRAWER_START: DrawerState = { trial: null, tab: null };

export const DRAWER_TITLE = "case-drawer-title";

// One state of the drawer, so a test can render each state.
export function CaseDrawerView({
  row,
  columns,
  target,
  targetName,
  marked,
  trialsHref,
  state,
  onTrial,
  onTab,
  onClose,
}: {
  row: CaseRow;
  // The columns of the results table, in the order of the cells of the row.
  columns: CaseColumn[];
  // The pass rate target in percent.
  target: number;
  targetName: string;
  // The id of the picked Criterion.
  marked: string | null;
  trialsHref: string;
  state: DrawerState;
  onTrial: (index: number) => void;
  onTab: (outcome: Outcome) => void;
  onClose: () => void;
}) {
  const shown = columns.flatMap((column, index) => {
    const cell = row.cells[index];
    return cell ? [{ column, cell }] : [];
  });
  const trial =
    row.trials.find((item) => item.index === state.trial) ?? row.trials[0];
  return (
    <div className="report drawer">
      <div className="drawer-head">
        <button
          type="button"
          className="drawer-close"
          aria-label="Close"
          autoFocus
          onClick={onClose}
        >
          <ChevronsRight size={18} aria-hidden />
        </button>
        <span className="n crumb">
          Results by test case
          <ChevronRight size={12} aria-hidden />
        </span>
        <b>{row.persona}</b>
        <span className="n">{row.scenario}</span>
        <Link href={trialsHref} className="to-trials">
          Open in the Trials tab
        </Link>
      </div>
      <div className="drawer-body">
        <div className="drawer-main quiet-scrollbar">
          <div className="dm-head">
            <h3 id={DRAWER_TITLE}>
              <span>{row.persona}</span>
              <span className="n">{row.scenario}</span>
            </h3>
            <p className="n">{row.description}</p>
          </div>
          <h4 className="dm-sec">
            Pass rate and 95% range for each criterion
            <Tip>
              The tick is the pass rate. The band is the range where the true
              pass rate can be. The red line is the {target}% target.
            </Tip>
          </h4>
          <div className="ci-list">
            <RangeAxis target={target} />
            {shown.map((item) => (
              <RangeRow
                key={item.column.criterionId}
                shown={item}
                target={target}
                marked={item.column.criterionId === marked}
              />
            ))}
          </div>
          <h4 className="dm-sec">Trials</h4>
          <TrialTable
            trials={row.trials}
            shown={shown}
            picked={trial}
            marked={marked}
            onTrial={onTrial}
          />
          {trial ? (
            <TrialSection
              trial={trial}
              targetName={targetName}
              tab={state.tab}
              marked={marked}
              onTab={onTab}
            />
          ) : (
            <p className="n">No trial record was found for this test case.</p>
          )}
        </div>
      </div>
    </div>
  );
}

// The drawer starts on the first trial of the test case. Give it the test case as its key, so
// that another test case starts again.
export function CaseDrawer(
  props: Omit<
    Parameters<typeof CaseDrawerView>[0],
    "state" | "onTrial" | "onTab"
  >,
) {
  const [state, setState] = useState(DRAWER_START);
  return (
    <Modal
      side
      labelledBy={DRAWER_TITLE}
      className="w-[min(1300px,calc(100vw-80px))] max-[1000px]:w-screen"
      onCancel={props.onClose}
    >
      <CaseDrawerView
        {...props}
        state={state}
        onTrial={(trial) => setState({ trial, tab: null })}
        onTab={(tab) => setState((now) => ({ ...now, tab }))}
      />
    </Modal>
  );
}
