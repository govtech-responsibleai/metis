import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import {
  api,
  TransportError,
  type InterviewState,
  type InterviewSuccess,
  type LocalInterviewRecord,
} from "../transport/api.ts";
import { emptyRecord, InterviewRepository } from "../storage/repository.ts";
import { startTranscript, toPresentation } from "./transcript.ts";
import { InterviewOperations, pendingEntry } from "./operations.ts";

const respond = api.respond;
afterEach(() => {
  api.respond = respond;
});
const state: InterviewState = {
  specification: {
    schema_version: 1,
    id: "test",
    runner_factory_ref:
      "metis.engine.simulation.runners.http.HttpRunnerFactory",
    tasks: [],
    target: { name: "Test", users: "", description: "", detail: "" },
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
  pending: {
    type: "chat",
    prompt: "Describe it",
    request_id: "req-1",
    stage: "clarify",
    state: "pending",
    multiline: true,
    answer: "",
  },
};
function record(id: string) {
  return emptyRecord(
    id,
    structuredClone(state),
    "clarify",
    startTranscript("Test", state),
  );
}
function result(): InterviewSuccess {
  return {
    type: "success",
    state: {
      ...structuredClone(state),
      pending: { ...state.pending!, request_id: "req-2" },
    },
    stage: "clarify",
    missing: [],
    outcome: "awaiting_response",
  };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (cause: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
const reply = { type: "chat" as const, text: "A reply" };

test("saves a reply with its sender while another Interview remains operable", async () => {
  const repository = new InterviewRepository();
  const a = record("sender-a"),
    b = record("sender-b");
  await repository.put(a);
  await repository.put(b);
  let visible = a;
  const operations = new InterviewOperations(repository, (saved) => {
    if (visible.id === saved.id) visible = saved;
  });
  const waiting = deferred<InterviewSuccess>();
  const called = deferred<void>();
  let calls = 0;
  api.respond = async () => {
    calls++;
    called.resolve();
    return waiting.promise;
  };
  const sending = operations.send(a, reply);
  await called.promise;
  const durable = (await repository.read(a.id))!;
  assert.equal(pendingEntry(durable)?.status, "sending");
  assert.equal(
    toPresentation(durable).requests.filter(
      (request) => request.type === "chat" && request.answer === reply.text,
    ).length,
    1,
  );
  assert.equal(
    (await operations.recover(durable)).transcript.at(-1)?.kind,
    "interaction",
  );
  assert.equal(
    pendingEntry(await operations.recover(durable))?.status,
    "sending",
  );
  visible = b;
  assert.equal(operations.active.has(b.id), false);
  await operations.send(a, reply);
  assert.equal(calls, 1);
  waiting.resolve(result());
  await sending;
  assert.equal(visible.id, b.id);
  assert.equal(
    (await repository.read(a.id))?.state.pending?.request_id,
    "req-2",
  );
  assert.deepEqual((await repository.read(b.id))?.state, b.state);
});

test("failed replies retain exact files and retry once without duplicate receipts", async () => {
  const repository = new InterviewRepository();
  let current = record("retry-files");
  const operations = new InterviewOperations(repository, (next) => {
    current = next;
  });
  const file = new File(["policy"], "policy.txt", { type: "text/plain" });
  api.respond = async () => {
    throw new TransportError("Unavailable", { retryable: true });
  };
  await operations.send(current, reply, [file]);
  assert.equal(pendingEntry(current)?.status, "failed");
  assert.equal(current.fixtures.length, 0);
  assert.deepEqual(current.state, state);
  const reloaded = (await repository.read(current.id))!;
  assert.equal(
    await pendingEntry(reloaded)?.outbound?.files[0]?.blob.text(),
    "policy",
  );
  let calls = 0;
  api.respond = async (_state, id, response) => {
    calls++;
    assert.equal(id, "req-1");
    assert.deepEqual(response, reply);
    return result();
  };
  await operations.retry(reloaded);
  assert.equal(calls, 1);
  assert.equal(
    current.transcript.filter(
      (entry) => entry.kind === "interaction" && entry.request_id === "req-1",
    ).length,
    1,
  );
  assert.equal(await current.fixtures[0]?.blob.text(), "policy");
  assert.equal(
    current.transcript[1]?.kind === "interaction" &&
      current.transcript[1].status,
    "answered",
  );
});

test("reload marks an unowned send interrupted and waits for manual retry", async () => {
  const repository = new InterviewRepository();
  const interrupted = record("interrupted");
  const entry = pendingEntry(interrupted)!;
  entry.status = "sending";
  entry.response = reply;
  entry.outbound = { files: [], removedFixtures: [], attempt: 1 };
  await repository.put(interrupted);
  let calls = 0;
  api.respond = async () => {
    calls++;
    return result();
  };
  const operations = new InterviewOperations(repository, () => {});
  const recovered = await operations.recover(interrupted);
  assert.equal(pendingEntry(recovered)?.failure?.kind, "interrupted");
  assert.equal(calls, 0);
  assert.equal(
    pendingEntry((await repository.read(interrupted.id))!)?.status,
    "failed",
  );
  await operations.retry(recovered);
  assert.equal(calls, 1);
});

test("storage errors preserve the authoritative state and retry the local save", async () => {
  let durable = record("save-failure");
  let visible = durable;
  let writes = 0,
    calls = 0;
  const operations = new InterviewOperations(
    {
      put: async (next) => {
        writes++;
        if (writes === 2 || writes === 3) throw new Error("Disk full");
        durable = structuredClone(next);
      },
    },
    (next) => {
      visible = next;
    },
  );
  api.respond = async () => {
    calls++;
    return result();
  };
  await operations.send(durable, reply);
  assert.deepEqual(durable.state, state);
  assert.equal(pendingEntry(visible)?.failure?.kind, "storage");
  assert.equal(pendingEntry(durable)?.status, "sending");
  const retry = operations.feedback.get(durable.id)?.retry;
  assert.ok(retry);
  await retry();
  assert.equal(calls, 1);
  assert.equal(durable.state.pending?.request_id, "req-2");
  assert.equal(operations.feedback.has(durable.id), false);
});

test("failed submission storage prevents API calls and retains the draft", async () => {
  let accepted = false,
    called = false;
  const operations = new InterviewOperations(
    {
      put: async () => {
        throw new Error("Disk full");
      },
    },
    () => {},
  );
  api.respond = async () => {
    called = true;
    return result();
  };
  await operations.send(record("full"), reply, [], [], () => {
    accepted = true;
  });
  assert.equal(called, false);
  assert.equal(accepted, false);
  assert.match(operations.feedback.get("full")?.message ?? "", /Disk full/);
});

test("non-retryable replies preserve state and offer no retry", async () => {
  let current: LocalInterviewRecord = record("invalid");
  const operations = new InterviewOperations(
    new InterviewRepository(),
    (next) => {
      current = next;
    },
  );
  api.respond = async () => {
    throw new TransportError("Invalid response", { retryable: false });
  };
  await operations.send(current, reply);
  assert.equal(pendingEntry(current)?.failure?.retryable, false);
  assert.deepEqual(current.state, state);
});

test("reload offers manual request recovery when an unsaved result is no longer in memory", async () => {
  const repository = new InterviewRepository();
  const prior = record("unsaved-reload");
  const entry = pendingEntry(prior)!;
  entry.status = "failed";
  entry.response = reply;
  entry.outbound = { files: [], removedFixtures: [], attempt: 1 };
  entry.failure = { message: "Not saved", retryable: true, kind: "storage" };
  let calls = 0;
  api.respond = async () => {
    calls++;
    return result();
  };
  const operations = new InterviewOperations(repository, () => {});
  const restored = await operations.recover(prior);
  assert.equal(pendingEntry(restored)?.failure?.kind, "interrupted");
  assert.equal(calls, 0);
});
