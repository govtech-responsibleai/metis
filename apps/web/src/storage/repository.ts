import type {
  FileRef,
  InterviewState,
  InterviewSummary,
  LoadedFixture,
  LoadedInterviewRecord,
  StorageProblem,
  StoredInterviewRecord,
  TranscriptEntry,
} from "../transport/api.ts";
import { store, TransportError } from "../transport/api.ts";
import { fixtureNameIdentity, type AdmittedFile } from "../fixture-policy.ts";

export type { StorageProblem };

function fileRef(fixture: LoadedFixture): FileRef {
  return { name: fixture.name, type: fixture.type, size: fixture.size };
}

function outboundFiles(entry: TranscriptEntry): LoadedFixture[] {
  return entry.kind === "interaction" ? (entry.outbound?.files ?? []) : [];
}

// Each file of a record, one time for each name. The files of an answer that is not accepted
// yet are in the transcript and not in `fixtures`, and the store holds them too.
export function recordFiles(record: LoadedInterviewRecord): LoadedFixture[] {
  const files = new Map<string, LoadedFixture>();
  for (const fixture of [
    ...record.fixtures,
    ...record.transcript.flatMap(outboundFiles),
  ])
    if (!files.has(fixture.name)) files.set(fixture.name, fixture);
  return [...files.values()];
}

function fileSizes(files: readonly LoadedFixture[]): Map<string, number> {
  return new Map(files.map((fixture) => [fixture.name, fixture.blob.size]));
}

function storedRecord(record: LoadedInterviewRecord): StoredInterviewRecord {
  return {
    ...record,
    fixtures: record.fixtures.map(fileRef),
    transcript: record.transcript.map((entry) =>
      entry.kind === "interaction" && entry.outbound
        ? {
            ...entry,
            outbound: {
              ...entry.outbound,
              files: entry.outbound.files.map(fileRef),
            },
          }
        : entry,
    ),
  };
}

async function loadedFixture(id: string, ref: FileRef): Promise<LoadedFixture> {
  try {
    return { ...ref, blob: await store.interviewFile(id, ref.name) };
  } catch (cause) {
    if (cause instanceof TransportError && cause.status === 404)
      throw new Error(`The file ${ref.name} is missing from the store.`, {
        cause,
      });
    throw cause;
  }
}

async function loadedRecord(
  record: StoredInterviewRecord,
): Promise<LoadedInterviewRecord> {
  const fixtures = await Promise.all(
    record.fixtures.map((ref) => loadedFixture(record.id, ref)),
  );
  const transcript = await Promise.all(
    record.transcript.map(async (entry): Promise<TranscriptEntry> => {
      if (entry.kind !== "interaction") return entry;
      const { outbound, ...interaction } = entry;
      if (!outbound) return interaction;
      const files = await Promise.all(
        outbound.files.map((ref) => loadedFixture(record.id, ref)),
      );
      return { ...interaction, outbound: { ...outbound, files } };
    }),
  );
  return { ...record, transcript, fixtures };
}

// The Interviews of every Target in the API store.
export class InterviewRepository {
  private problemsValue: StorageProblem[] = [];
  // The size of each file that the store has, by Target id and file name. A put sends only
  // the other files. A copy of a record has new Blob objects, so the name is the key. After a
  // save, the store has exactly the files of the saved record.
  private stored = new Map<string, Map<string, number>>();

  get problems(): readonly StorageProblem[] {
    return this.problemsValue;
  }

  async list(): Promise<InterviewSummary[]> {
    const listed = await store.targets();
    this.problemsValue = listed.problems;
    return listed.targets.map((target) => ({
      id: target.id,
      title: target.title,
      updated: Date.parse(target.updated_at),
    }));
  }

  async read(id: string): Promise<LoadedInterviewRecord | undefined> {
    let record: StoredInterviewRecord;
    try {
      record = await store.interview(id);
    } catch (cause) {
      if (cause instanceof TransportError && cause.status === 404)
        return undefined;
      if (cause instanceof TransportError && cause.status === 409) {
        this.problemsValue = [{ id, message: cause.message }];
        return undefined;
      }
      throw cause;
    }
    const loaded = await loadedRecord(record);
    this.stored.set(id, fileSizes(recordFiles(loaded)));
    return loaded;
  }

  async put(record: LoadedInterviewRecord): Promise<void> {
    const files = recordFiles(record);
    const stored = this.stored.get(record.id);
    const uploads = files.filter(
      (fixture) => stored?.get(fixture.name) !== fixture.blob.size,
    );
    await store.putInterview(record.id, storedRecord(record), uploads);
    this.stored.set(record.id, fileSizes(files));
  }

  async delete(id: string): Promise<void> {
    await store.deleteTarget(id);
    this.stored.delete(id);
  }
}

// The Target id of a new Interview, which is also its folder name. It has the format of a
// `metis wizard init` folder, in local time. A later attempt adds `-2`, `-3`, and so on.
export function interviewId(now: Date, attempt = 1): string {
  const two = (value: number) => String(value).padStart(2, "0");
  const date = `${now.getFullYear()}${two(now.getMonth() + 1)}${two(now.getDate())}`;
  const time = `${two(now.getHours())}${two(now.getMinutes())}${two(now.getSeconds())}`;
  return `${date}-${time}-interview${attempt > 1 ? `-${attempt}` : ""}`;
}

const CREATE_ATTEMPTS = 5;

// Save a new Interview under the id of `started`. When another Interview has the id, save it
// under the next id. The record keeps its `created_at`, so a resend of a save that the store
// already has does not make a second Interview.
export async function putNew(
  repository: Pick<InterviewRepository, "put">,
  record: LoadedInterviewRecord,
  started: Date,
): Promise<LoadedInterviewRecord> {
  for (let attempt = 1; ; attempt++) {
    const next = { ...record, id: interviewId(started, attempt) };
    try {
      await repository.put(next);
      return next;
    } catch (cause) {
      const taken =
        cause instanceof TransportError &&
        cause.status === 409 &&
        cause.code === "target_exists";
      if (!taken || attempt >= CREATE_ATTEMPTS) throw cause;
    }
  }
}

export function emptyRecord(
  id: string,
  state: InterviewState,
  stage: LoadedInterviewRecord["stage"],
  transcript: TranscriptEntry[],
): LoadedInterviewRecord {
  const now = Date.now();
  return {
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
  record: LoadedInterviewRecord,
  files: readonly AdmittedFile[],
): LoadedInterviewRecord {
  const names = new Set(
    record.fixtures.map((fixture) => fixtureNameIdentity(fixture.name)),
  );
  for (const file of files)
    if (names.has(fixtureNameIdentity(file.name)))
      throw new Error(
        `The Interview already has a file named ${file.name}. Admit each file before you add it.`,
      );
  return {
    ...record,
    fixtures: [
      ...record.fixtures,
      ...files.map((file) => ({
        name: file.name,
        type: file.type,
        size: file.size,
        blob: file,
      })),
    ],
  };
}

export function removeUnreferencedFixtures(
  record: LoadedInterviewRecord,
  names: readonly string[],
): LoadedInterviewRecord {
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
  record: LoadedInterviewRecord,
): LoadedFixture[] {
  const excluded = new Set(record.state.excluded_tasks ?? []);
  const references = new Set(
    record.state.specification.tasks
      .filter((task) => !excluded.has(task.id))
      .flatMap((task) => task.fixtures),
  );
  return record.fixtures.filter((fixture) => references.has(fixture.name));
}
