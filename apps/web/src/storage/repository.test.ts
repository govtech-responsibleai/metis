import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { indexedDB as fakeIndexedDB } from "fake-indexeddb";
import type { InterviewState } from "../transport/api.ts";
import {
  addFixtures,
  InterviewRepository,
  emptyRecord,
  fixturesForSpecification,
  removeUnreferencedFixtures,
} from "./repository.ts";

before(async () => {
  globalThis.indexedDB = fakeIndexedDB;
  await new Promise<void>((resolve, reject) => {
    const request = fakeIndexedDB.deleteDatabase("metis-web");
    request.onsuccess = () => resolve();
    request.onerror = () => reject(request.error);
  });
});

after(() => {
  (globalThis as { indexedDB?: IDBFactory }).indexedDB = undefined;
});

const state: InterviewState = {
  specification: {
    schema_version: 1,
    id: "test",
    runner_factory_ref:
      "metis.engine.simulation.runners.http.HttpRunnerFactory",
    tasks: [],
    target: { name: "", users: "", description: "", detail: "" },
    features: [],
    personas: [],
    scenarios: [],
  },
  behaviours_confirmed: false,
  confirmed: false,
  context: {
    perspective: "end_user",
    opening_description: "",
    capability_evidence: { known_capability_ids: [], confidence: "low" },
  },
  history: [],
  user_typed: [],
  issued_ids: [],
  pending: null,
};

test("migrates saved Interviews with their description and fixture bytes", async () => {
  const request = fakeIndexedDB.open("metis-web", 4);
  const database = await new Promise<IDBDatabase>((resolve, reject) => {
    request.onupgradeneeded = () =>
      request.result.createObjectStore("interviews", { keyPath: "id" });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  const bytes = new Blob(["policy bytes"], { type: "text/markdown" });
  const { target, ...specification } = state.specification;
  const pending = {
    type: "form",
    request_id: "resume-target-name",
    stage: "clarify",
    prompt: "Enter product details.",
    fields: [{ id: "product.name", label: "Product name" }],
    answer: { "product.name": "A product named product.name" },
  };
  const oldRecord = {
    ...emptyRecord("legacy-opening-files", state, "clarify", []),
    storage_version: 3,
    transcript: [
      {
        kind: "interaction",
        request_id: pending.request_id,
        request: pending,
        response: {
          type: "form",
          values: { "product.name": "A product named product.name" },
        },
        status: "answered",
      },
      {
        kind: "initial_description",
        id: "initial-message",
        description: "The opening explanation.",
      },
    ],
    state: {
      ...state,
      specification: { ...specification, product: target },
      pending,
      history: [{ role: "user", text: "Keep product.name in my description." }],
      context: {
        perspective: "end_user",
        capability_evidence: {
          known_capability_ids: [],
          confidence: "low",
        },
      },
    },
    fixtures: [
      {
        name: "policy.md",
        type: "text/markdown",
        size: bytes.size,
        blob: bytes,
      },
    ],
  };
  await new Promise<void>((resolve, reject) => {
    const transaction = database.transaction("interviews", "readwrite");
    transaction.objectStore("interviews").put(oldRecord);
    transaction
      .objectStore("interviews")
      .put({ ...oldRecord, id: "version-four", storage_version: 4 });
    transaction.objectStore("interviews").put({
      ...oldRecord,
      id: "version-five",
      storage_version: 5,
    });
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
  });
  database.close();

  const migrated = await new InterviewRepository().read("legacy-opening-files");

  assert.equal(migrated?.storage_version, 6);
  assert.equal(
    migrated?.state.context.opening_description,
    "The opening explanation.",
  );
  assert.deepEqual(migrated?.state.context.documents, []);
  assert.equal(await migrated?.fixtures[0]?.blob.text(), "policy bytes");
  const versionFour = await new InterviewRepository().read("version-four");
  assert.equal(versionFour?.storage_version, 6);
  assert.equal(await versionFour?.fixtures[0]?.blob.text(), "policy bytes");
  const versionFive = await new InterviewRepository().read("version-five");
  assert.equal(versionFive?.storage_version, 6);
  assert.deepEqual(versionFive?.state.specification.target, target);
  assert.equal(
    versionFive?.state.history[0]?.text,
    "Keep product.name in my description.",
  );
  assert.equal(versionFive?.state.pending?.type, "form");
  if (versionFive?.state.pending?.type === "form") {
    assert.equal(versionFive.state.pending.fields[0]?.id, "target.name");
    assert.equal(
      versionFive.state.pending.answer["target.name"],
      "A product named product.name",
    );
  }
  const interaction = versionFive?.transcript[0];
  assert.equal(interaction?.kind, "interaction");
  if (
    interaction?.kind === "interaction" &&
    interaction.response?.type === "form"
  ) {
    assert.equal(
      interaction.response.values?.["target.name"],
      "A product named product.name",
    );
  }
  assert.equal(await versionFive?.fixtures[0]?.blob.text(), "policy bytes");
  assert.ok(versionFive);
  await new InterviewRepository().put(versionFive);
  assert.deepEqual(
    await new InterviewRepository().read("version-five"),
    versionFive,
  );
  await new InterviewRepository().delete("version-five");
  await new InterviewRepository().delete("version-four");
  await new InterviewRepository().delete("legacy-opening-files");
});

test("local repository creates, orders, reads and deletes browser records", async () => {
  const repository = new InterviewRepository();
  const first = emptyRecord(
    "storage-test-a",
    { ...state, context: { ...state.context, capability_evidence: null } },
    "clarify",
    [],
  );
  await repository.put(first);
  await new Promise((resolve) => setTimeout(resolve, 1));
  const second = {
    ...emptyRecord("storage-test-b", state, "clarify", []),
    updated_at: Date.now() + 1,
  };
  await repository.put(second);

  assert.deepEqual(
    (await repository.list()).map((record) => record.id),
    ["storage-test-b", "storage-test-a"],
  );
  assert.equal((await repository.read("storage-test-a"))?.storage_version, 6);
  assert.equal(
    (await repository.read("storage-test-a"))?.state.context
      .capability_evidence,
    null,
  );
  await repository.delete("storage-test-a");
  assert.equal(await repository.read("storage-test-a"), undefined);
  await repository.delete("storage-test-b");
});

test("isolates unsupported and corrupt records while keeping healthy records", async () => {
  const repository = new InterviewRepository();
  const healthy = emptyRecord("healthy-record", state, "clarify", []);
  await repository.put(healthy);
  await new Promise<void>((resolve, reject) => {
    const request = fakeIndexedDB.open("metis-web", 5);
    request.onsuccess = () => {
      const tx = request.result.transaction("interviews", "readwrite");
      tx.objectStore("interviews").put({
        storage_version: 99,
        id: "old-record",
      });
      tx.objectStore("interviews").put({
        storage_version: 2,
        id: "bad-record",
        state: {},
      });
      tx.objectStore("interviews").put({
        ...healthy,
        id: "invalid-capability-evidence",
        state: {
          ...state,
          context: { ...state.context, capability_evidence: {} },
        },
      });
      for (const [id, references] of [
        ["invalid-task-references", [42]],
        ["missing-task-references", undefined],
      ]) {
        tx.objectStore("interviews").put({
          ...healthy,
          id,
          state: {
            ...state,
            specification: {
              ...state.specification,
              tasks: [{ id: "TC-001", behaviour_refs: references }],
            },
          },
        });
      }
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    };
    request.onerror = () => reject(request.error);
  });

  assert.deepEqual(
    (await repository.list()).map((record) => record.id),
    ["healthy-record"],
  );
  assert.equal(repository.problems.length, 5);
  assert.equal(await repository.read("bad-record"), undefined);
  assert.equal(await repository.read("missing-capability-evidence"), undefined);
  assert.equal(await repository.read("invalid-task-references"), undefined);
  assert.equal(await repository.read("missing-task-references"), undefined);
  const preserved = await new Promise<unknown>((resolve, reject) => {
    const request = fakeIndexedDB.open("metis-web", 5);
    request.onsuccess = () => {
      const row = request.result
        .transaction("interviews", "readonly")
        .objectStore("interviews")
        .get("invalid-task-references");
      row.onsuccess = () => resolve(row.result);
      row.onerror = () => reject(row.error);
    };
    request.onerror = () => reject(request.error);
  });
  assert.ok(preserved);
});

test("rejects an invalid update before it can replace a healthy record", async () => {
  const repository = new InterviewRepository();
  const healthy = emptyRecord("atomic-record", state, "clarify", []);
  await repository.put(healthy);
  await assert.rejects(
    repository.put({
      ...healthy,
      storage_version: 1,
    } as unknown as typeof healthy),
  );
  assert.deepEqual(await repository.read("atomic-record"), healthy);
});

test("stores fixture Blobs with one local Interview and restores them", async () => {
  const repository = new InterviewRepository();
  const record = emptyRecord("fixture-record", state, "scenarios", []);
  const file = new File(["fixture bytes"], "policy.pdf", {
    type: "application/pdf",
  });

  await repository.put(addFixtures(record, [file]));
  const restored = await repository.read("fixture-record");

  assert.equal(restored?.fixtures[0]?.name, "policy.pdf");
  assert.equal(await restored?.fixtures[0]?.blob.text(), "fixture bytes");
  await repository.delete("fixture-record");
});

test("later uploads cannot replace an opening original with the same name", () => {
  const started = emptyRecord(
    "initial-name-conflict",
    {
      ...state,
      context: {
        ...state.context,
        documents: [{ name: "policy.md" }],
      },
    },
    "clarify",
    [],
  );
  const initial = addFixtures(started, [new File(["original"], "policy.md")]);

  assert.throws(
    () => addFixtures(initial, [new File(["replacement"], "policy.md")]),
    /cannot be replaced/,
  );
});

test("fixture Blobs are isolated between local Interviews", async () => {
  const repository = new InterviewRepository();
  const first = addFixtures(
    emptyRecord("fixture-one", state, "scenarios", []),
    [new File(["one"], "shared.pdf")],
  );
  const second = addFixtures(
    emptyRecord("fixture-two", state, "scenarios", []),
    [new File(["two"], "shared.pdf")],
  );

  await repository.put(first);
  await repository.put(second);

  assert.equal(
    await (await repository.read("fixture-one"))?.fixtures[0]?.blob.text(),
    "one",
  );
  assert.equal(
    await (await repository.read("fixture-two"))?.fixtures[0]?.blob.text(),
    "two",
  );
  await repository.delete("fixture-one");
  await repository.delete("fixture-two");
});

test("removing a fixture reference keeps a Blob used by another scenario", () => {
  const fixture = new File(["shared"], "shared.txt");
  const specification = {
    ...state.specification,
    tasks: [
      {
        id: "S-1",

        description: "First scenario",
        scenario_ref: "S-1",
        persona_ref: "P-1",
        behaviour_refs: [],
        fixtures: ["shared.txt"],
        num_trials: 1,
        max_turns: 20,
        timeout_minutes: 15,
        response_wait_ms: 300000,
        max_run_retries: null,
      },
      {
        id: "S-2",

        description: "Second scenario",
        scenario_ref: "S-1",
        persona_ref: "P-1",
        behaviour_refs: [],
        fixtures: ["shared.txt"],
        num_trials: 1,
        max_turns: 20,
        timeout_minutes: 15,
        response_wait_ms: 300000,
        max_run_retries: null,
      },
    ],
  };
  const record = addFixtures(
    emptyRecord(
      "fixture-reference",
      { ...state, specification },
      "scenarios",
      [],
    ),
    [fixture],
  );

  const stillUsed = removeUnreferencedFixtures(record, ["shared.txt"]);
  assert.equal(stillUsed.fixtures.length, 1);

  const noLongerUsed = removeUnreferencedFixtures(
    {
      ...record,
      state: {
        ...record.state,
        specification: {
          ...record.state.specification,
          tasks: record.state.specification.tasks.map((scenario) => ({
            ...scenario,
            fixtures: [],
          })),
        },
      },
    },
    ["shared.txt"],
  );
  assert.equal(noLongerUsed.fixtures.length, 0);
});

test("only the files of selected Test Cases are packaged", () => {
  const task = (id: string, file: string) => ({
    id,
    scenario_ref: "S-1",
    persona_ref: id === "TC-001" ? "P-1" : "P-2",
    behaviour_refs: [],
    fixtures: [file],
    num_trials: 1,
    max_turns: 20,
    timeout_minutes: 15,
    response_wait_ms: 300000,
    max_run_retries: null,
  });
  const record = addFixtures(
    emptyRecord(
      "selected-files",
      {
        ...state,
        specification: {
          ...state.specification,
          tasks: [task("TC-001", "kept.txt"), task("TC-002", "cleared.txt")],
        },
        excluded_tasks: ["TC-002"],
      },
      "scenarios",
      [],
    ),
    [new File(["a"], "kept.txt"), new File(["b"], "cleared.txt")],
  );

  assert.deepEqual(
    fixturesForSpecification(record).map((file) => file.name),
    ["kept.txt"],
  );
});

test("preserves unreadable assessment records and gives a restart action", async () => {
  const repository = new InterviewRepository();
  const record = emptyRecord("old-assessment", state, "criteria", []);
  const oldRows = [
    {
      ...record,
      id: "old-assessment",
      state: {
        ...state,
        specification: {
          ...state.specification,
          features: [
            {
              id: "F-1",
              behaviours: [
                {
                  id: "EB-1",
                  criteria: [
                    {
                      id: "AC-1-1",
                      description: {
                        given: "a request",
                        when: "it answers",
                        then: "it cites sources",
                      },
                    },
                  ],
                },
              ],
            },
          ],
        },
      },
    },
    {
      ...record,
      id: "old-pending-form",
      state: {
        ...state,
        pending: {
          type: "form",
          fields: ["given", "when", "then"].map((id) => ({ id })),
        },
      },
    },
  ];
  const database = await new Promise<IDBDatabase>((resolve, reject) => {
    const request = fakeIndexedDB.open("metis-web", 5);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  await new Promise<void>((resolve, reject) => {
    const tx = database.transaction("interviews", "readwrite");
    for (const row of oldRows) tx.objectStore("interviews").put(row);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
  for (const expected of oldRows) {
    assert.equal(await repository.read(expected.id), undefined);
    assert.match(repository.problems[0].message, /Start a new Interview/);
    const raw = await new Promise<unknown>((resolve, reject) => {
      const request = database
        .transaction("interviews", "readonly")
        .objectStore("interviews")
        .get(expected.id);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    assert.deepEqual(raw, expected);
  }
  database.close();
});

test("reads saved review details and form choices in the current shapes", async () => {
  const repository = new InterviewRepository();
  const review = {
    type: "choice",
    prompt: "Review",
    state: "pending",
    request_id: "review",
    stage: "criteria",
    options: [],
    warnings: [],
    multi: false,
    cards: [
      {
        kind: "standard",
        id: "EB-1",
        title: "Cite sources",
        options: [],
        components: [
          {
            type: "disclosure",
            label: "Grader details",
            items: [{ type: "text", text: "Judge" }],
          },
        ],
      },
    ],
  };
  const form = {
    type: "form",
    prompt: "Edit",
    state: "resolved",
    request_id: "form",
    stage: "criteria",
    fields: [{ id: "mode", label: "Mode", choices: ["strict"] }],
    answer: {},
  };
  const record = emptyRecord(
    "older-shapes",
    { ...state, pending: review as never },
    "criteria",
    [
      {
        kind: "interaction",
        request_id: "form",
        request: form as never,
        status: "answered",
      },
    ],
  );
  await repository.put(record);
  const read = await repository.read("older-shapes");
  const pending = read?.state.pending;
  assert.deepEqual(
    pending?.type === "choice" ? pending.cards[0]?.components[0] : undefined,
    {
      type: "details",
      title: "Grader details",
      muted: true,
      expanded: false,
      components: [{ type: "text", text: "Judge" }],
    },
  );
  const entry = read?.transcript[0];
  const fields =
    entry?.kind === "interaction" && entry.request.type === "form"
      ? entry.request.fields
      : [];
  assert.deepEqual(fields[0]?.choices, [{ value: "strict", label: "strict" }]);
  await repository.delete("older-shapes");
});
