import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import type {
  InterviewState,
  LoadedInterviewRecord,
} from "../transport/api.ts";
import {
  addFixtures,
  InterviewRepository,
  emptyRecord,
  fixturesForSpecification,
  interviewId,
  putNew,
  recordFiles,
  removeUnreferencedFixtures,
} from "./repository.ts";
import { fakeStore } from "./fake-store.test-helper.ts";
import { admitFiles } from "../fixture-policy.ts";

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
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

function withReply(
  record: LoadedInterviewRecord,
  file: File,
): LoadedInterviewRecord {
  return {
    ...record,
    transcript: [
      ...record.transcript,
      {
        kind: "interaction",
        request_id: "req-1",
        request: {
          type: "chat",
          prompt: "Describe it",
          request_id: "req-1",
          stage: "clarify",
          state: "pending",
          multiline: true,
          answer: "",
        },
        response: { type: "chat", text: "See the file" },
        status: "sending",
        outbound: {
          files: [
            { name: file.name, type: file.type, size: file.size, blob: file },
          ],
          removedFixtures: [],
          attempt: 1,
        },
      },
    ],
  };
}

test("a saved record and its file bytes read back through the store", async () => {
  const server = fakeStore();
  globalThis.fetch = server.fetch;
  const policy = new File(["policy bytes"], "policy.pdf", {
    type: "application/pdf",
  });
  const notes = new File(["reply notes"], "notes.txt", { type: "text/plain" });
  const record = withReply(
    addFixtures(
      emptyRecord("target-a", state, "clarify", []),
      admitFiles([policy], []),
    ),
    notes,
  );

  await new InterviewRepository().put(record);
  const read = (await new InterviewRepository().read("target-a"))!;

  assert.deepEqual(server.requests[0], {
    method: "PUT",
    path: "/api/v1/targets/target-a/interview",
    files: ["files/policy.pdf", "files/notes.txt"],
  });
  assert.deepEqual(server.targets.get("target-a")?.record.fixtures, [
    { name: "policy.pdf", type: "application/pdf", size: 12 },
  ]);
  assert.deepEqual(
    { ...read, fixtures: [], transcript: [] },
    { ...record, fixtures: [], transcript: [] },
  );
  assert.equal(await read.fixtures[0]?.blob.text(), "policy bytes");
  assert.equal(read.fixtures[0]?.type, "application/pdf");
  const reply = read.transcript[0];
  assert.equal(
    reply?.kind === "interaction"
      ? await reply.outbound?.files[0]?.blob.text()
      : undefined,
    "reply notes",
  );
});

test("a put sends only the files that the store does not have", async () => {
  const server = fakeStore();
  globalThis.fetch = server.fetch;
  const repository = new InterviewRepository();
  const record = addFixtures(
    emptyRecord("target-b", state, "clarify", []),
    admitFiles([new File(["one"], "one.txt", { type: "text/plain" })], []),
  );
  await repository.put(record);
  await repository.put({ ...structuredClone(record), title: "Renamed" });
  const read = (await repository.read("target-b"))!;
  const both = addFixtures(
    read,
    admitFiles(
      [new File(["two"], "two.txt", { type: "text/plain" })],
      read.fixtures,
    ),
  );
  await repository.put(both);
  await repository.put({ ...both, fixtures: both.fixtures.slice(1) });
  await repository.put(structuredClone(both));

  const puts = server.requests.filter((request) => request.method === "PUT");
  assert.deepEqual(
    puts.map((request) => request.files),
    [["files/one.txt"], [], ["files/two.txt"], [], ["files/one.txt"]],
  );
});

test("a new answer file with the name of a file of an unaccepted answer gets its own name", async () => {
  const server = fakeStore();
  globalThis.fetch = server.fetch;
  const repository = new InterviewRepository();
  const started = emptyRecord("target-e", state, "clarify", []);
  const first = withReply(started, new File(["first"], "notes.txt"));
  await repository.put(first);

  const [other] = admitFiles(
    [new File(["other"], "notes.txt")],
    recordFiles(first),
  );
  await repository.put(withReply(started, other!));

  const stored = server.targets.get("target-e")!.files;
  assert.deepEqual([...stored.keys()], ["notes (2).txt"]);
  assert.equal(await stored.get("notes (2).txt")?.blob.text(), "other");
});

test("an Interview with a file that the store lost names the file", async () => {
  const server = fakeStore();
  globalThis.fetch = server.fetch;
  const record = addFixtures(
    emptyRecord("target-f", state, "clarify", []),
    admitFiles([new File(["policy bytes"], "policy.pdf")], []),
  );
  await new InterviewRepository().put(record);
  server.targets.get("target-f")!.files.delete("policy.pdf");

  await assert.rejects(
    new InterviewRepository().read("target-f"),
    /The file policy\.pdf is missing from the store\./,
  );
});

test("lists summaries newest first with the problems that the store reports", async () => {
  const server = fakeStore();
  globalThis.fetch = server.fetch;
  const repository = new InterviewRepository();
  const older = { ...emptyRecord("older", state, "clarify", []), title: "A" };
  const newer = { ...emptyRecord("newer", state, "clarify", []), title: "B" };
  await repository.put({ ...older, updated_at: 1_000 });
  await repository.put({ ...newer, updated_at: 2_000 });
  server.problems.push({ id: "broken", message: "Delete it." });

  assert.deepEqual(await repository.list(), [
    { id: "newer", title: "B", updated: 2_000 },
    { id: "older", title: "A", updated: 1_000 },
  ]);
  assert.deepEqual(repository.problems, [
    { id: "broken", message: "Delete it." },
  ]);
});

test("an Interview id is the local start time in the folder format of the wizard", () => {
  const sent = new Date(2026, 10, 12, 10, 15, 0);

  assert.equal(interviewId(sent), "20261112-101500-interview");
  assert.equal(interviewId(sent, 2), "20261112-101500-interview-2");
  assert.equal(
    interviewId(new Date(2026, 0, 2, 3, 4, 5)),
    "20260102-030405-interview",
  );
});

test("a new Interview whose id another Interview has is saved under the next id", async () => {
  const server = fakeStore();
  globalThis.fetch = server.fetch;
  const repository = new InterviewRepository();
  const sent = new Date(2026, 10, 12, 10, 15, 0);
  const other = emptyRecord(interviewId(sent), state, "clarify", []);
  await repository.put({ ...other, created_at: 1 });
  const record = emptyRecord(interviewId(sent), state, "clarify", []);

  const saved = await putNew(repository, record, sent);

  assert.equal(saved.id, "20261112-101500-interview-2");
  assert.equal(server.targets.get(saved.id)?.record.id, saved.id);
  assert.equal(server.targets.get(interviewId(sent))?.record.created_at, 1);
  assert.equal((await putNew(repository, record, sent)).id, saved.id);
});

test("a deleted Interview reads as missing", async () => {
  const server = fakeStore();
  globalThis.fetch = server.fetch;
  const repository = new InterviewRepository();
  await repository.put(emptyRecord("target-c", state, "clarify", []));

  await repository.delete("target-c");

  assert.equal(await repository.read("target-c"), undefined);
  assert.deepEqual(await repository.list(), []);
});

test("a record refuses a file whose name it already has", () => {
  const started = emptyRecord("name-conflict", state, "clarify", []);
  const initial = addFixtures(
    started,
    admitFiles([new File(["original"], "policy.md")], []),
  );

  assert.throws(
    () => addFixtures(initial, admitFiles([new File(["x"], "policy.md")], [])),
    /already has a file named policy\.md/,
  );
});

test("removing a fixture reference keeps a Blob used by another scenario", () => {
  const fixture = new File(["shared"], "shared.txt");
  const task = (id: string) => ({
    id,
    description: "A scenario",
    scenario_ref: "S-1",
    persona_ref: "P-1",
    behaviour_refs: [],
    fixtures: ["shared.txt"],
    num_trials: 1,
    max_turns: 20,
    timeout_minutes: 15,
    response_wait_ms: 300000,
    max_run_retries: null,
  });
  const specification = {
    ...state.specification,
    tasks: [task("S-1"), task("S-2")],
  };
  const record = addFixtures(
    emptyRecord(
      "fixture-reference",
      { ...state, specification },
      "scenarios",
      [],
    ),
    admitFiles([fixture], []),
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
    admitFiles(
      [new File(["a"], "kept.txt"), new File(["b"], "cleared.txt")],
      [],
    ),
  );

  assert.deepEqual(
    fixturesForSpecification(record).map((file) => file.name),
    ["kept.txt"],
  );
});
