import {
  api,
  store,
  type EngineRunAccepted,
  type ExperimentRecord,
  type ExperimentSave,
  type SpecificationRecord,
} from "./transport/api.ts";

export interface StartCalls {
  specification: (targetId: string) => Promise<SpecificationRecord>;
  simulate: (inputDir: string) => Promise<EngineRunAccepted>;
  putExperiment: (
    experimentId: string,
    body: ExperimentSave,
  ) => Promise<ExperimentRecord>;
}

const CALLS: StartCalls = {
  specification: store.specification,
  simulate: api.simulate,
  putExperiment: store.putExperiment,
};

// The engine does not know the Target, so the row of the Experiment is the only link between
// them. The row is saved after the engine makes the Experiment folder, because the store refuses
// a row with no folder. The server sets how many trials run at a time.
export async function startExperiment(
  targetId: string,
  calls: StartCalls = CALLS,
): Promise<ExperimentRecord> {
  const { input_dir } = await calls.specification(targetId);
  const { experiment_id } = await calls.simulate(input_dir);
  return calls.putExperiment(experiment_id, {
    target_id: targetId,
    step: "simulate",
  });
}
