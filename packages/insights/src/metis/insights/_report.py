"""Join scores to the frozen specification by Task, Trial, and Criterion ID.

A criterion pools its grader runs. Each run contributes one verdict. Every level above
the criterion takes the unweighted mean of its evaluated children.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, NamedTuple

from metis.core import execution_layout
from metis.core.logging import get_logger
from metis.core.trace_processing import Problem
from metis.core.trials import TrialRecord
from metis.insights._aggregation import (
    OutcomeCounts,
    mean_of,
    summarize_run,
    wilson_interval,
)
from metis.insights._conversation import conversation_rows, read_turns

if TYPE_CHECKING:
    from pathlib import Path

    from metis.core.reporting import EvaluationResults, GraderRecord
    from metis.core.trials import TrialConfig

logger = get_logger(__name__)

Row = Mapping[str, Any]
# A rate below this is shown in red on the page.
PASS_RATE_TARGET = 70

_OUTCOME_LABELS = {
    "passed": "pass",
    "failed": "fail",
    "skipped": "skip",
    "errored": "error",
}


class _RunKey(NamedTuple):
    task_id: str
    trial_index: int
    session_id: str
    criterion_id: str


@dataclass
class _CriterionRuns:
    counts: OutcomeCounts = field(default_factory=OutcomeCounts)
    breakdown: dict[str, dict[str, OutcomeCounts]] = field(
        default_factory=lambda: {
            "P": defaultdict(OutcomeCounts),
            "S": defaultdict(OutcomeCounts),
        }
    )
    evidence: list[dict[str, Any]] = field(default_factory=list)
    fqns: set[str] = field(default_factory=set)
    models: set[str] = field(default_factory=set)


@dataclass
class _AxisBucket:
    counts: OutcomeCounts = field(default_factory=OutcomeCounts)
    sessions: set[str] = field(default_factory=set)
    behaviours: set[str] = field(default_factory=set)
    graders: set[str] = field(default_factory=set)
    partners: set[str] = field(default_factory=set)


@dataclass
class _UnmappedRuns:
    counts: OutcomeCounts = field(default_factory=OutcomeCounts)
    records: list[GraderRecord] = field(default_factory=list)


@dataclass
class _RunAggregation:
    criteria: dict[str, _CriterionRuns]
    axes: dict[str, dict[str, _AxisBucket]] = field(
        default_factory=lambda: {
            "P": defaultdict(_AxisBucket),
            "S": defaultdict(_AxisBucket),
        }
    )
    trial_counts: dict[_RunKey, OutcomeCounts] = field(
        default_factory=lambda: defaultdict(OutcomeCounts)
    )
    case_counts: dict[tuple[str, str], OutcomeCounts] = field(
        default_factory=lambda: defaultdict(OutcomeCounts)
    )
    unmapped: dict[tuple[str, str, str], _UnmappedRuns] = field(
        default_factory=lambda: defaultdict(_UnmappedRuns)
    )
    scored_by_task: dict[str, set[str]] = field(
        default_factory=lambda: defaultdict(set)
    )


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


def load_report_sources(
    run_dir: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    specification_path = run_dir / execution_layout.SPECIFICATION
    if not specification_path.is_file():
        return None
    try:
        import yaml

        specification = yaml.safe_load(specification_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning(
            "specification_unreadable", path=str(specification_path), error=str(exc)
        )
        return None

    trial_outcomes = _load_trial_records(run_dir)
    return specification, trial_outcomes


def _load_trial_records(run_dir: Path) -> list[dict[str, Any]]:
    trials: list[dict[str, Any]] = []
    for record_path in sorted(
        (run_dir / execution_layout.TRIALS).glob(f"*/{execution_layout.TRIAL_RECORD}")
    ):
        try:
            record = TrialRecord.load_file(record_path)
        except (OSError, ValueError) as exc:
            # ValidationError is a ValueError. A record the model rejects is dropped from
            # the report, so say so where it can be seen.
            logger.warning("record_unreadable", path=str(record_path), error=str(exc))
            continue
        config = record.config
        outcome = record.outcome
        session = record.target_session_id
        stop_reason = outcome.stop_reason or "unknown"
        failure_source = _failure_source(outcome.failure_source)
        message = stop_reason if stop_reason == "goal_achieved" else None
        message = outcome.failure_message or message
        if stop_reason == "goal_achieved":
            failure_source = "outcome"

        if stop_reason == "system_error" and (not failure_source or not message):
            legacy_source, legacy_message = _legacy_failure_details(
                run_dir, record_path, config
            )
            failure_source = failure_source or legacy_source
            message = message or legacy_message

        if not failure_source:
            if stop_reason == "user_abandoned":
                failure_source = "userAgent"
            else:
                failure_source = "evaluationRunner"
        trials.append(
            {
                "id": record_path.parent.name,
                "task_id": config.task_id,
                "trial_index": config.trial_index,
                "session": session or "",
                "persona": config.persona,
                "scenario": config.scenario,
                "stopReason": stop_reason,
                "message": message or stop_reason,
                "failureSource": failure_source,
                "simulated_turns_completed": outcome.simulated_turns_completed,
                "duration": outcome.duration_seconds,
                # A retried run is a run whose comparability is worth a second
                # look: a retry is a free do-over only if the failure was
                # independent of what the run was doing, which is not obvious
                # for ConsecutiveFailureEscalation.
                "attempt": record.attempt_number,
                **_conversation(run_dir, session),
            }
        )
    return trials


def _conversation(run_dir: Path, session: str | None) -> dict[str, Any]:
    """The trial's conversation fields: its turns, or why there are none."""
    if not session:
        return {
            "conversation": [],
            "conversationProblem": "the trial record names no target session",
        }
    session_turns = read_turns(run_dir, session)
    if isinstance(session_turns, Problem):
        return {"conversation": [], "conversationProblem": session_turns.detail}
    return {
        "conversation": conversation_rows(session_turns),
    }


def _failure_source(value: object) -> str | None:
    """Map recorded failure-source names to the report vocabulary."""
    if value is None:
        return None
    normalised = str(value).strip().lower().replace("-", "_")
    return {
        "product": "target",
        "target": "target",
        "user_agent": "userAgent",
        "useragent": "userAgent",
        "evaluation_runner": "evaluationRunner",
        "eval_runner": "evaluationRunner",
        "runner": "evaluationRunner",
        "system": "evaluationRunner",
    }.get(normalised)


def _legacy_failure_details(
    run_dir: Path, record_path: Path, config: TrialConfig
) -> tuple[str | None, str | None]:
    """Read an explicit error source from old simulation logs when available.

    Older records stored only ``system_error``. Their matching run log still states
    whether the user-agent LLM failed or the evaluation runner crashed. This fallback
    lets old reports use that fact without guessing from the error text.
    """
    _, separator, trial_text = record_path.parent.name.rpartition("-")
    scenario = config.scenario
    persona = config.persona
    if not separator or not trial_text.isdigit() or not scenario or not persona:
        return None, None
    log_path = (
        run_dir
        / execution_layout.LOGS
        / f"simulate-{scenario}_{persona}-{int(trial_text):02d}.log"
    )
    try:
        log_text = log_path.read_text(encoding="utf-8")
    except OSError:
        return None, None

    user_agent_marker = "STOP: system_error (user agent LLM failed: "
    marker_at = log_text.rfind(user_agent_marker)
    if marker_at >= 0:
        message = log_text[marker_at + len(user_agent_marker) :]
        message = message.split("\n[", 1)[0].strip()
        if message.endswith(")"):
            message = message[:-1].rstrip()
        return "userAgent", message or None

    runner_marker = f"unexpected crash for {scenario} × {persona}: "
    marker_at = log_text.rfind(runner_marker)
    if marker_at >= 0:
        message = log_text[marker_at + len(runner_marker) :]
        message = message.split("\n[", 1)[0].strip()
        return "evaluationRunner", message or None
    return None, None


def _rounded(rate: float | None) -> int | None:
    return round(100 * rate) if rate is not None else None


def _state(counts: OutcomeCounts) -> str | None:
    if counts.failed:
        return "fail"
    if counts.passed:
        return "pass"
    if counts.errored:
        return "error"
    return None


def _clean_prose(text: str | None) -> str:
    return (text or "").replace("—", ",").strip()


def _record_match(
    record: GraderRecord,
    tasks: Mapping[str, Row],
    behaviour_of: Mapping[str, str],
) -> tuple[Row | None, str | None]:
    task = tasks.get(record.task_id)
    if task is None:
        return None, "No task matches this result."
    if record.scenario_id != task["scenario_ref"]:
        return None, "The result scenario differs from the task scenario."
    behaviour = behaviour_of.get(record.criterion_id)
    if behaviour is None:
        return None, "No criterion matches this result."
    if behaviour not in task.get("behaviour_refs", []):
        return None, "The task does not measure this criterion's behaviour."
    return task, None


def _criterion_index(
    specification: Mapping[str, Any],
) -> tuple[dict[str, Row], dict[str, str]]:
    criteria: dict[str, Row] = {}
    behaviour_of: dict[str, str] = {}
    for feature in specification.get("features") or []:
        for behaviour in feature.get("behaviours") or []:
            for criterion in behaviour.get("criteria") or []:
                criteria[criterion["id"]] = criterion
                behaviour_of[criterion["id"]] = behaviour["id"]
    return criteria, behaviour_of


def _trial_rows(
    specification: Mapping[str, Any],
    tasks: Mapping[str, Row],
    trial_outcomes: Sequence[Row] | None,
) -> list[dict[str, Any]]:
    trials = []
    for item in trial_outcomes or []:
        stop = str(item.get("stopReason") or "unknown")
        category = (
            "succeeded"
            if stop == "goal_achieved"
            else "timedOut"
            if "timeout" in stop
            else "error"
            if "error" in stop
            else "abandoned"
        )
        task = tasks.get(str(item.get("task_id") or ""))
        feature_names = [
            feature.get("name", feature["id"])
            for feature in specification.get("features") or []
            if task
            and any(
                b["id"] in task.get("behaviour_refs", [])
                for b in feature.get("behaviours") or []
            )
        ]
        trials.append({**item, "category": category, "features": feature_names})
    return trials


def _aggregate_runs(
    records: Sequence[GraderRecord],
    criteria: Mapping[str, Row],
    tasks: Mapping[str, Row],
    behaviour_of: Mapping[str, str],
    trials: Sequence[Row],
    *,
    has_trial_outcomes: bool,
) -> _RunAggregation:
    trial_keys = {
        (item["task_id"], item["trial_index"], item["session"]): item
        for item in trials
        if item.get("session")
    }
    seen: set[_RunKey] = set()
    runs = _RunAggregation({cid: _CriterionRuns() for cid in criteria})
    for record in records:
        persona = ""
        scenario = ""
        identity = _RunKey(
            record.task_id,
            record.trial_index,
            record.session_id,
            record.criterion_id,
        )
        if identity in seen:
            raise ValueError(f"Duplicate grader record for {tuple(identity)!r}")
        seen.add(identity)
        task, reason = _record_match(record, tasks, behaviour_of)
        trial = trial_keys.get((record.task_id, record.trial_index, record.session_id))
        if task is not None and has_trial_outcomes and trial is None:
            reason = "No saved trial matches the task, trial index, and session."
        if (
            task is not None
            and trial is not None
            and (
                trial["persona"] != task["persona_ref"]
                or trial["scenario"] != task["scenario_ref"]
            )
        ):
            reason = "The saved trial persona or scenario differs from the task."
        if reason is not None:
            key = (record.criterion_id, record.grader_fqn, reason)
            runs.unmapped[key].records.append(record)
        else:
            cid = record.criterion_id
            persona = task["persona_ref"] if task else ""
            scenario = task["scenario_ref"] if task else ""
            runs.criteria[cid].fqns.add(record.grader_fqn)
            model = record.grader_args.get("model")
            if isinstance(model, str) and model:
                runs.criteria[cid].models.add(model)
        summary = summarize_run(record)
        if reason is not None:
            runs.unmapped[(record.criterion_id, record.grader_fqn, reason)].counts.add(
                summary
            )
            continue
        cid = record.criterion_id
        runs.criteria[cid].counts.add(summary)
        if summary.outcome in ("passed", "failed"):
            runs.scored_by_task[record.task_id].add(cid)
        runs.criteria[cid].breakdown["P"][persona].add(summary)
        runs.criteria[cid].breakdown["S"][scenario].add(summary)
        runs.trial_counts[identity].add(summary)
        runs.case_counts[(record.task_id, cid)].add(summary)
        for axis, name, partner in (
            ("P", persona, scenario),
            ("S", scenario, persona),
        ):
            bucket = runs.axes[axis][name]
            bucket.counts.add(summary)
            if record.session_id:
                bucket.sessions.add(record.session_id)
            bucket.behaviours.add(behaviour_of[cid])
            bucket.graders.add(cid)
            bucket.partners.add(partner)
        for index, result in enumerate(record.results, 1):
            runs.criteria[cid].evidence.append(
                {
                    "task_id": record.task_id,
                    "trial_index": record.trial_index,
                    "session": record.session_id,
                    "criterion_id": cid,
                    "grader_fqn": record.grader_fqn,
                    "grader_args": record.grader_args,
                    "run_score": summary.score,
                    "run_threshold": summary.threshold,
                    "run_outcome": summary.outcome,
                    "result_number": index,
                    "status": _OUTCOME_LABELS[result.outcome],
                    "outcome": result.outcome,
                    "score": result.score,
                    "message": result.reason,
                    "persona": persona,
                    "scenario": scenario,
                }
            )

    return runs


def _criterion_cells(
    runs: _CriterionRuns, axis: str, order: Sequence[str]
) -> list[dict[str, Any] | None]:
    return [
        {
            **runs.breakdown[axis][name].as_dict(),
            "rate": _rounded(runs.breakdown[axis][name].pass_rate),
            "n": runs.breakdown[axis][name].evaluated,
        }
        if runs.breakdown[axis][name].total
        else None
        for name in order
    ]


def _criterion_rows(
    criteria: Mapping[str, Row],
    runs: Mapping[str, _CriterionRuns],
    asked: Mapping[str, set[str]],
    personas: list[str],
    scenarios: list[str],
) -> dict[str, Any]:
    out_criteria = {}
    for cid, criterion in criteria.items():
        criterion_runs = runs[cid]
        counts = criterion_runs.counts
        configured_fqn = criterion.get("grader_fqn") or ""
        fqns = criterion_runs.fqns
        # A Criterion names one grader, so its records share one FQN. Fall back to the
        # specification when no record matched.
        fqn = next(iter(fqns)) if len(fqns) == 1 else configured_fqn
        if not configured_fqn and not fqns:
            blank = {
                "cause": "no grader",
                "note": "The specification names no grader for this criterion.",
            }
        elif cid not in {item for selected in asked.values() for item in selected}:
            blank = {"cause": "not asked", "note": "No task measures this criterion."}
        elif counts.errored:
            blank = {
                "cause": "grader error",
                "note": f"{counts.errored} grader runs errored.",
            }
        elif counts.skipped:
            blank = {
                "cause": "all skipped",
                "note": f"{counts.skipped} grader runs skipped.",
            }
        else:
            blank = {
                "cause": "no result",
                "note": "No result was recorded for this criterion.",
            }
        out_criteria[cid] = {
            "name": criterion.get("name") or cid,
            "description": criterion["description"],
            "grader_name": fqn.rsplit(".", 1)[-1] if fqn else "",
            "grader_fqn": fqn or None,
            "grader_args": criterion.get("grader_args") or {},
            "judge_models": sorted(criterion_runs.models),
            **counts.as_dict(),
            "rate": _rounded(counts.pass_rate),
            "mean_score": counts.average_score,
            "status": _state(counts),
            "blank": blank if counts.pass_rate is None else None,
            "P": _criterion_cells(criterion_runs, "P", personas),
            "S": _criterion_cells(criterion_runs, "S", scenarios),
            "evidence": criterion_runs.evidence,
        }
    return out_criteria


def _feature_rollups(
    specification: Mapping[str, Any], runs: Mapping[str, _CriterionRuns]
) -> tuple[
    dict[str, Any], list[dict[str, Any]], list[tuple[float | None, float | None]]
]:
    out_behaviours = {}
    behaviour_counts = {}
    behaviour_scores: dict[str, tuple[float | None, float | None]] = {}
    for feature in specification.get("features") or []:
        for behaviour in feature.get("behaviours") or []:
            counts = OutcomeCounts()
            children = [
                runs[item["id"]].counts for item in behaviour.get("criteria") or []
            ]
            for child in children:
                counts.merge(child)
            behaviour_counts[behaviour["id"]] = counts
            rate = mean_of(child.pass_rate for child in children)
            mean = mean_of(child.average_score for child in children)
            behaviour_scores[behaviour["id"]] = (rate, mean)
            statement = _clean_prose(behaviour.get("description"))
            out_behaviours[behaviour["id"]] = {
                "label": behaviour["name"],
                "statement": statement,
                "detail": statement.partition(". ")[2],
                "priority": behaviour["measured"],
                "criteria": [item["id"] for item in behaviour.get("criteria") or []],
                **counts.as_dict(),
                "rate": _rounded(rate),
                "mean_score": mean,
                "status": _state(counts),
            }
    out_features = []
    feature_scores: list[tuple[float | None, float | None]] = []
    for feature in specification.get("features") or []:
        counts = OutcomeCounts()
        children = [item["id"] for item in feature.get("behaviours") or []]
        for bid in children:
            counts.merge(behaviour_counts[bid])
        rate = mean_of(behaviour_scores[bid][0] for bid in children)
        mean = mean_of(behaviour_scores[bid][1] for bid in children)
        feature_scores.append((rate, mean))
        out_features.append(
            {
                "id": feature["id"],
                "name": feature.get("name", feature["id"]),
                "behaviours": children,
                **counts.as_dict(),
                "rate": _rounded(rate),
                "mean_score": mean,
                "status": _state(counts),
            }
        )

    return out_behaviours, out_features, feature_scores


def _axis_rows(
    runs: _RunAggregation, axis: str, order: Sequence[str], partner_total: int
) -> list[dict[str, Any]]:
    return [
        {
            "id": name,
            **runs.axes[axis][name].counts.as_dict(),
            "rate": _rounded(
                mean_of(
                    runs.criteria[cid].breakdown[axis][name].pass_rate
                    for cid in runs.criteria
                )
            ),
            "ran": runs.axes[axis][name].counts.evaluated,
            "sessions": len(runs.axes[axis][name].sessions),
            "behaviours": len(runs.axes[axis][name].behaviours),
            "graders": len(runs.axes[axis][name].graders),
            "partners": len(runs.axes[axis][name].partners),
            "partnerTotal": partner_total,
        }
        for name in order
    ]


def _result_cell(bucket: OutcomeCounts) -> dict[str, Any]:
    return {
        **bucket.as_dict(),
        "evaluated": bucket.evaluated,
        "rate": _rounded(bucket.pass_rate),
        "mean_score": bucket.average_score,
        "status": _state(bucket),
    }


def _case_result_cell(bucket: OutcomeCounts) -> dict[str, Any]:
    interval = wilson_interval(bucket.passed, bucket.failed)
    return {
        **_result_cell(bucket),
        "confidence_interval": interval.model_dump() if interval is not None else None,
    }


def _result_table(
    specification: Mapping[str, Any],
    tasks: Mapping[str, Row],
    criteria: Mapping[str, Row],
    out_criteria: Mapping[str, Row],
    trials: Sequence[Row],
    runs: _RunAggregation,
) -> dict[str, Any]:
    table_features = []
    for feature in specification.get("features") or []:
        columns = [
            {
                "criterion": criterion["id"],
                "grader_name": out_criteria[criterion["id"]]["grader_name"],
                "grader_fqn": out_criteria[criterion["id"]]["grader_fqn"],
            }
            for behaviour in feature.get("behaviours") or []
            for criterion in behaviour.get("criteria") or []
            if any(key[1] == criterion["id"] for key in runs.case_counts)
        ]
        if columns:
            table_features.append(
                {
                    "id": feature["id"],
                    "name": feature.get("name", feature["id"]),
                    "columns": columns,
                }
            )

    table_rows = []
    for task_id, task in tasks.items():
        task_trials = [trial for trial in trials if trial["task_id"] == task_id]
        results_by_criterion = {
            cid: _case_result_cell(runs.case_counts[(task_id, cid)])
            for cid in criteria
            if (task_id, cid) in runs.case_counts
        }
        if not task_trials and not results_by_criterion:
            continue
        table_rows.append(
            {
                "task_id": task_id,
                "persona": task["persona_ref"],
                "scenario": task["scenario_ref"],
                "results": results_by_criterion,
                "trials": [
                    {
                        **trial,
                        "results": {
                            cid: _result_cell(bucket)
                            for cid in criteria
                            if (
                                bucket := runs.trial_counts.get(
                                    _RunKey(
                                        trial["task_id"],
                                        trial["trial_index"],
                                        trial["session"],
                                        cid,
                                    )
                                )
                            )
                            is not None
                        },
                    }
                    for trial in task_trials
                ],
            }
        )
    return {"features": table_features, "rows": table_rows}


def _plan_tasks(
    tasks: Mapping[str, Row],
    trials: Sequence[Row],
    asked: Mapping[str, set[str]],
    scored_by_task: Mapping[str, set[str]],
) -> list[dict[str, Any]]:
    plan_tasks = []
    for task_id, task in tasks.items():
        plan_tasks.append(
            {
                "id": task_id,
                "scenario": task["scenario_ref"],
                "personas": [task["persona_ref"]],
                "trials": task["num_trials"],
                "trialsPlanned": task["num_trials"],
                "trialsRun": len(
                    {
                        (t["task_id"], t["trial_index"])
                        for t in trials
                        if t["task_id"] == task_id
                    }
                ),
                "personasRun": [task["persona_ref"]]
                if any(t["task_id"] == task_id for t in trials)
                else [],
                "gradersAsked": len(asked[task_id]),
                "gradersScored": len(scored_by_task[task_id]),
            }
        )
    return plan_tasks


def build_report(
    specification: Mapping[str, Any],
    results: EvaluationResults,
    *,
    timestamp: str = "",
    trial_outcomes: Sequence[Row] | None = None,
) -> dict[str, Any]:
    criteria, behaviour_of = _criterion_index(specification)
    tasks: dict[str, Row] = {
        task["id"]: task for task in specification.get("tasks") or []
    }
    personas = [item["id"] for item in specification.get("personas") or []]
    scenarios = [item["id"] for item in specification.get("scenarios") or []]
    trials = _trial_rows(specification, tasks, trial_outcomes)
    runs = _aggregate_runs(
        results.records,
        criteria,
        tasks,
        behaviour_of,
        trials,
        has_trial_outcomes=bool(trial_outcomes),
    )
    asked = {
        task_id: {
            cid
            for cid, bid in behaviour_of.items()
            if bid in task.get("behaviour_refs", [])
        }
        for task_id, task in tasks.items()
    }
    out_criteria = _criterion_rows(criteria, runs.criteria, asked, personas, scenarios)
    out_behaviours, out_features, feature_scores = _feature_rollups(
        specification, runs.criteria
    )
    matched = OutcomeCounts()
    for bucket in runs.criteria.values():
        matched.merge(bucket.counts)
    successful = sum(trial["category"] == "succeeded" for trial in trials)
    result_table = _result_table(
        specification, tasks, criteria, out_criteria, trials, runs
    )
    plan_tasks = _plan_tasks(tasks, trials, asked, runs.scored_by_task)
    return {
        "target": (specification.get("target") or {}).get("name", "the target"),
        "run": results.run_id,
        "date": timestamp[:10],
        "sessions": len(
            {record.session_id for record in results.records if record.session_id}
        ),
        "results": sum(len(record.results) for record in results.records),
        "latency": results.latency_seconds,
        "timings": results.timings,
        "trials": {
            "attempted": len(trials),
            "successful": successful,
            "rate": _rounded(successful / len(trials)) if trials else None,
            "items": trials,
        },
        "scores": {
            "graderPassRate": {
                "rate": _rounded(mean_of(rate for rate, _ in feature_scores)),
                "mean_score": mean_of(mean for _, mean in feature_scores),
                **matched.as_dict(),
                "ran": matched.evaluated,
                "skip": matched.skipped,
                "error": matched.errored,
            },
            "trialSuccess": {
                "rate": _rounded(successful / len(trials)) if trials else None,
                "successful": successful,
                "attempted": len(trials),
            },
        },
        "plan": {"personas": personas, "tasks": plan_tasks},
        "personas": personas,
        "scenarios": scenarios,
        "passRateTarget": PASS_RATE_TARGET,
        "names": {
            axis: {item["id"]: item.get("name") or item["id"] for item in items}
            for axis, items in (
                ("P", specification.get("personas") or []),
                ("S", specification.get("scenarios") or []),
            )
        },
        "describe": {
            "P": {
                item["id"]: _clean_prose(item.get("description"))
                for item in specification.get("personas") or []
            },
            "S": {
                item["id"]: _clean_prose(item.get("description"))
                for item in specification.get("scenarios") or []
            },
        },
        "axes": {
            "P": _axis_rows(runs, "P", personas, len(scenarios)),
            "S": _axis_rows(runs, "S", scenarios, len(personas)),
        },
        "behaviourTotal": len(out_behaviours),
        "personasRun": sorted({trial["persona"] for trial in trials}),
        "scenariosRun": sorted({trial["scenario"] for trial in trials}),
        "features": out_features,
        "behaviours": out_behaviours,
        "criteria": out_criteria,
        "resultTable": result_table,
        "unmapped": [
            {
                "criterion_id": cid,
                "grader_name": fqn.rsplit(".", 1)[-1],
                "grader_fqn": fqn,
                **bucket.counts.as_dict(),
                "why": reason,
                "records": [record.model_dump() for record in bucket.records],
            }
            for (cid, fqn, reason), bucket in sorted(runs.unmapped.items())
        ],
        "unresolved": [
            f"{cid} / {fqn}: {reason}" for cid, fqn, reason in sorted(runs.unmapped)
        ],
    }
