import assert from "node:assert/strict";
import test from "node:test";
import type { Specification } from "./transport/api.ts";
import { specificationHasCriteria } from "./graders.ts";

const specification: Specification = {
  schema_version: 1,
  id: "test",
  runner_factory_ref: "metis.engine.simulation.runners.http.HttpRunnerFactory",
  tasks: [],
  target: { name: "", users: "", description: "", detail: "" },
  features: [
    {
      id: "F-1",
      name: "Feature",
      description: "",
      behaviours: [
        {
          id: "B-1",
          name: "Behaviour",
          description: "",
          measured: true,
          criteria: [],
        },
      ],
    },
  ],
  personas: [],
  scenarios: [],
};

test("grader loading waits until the Specification contains a Criterion", () => {
  assert.equal(specificationHasCriteria(specification), false);
  const withCriterion: Specification = {
    ...specification,
    features: [
      {
        ...specification.features[0]!,
        behaviours: [
          {
            ...specification.features[0]!.behaviours[0]!,
            criteria: [
              {
                id: "C-1",
                name: "Criterion",
                description: "Given , when , then .",
              },
            ],
          },
        ],
      },
    ],
  };
  assert.equal(specificationHasCriteria(withCriterion), true);
});
