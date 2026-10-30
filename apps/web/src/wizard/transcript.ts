import type {
  ChoiceRequest,
  InterviewResult,
  InterviewState,
  LocalInterviewRecord,
  Option,
  PresentationView,
  TranscriptEntry,
  UserResponse,
  WizardRequest,
} from "../transport/api.ts";
import { optionKey, titleFor } from "../transport/api.ts";

function clone<T>(value: T): T {
  return structuredClone(value);
}
function localId(): string {
  return (
    globalThis.crypto?.randomUUID?.() ??
    `local-${Date.now()}-${Math.random().toString(16).slice(2)}`
  );
}

export function startTranscript(
  description: string,
  state: InterviewState,
): TranscriptEntry[] {
  const pending = state.pending;
  return [
    { kind: "initial_description", id: localId(), description },
    ...(pending
      ? [
          {
            kind: "interaction" as const,
            request_id: pending.request_id ?? "",
            request: clone(pending),
            status: "pending" as const,
          },
        ]
      : []),
  ];
}

function resolvedRequest(
  request: WizardRequest,
  response: UserResponse,
): WizardRequest {
  const next = clone(request);
  next.state = "resolved";
  if (next.type === "chat" && response.type === "chat")
    next.answer = response.text;
  if (next.type === "form" && response.type === "form")
    next.answer = response.values ?? {};
  if (next.type === "choice" && response.type === "choice") {
    next.feedback_answer = response.feedback ?? "";
    // A review keeps its own option state when it resolves. The Profile draws it while a form
    // or a send waits, and a `selected` flag on an option is the state of its item there (a
    // tick), not "was this the answer". Only a plain choice records which option was chosen.
    if (next.profile_section_id != null || (next.sections ?? []).length > 0)
      return next;
    const selected = new Set(response.selected ?? []);
    const mark = (option: {
      id: Parameters<typeof optionKey>[0];
      selected?: boolean | null;
    }) => {
      option.selected = selected.has(optionKey(option.id));
    };
    next.options.forEach(mark);
    next.warnings.forEach((warning) => warning.options.forEach(mark));
    next.cards.forEach((card) => {
      card.options.forEach(mark);
      card.components.forEach((component) => {
        if (component.type === "options") component.options.forEach(mark);
        if (component.type === "number" || component.type === "upload") {
          const value = response.values?.[optionKey(component.id)];
          if (component.type === "number" && typeof value === "number")
            component.value = value;
          if (component.type === "upload" && Array.isArray(value))
            component.value = value;
        }
      });
    });
  }
  return next;
}

function optionsOf(request: ChoiceRequest): Option[] {
  const options = [...request.options];
  request.warnings.forEach((warning) => options.push(...warning.options));
  request.cards.forEach((card) => {
    options.push(...card.options);
    card.components.forEach((component) => {
      if (component.type === "options") options.push(...component.options);
    });
  });
  return options;
}

function refreshesCurrentChoice(
  request: WizardRequest,
  response: UserResponse,
  nextRequest: WizardRequest | null,
): boolean {
  const selected = response.type === "choice" ? (response.selected ?? []) : [];
  if (
    request.type !== "choice" ||
    response.type !== "choice" ||
    nextRequest?.type !== "choice" ||
    nextRequest.stage !== request.stage ||
    selected.length === 0
  )
    return false;

  const current = new Map(
    optionsOf(request).map((option) => [optionKey(option.id), option]),
  );
  const returned = new Set(
    optionsOf(nextRequest).map((option) => optionKey(option.id)),
  );
  return selected.every((key) => {
    const option = current.get(key);
    return (
      option?.selected != null && option.patch != null && returned.has(key)
    );
  });
}

export function applyTurn(
  record: LocalInterviewRecord,
  result: InterviewResult,
  response: UserResponse,
): LocalInterviewRecord {
  if (result.type === "failure" || !result.state) return record;
  const nextState = result.state;
  const transcript = clone(record.transcript);
  const pending = transcript.find(
    (entry) =>
      entry.kind === "interaction" &&
      entry.status !== "answered" &&
      entry.status !== "ended_unanswered" &&
      entry.request_id === record.state.pending?.request_id,
  );
  const responseAdvancesRequest =
    nextState.pending?.request_id !== record.state.pending?.request_id;
  const refreshesChoice =
    pending?.kind === "interaction" &&
    refreshesCurrentChoice(pending.request, response, nextState.pending);
  if (
    pending?.kind === "interaction" &&
    (refreshesChoice || !responseAdvancesRequest) &&
    nextState.pending
  ) {
    pending.request_id = nextState.pending.request_id;
    pending.request = clone(nextState.pending);
    pending.status = "pending";
    delete pending.response;
    delete pending.outbound;
    delete pending.failure;
  } else if (
    pending &&
    pending.kind === "interaction" &&
    responseAdvancesRequest
  ) {
    pending.request = resolvedRequest(pending.request, response);
    pending.response = response;
    pending.status = "answered";
    delete pending.outbound;
    delete pending.failure;
  }
  if (
    nextState.pending &&
    !transcript.some(
      (entry) =>
        entry.kind === "interaction" &&
        entry.request_id === nextState.pending?.request_id,
    )
  )
    transcript.push({
      kind: "interaction" as const,
      request_id: nextState.pending.request_id ?? "",
      request: clone(nextState.pending),
      status: "pending",
    });
  return {
    ...record,
    updated_at: Date.now(),
    title: titleFor(nextState.specification),
    stage: result.stage,
    state: nextState,
    transcript,
  };
}

export function applyEnd(
  record: LocalInterviewRecord,
  result: InterviewResult,
): LocalInterviewRecord {
  if (result.type === "failure" || !result.state) return record;
  const transcript = clone(record.transcript);
  const pending = transcript.find(
    (entry) =>
      entry.kind === "interaction" &&
      (entry.status === "pending" || entry.status === "failed"),
  );
  if (pending && pending.kind === "interaction")
    pending.status = "ended_unanswered";
  if (result.state.pending)
    transcript.push({
      kind: "interaction",
      request_id: result.state.pending.request_id,
      request: clone(result.state.pending),
      status: "pending",
    });
  return {
    ...record,
    updated_at: Date.now(),
    title: titleFor(result.state.specification),
    stage: result.stage,
    state: result.state,
    transcript,
  };
}

export function toPresentation(record: LocalInterviewRecord): PresentationView {
  const requests: WizardRequest[] = record.transcript.map((entry) => {
    if (entry.kind === "interaction") {
      if (
        (entry.status === "sending" || entry.status === "failed") &&
        entry.response
      )
        return resolvedRequest(entry.request, entry.response);
      return entry.request;
    }
    return {
      type: "chat",
      prompt: "",
      title: null,
      step: null,
      steps: null,
      state: "resolved",
      request_id: entry.id,
      stage: "clarify",
      multiline: true,
      answer: entry.description,
    };
  });
  return {
    id: record.id,
    stage: record.stage,
    done: record.state.pending === null && record.state.confirmed,
    requests,
    specification: record.state.specification,
  };
}

export function activeReview(requests: WizardRequest[]): ChoiceRequest | null {
  const current = requests.at(-1);
  if (!current) return null;
  const review = [...requests]
    .reverse()
    .find(
      (request) =>
        request.type === "choice" &&
        request.stage === current.stage &&
        request.profile_section_id != null,
    );
  if (!review || review.type !== "choice") return null;
  return review;
}

// How the conversation pane groups its requests. Words stay visible: typed messages, chat
// requests and their replies, choices answered with feedback, and every request that still waits
// for an answer in the pane. The record of clicks folds into one "N actions" group: choices
// answered only by selection, edit and add forms, and a review prompt that repeats the one before
// it. Consecutive folded requests join one group.
export type TranscriptItem =
  { kind: "request"; index: number } | { kind: "actions"; indices: number[] };

function isReview(request: WizardRequest): boolean {
  return request.type === "choice" && request.profile_section_id != null;
}

function folds(
  request: WizardRequest,
  entry: TranscriptEntry | undefined,
  previousReview: WizardRequest | undefined,
): boolean {
  if (
    entry?.kind === "interaction" &&
    (entry.status === "sending" || entry.status === "failed")
  )
    return false;
  switch (request.type) {
    case "chat":
      return false;
    case "form":
      return request.purpose === "edit" || request.state === "resolved";
    case "choice":
      if (request.feedback_answer) return false;
      if (isReview(request))
        return (
          previousReview?.stage === request.stage &&
          previousReview.prompt === request.prompt
        );
      return request.state === "resolved";
  }
}

export function groupTranscript(
  requests: readonly WizardRequest[],
  entries: readonly TranscriptEntry[] = [],
): TranscriptItem[] {
  const items: TranscriptItem[] = [];
  let previousReview: WizardRequest | undefined;
  requests.forEach((request, index) => {
    const folded = folds(request, entries[index], previousReview);
    if (isReview(request)) previousReview = request;
    const last = items.at(-1);
    if (!folded) items.push({ kind: "request", index });
    else if (last?.kind === "actions") last.indices.push(index);
    else items.push({ kind: "actions", indices: [index] });
  });
  return items;
}
