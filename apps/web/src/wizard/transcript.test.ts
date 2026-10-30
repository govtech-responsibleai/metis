import assert from "node:assert/strict";
import test from "node:test";
import type {
  ChoiceRequest,
  InterviewState,
  InterviewSuccess,
} from "../transport/api.ts";
import { emptyRecord } from "../storage/repository.ts";
import {
  activeReview,
  applyEnd,
  applyTurn,
  groupTranscript,
  startTranscript,
  toPresentation,
} from "./transcript.ts";

const pending = {
  type: "chat" as const,
  prompt: "What does it do?",
  title: "Clarify",
  step: 1,
  steps: 5,
  state: "pending" as const,
  request_id: "req-1",
  stage: "clarify" as const,
  multiline: true,
  answer: "",
};
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
  pending,
};
const success = (next: InterviewState): InterviewSuccess => ({
  type: "success",
  state: next,
  stage: next.pending?.stage ?? "done",
  missing: [],
  outcome: next.pending ? "awaiting_response" : "done",
});

test("transcript projects start and one answered turn without changing API state", () => {
  const record = emptyRecord(
    "transcript-test",
    state,
    "clarify",
    startTranscript("A target", state),
  );
  const nextState = {
    ...state,
    pending: { ...pending, request_id: "req-2", prompt: "Who uses it?" },
  };
  const next = applyTurn(record, success(nextState), {
    type: "chat",
    text: "A target",
  });
  assert.equal(
    next.transcript.filter((entry) => entry.kind === "interaction").length,
    2,
  );
  const answered = next.transcript.find(
    (entry) => entry.kind === "interaction" && entry.request_id === "req-1",
  );
  assert.equal(
    answered?.kind === "interaction" ? answered.status : undefined,
    "answered",
  );
  assert.equal(toPresentation(next).requests.length, 3);
  assert.equal(record.state.pending?.request_id, "req-1");
});

test("choice toggles update the current transcript screen in place", () => {
  const behaviourScreen = (
    requestId: string,
    selected: boolean,
  ): ChoiceRequest => ({
    type: "choice",
    prompt: "Choose behaviours",
    title: "Behaviours",
    step: 2,
    steps: 5,
    state: "pending",
    request_id: requestId,
    stage: "behaviours",
    options: [],
    multi: true,
    cards: [
      {
        kind: "standard",
        id: "EB-1",
        title: "Cite sources",
        selected,
        components: [],
        options: [
          {
            id: { action: "tick", target: "EB-1" },
            label: "Measure this",
            patch: {
              op: "set",
              path: "features[F-1].behaviours[EB-1].measured",
              value: !selected,
              origin: "wizard",
            },
            selected,
            primary: false,
            enabled: true,
          },
        ],
        blocking: false,
      },
    ],
    warnings: [],
    footer: null,
    instruction: null,
  });
  const first = behaviourScreen("choice-1", true);
  const second = behaviourScreen("choice-2", false);
  const initialState = { ...state, pending: first };
  const record = emptyRecord("toggle-test", initialState, "behaviours", [
    {
      kind: "interaction",
      request_id: first.request_id,
      request: first,
      status: "pending",
    },
  ]);

  const next = applyTurn(
    record,
    success({ ...initialState, pending: second }),
    { type: "choice", selected: ["tick:EB-1"] },
  );

  assert.equal(next.transcript.length, 1);
  const current = next.transcript[0];
  assert.equal(
    current?.kind === "interaction" ? current.request_id : undefined,
    "choice-2",
  );
  assert.equal(
    current?.kind === "interaction" ? current.status : undefined,
    "pending",
  );
  assert.equal(
    current?.kind === "interaction" && current.request.type === "choice"
      ? current.request.cards[0]?.selected
      : undefined,
    false,
  );
});

test("failed end leaves the pending display entry available", () => {
  const record = emptyRecord(
    "end-test",
    state,
    "clarify",
    startTranscript("A target", state),
  );
  const failed = {
    type: "failure" as const,
    code: "completion_failed" as const,
    message: "Try again",
    retryable: true,
    state,
    missing: [],
  };
  assert.equal(applyEnd(record, failed), record);
});

test("choice and form receipts keep the offered fields and selections", () => {
  const choiceRequest = {
    type: "choice" as const,
    prompt: "Choose a goal",
    title: "Behaviours",
    step: 2,
    steps: 5,
    state: "pending" as const,
    request_id: "choice-1",
    stage: "behaviours" as const,
    options: [
      {
        id: { action: "continue" },
        label: "Continue",
        primary: true,
        enabled: true,
      },
    ],
    multi: false,
    cards: [],
    warnings: [],
    footer: null,
    instruction: null,
  };
  const formRequest = {
    type: "form" as const,
    cancellable: false,
    prompt: "Name the behaviour",
    title: "Behaviours",
    step: 2,
    steps: 5,
    state: "pending" as const,
    request_id: "form-1",
    stage: "behaviours" as const,
    fields: [
      {
        id: "name",
        label: "Name",
        placeholder: "",
        multiline: false,
        input_type: "string" as const,
        value: "",
        required: false,
        choices: [],
        help: "",
      },
    ],
    target: "B-1",
    answer: {},
  };
  const record = emptyRecord(
    "receipt-test",
    { ...state, pending: choiceRequest },
    "behaviours",
    [
      { kind: "initial_description", id: "initial", description: "A target" },
      {
        kind: "interaction",
        request_id: "choice-1",
        request: choiceRequest,
        status: "pending",
      },
    ],
  );
  const afterChoice = applyTurn(
    record,
    success({ ...state, pending: formRequest }),
    { type: "choice", selected: ["continue"] },
  );
  const answeredChoice = afterChoice.transcript[1];
  assert.equal(
    answeredChoice?.kind === "interaction" ? answeredChoice.status : undefined,
    "answered",
  );
  assert.deepEqual(
    answeredChoice?.kind === "interaction"
      ? answeredChoice.response
      : undefined,
    { type: "choice", selected: ["continue"] },
  );

  const formRecord = {
    ...afterChoice,
    state: { ...afterChoice.state, pending: formRequest },
    transcript: [
      ...afterChoice.transcript,
      {
        kind: "interaction" as const,
        request_id: "form-1",
        request: formRequest,
        status: "pending" as const,
      },
    ],
  };
  const afterForm = applyTurn(
    formRecord,
    success({ ...state, pending: null, confirmed: true }),
    { type: "form", cancelled: false, values: { name: "Reviewer" } },
  );
  const answeredForm = afterForm.transcript.find(
    (entry) => entry.kind === "interaction" && entry.request_id === "form-1",
  );
  assert.deepEqual(
    answeredForm?.kind === "interaction" ? answeredForm.response : undefined,
    { type: "form", cancelled: false, values: { name: "Reviewer" } },
  );
});

test("replaying a response does not duplicate a request ID", () => {
  const record = emptyRecord(
    "duplicate-test",
    state,
    "clarify",
    startTranscript("A target", state),
  );
  const nextState = { ...state, pending: { ...pending, request_id: "req-2" } };
  const response = { type: "chat" as const, text: "A target" };
  const once = applyTurn(record, success(nextState), response);
  const twice = applyTurn(once, success(nextState), response);
  assert.deepEqual(twice.transcript, once.transcript);
});

test("review projection retains context during correction and follows request stage", () => {
  const review: ChoiceRequest = {
    type: "choice",
    prompt: "Select",
    title: "Review",
    stage: "behaviours",
    request_id: "review-1",
    profile_section_id: "behaviours",
    state: "resolved",
    options: [],
    warnings: [],
    multi: true,
    cards: [
      {
        kind: "standard",
        id: "item-1",
        blocking: false,
        title: "Cite sources",
        section_id: "group-1",
        section: "Research",
        selected: true,
        components: [],
        options: [],
      },
    ],
  };
  const chat = {
    ...pending,
    stage: "behaviours" as const,
    target: "item-1",
    target_label: "Cite sources",
  };
  assert.equal(activeReview([review, chat]), review);
  const updated = {
    ...review,
    request_id: "review-2",
    state: "pending" as const,
  };
  assert.equal(activeReview([review, chat, updated]), updated);
  assert.equal(activeReview([review, { ...chat, stage: "criteria" }]), null);
  assert.equal(activeReview([]), null);
});

test("the transcript folds clicks into one actions group and keeps words visible", () => {
  const choice = (
    request_id: string,
    extra: Partial<ChoiceRequest> = {},
  ): ChoiceRequest => ({
    type: "choice",
    prompt: "Review the Behaviours.",
    stage: "behaviours",
    request_id,
    state: "resolved",
    profile_section_id: "behaviours",
    options: [],
    warnings: [],
    multi: true,
    cards: [],
    ...extra,
  });
  const form = {
    type: "form" as const,
    prompt: "Edit Cite sources.",
    state: "resolved" as const,
    request_id: "edit",
    stage: "behaviours" as const,
    purpose: "edit" as const,
    cancellable: true,
    fields: [],
    answer: {},
  };
  const items = groupTranscript([
    { ...pending, state: "resolved", answer: "A research assistant" },
    choice("review-1"),
    choice("review-2"),
    form,
    choice("review-3"),
    choice("review-4", { feedback_answer: "Add a Behaviour for tone." }),
    choice("pick", {
      profile_section_id: null,
      prompt: "Pick one.",
      state: "pending",
    }),
  ]);
  assert.deepEqual(items, [
    { kind: "request", index: 0 },
    { kind: "request", index: 1 },
    { kind: "actions", indices: [2, 3, 4] },
    { kind: "request", index: 5 },
    { kind: "request", index: 6 },
  ]);
});

test("a review that waits behind a send keeps its own option state", () => {
  const option = (action: string, extra = {}) => ({
    id: { action, target: "P-1" },
    label: action,
    primary: false,
    enabled: true,
    ...extra,
  });
  const review: ChoiceRequest = {
    type: "choice",
    prompt: "Review the Personas.",
    stage: "personas",
    request_id: "review-1",
    state: "pending",
    profile_section_id: "personas",
    options: [],
    warnings: [],
    multi: false,
    cards: [
      {
        kind: "standard",
        id: "P-1",
        blocking: false,
        title: "Careful reviewer",
        components: [],
        options: [option("edit", { icon: "pencil" }), option("remove")],
      },
    ],
  };
  const record = emptyRecord(
    "sending",
    { ...state, pending: review },
    "personas",
    [
      {
        kind: "interaction",
        request_id: "review-1",
        request: review,
        status: "sending",
        response: { type: "choice", selected: ["edit:P-1"] },
        outbound: { files: [], removedFixtures: [], attempt: 1 },
      },
    ],
  );
  const shown = activeReview(toPresentation(record).requests);
  assert.deepEqual(
    shown?.cards[0]?.options.map((item) => item.selected),
    [undefined, undefined],
  );
});
