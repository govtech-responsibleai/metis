import { useCallback, useRef, useState } from "react";
import { api, type InterviewDocument } from "./transport/api.ts";
import {
  admitFiles,
  type AdmittedFile,
  type FixtureFileLike,
  type FixtureLimits,
} from "./fixture-policy.ts";

// How far the app is with the text of one document that waits to be sent.
export type DocumentRead =
  | { status: "reading" | "not_read" | "kept" }
  | { status: "read"; text: string }
  | { status: "failed"; message: string };

export type DocumentReads = Record<string, DocumentRead>;

// The limits of `GET /config` that the intake of documents uses.
export interface DocumentLimits extends FixtureLimits {
  max_extraction_file_bytes: number;
  max_text_characters_total: number;
  extraction_extensions?: readonly string[];
}

function fileExtension(name: string): string {
  return name.split(".").at(-1)?.toLowerCase() ?? "";
}

// The API counts the characters of a text, so the browser counts them the same way.
export function unicodeLength(value: string): number {
  return Array.from(value).length;
}

// The characters of text that the documents of a list give to the model.
export function documentTextLength(
  documents: readonly InterviewDocument[],
): number {
  return documents.reduce(
    (total, document) => total + unicodeLength(document.text ?? ""),
    0,
  );
}

function textOf(read: DocumentRead | undefined): string | undefined {
  return read?.status === "read" ? read.text : undefined;
}

// The documents of a start request or a turn request, or the reason that they cannot go yet.
// `held` is the documents that the Interview has: the text limit is for the full list.
export function documentsForRequest(
  files: readonly FixtureFileLike[],
  reads: DocumentReads,
  limits: Pick<DocumentLimits, "max_text_characters_total"> | undefined,
  held: readonly InterviewDocument[] = [],
): { documents: InterviewDocument[] } | { blocked: string } {
  if (files.length === 0) return { documents: [] };
  if (!limits) return { blocked: "Document limits are not available yet." };
  const unresolved = files.some((file) =>
    ["reading", "failed"].includes(reads[file.name]?.status ?? ""),
  );
  if (unresolved)
    return {
      blocked:
        "Wait for files to finish reading. For a file that could not be read, choose Use name only or remove it.",
    };
  const documents = files.map((file) => {
    const text = textOf(reads[file.name]);
    return { name: file.name, ...(text === undefined ? {} : { text }) };
  });
  if (
    documentTextLength([...held, ...documents]) >
    limits.max_text_characters_total
  )
    return {
      blocked: `Document text is above ${limits.max_text_characters_total.toLocaleString()} characters. Remove a file or choose Use name only for it.`,
    };
  return { documents };
}

async function extractText(file: File, maxFileBytes: number): Promise<string> {
  if (file.size > maxFileBytes)
    throw new Error(`${file.name} is larger than the text-reading limit.`);
  const result = await api.extractDocuments([file]);
  const document = result.documents.find((item) => item.name === file.name);
  if (!document) throw new Error(`No text was returned for ${file.name}.`);
  return document.text;
}

function errorMessage(cause: unknown): string {
  return cause instanceof Error ? cause.message : "The operation failed.";
}

export interface DocumentIntake {
  documents: AdmittedFile[];
  reads: DocumentReads;
  add: (files: readonly File[]) => void;
  remove: (name: string) => void;
  keepUnread: (name: string) => void;
  reset: () => void;
  // Put back the documents of a message that was not accepted, so the user can edit it.
  restore: (
    files: readonly AdmittedFile[],
    sent: readonly InterviewDocument[],
  ) => void;
}

// The documents that wait in one input until the user sends them: the opening message, or a
// message of an Interview. Each added file is admitted against `taken`, the files that the
// Interview already has, and then read for its text.
export function useDocumentIntake(
  limits: DocumentLimits | undefined,
  taken: readonly FixtureFileLike[],
  setError: (message: string | null) => void,
): DocumentIntake {
  const [documents, setDocuments] = useState<AdmittedFile[]>([]);
  const [reads, setReads] = useState<DocumentReads>({});
  // A text that comes back belongs to the input that asked for it. A reset starts a new one.
  const generation = useRef(0);

  const add = useCallback(
    (files: readonly File[]) => {
      try {
        if (!limits) throw new Error("Document limits are not available yet.");
        const admitted = admitFiles(files, [...taken, ...documents], limits);
        const added: DocumentReads = {};
        for (const file of admitted) {
          const canRead = limits.extraction_extensions?.includes(
            fileExtension(file.name),
          );
          added[file.name] = !canRead
            ? { status: "not_read" }
            : file.size > limits.max_extraction_file_bytes
              ? {
                  status: "failed",
                  message: "This file is larger than the text-reading limit.",
                }
              : { status: "reading" };
        }
        setDocuments((current) => [...current, ...admitted]);
        setReads((current) => ({ ...current, ...added }));
        setError(null);
        const asked = generation.current;
        for (const file of admitted) {
          if (added[file.name]?.status !== "reading") continue;
          const settle = (read: DocumentRead) => {
            if (asked !== generation.current) return;
            setReads((current) =>
              file.name in current
                ? { ...current, [file.name]: read }
                : current,
            );
          };
          void extractText(file, limits.max_extraction_file_bytes).then(
            (text) => settle({ status: "read", text }),
            (cause: unknown) =>
              settle({ status: "failed", message: errorMessage(cause) }),
          );
        }
      } catch (cause) {
        setError(errorMessage(cause));
      }
    },
    [documents, limits, taken, setError],
  );

  const remove = useCallback(
    (name: string) => {
      setDocuments((current) => current.filter((file) => file.name !== name));
      setReads((current) => {
        const next = { ...current };
        delete next[name];
        return next;
      });
      setError(null);
    },
    [setError],
  );

  const keepUnread = useCallback(
    (name: string) => {
      setReads((current) => ({ ...current, [name]: { status: "kept" } }));
      setError(null);
    },
    [setError],
  );

  const reset = useCallback(() => {
    generation.current += 1;
    setDocuments([]);
    setReads({});
  }, []);

  const restore = useCallback(
    (files: readonly AdmittedFile[], sent: readonly InterviewDocument[]) => {
      generation.current += 1;
      const texts = new Map(sent.map((document) => [document.name, document]));
      const waiting = files.filter((file) => texts.has(file.name));
      setDocuments(waiting);
      setReads(
        Object.fromEntries(
          waiting.map((file): [string, DocumentRead] => {
            const text = texts.get(file.name)?.text;
            if (text != null) return [file.name, { status: "read", text }];
            const readable = limits?.extraction_extensions?.includes(
              fileExtension(file.name),
            );
            return [file.name, { status: readable ? "kept" : "not_read" }];
          }),
        ),
      );
    },
    [limits],
  );

  return { documents, reads, add, remove, keepUnread, reset, restore };
}
