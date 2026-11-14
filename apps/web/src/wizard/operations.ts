import type {
  InteractionEntry,
  LoadedInterviewRecord,
  UserResponse,
} from "../transport/api.ts";
import { api, TransportError } from "../transport/api.ts";
import {
  addFixtures,
  removeUnreferencedFixtures,
  type InterviewRepository,
} from "../storage/repository.ts";
import { readmitSavedFile, type AdmittedFile } from "../fixture-policy.ts";
import { applyTurn } from "./transcript.ts";

export interface OperationFeedback {
  message: string;
  retry?: () => Promise<void>;
}
export function pendingEntry(
  record: LoadedInterviewRecord,
): InteractionEntry | undefined {
  return record.transcript.find(
    (entry): entry is InteractionEntry =>
      entry.kind === "interaction" &&
      entry.request_id === record.state.pending?.request_id,
  );
}
export function messageOf(cause: unknown): string {
  return cause instanceof Error ? cause.message : "The operation failed.";
}

// This page owns live operations. A repository read alone never interrupts a send.
export class InterviewOperations {
  readonly pendingSaves = new Map<string, LoadedInterviewRecord>();
  readonly latest = new Map<string, LoadedInterviewRecord>();
  readonly active = new Set<string>();
  readonly feedback = new Map<string, OperationFeedback>();
  private revision = 0;
  private listeners = new Set<() => void>();
  private repository: Pick<InterviewRepository, "put">;
  private saved: (record: LoadedInterviewRecord) => void;
  constructor(
    repository: Pick<InterviewRepository, "put">,
    saved: (record: LoadedInterviewRecord) => void,
  ) {
    this.repository = repository;
    this.saved = (record) => {
      this.latest.set(record.id, record);
      saved(record);
    };
  }
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
  snapshot = () => this.revision;
  private changed() {
    this.revision++;
    this.listeners.forEach((listener) => listener());
  }
  dismiss(id: string) {
    this.feedback.delete(id);
    this.changed();
  }
  report(id: string, message: string, retry?: () => Promise<void>) {
    this.feedback.set(id, { message, retry });
    this.changed();
  }
  async run(
    id: string,
    work: () => Promise<void>,
    retry?: () => Promise<void>,
  ): Promise<void> {
    if (this.active.has(id)) return;
    this.active.add(id);
    this.feedback.delete(id);
    this.changed();
    try {
      await work();
    } catch (cause) {
      if (!this.feedback.has(id))
        this.report(
          id,
          messageOf(cause),
          cause instanceof TransportError && cause.retryable
            ? retry
            : undefined,
        );
    } finally {
      this.active.delete(id);
      this.changed();
    }
  }
  async save(record: LoadedInterviewRecord): Promise<void> {
    try {
      await this.repository.put(record);
    } catch (cause) {
      this.pendingSaves.set(record.id, record);
      this.report(
        record.id,
        `The update was not saved. ${messageOf(cause)}`,
        () => this.run(record.id, () => this.save(record)),
      );
      throw cause;
    }
    this.pendingSaves.delete(record.id);
    this.saved(record);
  }
  async recover(record: LoadedInterviewRecord): Promise<LoadedInterviewRecord> {
    if (this.active.has(record.id) || this.pendingSaves.has(record.id))
      return record;
    const entry = pendingEntry(record);
    if (
      entry?.status !== "sending" &&
      !(entry?.status === "failed" && entry.failure?.kind === "storage")
    )
      return record;
    const next = structuredClone(record);
    const pending = pendingEntry(next)!;
    pending.status = "failed";
    pending.failure = {
      message: "The reply was interrupted. Choose Retry to send it again.",
      retryable: true,
      kind: "interrupted",
    };
    try {
      await this.save(next);
    } catch {
      this.saved(next);
    }
    return next;
  }
  async send(
    record: LoadedInterviewRecord,
    response: UserResponse,
    files: readonly AdmittedFile[] = [],
    removedFixtures: readonly string[] = [],
    accepted?: () => void,
  ): Promise<void> {
    if (
      !record.state.pending ||
      this.active.has(record.id) ||
      this.pendingSaves.has(record.id)
    )
      return;
    const latest = this.latest.get(record.id);
    if (
      latest &&
      latest.state.pending?.request_id !== record.state.pending.request_id
    )
      return;
    record = latest ?? record;
    const existing = pendingEntry(record);
    if (
      !existing ||
      existing.status === "sending" ||
      (existing.status === "failed" && !existing.failure?.retryable)
    )
      return;
    await this.run(record.id, async () => {
      const sending = structuredClone(record);
      sending.submission_revision = (record.submission_revision ?? 0) + 1;
      const entry = pendingEntry(sending)!;
      // `addFixtures` checks the names before they can reach the store.
      const staged = addFixtures(record, files).fixtures.slice(
        record.fixtures.length,
      );
      entry.response = structuredClone(response);
      entry.outbound = {
        files: staged,
        removedFixtures: [...removedFixtures],
        attempt: (entry.outbound?.attempt ?? 0) + 1,
      };
      entry.status = "sending";
      delete entry.failure;
      // Nothing is sent if saving the submitted input fails.
      await this.repository.put(sending);
      this.saved(sending);
      accepted?.();
      let next: LoadedInterviewRecord;
      try {
        const result = await api.respond(
          sending.state,
          entry.request_id,
          response,
        );
        next = removeUnreferencedFixtures(
          applyTurn(addFixtures(sending, files), result, response),
          removedFixtures,
        );
      } catch (cause) {
        const failed = structuredClone(sending);
        const failedEntry = pendingEntry(failed)!;
        failedEntry.status = "failed";
        failedEntry.failure = {
          message: messageOf(cause),
          retryable: cause instanceof TransportError && cause.retryable,
          kind: "request",
        };
        await this.save(failed);
        return;
      }
      try {
        await this.save(next);
      } catch {
        const failed = structuredClone(sending);
        const failedEntry = pendingEntry(failed)!;
        failedEntry.status = "failed";
        failedEntry.failure = {
          message: "The result was not saved. Choose Retry to save it.",
          retryable: true,
          kind: "storage",
        };
        // A second storage write can fail too. Keep the visible failure and the save retry.
        try {
          await this.repository.put(failed);
        } catch {
          /* The last durable record stays sending. */
        }
        this.saved(failed);
      }
    });
  }
  // Back from a completed Interview. It has no pending request, so the turn carries an empty
  // request id; the package reopens the last review and clears the final confirmation.
  async reopen(record: LoadedInterviewRecord): Promise<void> {
    if (record.state.pending || this.pendingSaves.has(record.id)) return;
    await this.run(record.id, async () => {
      const response: UserResponse = { type: "choice", selected: ["back"] };
      const result = await api.respond(record.state, "", response);
      await this.save(applyTurn(record, result, response));
    });
  }
  async edit(record: LoadedInterviewRecord): Promise<void> {
    if (this.pendingSaves.has(record.id)) return;
    await this.run(record.id, async () => {
      const next = structuredClone(record);
      const entry = pendingEntry(next);
      if (entry?.status !== "failed") return;
      entry.status = "pending";
      delete entry.failure;
      delete entry.response;
      delete entry.outbound;
      await this.save(next);
    });
  }
  retry(record: LoadedInterviewRecord): Promise<void> {
    const unsaved = this.pendingSaves.get(record.id);
    if (unsaved) return this.run(record.id, () => this.save(unsaved));
    const entry = pendingEntry(record);
    if (!entry?.response || !entry.failure?.retryable) return Promise.resolve();
    const files = (entry.outbound?.files ?? []).map(readmitSavedFile);
    return this.send(
      record,
      entry.response,
      files,
      entry.outbound?.removedFixtures,
    );
  }
}
