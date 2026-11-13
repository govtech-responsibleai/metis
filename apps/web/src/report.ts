// The report of an experiment, as the Report tab shows it. This module is the only reader of
// report.json. It copies numbers and does only the arithmetic that report.html does: it never
// makes a rate.

import type { ExperimentTab } from "./routes.ts";
import { api, TransportError, type Report } from "./transport/api.ts";

// What the browser knows about the report of one experiment. The answer of the report route is
// the only signal for "evaluate is done" until the app has an experiment store.
export type ReportLoad =
  | { status: "loading" }
  | { status: "ready"; page: ReportPage }
  // The experiment has no results: evaluate is not done.
  | { status: "not-evaluated" }
  | { status: "not-found" }
  | { status: "failed"; message: string; retryable: boolean };

export type SettledReportLoad = Exclude<ReportLoad, { status: "loading" }>;

// This function never rejects. It matches on the error code, because status 409 has two codes
// with different meanings.
export async function loadReport(
  experimentId: string,
  read: (experimentId: string) => Promise<Report> = api.report,
): Promise<SettledReportLoad> {
  try {
    return { status: "ready", page: reportPage(await read(experimentId)) };
  } catch (error) {
    const code = error instanceof TransportError ? error.code : undefined;
    if (code === "experiment_not_found") return { status: "not-found" };
    if (code === "results_missing") return { status: "not-evaluated" };
    return {
      status: "failed",
      message:
        error instanceof Error ? error.message : "The report did not load.",
      retryable: error instanceof TransportError && error.retryable,
    };
  }
}

export interface ExperimentScreen {
  // Null only when the URL names no tab and the report is not here yet.
  tab: ExperimentTab | null;
  // Null when the Report tab is on. A string when it is off: the text says why.
  reportOff: string | null;
}

const REPORT_OFF: Record<ReportLoad["status"], string | null> = {
  loading: "The report is loading",
  ready: null,
  "not-evaluated": "The report is ready when evaluate is done",
  "not-found": "This experiment has no report",
  // On, so that the user can open the message and try again.
  failed: null,
};

// A tab that the URL names is always the tab on the screen. For the bare URL, a finished
// experiment opens on Report and every other experiment opens on Trials.
export function experimentScreen(
  tab: ExperimentTab | null,
  load: ReportLoad,
): ExperimentScreen {
  const fallback =
    load.status === "loading"
      ? null
      : load.status === "ready"
        ? "report"
        : "trials";
  return { tab: tab ?? fallback, reportOff: REPORT_OFF[load.status] };
}

export type Rate =
  // `low` means that the rate is below the pass rate target.
  { kind: "measured"; percent: number; low: boolean } | { kind: "no-result" };

export type BehaviourRate = Rate | { kind: "not-measured" };

export interface ScoreFacts {
  passRate: Rate;
  target: number;
  // The Behaviours with a rate, and how many of them have a rate at the target or above it. Null
  // when no Behaviour has a rate.
  behaviours: Passing | null;
  // The test cases with a rate, and how many of them have no rate below the target. Null when no
  // test case has a rate.
  testCases: Passing | null;
  date: string;
}

export interface Passing {
  passing: number;
  graded: number;
}

export type Outcome = "passed" | "failed" | "skipped" | "errored";

// One test case that has a result for a Criterion.
export interface CriterionCase {
  taskId: string;
  persona: string;
  scenario: string;
  rate: Rate;
  // One entry for each trial that has an outcome for the Criterion.
  trials: Array<{ index: number; outcome: Outcome }>;
}

export interface CriterionResult {
  id: string;
  name: string;
  description: string;
  rate: Rate;
  passed: number;
  // Passed plus failed results.
  graded: number;
  skipped: number;
  errored: number;
  graderName: string;
  judgeModels: string[];
  // The lowest score that passes. Null when the Grader has no threshold.
  passMark: number | null;
  meanScore: number | null;
  cases: CriterionCase[];
}

export interface BehaviourResult {
  id: string;
  label: string;
  statement: string;
  rate: BehaviourRate;
  criteria: CriterionResult[];
}

export interface FeatureResult {
  id: string;
  name: string;
  rate: Rate;
  behaviours: BehaviourResult[];
}

export interface CaseColumn {
  criterionId: string;
  label: string;
}

export interface CaseColumnGroup {
  featureId: string;
  name: string;
  // Never empty.
  columns: CaseColumn[];
}

export interface CaseCell {
  rate: Rate;
  passed: number;
  failed: number;
  skipped: number;
  errored: number;
  // The confidence interval in whole percent.
  interval: { lower: number; upper: number } | null;
}

// One result that a Grader returned for a Criterion in a trial.
export interface GraderResult {
  outcome: Outcome;
  score: number | null;
  reason: string;
  // The named numbers of the result, each from 0 to 1.
  measurements: Array<{ name: string; value: number }>;
  // The lowest score that passes. Null when the Grader has no threshold.
  passMark: number | null;
}

export interface TrialCriterion {
  criterionId: string;
  name: string;
  outcome: Outcome;
  results: GraderResult[];
}

export interface Turn {
  turn: number;
  // Null when the trial has no record of the message.
  user: string | null;
  target: string | null;
  errors: string[];
}

export interface TrialDetail {
  index: number;
  // How the trial ended: "succeeded", "abandoned", "error" or "timedOut".
  category: string;
  // Why a trial ended early.
  message: string;
  failureSource: string;
  attempt: number;
  turns: Turn[];
  conversationProblem: string | null;
  // One entry for each Criterion that has an outcome in the trial.
  criteria: TrialCriterion[];
}

export interface CaseRow {
  taskId: string;
  persona: string;
  scenario: string;
  personaDescription: string;
  scenarioDescription: string;
  trials: TrialDetail[];
  skipped: number;
  errored: number;
  // One entry for each column of the groups, in the same order. Null is a test case with no
  // result for that Criterion.
  cells: Array<CaseCell | null>;
}

export interface CaseTable {
  groups: CaseColumnGroup[];
  rows: CaseRow[];
  // The sums over every row.
  skipped: number;
  errored: number;
}

export interface UnmappedItem {
  outcome: Outcome;
  taskId: string;
  trialIndex: number;
  // Null when the record has one result.
  resultNumber: number | null;
  reason: string;
  // The recorded Grader and its arguments, as JSON text.
  settings: string;
}

export interface UnmappedResult {
  criterionId: string;
  grader: string;
  why: string;
  items: UnmappedItem[];
}

export interface ReportPage {
  target: string;
  score: ScoreFacts;
  specification: FeatureResult[];
  cases: CaseTable;
  unmapped: UnmappedResult[];
}

function rateOf(value: number | null | undefined, target: number): Rate {
  return value === null || value === undefined
    ? { kind: "no-result" }
    : { kind: "measured", percent: value, low: value < target };
}

function present<T>(value: T | undefined): value is T {
  return value !== undefined;
}

function passing(low: boolean[]): Passing | null {
  return low.length === 0
    ? null
    : { passing: low.filter((isLow) => !isLow).length, graded: low.length };
}

function scoreFacts(report: Report, cases: CaseTable): ScoreFacts {
  const target = report.passRateTarget;
  const rates = report.features
    .flatMap((feature) => feature.behaviours)
    .map((id) => report.behaviours[id])
    .filter(present)
    .map((behaviour) => behaviour.rate)
    .filter((rate) => rate !== null && rate !== undefined);
  const measured = cases.rows
    .map((row) =>
      row.cells.flatMap((cell) =>
        cell?.rate.kind === "measured" ? [cell.rate.low] : [],
      ),
    )
    .filter((cells) => cells.length > 0);
  return {
    passRate: rateOf(report.scores.graderPassRate.rate, target),
    target,
    behaviours: passing(rates.map((rate) => rate < target)),
    testCases: passing(measured.map((cells) => cells.some(Boolean))),
    date: report.date,
  };
}

type Row = Report["resultTable"]["rows"][number];
type Counts = { pass: number; fail: number; skip: number; error: number };

const personaOf = (report: Report, row: Row) =>
  report.names.P?.[row.persona] ?? row.persona;
const scenarioOf = (report: Report, row: Row) =>
  report.names.S?.[row.scenario] ?? row.scenario;

function outcomeOf(counts: Counts | undefined): Outcome | null {
  if (!counts) return null;
  if (counts.pass) return "passed";
  if (counts.fail) return "failed";
  if (counts.error) return "errored";
  return counts.skip ? "skipped" : null;
}

function criterionCases(report: Report, id: string): CriterionCase[] {
  return report.resultTable.rows.flatMap((row) => {
    const result = row.results?.[id];
    if (!result) return [];
    return [
      {
        taskId: row.task_id,
        persona: personaOf(report, row),
        scenario: scenarioOf(report, row),
        rate: rateOf(result.rate, report.passRateTarget),
        trials: (row.trials ?? []).flatMap((trial) => {
          const outcome = outcomeOf(trial.results?.[id]);
          return outcome ? [{ index: trial.trial_index, outcome }] : [];
        }),
      },
    ];
  });
}

const MEASUREMENT: Record<string, string> = {
  applicable: "Applicable",
  satisfied: "Satisfied",
};

function measurementName(key: string): string {
  return (
    MEASUREMENT[key] ??
    key.replace(/_/g, " ").replace(/^./, (first) => first.toUpperCase())
  );
}

function trialDetails(report: Report, row: Row): TrialDetail[] {
  return (row.trials ?? []).map((trial) => ({
    index: trial.trial_index,
    category: trial.category,
    message: trial.message || trial.stopReason,
    failureSource: trial.failureSource,
    attempt: trial.attempt,
    turns: (trial.conversation ?? []).map((turn) => ({
      turn: turn.turn,
      user: turn.user || null,
      target:
        !turn.target || /^\[unreadable: missing/.test(turn.target)
          ? null
          : turn.target,
      errors: turn.errors ?? [],
    })),
    conversationProblem: trial.conversationProblem ?? null,
    criteria: Object.entries(trial.results ?? {}).flatMap(([id, counts]) => {
      const outcome = outcomeOf(counts);
      if (!outcome) return [];
      const evidence = (report.criteria[id]?.evidence ?? [])
        .filter(
          (item) =>
            item.task_id === row.task_id &&
            item.trial_index === trial.trial_index,
        )
        .sort((a, b) => a.result_number - b.result_number);
      return [
        {
          criterionId: id,
          name: report.criteria[id]?.name ?? id,
          outcome,
          results: evidence.map((item) => {
            const threshold = item.grader_args?.threshold;
            return {
              outcome: item.outcome,
              score: item.score ?? null,
              reason: item.message,
              measurements: Object.entries(item.measurements ?? {}).map(
                ([key, value]) => ({ name: measurementName(key), value }),
              ),
              passMark: typeof threshold === "number" ? threshold : null,
            };
          }),
        },
      ];
    }),
  }));
}

function specificationResults(report: Report): FeatureResult[] {
  const target = report.passRateTarget;
  const criterion = (id: string): CriterionResult | undefined => {
    const found = report.criteria[id];
    if (!found) return undefined;
    const threshold = found.grader_args?.threshold;
    return {
      id,
      name: found.name,
      description: found.description,
      rate: rateOf(found.rate, target),
      passed: found.pass,
      graded: found.pass + found.fail,
      skipped: found.skip,
      errored: found.error,
      graderName: found.grader_name,
      judgeModels: found.judge_models ?? [],
      passMark: typeof threshold === "number" ? threshold : null,
      meanScore: found.mean_score ?? null,
      cases: criterionCases(report, id),
    };
  };
  const behaviour = (id: string): BehaviourResult | undefined => {
    const found = report.behaviours[id];
    return (
      found && {
        id,
        label: found.label,
        statement: found.statement,
        rate:
          found.priority === false || found.criteria.length === 0
            ? { kind: "not-measured" }
            : rateOf(found.rate, target),
        criteria: found.criteria.map(criterion).filter(present),
      }
    );
  };
  return report.features.map((feature) => ({
    id: feature.id,
    name: feature.name,
    rate: rateOf(feature.rate, target),
    behaviours: feature.behaviours.map(behaviour).filter(present),
  }));
}

function caseTable(report: Report): CaseTable {
  const target = report.passRateTarget;
  const groups = report.resultTable.features
    .filter((feature) => feature.columns.length > 0)
    .map((feature) => ({
      featureId: feature.id,
      name: feature.name,
      columns: feature.columns.map(({ criterion }) => ({
        criterionId: criterion,
        label: report.criteria[criterion]?.name ?? criterion,
      })),
    }));
  const columns = groups.flatMap((group) => group.columns);
  const rows = report.resultTable.rows.map((row) => {
    const results = row.results ?? {};
    const counted = Object.values(results);
    return {
      taskId: row.task_id,
      persona: personaOf(report, row),
      scenario: scenarioOf(report, row),
      personaDescription: report.describe.P?.[row.persona] ?? "",
      scenarioDescription: report.describe.S?.[row.scenario] ?? "",
      trials: trialDetails(report, row),
      skipped: counted.reduce((sum, result) => sum + result.skip, 0),
      errored: counted.reduce((sum, result) => sum + result.error, 0),
      cells: columns.map(({ criterionId }) => {
        const result = results[criterionId];
        if (!result) return null;
        const interval = result.confidence_interval;
        return {
          rate: rateOf(result.rate, target),
          passed: result.pass,
          failed: result.fail,
          skipped: result.skip,
          errored: result.error,
          interval: interval
            ? {
                lower: Math.round(interval.lower * 100),
                upper: Math.round(interval.upper * 100),
              }
            : null,
        };
      }),
    };
  });
  return {
    groups,
    rows,
    skipped: rows.reduce((sum, row) => sum + row.skipped, 0),
    errored: rows.reduce((sum, row) => sum + row.errored, 0),
  };
}

function unmappedResults(report: Report): UnmappedResult[] {
  return report.unmapped.map((group) => ({
    criterionId: group.criterion_id,
    grader: group.grader_fqn,
    why: group.why,
    items: (group.records ?? []).flatMap((record) =>
      record.results.map((result, index) => ({
        outcome: result.outcome,
        taskId: record.task_id,
        trialIndex: record.trial_index,
        resultNumber: record.results.length > 1 ? index + 1 : null,
        reason: result.reason,
        settings: JSON.stringify(
          { grader_fqn: record.grader_fqn, grader_args: record.grader_args },
          null,
          1,
        ),
      })),
    ),
  }));
}

export function reportPage(report: Report): ReportPage {
  const cases = caseTable(report);
  return {
    target: report.target,
    score: scoreFacts(report, cases),
    specification: specificationResults(report),
    cases,
    unmapped: unmappedResults(report),
  };
}
