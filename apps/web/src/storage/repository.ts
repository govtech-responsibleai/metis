import type {
  InterviewState,
  InterviewStep,
  LocalFixture,
  LocalInterviewRecord,
  TranscriptEntry,
} from "../transport/api.ts";
import { fixtureNameIdentity } from "../fixture-policy.ts";

const DB_NAME = "metis-web";
const STORE_NAME = "interviews";
const DB_VERSION = 5;
const STORAGE_VERSION = 6 as const;
const INTERVIEW_STEPS: readonly InterviewStep[] = [
  "clarify",
  "behaviours",
  "criteria",
  "personas",
  "scenarios",
  "test_cases",
  "done",
];

export interface LocalStorageProblem {
  id: string;
  message: string;
}

function hasOldCriterionFormat(value: unknown): boolean {
  if (Array.isArray(value)) return value.some(hasOldCriterionFormat);
  if (!storedObject(value)) return false;
  if ("given" in value && "when" in value && "then" in value) return true;
  if (value.type === "form" && Array.isArray(value.fields)) {
    const ids = value.fields.filter(storedObject).map((field) => field.id);
    if (["given", "when", "then"].every((id) => ids.includes(id))) return true;
  }
  return Object.values(value).some(hasOldCriterionFormat);
}

function unreadableMessage(value: unknown): string {
  return hasOldCriterionFormat(value)
    ? "This saved Interview uses an older Criterion format. Start a new Interview to continue. The saved Interview remains in this browser."
    : "This local Interview cannot be read.";
}

function validRecord(value: unknown): value is LocalInterviewRecord {
  if (!value || typeof value !== "object") return false;
  const record = value as Partial<LocalInterviewRecord>;
  return (
    !hasOldCriterionFormat(value) &&
    record.storage_version === STORAGE_VERSION &&
    typeof record.id === "string" &&
    typeof record.created_at === "number" &&
    Number.isFinite(record.created_at) &&
    typeof record.updated_at === "number" &&
    Number.isFinite(record.updated_at) &&
    typeof record.title === "string" &&
    typeof record.stage === "string" &&
    INTERVIEW_STEPS.includes(record.stage) &&
    validState(record.state) &&
    Array.isArray(record.transcript) &&
    record.transcript.every(validTranscriptEntry) &&
    Array.isArray(record.fixtures) &&
    record.fixtures.every(validFixture)
  );
}

function validFixture(value: unknown): value is LocalFixture {
  if (!value || typeof value !== "object") return false;
  const fixture = value as Partial<LocalFixture>;
  return (
    typeof fixture.name === "string" &&
    fixture.name.length > 0 &&
    typeof fixture.type === "string" &&
    typeof fixture.size === "number" &&
    Number.isFinite(fixture.size) &&
    fixture.size >= 0 &&
    typeof Blob !== "undefined" &&
    fixture.blob instanceof Blob &&
    fixture.size === fixture.blob.size
  );
}

function validState(value: unknown): value is InterviewState {
  if (!value || typeof value !== "object") return false;
  const state = value as Partial<InterviewState>;
  const context = state.context;
  if (!context || typeof context !== "object") return false;
  const evidence = context.capability_evidence;
  if (
    evidence != null &&
    (typeof evidence !== "object" ||
      !Array.isArray(evidence.known_capability_ids) ||
      typeof evidence.confidence !== "string")
  )
    return false;
  return (
    !!state.specification &&
    typeof state.specification === "object" &&
    state.specification.schema_version === 1 &&
    storedObject(state.specification.target) &&
    typeof state.specification.target.name === "string" &&
    typeof state.specification.target.description === "string" &&
    typeof state.specification.target.users === "string" &&
    Array.isArray(state.specification.features) &&
    Array.isArray(state.specification.personas) &&
    Array.isArray(state.specification.scenarios) &&
    Array.isArray(state.specification.tasks) &&
    state.specification.tasks.every(
      (task) =>
        !!task &&
        Array.isArray(task.behaviour_refs) &&
        task.behaviour_refs.every((ref) => typeof ref === "string"),
    ) &&
    Array.isArray(state.history) &&
    Array.isArray(state.user_typed) &&
    Array.isArray(state.issued_ids) &&
    (state.pending === null ||
      (typeof state.pending === "object" && state.pending !== null))
  );
}

function validTranscriptEntry(value: unknown): value is TranscriptEntry {
  if (!value || typeof value !== "object") return false;
  const entry = value as Partial<TranscriptEntry>;
  if (entry.kind === "initial_description") {
    return (
      typeof entry.id === "string" && typeof entry.description === "string"
    );
  }
  return (
    entry.kind === "interaction" &&
    typeof entry.request_id === "string" &&
    (entry.outbound === undefined ||
      (!!entry.outbound &&
        Array.isArray(entry.outbound.files) &&
        entry.outbound.files.every(validFixture) &&
        Array.isArray(entry.outbound.removedFixtures) &&
        entry.outbound.removedFixtures.every(
          (name) => typeof name === "string",
        ) &&
        Number.isInteger(entry.outbound.attempt) &&
        entry.outbound.attempt > 0)) &&
    (entry.failure === undefined ||
      (!!entry.failure &&
        typeof entry.failure.message === "string" &&
        typeof entry.failure.retryable === "boolean" &&
        ["request", "storage", "interrupted"].includes(entry.failure.kind))) &&
    (!["sending", "failed"].includes(entry.status ?? "") ||
      (!!entry.response && !!entry.outbound)) &&
    (entry.status !== "failed" || !!entry.failure) &&
    (entry.status === "pending" ||
      entry.status === "sending" ||
      entry.status === "failed" ||
      entry.status === "answered" ||
      entry.status === "ended_unanswered") &&
    !!entry.request &&
    typeof entry.request === "object"
  );
}

function storedObject(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function targetPath(value: unknown): unknown {
  return typeof value === "string" && value.startsWith("product.")
    ? `target.${value.slice("product.".length)}`
    : value;
}

// Requests can contain field IDs and patch paths. Keep all user prose unchanged.
function targetRequest(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(targetRequest);
  if (!storedObject(value)) return value;
  return Object.fromEntries(
    Object.entries(value).map(([key, entry]) => {
      if ((key === "answer" || key === "values") && storedObject(entry)) {
        return [
          key,
          Object.fromEntries(
            Object.entries(entry).map(([field, text]) => [
              targetPath(field),
              text,
            ]),
          ),
        ];
      }
      if (["id", "path", "target", "subject"].includes(key)) {
        return [key, targetPath(entry)];
      }
      return [key, key === "value" ? entry : targetRequest(entry)];
    }),
  );
}

function targetSpecification(value: unknown): unknown {
  if (!storedObject(value) || !("product" in value)) return value;
  const { product, ...specification } = value;
  return { ...specification, target: specification.target ?? product };
}

function targetTranscript(value: unknown): unknown {
  if (!Array.isArray(value)) return value;
  return value.map((entry) => {
    if (!storedObject(entry) || entry.kind !== "interaction") return entry;
    return {
      ...entry,
      request: targetRequest(entry.request),
      ...(entry.response === undefined
        ? {}
        : { response: targetRequest(entry.response) }),
    };
  });
}

function currentRecord(
  value: Record<string, unknown>,
): Record<string, unknown> {
  const rawState = value.state;
  if (!rawState || typeof rawState !== "object") return value;
  const state = rawState as Record<string, unknown>;
  const rawContext = state.context;
  if (!rawContext || typeof rawContext !== "object") return value;
  const context = rawContext as Record<string, unknown>;
  const openingEntry = Array.isArray(value.transcript)
    ? value.transcript.find(
        (entry) =>
          !!entry &&
          typeof entry === "object" &&
          (entry as Record<string, unknown>).kind === "initial_description" &&
          typeof (entry as Record<string, unknown>).description === "string",
      )
    : undefined;
  return {
    ...value,
    storage_version: STORAGE_VERSION,
    transcript: targetTranscript(value.transcript),
    state: {
      ...state,
      specification: targetSpecification(state.specification),
      pending: targetRequest(state.pending),
      user_typed: Array.isArray(state.user_typed)
        ? state.user_typed.map(targetPath)
        : state.user_typed,
      context: {
        ...context,
        opening_description:
          typeof context.opening_description === "string"
            ? context.opening_description
            : openingEntry
              ? (openingEntry as Record<string, string>).description
              : "",
        documents: Array.isArray(context.documents) ? context.documents : [],
      },
    },
    fixtures: Array.isArray(value.fixtures) ? value.fixtures : [],
  };
}

const memory = new Map<string, LocalInterviewRecord>();

// Two request shapes changed in this storage version. A `disclosure` component (a label and text
// items) is now a `details` component, and a form choice is now `{value, label}`. Both convert
// without loss, in the transcript and in the pending request. The conversion runs on each read
// and changes nothing in a record that already has the new shapes.
function reviewShape(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(reviewShape);
  if (!storedObject(value)) return value;
  if (value.type === "disclosure")
    return {
      type: "details",
      title: typeof value.label === "string" ? value.label : "Details",
      muted: true,
      expanded: false,
      components: Array.isArray(value.items) ? value.items : [],
    };
  return Object.fromEntries(
    Object.entries(value).map(([key, entry]) => [
      key,
      key === "choices" && Array.isArray(entry)
        ? entry.map((choice) =>
            typeof choice === "string"
              ? { value: choice, label: choice }
              : choice,
          )
        : key === "value" || key === "text"
          ? entry
          : reviewShape(entry),
    ]),
  );
}

function reviewRecord(value: unknown): unknown {
  if (!storedObject(value) || value.storage_version !== STORAGE_VERSION)
    return value;
  const state = storedObject(value.state) ? value.state : undefined;
  return {
    ...value,
    // Only the request objects change. Entries keep their outbound files (Blobs) as they are.
    transcript: Array.isArray(value.transcript)
      ? value.transcript.map((entry) =>
          storedObject(entry) && entry.kind === "interaction"
            ? { ...entry, request: reviewShape(entry.request) }
            : entry,
        )
      : value.transcript,
    ...(state
      ? { state: { ...state, pending: reviewShape(state.pending) } }
      : {}),
  };
}

export class InterviewRepository {
  private problemsValue: LocalStorageProblem[] = [];

  get problems(): readonly LocalStorageProblem[] {
    return this.problemsValue;
  }

  async list(): Promise<LocalInterviewRecord[]> {
    const rows = (await this.allRaw()).map(reviewRecord);
    const healthy: LocalInterviewRecord[] = [];
    this.problemsValue = [];
    for (const row of rows) {
      if (validRecord(row)) healthy.push(row);
      else
        this.problemsValue.push({
          id:
            typeof row === "object" && row && "id" in row
              ? String((row as { id?: unknown }).id)
              : "unknown",
          message: unreadableMessage(row),
        });
    }
    return healthy.sort((a, b) => b.updated_at - a.updated_at);
  }

  async read(id: string): Promise<LocalInterviewRecord | undefined> {
    const row = reviewRecord(await this.raw(id));
    if (row === undefined) return undefined;
    if (!validRecord(row)) {
      this.problemsValue = [{ id, message: unreadableMessage(row) }];
      return undefined;
    }
    return row;
  }

  async put(record: LocalInterviewRecord): Promise<void> {
    if (!validRecord(record))
      throw new Error("Invalid local Interview record.");
    await this.write(record);
  }

  async delete(id: string): Promise<void> {
    if (!globalThis.indexedDB) {
      memory.delete(id);
      return;
    }
    const db = await this.database();
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, "readwrite");
      tx.objectStore(STORE_NAME).delete(id);
      tx.oncomplete = () => resolve();
      tx.onerror = () =>
        reject(tx.error ?? new Error("Local Interview deletion failed."));
      tx.onabort = () =>
        reject(tx.error ?? new Error("Local Interview deletion failed."));
    });
  }

  private async allRaw(): Promise<unknown[]> {
    if (!globalThis.indexedDB) return [...memory.values()];
    const db = await this.database();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, "readonly");
      const request = tx.objectStore(STORE_NAME).getAll();
      request.onsuccess = () => resolve(request.result as unknown[]);
      request.onerror = () =>
        reject(
          request.error ?? new Error("Local Interviews could not be read."),
        );
    });
  }

  private async raw(id: string): Promise<unknown> {
    if (!globalThis.indexedDB) return memory.get(id);
    const db = await this.database();
    return new Promise((resolve, reject) => {
      const request = db
        .transaction(STORE_NAME, "readonly")
        .objectStore(STORE_NAME)
        .get(id);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () =>
        reject(
          request.error ?? new Error("Local Interview could not be read."),
        );
    });
  }

  private async write(record: LocalInterviewRecord): Promise<void> {
    if (!globalThis.indexedDB) {
      memory.set(record.id, structuredClone(record));
      return;
    }
    const db = await this.database();
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, "readwrite");
      tx.objectStore(STORE_NAME).put(record);
      tx.oncomplete = () => resolve();
      tx.onerror = () =>
        reject(tx.error ?? new Error("Local Interview could not be saved."));
      tx.onabort = () =>
        reject(tx.error ?? new Error("Local Interview could not be saved."));
    });
  }

  private database(): Promise<IDBDatabase> {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = (event) => {
        const oldVersion = (event as IDBVersionChangeEvent).oldVersion;
        const store = request.result.objectStoreNames.contains(STORE_NAME)
          ? request.transaction?.objectStore(STORE_NAME)
          : request.result.createObjectStore(STORE_NAME, { keyPath: "id" });
        if (!store || oldVersion >= DB_VERSION) return;
        const cursor = store.openCursor();
        cursor.onsuccess = () => {
          const current = cursor.result;
          if (!current) return;
          const value = current.value as Partial<LocalInterviewRecord>;
          const storageVersion = (value as { storage_version?: number })
            .storage_version;
          if (
            storageVersion === 2 ||
            storageVersion === 3 ||
            storageVersion === 4 ||
            storageVersion === 5
          ) {
            const row = value as unknown as Record<string, unknown>;
            current.update(currentRecord(row));
          }
          current.continue();
        };
      };
      request.onsuccess = () => {
        request.result.onversionchange = () => request.result.close();
        resolve(request.result);
      };
      request.onerror = () =>
        reject(
          request.error ?? new Error("Local Interview storage is unavailable."),
        );
    });
  }
}

export function emptyRecord(
  id: string,
  state: InterviewState,
  stage: LocalInterviewRecord["stage"],
  transcript: TranscriptEntry[],
): LocalInterviewRecord {
  const now = Date.now();
  return {
    storage_version: STORAGE_VERSION,
    id,
    created_at: now,
    updated_at: now,
    title: state.specification.target.name.trim() || "Untitled Interview",
    stage,
    state,
    transcript,
    fixtures: [],
  };
}

export function addFixtures(
  record: LocalInterviewRecord,
  files: readonly File[],
): LocalInterviewRecord {
  const fixtures = [...record.fixtures];
  for (const file of files) {
    const existing = fixtures.find(
      (fixture) =>
        fixtureNameIdentity(fixture.name) === fixtureNameIdentity(file.name),
    );
    const isOpeningDocument = (record.state.context.documents ?? []).some(
      (document) =>
        fixtureNameIdentity(document.name) === fixtureNameIdentity(file.name),
    );
    if (existing && isOpeningDocument) {
      throw new Error(
        `The initial document ${existing.name} cannot be replaced by a later upload.`,
      );
    }
    const next: LocalFixture = {
      name: file.name,
      type: file.type,
      size: file.size,
      blob: file,
    };
    const index = fixtures.findIndex((fixture) => fixture.name === file.name);
    if (index === -1) fixtures.push(next);
    else fixtures[index] = next;
  }
  return { ...record, fixtures };
}

export function removeUnreferencedFixtures(
  record: LocalInterviewRecord,
  names: readonly string[],
): LocalInterviewRecord {
  // A Test Case that the user cleared does not run, so its files are not packaged.
  const excluded = new Set(record.state.excluded_tasks ?? []);
  const references = new Set(
    record.state.specification.tasks
      .filter((task) => !excluded.has(task.id))
      .flatMap((task) => task.fixtures),
  );
  const removable = new Set(names.filter((name) => !references.has(name)));
  const openingDocuments = new Set(
    (record.state.context.documents ?? []).map((document) =>
      fixtureNameIdentity(document.name),
    ),
  );
  if (removable.size === 0) return record;
  return {
    ...record,
    fixtures: record.fixtures.filter(
      (fixture) =>
        !removable.has(fixture.name) ||
        openingDocuments.has(fixtureNameIdentity(fixture.name)),
    ),
  };
}

export function fixturesForSpecification(
  record: LocalInterviewRecord,
): LocalFixture[] {
  // A Test Case that the user cleared does not run, so its files are not packaged.
  const excluded = new Set(record.state.excluded_tasks ?? []);
  const references = new Set(
    record.state.specification.tasks
      .filter((task) => !excluded.has(task.id))
      .flatMap((task) => task.fixtures),
  );
  return record.fixtures.filter((fixture) => references.has(fixture.name));
}
