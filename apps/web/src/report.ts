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
  // Null when no Behaviour has a rate.
  behavioursBelowTarget: { below: number; graded: number } | null;
  // Null when no trial was attempted.
  trialsReached: { successful: number; attempted: number } | null;
  testCases: number;
}

export interface CriterionResult {
  id: string;
  name: string;
  rate: Rate;
  passed: number;
  // Passed plus failed results.
  graded: number;
  skipped: number;
  errored: number;
}

export interface BehaviourResult {
  id: string;
  label: string;
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
  // The confidence interval in whole percent.
  interval: { lower: number; upper: number } | null;
}

export interface CaseRow {
  taskId: string;
  persona: string;
  scenario: string;
  skipped: number;
  errored: number;
  // One entry for each column of the groups, in the same order. Null is a test case with no
  // result for that Criterion.
  cells: Array<CaseCell | null>;
}

export interface CaseTable {
  groups: CaseColumnGroup[];
  rows: CaseRow[];
}

export interface UnmappedResult {
  criterionId: string;
  graderName: string;
  why: string;
}

export interface ReportPage {
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

function scoreFacts(report: Report): ScoreFacts {
  const target = report.passRateTarget;
  const rates = report.features
    .flatMap((feature) => feature.behaviours)
    .map((id) => report.behaviours[id])
    .filter(present)
    .map((behaviour) => behaviour.rate)
    .filter((rate) => rate !== null && rate !== undefined);
  const { attempted, successful } = report.trials;
  return {
    passRate: rateOf(report.scores.graderPassRate.rate, target),
    target,
    behavioursBelowTarget:
      rates.length === 0
        ? null
        : {
            below: rates.filter((rate) => rate < target).length,
            graded: rates.length,
          },
    trialsReached: attempted === 0 ? null : { successful, attempted },
    testCases: report.plan.tasks.length,
  };
}

function specificationResults(report: Report): FeatureResult[] {
  const target = report.passRateTarget;
  const criterion = (id: string): CriterionResult | undefined => {
    const found = report.criteria[id];
    return (
      found && {
        id,
        name: found.name,
        rate: rateOf(found.rate, target),
        passed: found.pass,
        graded: found.pass + found.fail,
        skipped: found.skip,
        errored: found.error,
      }
    );
  };
  const behaviour = (id: string): BehaviourResult | undefined => {
    const found = report.behaviours[id];
    return (
      found && {
        id,
        label: found.label,
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
      persona: report.names.P?.[row.persona] ?? row.persona,
      scenario: report.names.S?.[row.scenario] ?? row.scenario,
      skipped: counted.reduce((sum, result) => sum + result.skip, 0),
      errored: counted.reduce((sum, result) => sum + result.error, 0),
      cells: columns.map(({ criterionId }) => {
        const result = results[criterionId];
        if (!result) return null;
        const interval = result.confidence_interval;
        return {
          rate: rateOf(result.rate, target),
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
  return { groups, rows };
}

export function reportPage(report: Report): ReportPage {
  return {
    score: scoreFacts(report),
    specification: specificationResults(report),
    cases: caseTable(report),
    unmapped: report.unmapped.map((group) => ({
      criterionId: group.criterion_id,
      graderName: group.grader_name,
      why: group.why,
    })),
  };
}
