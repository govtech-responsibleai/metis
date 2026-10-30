// The API wire contract is generated from FastAPI. The small projections below only make
// server-defaulted arrays required for rendering and add browser-owned display types later in
// this module. They do not copy the Pydantic wire models.
import type { components, operations, paths } from "../generated/api.ts";

export type ApiPaths = paths;
type Schema = components["schemas"];
type RequiredFields<T, K extends keyof T> = Omit<T, K> & {
  [P in K]-?: T[P];
};
type Present<T> = Exclude<T, undefined | null>;
// A field with a server default. The server always sends it; a hand-written value may omit it.
type Defaulted<T, K extends keyof T> = Omit<T, K> & { [P in K]?: T[P] };
type JsonResponse<O, Status extends PropertyKey = 200> = O extends {
  responses: infer Responses;
}
  ? Responses extends Record<
      Status,
      { content: { "application/json": infer Body } }
    >
    ? Body
    : never
  : never;
type BinaryResponse<O, Status extends PropertyKey = 200> = O extends {
  responses: infer Responses;
}
  ? Responses extends Record<
      Status,
      { content: { "application/zip": infer Body } }
    >
    ? Body
    : never
  : never;

type StartOperation = operations["start_api_v1_wizard_interview_start_post"];
type TurnOperation = operations["turn_api_v1_wizard_interview_turn_post"];
type EndOperation = operations["end_api_v1_wizard_interview_end_post"];
type ExtractDocumentsOperation =
  operations["extract_document_text_api_v1_wizard_documents_extract_post"];
type CompileOperation = operations["compile__api_v1_wizard_compile_post"];
type GradersOperation = operations["graders_api_v1_graders_get"];
type ModelsOperation = operations["models_api_v1_models_get"];
type ConfigOperation = operations["config_api_v1_wizard_config_get"];
type PackageOperation = operations["package_api_v1_wizard_package_post"];
type ConnectionCheckOperation =
  operations["check_target_connection_api_v1_wizard_connection_check_post"];
type ConnectionOperation =
  operations["update_target_connection_api_v1_wizard_connection_post"];
type PackageWireRequest = Schema["Body_package_api_v1_wizard_package_post"];

export type InterviewStep = Schema["InterviewStep"];
export type Perspective = Schema["Perspective"];
export type InterviewDocument = Schema["InterviewDocument"];
export type PerspectiveDefinition = Schema["PerspectiveDefinition"];
export type CapabilityCategory = Schema["CapabilityCategory"];
export type CapabilityCategoryDefinition =
  Schema["CapabilityCategoryDefinition"];
export type CapabilityConfidence = Schema["CapabilityConfidence"];
export type CapabilityDefinition = Schema["CapabilityDefinition"];
export type CapabilityEvidence = Schema["CapabilityEvidence"];
export type CapabilityId = Schema["CapabilityId"];
export type OptionId = Schema["OptionId"];
export function optionKey(id: OptionId): string {
  return [id.action, id.target, id.via].filter(Boolean).join(":");
}
export type Option = Schema["Option"];
export type CardText = Defaulted<Schema["CardText"], "muted">;
export type CardOptionGroup = Defaulted<
  RequiredFields<Schema["CardOptionGroup"], "options">,
  "muted"
>;
export type CardNumberField = Defaulted<Schema["CardNumberField"], "muted">;
export type CardUploadField = Defaulted<
  RequiredFields<Schema["CardUploadField"], "value">,
  "muted"
>;
export type CardDivider = Defaulted<Schema["CardDivider"], "muted">;
export type CardDetails = Defaulted<
  Omit<Schema["CardDetails-Input"], "components">,
  "muted"
> & {
  components: CardComponent[];
};
export type CardColumn = Omit<Schema["CardColumn-Input"], "components"> & {
  components: CardComponent[];
};
export type CardComponent =
  | CardText
  | CardOptionGroup
  | CardNumberField
  | CardUploadField
  | CardDivider
  | CardDetails;
export type Card = Defaulted<
  Omit<Schema["BehaviourCard-Input"], "components" | "options" | "columns">,
  "show_id"
> & {
  components: CardComponent[];
  options: Option[];
  columns?: CardColumn[];
};
export type ScenarioCard = Defaulted<
  Omit<Schema["ScenarioCard-Input"], "components" | "options" | "columns">,
  "show_id"
> & {
  components: CardComponent[];
  options: Option[];
  columns?: CardColumn[];
};
export type AnyCard = Card | ScenarioCard;
export type WarningSource = Schema["WarningSource"];
export type Warning = RequiredFields<Schema["Warning"], "options">;

export type ChatRequest = Schema["ChatRequest"];
export type ReviewSection = RequiredFields<Schema["ReviewSection"], "options">;
export type ChoiceRequest = Omit<
  Schema["ChoiceRequest-Input"],
  "options" | "cards" | "warnings" | "sections"
> & {
  options: Option[];
  cards: AnyCard[];
  warnings: Warning[];
  sections?: ReviewSection[];
};
export type FormChoice = Schema["FormChoice"];
export type FormField = Defaulted<Schema["FormField"], "multiple">;
export type FormRequest = Defaulted<
  Omit<RequiredFields<Schema["FormRequest"], "answer">, "fields">,
  "submit_label" | "used_combinations"
> & { fields: FormField[] };
export type WizardRequest = ChatRequest | ChoiceRequest | FormRequest;
export type AnyRequest = WizardRequest;
export type UserResponse =
  Schema["ChatResponse"] | Schema["ChoiceResponse"] | Schema["FormResponse"];
export type AnyResponse = UserResponse;

export type Criterion = Schema["Criterion"];
export type Behaviour = Omit<Schema["Behaviour"], "criteria"> & {
  criteria: Criterion[];
};
export type Feature = Omit<Schema["Feature"], "behaviours"> & {
  behaviours: Behaviour[];
};
export type Persona = Schema["Persona"];
export type Scenario = Schema["Scenario"];
export type Task = Omit<
  Schema["Task"],
  "fixtures" | "behaviour_refs" | "num_trials"
> & { fixtures: string[]; behaviour_refs: string[]; num_trials: number };
export type Target = Schema["Target"];
export type Specification = Omit<
  Schema["Specification"],
  "features" | "personas" | "scenarios" | "tasks"
> & {
  features: Feature[];
  personas: Persona[];
  scenarios: Scenario[];
  tasks: Task[];
};
export type InterviewMessage = Schema["InterviewMessage"];
export type InterviewState = RequiredFields<
  Omit<Schema["InterviewState-Input"], "specification" | "pending">,
  "history" | "user_typed" | "issued_ids"
> & { specification: Specification; pending: WizardRequest | null };
export type MissingData = Schema["MissingData"];
export type InterviewSuccess = Omit<
  Schema["InterviewSuccess"],
  "state" | "missing"
> & {
  state: InterviewState;
  missing: MissingData[];
};
export type InterviewFailure = Omit<
  Schema["InterviewFailure"],
  "state" | "missing"
> & {
  state?: InterviewState | null;
  missing: MissingData[];
};
export type InterviewResult = InterviewSuccess | InterviewFailure;
export type CompileResult = Schema["CompileResult"];
export type ConnectionTransport = Schema["ConnectionTransport"];
export type ConnectionStatus = Schema["ConnectionStatus"];
export type TargetBinding = Schema["TargetBinding"];
export type TargetConnection = Schema["TargetConnection"];
export type ConnectionProbe = Schema["ConnectionProbe"];
export type ConnectionCheckRequest = Schema["ConnectionCheckRequest"];
export type ConnectionCheckResult = JsonResponse<ConnectionCheckOperation>;
export type ConnectionRequest = Schema["InterviewConnectionRequest"];
export type ConnectionResponse = JsonResponse<ConnectionOperation>;
export type GraderSpec = Schema["GraderSummary"];
export type Dimension = Schema["Dimension"];
export type GraderSetting = Schema["GraderSetting"];
export type ModelRole = Schema["ModelRole"];
export type ModelStatus = Schema["ModelStatus"];
export type StartRequest = Schema["InterviewStartRequest"];
export type StartResponse = JsonResponse<StartOperation>;
export type TurnRequest = Schema["InterviewTurnRequest"];
export type TurnResponse = JsonResponse<TurnOperation>;
export type EndRequest = Schema["InterviewEndRequest"];
export type EndResponse = JsonResponse<EndOperation>;
export type ExtractDocumentsResponse = JsonResponse<ExtractDocumentsOperation>;
export type CompileResponse = JsonResponse<CompileOperation>;
export type GradersResponse = JsonResponse<GradersOperation>;
export type ModelsResponse = JsonResponse<ModelsOperation>;
export type ConfigResponse = JsonResponse<ConfigOperation>;
export type PackageRequest = Omit<PackageWireRequest, "files"> & {
  files?: PackageFile[] | null;
};
export type PackageResponse =
  BinaryResponse<PackageOperation> extends string
    ? Blob
    : BinaryResponse<PackageOperation>;

export interface PackageFile {
  name: string;
  blob: Blob;
}

type GeneratedCardComponent = Present<
  Schema["BehaviourCard-Input"]["components"]
>[number];
function normalizeComponent(component: GeneratedCardComponent): CardComponent {
  if (component.type === "options")
    return { ...component, options: component.options ?? [] };
  if (component.type === "upload")
    return {
      ...component,
      value: component.value ?? [],
      available: component.available ?? [],
    };
  if (component.type === "details")
    return {
      ...component,
      components: (component.components ?? []).map(normalizeComponent),
    };
  return component;
}

function normalizeCard(
  card: Schema["BehaviourCard-Input"] | Schema["ScenarioCard-Input"],
): AnyCard {
  return {
    ...card,
    components: (card.components ?? []).map(normalizeComponent),
    options: card.options ?? [],
    ...(card.columns
      ? {
          columns: card.columns.map((column) => ({
            ...column,
            components: (column.components ?? []).map(normalizeComponent),
          })),
        }
      : {}),
  } as AnyCard;
}

function normalizeRequest(
  request: NonNullable<Schema["InterviewState-Input"]["pending"]>,
): WizardRequest {
  if (request.type === "choice")
    return {
      ...request,
      options: request.options ?? [],
      cards: (request.cards ?? []).map(normalizeCard),
      sections: (request.sections ?? []).map((section) => ({
        ...section,
        options: section.options ?? [],
      })),
      warnings: (request.warnings ?? []).map((warning) => ({
        ...warning,
        options: warning.options ?? [],
      })),
    } as ChoiceRequest;
  if (request.type === "form")
    return { ...request, answer: request.answer ?? {} } as FormRequest;
  return request;
}

function normalizeSpecification(
  specification: Schema["Specification"],
): Specification {
  return {
    ...specification,
    features: (specification.features ?? []).map((feature) => ({
      ...feature,
      behaviours: (feature.behaviours ?? []).map((behaviour) => ({
        ...behaviour,
        criteria: behaviour.criteria ?? [],
      })),
    })),
    personas: specification.personas ?? [],
    scenarios: specification.scenarios ?? [],
    tasks: (specification.tasks ?? []).map((task) => ({
      ...task,
      fixtures: task.fixtures ?? [],
      behaviour_refs: task.behaviour_refs ?? [],
      num_trials: task.num_trials ?? 3,
      max_turns: task.max_turns ?? 20,
      timeout_minutes: task.timeout_minutes ?? 15,
      response_wait_ms: task.response_wait_ms ?? 300000,
      max_run_retries: task.max_run_retries ?? null,
    })),
  };
}

function normalizeState(state: Schema["InterviewState-Input"]): InterviewState {
  return {
    ...state,
    specification: normalizeSpecification(state.specification),
    context: state.context,
    history: state.history ?? [],
    user_typed: state.user_typed ?? [],
    issued_ids: state.issued_ids ?? [],
    pending: state.pending ? normalizeRequest(state.pending) : null,
  };
}

// The browser state omits some server-defaulted fields (`muted`, `submit_label`). The server
// fills each default, so the browser value is a valid request body.
function wireState(state: InterviewState): TurnRequest["state"] {
  return state as TurnRequest["state"];
}

type WireInterviewResult = StartResponse | TurnResponse | EndResponse;
function normalizeResult(resultValue: WireInterviewResult): InterviewResult {
  if (resultValue.type === "failure")
    return {
      ...resultValue,
      state: resultValue.state
        ? normalizeState(resultValue.state)
        : resultValue.state,
      missing: resultValue.missing ?? [],
    } as InterviewFailure;
  return {
    ...resultValue,
    state: normalizeState(resultValue.state),
    missing: resultValue.missing ?? [],
  } as InterviewSuccess;
}

// Browser-only display state. These fields never enter InterviewState or an API request.
export interface InitialDescriptionEntry {
  kind: "initial_description";
  id: string;
  description: string;
}
export interface InteractionEntry {
  kind: "interaction";
  request_id: string;
  request: WizardRequest;
  response?: UserResponse;
  status: "pending" | "sending" | "failed" | "answered" | "ended_unanswered";
  outbound?: {
    files: LocalFixture[];
    removedFixtures: string[];
    attempt: number;
  };
  failure?: {
    message: string;
    retryable: boolean;
    kind: "request" | "interrupted" | "storage";
  };
}
export type TranscriptEntry = InitialDescriptionEntry | InteractionEntry;
export interface LocalInterviewRecord {
  storage_version: 6;
  submission_revision?: number;
  id: string;
  created_at: number;
  updated_at: number;
  title: string;
  stage: InterviewStep;
  state: InterviewState;
  transcript: TranscriptEntry[];
  fixtures: LocalFixture[];
}
export interface LocalFixture {
  name: string;
  type: string;
  size: number;
  blob: Blob;
}
export interface InterviewSummary {
  id: string;
  title: string;
  updated: number;
}
export interface PresentationView {
  id: string;
  stage: InterviewStep;
  done: boolean;
  requests: WizardRequest[];
  specification: Specification;
}

export class TransportError extends Error {
  readonly status?: number;
  readonly code?: string;
  readonly retryable: boolean;
  constructor(
    message: string,
    options: {
      status?: number;
      code?: string;
      retryable?: boolean;
      cause?: unknown;
    } = {},
  ) {
    super(
      message,
      options.cause === undefined ? undefined : { cause: options.cause },
    );
    this.name = "TransportError";
    this.status = options.status;
    this.code = options.code;
    this.retryable = options.retryable ?? false;
  }
}

async function responseFor(
  path: keyof ApiPaths,
  init?: RequestInit,
): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch (cause) {
    throw new TransportError("Couldn't reach the METIS API.", {
      retryable: true,
      cause,
    });
  }
  if (!response.ok) {
    let detail: Partial<InterviewFailure> = {};
    try {
      detail = (await response.json()) as Partial<InterviewFailure>;
    } catch {
      /* status is enough */
    }
    throw new TransportError(
      detail.message ?? `The METIS API returned HTTP ${response.status}.`,
      {
        status: response.status,
        code: detail.code,
        retryable: detail.retryable ?? response.status >= 500,
      },
    );
  }
  return response;
}

async function call<T>(path: keyof ApiPaths, init?: RequestInit): Promise<T> {
  return (await responseFor(path, init).then((response) =>
    response.json(),
  )) as T;
}

async function callBlob(
  path: keyof ApiPaths,
  init?: RequestInit,
): Promise<{ blob: Blob; filename: string }> {
  const response = await responseFor(path, init);
  const filename = response.headers
    .get("Content-Disposition")
    ?.match(/^attachment; filename="([a-z0-9-]+\.zip)"$/)?.[1];
  if (!filename) throw new Error("The export response has no valid filename.");
  return { blob: await response.blob(), filename };
}

const JSON_POST: RequestInit = {
  method: "POST",
  headers: { "content-type": "application/json" },
};
function result(resultValue: WireInterviewResult): InterviewSuccess {
  const normalized = normalizeResult(resultValue);
  if (normalized.type === "failure")
    throw new TransportError(normalized.message, {
      code: normalized.code,
      retryable: normalized.retryable,
    });
  return normalized;
}

export const api = {
  start: async (
    description: string,
    capabilityEvidence: CapabilityEvidence | null,
    perspective: Perspective = "end_user",
    documents: InterviewDocument[] = [],
    connection: TargetConnection | null = null,
  ) => {
    const body: StartRequest = {
      description,
      perspective,
      ...(capabilityEvidence
        ? {
            known_capability_ids: capabilityEvidence.known_capability_ids,
            capability_confidence: capabilityEvidence.confidence,
          }
        : {}),
      documents,
      // spec-only mode sends no connection, so its request is unchanged
      ...(connection ? { connection } : {}),
    };
    return result(
      await call<StartResponse>("/api/v1/wizard/interview/start", {
        ...JSON_POST,
        body: JSON.stringify(body),
      }),
    );
  },
  respond: async (
    state: InterviewState,
    request_id: string,
    response: UserResponse,
  ) => {
    const body: TurnRequest = { state: wireState(state), request_id, response };
    return result(
      await call<TurnResponse>("/api/v1/wizard/interview/turn", {
        ...JSON_POST,
        body: JSON.stringify(body),
      }),
    );
  },
  end: async (state: InterviewState) => {
    const body: EndRequest = { state: wireState(state) };
    return result(
      await call<EndResponse>("/api/v1/wizard/interview/end", {
        ...JSON_POST,
        body: JSON.stringify(body),
      }),
    );
  },
  compile: (specification: Specification) =>
    call<CompileResponse>("/api/v1/wizard/compile", {
      ...JSON_POST,
      body: JSON.stringify(specification),
    }),
  checkConnection: (binding: Record<string, unknown>) => {
    const body: ConnectionCheckRequest = { binding };
    return call<ConnectionCheckResult>("/api/v1/wizard/connection/check", {
      ...JSON_POST,
      body: JSON.stringify(body),
    });
  },
  setConnection: async (
    state: InterviewState,
    connection: TargetConnection | null,
  ) => {
    const body: ConnectionRequest = { state: wireState(state), connection };
    return normalizeState(
      await call<ConnectionResponse>("/api/v1/wizard/connection", {
        ...JSON_POST,
        body: JSON.stringify(body),
      }),
    );
  },
  graders: () => call<GradersResponse>("/api/v1/graders"),
  models: () => call<ModelsResponse>("/api/v1/models"),
  config: () => call<ConfigResponse>("/api/v1/wizard/config"),
  extractDocuments: (files: readonly File[]) => {
    const form = new FormData();
    for (const file of files) form.append("files", file, file.name);
    return call<ExtractDocumentsResponse>("/api/v1/wizard/documents/extract", {
      method: "POST",
      body: form,
    });
  },
  package: (
    // An Interview carries its connection in its state. A manual Specification sends its own.
    source:
      | { state: InterviewState }
      | { specification: Specification; connection?: TargetConnection },
    files: readonly PackageFile[],
  ) => {
    const form = new FormData();
    if ("state" in source) form.append("state", JSON.stringify(source.state));
    else {
      form.append("specification", JSON.stringify(source.specification));
      if (source.connection)
        form.append("connection", JSON.stringify(source.connection));
    }
    for (const file of files) form.append("files", file.blob, file.name);
    return callBlob("/api/v1/wizard/package", {
      method: "POST",
      body: form,
    });
  },
};

export function toSummary(record: LocalInterviewRecord): InterviewSummary {
  return { id: record.id, title: record.title, updated: record.updated_at };
}
export function titleFor(specification: Specification): string {
  return specification.target.name.trim() || "Untitled Interview";
}
