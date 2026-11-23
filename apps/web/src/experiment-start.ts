import {
  api,
  store,
  type EngineRunAccepted,
  type SpecificationRecord,
} from "./transport/api.ts";

export interface StartCalls {
  specification: (targetId: string) => Promise<SpecificationRecord>;
  simulate: (inputDir: string) => Promise<EngineRunAccepted>;
}

const CALLS: StartCalls = {
  specification: store.specification,
  simulate: api.simulate,
};

// The server sets how many trials run at a time.
export async function startExperiment(
  targetId: string,
  calls: StartCalls = CALLS,
): Promise<EngineRunAccepted> {
  const { input_dir } = await calls.specification(targetId);
  return calls.simulate(input_dir);
}
