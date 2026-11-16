import {
  File as FileIcon,
  FileCode,
  FileImage,
  FileSpreadsheet,
  FileText,
  Paperclip,
  Plus,
  Presentation,
  X,
  type LucideIcon,
} from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "./ui";
import {
  unicodeLength,
  type DocumentLimits,
  type DocumentReads,
} from "./document-intake";

// The plus button of a message box. It opens the panel of the things that the user can add to
// the message.
export function AddButton({
  expanded,
  controls,
  disabled,
  onClick,
}: {
  expanded: boolean;
  controls: string;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-label="Add"
      aria-expanded={expanded}
      aria-controls={controls}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "-ml-2 mr-1.5 inline-flex size-9 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-45",
        expanded && "bg-muted text-foreground",
      )}
    >
      <Plus size={16} strokeWidth={1.75} aria-hidden />
    </button>
  );
}

// The rows of the Add panel. There is one row now: the file dialog of the browser. `onDone`
// closes the panel after the user chooses files.
export function AddOptions({
  limits,
  disabled,
  onAdd,
  onDone,
}: {
  limits: DocumentLimits | undefined;
  disabled: boolean;
  onAdd: (files: readonly File[]) => void;
  onDone: () => void;
}) {
  const extensions = limits?.fixture_extensions;
  const canUpload = limits !== undefined && extensions !== undefined;
  const off = disabled || !canUpload;
  return (
    <div className="flex flex-col gap-1 pr-9">
      <label
        title={
          canUpload
            ? `File types: ${extensions.join(", ")}. File size: ${limits.max_initial_bytes / 1_000_000} MB total.`
            : "Document limits are not available."
        }
        className={cn(
          "flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm font-medium text-foreground transition-colors duration-150 focus-within:bg-muted",
          off
            ? "cursor-not-allowed opacity-45"
            : "cursor-pointer hover:bg-muted",
        )}
      >
        <Paperclip
          size={16}
          strokeWidth={1.75}
          aria-hidden
          className="shrink-0 text-muted-foreground"
        />
        Upload files
        <input
          type="file"
          multiple
          disabled={off}
          accept={(extensions ?? [])
            .map((extension) => `.${extension}`)
            .join(",")}
          onChange={(event) => {
            onAdd([...(event.currentTarget.files ?? [])]);
            event.currentTarget.value = "";
            onDone();
          }}
          className="sr-only"
        />
      </label>
    </div>
  );
}

const TYPE_ICONS: Record<string, LucideIcon> = {
  csv: FileSpreadsheet,
  xlsx: FileSpreadsheet,
  pptx: Presentation,
  png: FileImage,
  jpg: FileImage,
  gif: FileImage,
  webp: FileImage,
  json: FileCode,
  yaml: FileCode,
  yml: FileCode,
  html: FileCode,
  pdf: FileText,
  docx: FileText,
  txt: FileText,
  md: FileText,
};

// One document: the icon of its file type, its name, and then `children`.
export function DocumentChip({
  name,
  children,
}: {
  name: string;
  children?: ReactNode;
}) {
  const Icon =
    TYPE_ICONS[name.split(".").at(-1)?.toLowerCase() ?? ""] ?? FileIcon;
  return (
    <li className="flex min-h-7 min-w-0 max-w-full flex-wrap items-center gap-x-2 rounded-md border border-border px-2 text-sm">
      <span className="flex min-w-0 items-center gap-1.5" title={name}>
        <Icon
          size={14}
          strokeWidth={1.75}
          aria-hidden
          className="shrink-0 text-muted-foreground"
        />
        <span className="max-w-56 truncate text-foreground">{name}</span>
      </span>
      {children}
    </li>
  );
}

const NAME_ONLY = "The wizard gets the name of this file, without its text.";

// The documents that wait in a message box. A document that shows no status was read.
// `heldText` is the characters of text that the Interview already has, which count toward the
// same limit.
export function DocumentList({
  documents,
  reads,
  limits,
  heldText = 0,
  disabled,
  onRemove,
  onUseNameOnly,
}: {
  documents: readonly File[];
  reads: DocumentReads;
  limits: DocumentLimits | undefined;
  heldText?: number;
  disabled: boolean;
  onRemove: (name: string) => void;
  onUseNameOnly: (name: string) => void;
}) {
  if (documents.length === 0) return null;
  const totalText = documents.reduce((total, file) => {
    const read = reads[file.name];
    return total + (read?.status === "read" ? unicodeLength(read.text) : 0);
  }, heldText);
  const textLimitExceeded =
    limits !== undefined && totalText > limits.max_text_characters_total;

  return (
    <ul
      aria-label="Documents"
      className="flex w-full flex-wrap gap-1.5 pr-2 pt-1.5"
    >
      {documents.map((file) => {
        const read = reads[file.name] ?? { status: "not_read" };
        const nameOnly = read.status === "not_read" || read.status === "kept";
        return (
          <DocumentChip key={file.name} name={file.name}>
            {read.status === "failed" ? (
              <span className="text-xs text-destructive">
                Could not read: {read.message}
              </span>
            ) : (
              <span
                aria-live="polite"
                title={nameOnly ? NAME_ONLY : undefined}
                className="text-xs text-muted-foreground empty:hidden"
              >
                {read.status === "reading"
                  ? "Reading…"
                  : nameOnly
                    ? "Name only"
                    : null}
              </span>
            )}
            {(read.status === "failed" ||
              (textLimitExceeded && read.status === "read")) && (
              <button
                type="button"
                disabled={disabled}
                title={NAME_ONLY}
                onClick={() => onUseNameOnly(file.name)}
                className="rounded-md px-1 py-0.5 text-xs text-foreground underline decoration-border underline-offset-2 hover:bg-muted disabled:opacity-40"
              >
                Use name only
              </button>
            )}
            <button
              type="button"
              disabled={disabled || read.status === "reading"}
              onClick={() => onRemove(file.name)}
              aria-label={`Remove ${file.name}`}
              title="Remove"
              className="-mr-1 rounded-sm p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-40"
            >
              <X size={14} strokeWidth={1.75} aria-hidden />
            </button>
          </DocumentChip>
        );
      })}
    </ul>
  );
}
