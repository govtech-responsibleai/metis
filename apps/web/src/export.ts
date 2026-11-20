import type {
  ConnectionTransport,
  InterviewState,
  Specification,
} from "./transport/api.ts";

const RUNNER_FACTORY_REFS: Record<ConnectionTransport, string> = {
  http: "metis.engine.simulation.runners.http.HttpRunnerFactory",
  browser: "metis.engine.simulation.runners.browser.BrowserRunnerFactory",
};

const TARGET_BINDING_FILE = "target-binding.yaml";

// The Specification that the package route exports for an Interview, so the YAML view shows
// the same document as the download. It mirrors `selected_specification` in
// metis.wizard.application.readiness and `connected_specification` in
// metis.wizard.application.connection.
export function exportedSpecification(state: InterviewState): Specification {
  const excluded = new Set(state.excluded_tasks ?? []);
  const tasks = state.specification.tasks.filter(
    (task) => !excluded.has(task.id),
  );
  const used = new Set(tasks.map((task) => task.scenario_ref));
  const selected: Specification = {
    ...state.specification,
    tasks,
    scenarios: state.specification.scenarios.filter((scenario) =>
      used.has(scenario.id),
    ),
  };
  const connection = state.context.connection;
  if (!connection) return selected;
  return {
    ...selected,
    runner_factory_ref: RUNNER_FACTORY_REFS[connection.transport],
    target_binding: TARGET_BINDING_FILE,
  };
}
