// The field primitives every form in the client draws with: the manual form, the review's typed
// forms, and the inline edit that takes a card's place in the Profile. One set of controls, so a
// Name field looks and behaves the same wherever the user meets it.
//
// `density` picks the size. "form" is the manual form and the forms in the conversation: a label
// above a full-height control. "inline" is an edit inside a Profile row: a shorter control at the
// row's own text size, so the field sits where the text it replaces sat.

import { ChevronDown, Minus, Plus } from "lucide-react";
import type { KeyboardEvent, ReactNode, Ref } from "react";
import { cn } from "./ui";

export type FieldDensity = "form" | "inline";

const CONTROL =
  "rounded-md border border-input bg-background text-foreground placeholder:text-muted-foreground transition-colors focus:border-accent focus:outline-none disabled:cursor-not-allowed disabled:opacity-45 aria-[invalid=true]:border-destructive";

const SIZE: Record<FieldDensity, string> = {
  form: "h-10 px-3 text-sm",
  inline: "h-8 px-2 text-sm",
};

export function Field({
  label,
  error,
  help,
  density = "form",
  hideLabel = false,
  title,
  group = false,
  fill = false,
  children,
}: {
  // A field with several controls (a details list) is a group, not one labelled control, so
  // a click on the label does not move to its first box.
  group?: boolean;
  // The field takes the full height of its grid row, so a fill text area can grow into it.
  fill?: boolean;
  // Hover text for the whole field.
  title?: string;
  label: string;
  error?: string;
  help?: string;
  density?: FieldDensity;
  // An inline field that takes a title's place carries its label for screen readers only.
  hideLabel?: boolean;
  children: ReactNode;
}) {
  const Wrapper = group ? "div" : "label";
  return (
    <Wrapper
      title={title}
      className={cn(
        "flex min-w-0 flex-col",
        density === "form" ? "gap-1.5" : "gap-1",
        fill && "h-full",
      )}
    >
      <span
        className={cn(
          "text-xs font-medium text-muted-foreground",
          hideLabel && "sr-only",
        )}
      >
        {label}
      </span>
      {children}
      {help && <span className="text-xs text-muted-foreground">{help}</span>}
      {error && <span className="text-xs text-destructive">{error}</span>}
    </Wrapper>
  );
}

export function TextInput({
  id,
  inputRef,
  ariaLabel,
  value,
  placeholder,
  spellCheck,
  invalid = false,
  disabled,
  required,
  type = "text",
  step,
  autoFocus,
  density = "form",
  className,
  form,
  onChange,
  onKeyDown,
}: {
  // The id of the form this control belongs to, when the control is outside the form element
  // (a table cell of a row edit).
  form?: string;
  id?: string;
  inputRef?: Ref<HTMLInputElement>;
  ariaLabel?: string;
  value: string;
  placeholder?: string;
  spellCheck?: boolean;
  invalid?: boolean;
  disabled?: boolean;
  required?: boolean;
  type?: "text" | "number";
  step?: number | "any";
  autoFocus?: boolean;
  density?: FieldDensity;
  className?: string;
  onChange: (value: string) => void;
  onKeyDown?: (event: KeyboardEvent<HTMLInputElement>) => void;
}) {
  return (
    <input
      id={id}
      ref={inputRef}
      type={type}
      step={step}
      aria-label={ariaLabel}
      aria-invalid={invalid}
      value={value}
      placeholder={placeholder}
      spellCheck={spellCheck}
      disabled={disabled}
      required={required}
      autoFocus={autoFocus}
      form={form}
      onChange={(event) => onChange(event.target.value)}
      onKeyDown={onKeyDown}
      className={cn(CONTROL, SIZE[density], "min-w-0", className)}
    />
  );
}

export function TextArea({
  id,
  ariaLabel,
  value,
  placeholder,
  invalid = false,
  disabled,
  required,
  density = "form",
  rows,
  fill = false,
  form,
  onChange,
}: {
  id?: string;
  ariaLabel?: string;
  value: string;
  placeholder?: string;
  invalid?: boolean;
  disabled?: boolean;
  required?: boolean;
  density?: FieldDensity;
  /** Sets the height in lines. Without it, the density sets a minimum height. */
  rows?: number;
  /** Grows to the height of a fill Field. `rows` is then the minimum height. */
  fill?: boolean;
  form?: string;
  onChange: (value: string) => void;
}) {
  return (
    <textarea
      rows={rows}
      form={form}
      id={id}
      aria-label={ariaLabel}
      aria-invalid={invalid}
      value={value}
      placeholder={placeholder}
      disabled={disabled}
      required={required}
      onChange={(event) => onChange(event.target.value)}
      className={cn(
        CONTROL,
        "resize-y rounded-lg py-2 text-sm",
        density === "form" ? "px-3" : "px-2",
        rows === undefined && (density === "form" ? "min-h-24" : "min-h-16"),
        fill && "flex-1",
      )}
    />
  );
}

export interface SelectChoice {
  value: string;
  label: string;
  disabled?: boolean;
  // Hover text, such as a description for a short id label.
  hint?: string | null;
}

export function SelectInput({
  id,
  selectRef,
  ariaLabel,
  value,
  choices,
  placeholder,
  invalid = false,
  disabled,
  required,
  density = "form",
  form,
  onChange,
}: {
  form?: string;
  id?: string;
  selectRef?: Ref<HTMLSelectElement>;
  ariaLabel?: string;
  value: string;
  choices: readonly SelectChoice[];
  // The empty first entry. Omit it when the select always holds a value.
  placeholder?: string;
  invalid?: boolean;
  disabled?: boolean;
  required?: boolean;
  density?: FieldDensity;
  onChange: (value: string) => void;
}) {
  // The select draws its own chevron and keeps room for it on the right. The browser's arrow sits
  // over the padding, so in a narrow table cell a long choice ran under it.
  return (
    <span className="relative block min-w-0">
      <select
        form={form}
        id={id}
        ref={selectRef}
        aria-label={ariaLabel}
        aria-invalid={invalid}
        value={value}
        disabled={disabled}
        required={required}
        onChange={(event) => onChange(event.target.value)}
        className={cn(
          CONTROL,
          SIZE[density],
          "w-full appearance-none truncate rounded-lg pr-7",
        )}
      >
        {placeholder != null && <option value="">{placeholder}</option>}
        {choices.map((choice) => (
          <option
            key={choice.value}
            value={choice.value}
            disabled={choice.disabled}
            title={choice.hint ?? undefined}
          >
            {choice.label}
          </option>
        ))}
      </select>
      <ChevronDown
        size={14}
        strokeWidth={1.75}
        aria-hidden
        className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground"
      />
    </span>
  );
}

// A whole-number control. The form density has steppers; the inline density is a plain
// right-aligned box that fits a narrow table column.
export function NumberInput({
  value,
  min = 1,
  max,
  disabled = false,
  ariaLabel,
  density = "form",
  onChange,
  onCommit,
}: {
  value: number;
  min?: number;
  max?: number;
  disabled?: boolean;
  ariaLabel?: string;
  density?: FieldDensity;
  onChange: (value: number) => void;
  onCommit?: (value: number) => void;
}) {
  const clamp = (value: number) =>
    Math.min(max ?? Number.POSITIVE_INFINITY, Math.max(min, value));
  const input = (
    <input
      type="number"
      aria-label={ariaLabel}
      min={min}
      max={max}
      value={value}
      disabled={disabled}
      onChange={(event) =>
        onChange(clamp(Math.round(Number(event.target.value) || min)))
      }
      onBlur={() => onCommit?.(clamp(value))}
      onKeyDown={(event) => {
        if (event.key === "Enter") onCommit?.(clamp(value));
      }}
      className={cn(
        "min-w-0 bg-transparent tabular-nums focus:outline-none",
        "[appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none",
        density === "form"
          ? "flex-1 p-2 text-center text-sm"
          : cn(CONTROL, "h-7 w-full px-1.5 text-right text-sm"),
      )}
    />
  );
  if (density === "inline") return input;

  return (
    <div
      className={cn(
        "flex w-full max-w-48 items-stretch overflow-hidden rounded-md border border-input bg-background",
        "transition-colors focus-within:border-accent",
        disabled && "opacity-45",
      )}
    >
      <Stepper
        label="Decrease"
        disabled={disabled || value <= min}
        onClick={() => {
          const next = clamp(value - 1);
          onChange(next);
          onCommit?.(next);
        }}
      >
        <Minus size={14} strokeWidth={1.75} aria-hidden />
      </Stepper>
      {input}
      <Stepper
        label="Increase"
        disabled={disabled || (max != null && value >= max)}
        onClick={() => {
          const next = clamp(value + 1);
          onChange(next);
          onCommit?.(next);
        }}
      >
        <Plus size={14} strokeWidth={1.75} aria-hidden />
      </Stepper>
    </div>
  );
}

function Stepper({
  label,
  disabled,
  onClick,
  children,
}: {
  label: string;
  disabled?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onMouseDown={(event) => event.preventDefault()}
      onClick={onClick}
      className={cn(
        "flex h-8 w-10 shrink-0 items-center justify-center px-2 text-lg leading-none text-muted-foreground transition-colors",
        "hover:bg-muted hover:text-foreground",
        "disabled:pointer-events-none disabled:opacity-40",
      )}
    >
      {children}
    </button>
  );
}

// A set of toggle chips for a field that holds several values. The value is the chosen values
// joined by commas, in the order of the choices.
export function MultiChoice({
  ariaLabel,
  value,
  choices,
  disabled,
  onChange,
}: {
  ariaLabel?: string;
  value: string;
  choices: readonly SelectChoice[];
  disabled?: boolean;
  onChange: (value: string) => void;
}) {
  const chosen = new Set(
    value
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean),
  );
  if (choices.length === 0)
    return <span className="text-xs text-muted-foreground">None</span>;
  return (
    <div
      role="group"
      aria-label={ariaLabel}
      className="flex min-w-0 flex-wrap items-center gap-1"
    >
      {choices.map((choice) => {
        const on = chosen.has(choice.value);
        return (
          <button
            key={choice.value}
            type="button"
            aria-pressed={on}
            title={choice.hint ?? undefined}
            disabled={disabled || (choice.disabled && !on)}
            onClick={() => {
              const next = new Set(chosen);
              if (on) next.delete(choice.value);
              else next.add(choice.value);
              onChange(
                choices
                  .map((item) => item.value)
                  .filter((item) => next.has(item))
                  .join(","),
              );
            }}
            className={cn(
              "max-w-full truncate rounded-md border px-1.5 py-0.5 font-mono text-xs tracking-tight transition-colors duration-150",
              "disabled:cursor-not-allowed disabled:opacity-45",
              on
                ? "border-accent bg-accent/12 text-foreground"
                : "border-border text-muted-foreground hover:bg-muted",
            )}
          >
            {choice.label}
          </button>
        );
      })}
    </div>
  );
}

// A list of labelled details, such as "Role: Policy analyst". Each detail is one row with a name
// box and a value box, so the user never writes a separator. The value is JSON text: a list of
// [name, value] pairs, which the package reads. The placeholder is "Name|Value" for the two boxes.
export function PairsInput({
  ariaLabel,
  value,
  placeholder = "",
  disabled,
  density = "form",
  onChange,
}: {
  ariaLabel?: string;
  value: string;
  placeholder?: string;
  disabled?: boolean;
  density?: FieldDensity;
  onChange: (value: string) => void;
}) {
  const rows = parsePairs(value);
  const [namePlaceholder = "", valuePlaceholder = ""] = placeholder.split("|");
  const write = (next: [string, string][]) => onChange(JSON.stringify(next));
  const set = (index: number, part: 0 | 1, text: string) =>
    write(
      rows.map((row, i) =>
        i === index ? (part === 0 ? [text, row[1]] : [row[0], text]) : row,
      ),
    );
  return (
    <div role="group" aria-label={ariaLabel} className="flex flex-col gap-2">
      {rows.map((row, index) => (
        <div key={index} className="flex min-w-0 items-center gap-2">
          <TextInput
            ariaLabel={`${ariaLabel ?? "Detail"} ${index + 1} name`}
            value={row[0]}
            placeholder={index === 0 ? namePlaceholder : ""}
            disabled={disabled}
            density={density}
            className="w-2/5 shrink-0"
            onChange={(text) => set(index, 0, text)}
          />
          <TextInput
            ariaLabel={`${ariaLabel ?? "Detail"} ${index + 1} value`}
            value={row[1]}
            placeholder={index === 0 ? valuePlaceholder : ""}
            disabled={disabled}
            density={density}
            className="flex-1"
            onChange={(text) => set(index, 1, text)}
          />
          <button
            type="button"
            aria-label={`Remove detail ${index + 1}`}
            disabled={disabled}
            onClick={() => write(rows.filter((_, i) => i !== index))}
            className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-45"
          >
            <Minus size={14} strokeWidth={1.75} aria-hidden />
          </button>
        </div>
      ))}
      <button
        type="button"
        disabled={disabled}
        onClick={() => write([...rows, ["", ""]])}
        className="flex w-fit items-center gap-1 rounded-md px-1.5 py-1 text-xs font-medium text-accent hover:bg-muted disabled:opacity-45"
      >
        <Plus size={13} strokeWidth={2} aria-hidden />
        Add a detail
      </button>
    </div>
  );
}

// Read the JSON value of a details field. Text that is not a list of pairs reads as no rows.
export function parsePairs(value: string): [string, string][] {
  try {
    const rows: unknown = JSON.parse(value || "[]");
    if (!Array.isArray(rows)) return [];
    return rows
      .filter(
        (row): row is [string, string] =>
          Array.isArray(row) &&
          row.length === 2 &&
          typeof row[0] === "string" &&
          typeof row[1] === "string",
      )
      .map(([name, text]) => [name, text]);
  } catch {
    return [];
  }
}
