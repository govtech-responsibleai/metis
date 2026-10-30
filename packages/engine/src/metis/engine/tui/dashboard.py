"""Top panel: progress bars, scenario/trial status table."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Group, RenderableType
from rich.progress_bar import ProgressBar
from rich.table import Table
from rich.text import Text

if TYPE_CHECKING:
    from .state import SimulationState


def _format_elapsed(seconds: float) -> str:
    h = int(seconds) // 3600
    m = (int(seconds) % 3600) // 60
    s = int(seconds) % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    m = int(seconds) // 60
    s = int(seconds) % 60
    return f"{m}m{s:02d}s"


def render_dashboard(state: SimulationState) -> RenderableType:
    """Build the dashboard renderable from current state."""
    parts: list[RenderableType] = []

    # Header
    header = Text()
    header.append("METIS Engine Simulate", style="bold")
    header.append(f" — {state.experiment_id}\n")
    header.append(f"Elapsed: {_format_elapsed(state.elapsed_seconds)}\n")
    parts.append(header)

    # Progress bars
    total_scenarios = len(state.scenarios)
    total_trials = state.total_trials

    scenarios_table = Table.grid(padding=(0, 1))
    scenarios_table.add_row(
        Text("Scenarios:", style="dim"),
        ProgressBar(
            total=total_scenarios, completed=state.completed_scenarios, width=20
        ),
        Text(f"{state.completed_scenarios}/{total_scenarios}"),
    )
    scenarios_table.add_row(
        Text("Trials:", style="dim"),
        ProgressBar(total=total_trials, completed=state.completed_trials, width=20),
        Text(f"{state.completed_trials}/{total_trials}"),
    )
    parts.append(scenarios_table)
    parts.append(Text(""))

    # Active scenarios (may be multiple with concurrent workers)
    active_scenarios = [sc for sc in state.scenarios if sc.phase == "active"]
    for active in active_scenarios:
        active_text = Text()
        active_text.append(f"Ongoing scenario: {active.scenario_id}\n", style="bold")
        for trial in active.trials:
            worker_tag = f"[w{trial.worker_id}] " if trial.worker_id is not None else ""
            if trial.phase == "simulating":
                turn_info = ""
                if trial.current_turn is not None:
                    turn_info = f"[turn {trial.current_turn}/{trial.max_turns}]"
                detail = trial.turn_detail or ""
                active_text.append(
                    f"  ● {worker_tag}{trial.persona_id} simulating "
                    f"{turn_info} {detail}\n",
                    style="yellow",
                )
            elif trial.phase == "completed":
                dur = _format_duration(trial.duration_seconds or 0)
                active_text.append(
                    f"  ✓ {worker_tag}{trial.persona_id} "
                    f"[done trial {trial.trial_index}/{trial.num_trials}]  {dur}\n",
                    style="green",
                )
            elif trial.phase == "failed":
                active_text.append(
                    f"  ✗ {worker_tag}{trial.persona_id} [failed: {trial.stop_reason}]\n",
                    style="red",
                )
            elif trial.phase == "pending":
                active_text.append(
                    f"  ○ {trial.persona_id} [pending]\n",
                    style="dim",
                )
        parts.append(active_text)

    # Completed scenarios
    completed = [sc for sc in state.scenarios if sc.phase == "completed"]
    if completed:
        comp_text = Text()
        comp_text.append("Completed scenarios:\n", style="dim")
        for sc in completed:
            trial_count = len(sc.trials)
            total_dur = sum(t.duration_seconds or 0 for t in sc.trials)
            comp_text.append(
                f"  ✓ {sc.scenario_id} ({trial_count} trial{'s' if trial_count > 1 else ''})  "
                f"{_format_duration(total_dur)}\n",
                style="green",
            )
        parts.append(comp_text)

    # Pending count
    pending = state.pending_scenario_count
    if pending > 0:
        parts.append(
            Text(
                f"Pending: {pending} scenario{'s' if pending > 1 else ''}", style="dim"
            )
        )

    return Group(*parts)
