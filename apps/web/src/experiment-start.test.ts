import assert from "node:assert/strict";
import { test } from "node:test";
import { startExperiment, type StartCalls } from "./experiment-start.ts";
import { TransportError } from "./transport/api.ts";

function recording(simulate?: StartCalls["simulate"]) {
  const calls: string[] = [];
  const fake: StartCalls = {
    specification: async (targetId) => {
      calls.push(`specification ${targetId}`);
      return {
        target_id: targetId,
        specification_yaml: "id: shop\n",
        sha256: "0",
        input_dir: `evaluations/specifications/${targetId}`,
        updated_at: "2026-01-02T03:04:05Z",
      };
    },
    simulate:
      simulate ??
      (async (inputDir) => {
        calls.push(`simulate ${inputDir}`);
        return { experiment_id: "shop-20260102-030405" };
      }),
  };
  return { calls, fake };
}

test("a start simulates the input folder of the Target and gives the Experiment id", async () => {
  const { calls, fake } = recording();

  const started = await startExperiment("t1", fake);

  assert.deepEqual(calls, [
    "specification t1",
    "simulate evaluations/specifications/t1",
  ]);
  assert.equal(started.experiment_id, "shop-20260102-030405");
});

test("a start gives the error of a refused simulate", async () => {
  const refused = new TransportError("The Specification id is not valid.", {
    status: 422,
    code: "invalid_inputs",
    retryable: false,
  });
  const { calls, fake } = recording(async () => {
    throw refused;
  });

  await assert.rejects(startExperiment("t1", fake), refused);
  assert.deepEqual(calls, ["specification t1"]);
});
