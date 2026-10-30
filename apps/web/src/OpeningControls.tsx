import type { KeyboardEvent, ReactNode } from "react";
import {
  Check,
  ChevronDown,
  ClipboardCheck,
  Code2,
  ShieldCheck,
  UserRound,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type {
  CapabilityCategoryDefinition,
  CapabilityConfidence,
  CapabilityId,
  Perspective,
  PerspectiveDefinition,
} from "./transport/api";
import { Tooltip, cn } from "./ui";

export const PERSPECTIVE_ICONS: Record<Perspective, LucideIcon> = {
  end_user: UserRound,
  engineer: Code2,
  compliance: ClipboardCheck,
  security: ShieldCheck,
};

export const DEFAULT_PERSPECTIVE: Perspective = "end_user";

const CONFIDENCE_OPTIONS: Array<{ id: CapabilityConfidence; label: string }> = [
  { id: "low", label: "Low" },
  { id: "medium", label: "Medium" },
  { id: "high", label: "High" },
];

// A radio group moves its selection with the arrow keys, and only the checked radio is in the tab
// order. The buttons are found in DOM order, so the keyboard order is the visual order.
function moveRadio<T>(
  event: KeyboardEvent<HTMLButtonElement>,
  ids: readonly T[],
  current: T | null,
  onSelect: (id: T) => void,
) {
  const step =
    event.key === "ArrowDown" || event.key === "ArrowRight"
      ? 1
      : event.key === "ArrowUp" || event.key === "ArrowLeft"
        ? -1
        : 0;
  if (step === 0) return;
  event.preventDefault();
  const index = current === null ? -1 : ids.indexOf(current);
  // With no selection, the first step selects the first or the last radio.
  const nextIndex =
    index < 0
      ? step > 0
        ? 0
        : ids.length - 1
      : (index + step + ids.length) % ids.length;
  const next = ids[nextIndex];
  if (next === undefined) return;
  onSelect(next);
  const radios =
    event.currentTarget
      .closest('[role="radiogroup"]')
      ?.querySelectorAll<HTMLButtonElement>('[role="radio"]') ?? [];
  radios[nextIndex]?.focus();
}

// The surface that opens under the opening box. It is attached to the box, so it reads as part of
// the same control group. On a small screen, a `sheet` surface becomes a full-width bottom sheet.
export function UnderBoxSurface({
  id,
  label,
  onClose,
  sheet = false,
  children,
}: {
  id: string;
  label: string;
  onClose: () => void;
  sheet?: boolean;
  children: ReactNode;
}) {
  return (
    <>
      {sheet && (
        <button
          type="button"
          tabIndex={-1}
          aria-hidden
          onClick={onClose}
          className="fixed inset-0 z-20 bg-foreground/20 sm:hidden"
        />
      )}
      <section
        id={id}
        aria-label={label}
        className={cn(
          "animate-open-under-box relative flex flex-col gap-3 rounded-2xl border border-border bg-card px-4 py-4",
          sheet &&
            "under-box-sheet max-sm:quiet-scrollbar max-sm:fixed max-sm:inset-x-0 max-sm:bottom-0 max-sm:z-30 max-sm:max-h-[80vh] max-sm:w-full max-sm:overflow-y-auto max-sm:rounded-b-none max-sm:pt-4 max-sm:shadow-[0_-8px_24px_hsl(0_0%_0%/0.08)]",
        )}
      >
        {/* The chip that opens the panel names it, so the panel shows no visible title. The close
            button sits in the corner, so it takes no row and the content stays centred. */}
        <button
          type="button"
          aria-label={`Close ${label.toLowerCase()}`}
          onClick={onClose}
          className={cn(
            "under-box-close absolute right-2.5 top-2.5 rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
          )}
        >
          <X size={16} strokeWidth={1.75} aria-hidden />
        </button>
        {children}
      </section>
    </>
  );
}

// A trigger in the footer of the opening box. It shows its value.
export function FooterChip({
  value,
  expanded,
  onClick,
  controls,
  disabled = false,
  marked = false,
  icon,
  ariaLabel,
}: {
  value: string;
  expanded: boolean;
  onClick: () => void;
  controls: string;
  disabled?: boolean;
  // The still marker that shows a default value. It enters once with a short animation.
  marked?: boolean;
  icon?: ReactNode;
  ariaLabel?: string;
}) {
  return (
    <button
      type="button"
      aria-label={ariaLabel}
      aria-expanded={expanded}
      aria-controls={controls}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "inline-flex h-9 max-w-full shrink-0 items-center gap-1.5 rounded-md border px-2.5 text-sm transition-colors duration-150",
        expanded
          ? "border-accent bg-accent/10 text-foreground"
          : "border-border bg-card text-foreground hover:bg-muted",
        marked && "perspective-default",
        "disabled:cursor-not-allowed disabled:opacity-45",
      )}
    >
      {icon}
      <span className="truncate font-medium">{value}</span>
      <ChevronDown
        size={14}
        strokeWidth={1.75}
        aria-hidden
        className={cn(
          "shrink-0 text-muted-foreground transition-transform duration-150",
          expanded && "rotate-180",
        )}
      />
    </button>
  );
}

export function PerspectivePicker({
  perspectives,
  selected,
  onSelect,
  disabled = false,
}: {
  perspectives: PerspectiveDefinition[];
  selected: Perspective;
  onSelect: (perspective: Perspective) => void;
  disabled?: boolean;
}) {
  const ids = perspectives.map((perspective) => perspective.id);
  return (
    <div
      role="radiogroup"
      aria-label="Perspective"
      className="flex flex-col gap-1"
    >
      {perspectives.map((perspective) => {
        const Icon = PERSPECTIVE_ICONS[perspective.id];
        const active = perspective.id === selected;
        return (
          <button
            key={perspective.id}
            type="button"
            role="radio"
            aria-checked={active}
            tabIndex={active ? 0 : -1}
            disabled={disabled}
            onClick={() => onSelect(perspective.id)}
            onKeyDown={(event) => moveRadio(event, ids, selected, onSelect)}
            className={cn(
              "flex w-full items-start gap-3 rounded-md border px-3 py-2.5 text-left transition-colors duration-150",
              active
                ? "border-accent bg-accent/10"
                : "border-transparent hover:bg-muted",
              "disabled:cursor-not-allowed disabled:opacity-45",
            )}
          >
            <Icon
              size={18}
              strokeWidth={1.75}
              aria-hidden
              className={cn(
                "mt-0.5 shrink-0",
                active ? "text-accent" : "text-muted-foreground",
              )}
            />
            <span className="flex min-w-0 flex-1 flex-col">
              <span className="flex items-center gap-2 text-sm font-medium text-foreground">
                {perspective.label}
                {perspective.id === DEFAULT_PERSPECTIVE && (
                  <span className="text-xs font-normal text-muted-foreground">
                    Default
                  </span>
                )}
              </span>
              <span className="text-sm text-muted-foreground">
                {perspective.question}
              </span>
            </span>
            {active && (
              <Check
                size={16}
                strokeWidth={2}
                aria-hidden
                className="mt-0.5 shrink-0 text-accent"
              />
            )}
          </button>
        );
      })}
    </div>
  );
}

export function CapabilityPicker({
  categories,
  selected,
  onChange,
  disabled = false,
  hideLegend = false,
}: {
  categories: CapabilityCategoryDefinition[];
  selected: CapabilityId[];
  onChange: (capabilities: CapabilityId[]) => void;
  disabled?: boolean;
  hideLegend?: boolean;
}) {
  const toggle = (id: CapabilityId) =>
    onChange(
      selected.includes(id)
        ? selected.filter((value) => value !== id)
        : [...selected, id],
    );

  return (
    <fieldset className="flex flex-col gap-3">
      <legend
        className={cn(
          "text-sm font-medium text-foreground",
          hideLegend && "sr-only",
        )}
      >
        Capabilities
      </legend>
      {/* Three open columns. The vertical lines between them meet the line above Confidence. */}
      <div className="grid gap-5 border-b border-border pb-4 sm:grid-cols-3 sm:gap-0 sm:divide-x sm:divide-border sm:pb-0">
        {categories.map((category) => (
          <div
            key={category.id}
            role="group"
            aria-label={category.name}
            className="flex flex-col gap-1 sm:px-5 sm:pb-5 sm:first:pl-0 sm:last:pr-0"
          >
            <h2 className="pb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {category.name}
            </h2>
            {category.capabilities.map((capability) => {
              const active = selected.includes(capability.id);
              return (
                <Tooltip
                  key={capability.id}
                  label={capability.description}
                  className="w-full"
                >
                  <button
                    type="button"
                    role="checkbox"
                    aria-checked={active}
                    aria-label={`${capability.name}: ${capability.description}`}
                    disabled={disabled}
                    onClick={() => toggle(capability.id)}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left text-sm transition-colors duration-150 -mx-1.5",
                      active
                        ? "font-medium text-foreground"
                        : "text-card-foreground hover:bg-muted",
                      "disabled:cursor-not-allowed disabled:opacity-45",
                    )}
                  >
                    <span
                      aria-hidden
                      className={cn(
                        // A square box, so a checkbox does not look like a Confidence radio.
                        "flex h-4 w-4 shrink-0 items-center justify-center rounded-[3px] border",
                        active
                          ? "border-accent bg-accent text-accent-foreground"
                          : "border-input bg-background",
                      )}
                    >
                      {active && <Check size={12} strokeWidth={2.5} />}
                    </span>
                    {capability.name}
                  </button>
                </Tooltip>
              );
            })}
          </div>
        ))}
      </div>
    </fieldset>
  );
}

export function CapabilityConfidencePicker({
  selected,
  onSelect,
  disabled = false,
}: {
  selected: CapabilityConfidence | null;
  onSelect: (confidence: CapabilityConfidence) => void;
  disabled?: boolean;
}) {
  const ids = CONFIDENCE_OPTIONS.map((option) => option.id);
  const radios = (
    <div
      role="radiogroup"
      aria-label="Confidence"
      className="flex flex-wrap gap-1.5"
    >
      {CONFIDENCE_OPTIONS.map((option, index) => {
        const active = selected === option.id;
        return (
          <button
            key={option.id}
            type="button"
            role="radio"
            aria-checked={active}
            tabIndex={active || (selected === null && index === 0) ? 0 : -1}
            disabled={disabled}
            onClick={() => onSelect(option.id)}
            onKeyDown={(event) => moveRadio(event, ids, selected, onSelect)}
            className={cn(
              "flex h-8 items-center gap-2 rounded-md border px-2.5 text-sm font-medium transition-colors duration-150",
              active
                ? "border-accent bg-accent/10 text-foreground"
                : "border-border bg-card text-card-foreground hover:border-accent/40 hover:bg-muted",
              "disabled:cursor-not-allowed disabled:opacity-45",
            )}
          >
            <span
              aria-hidden
              className={cn(
                "flex h-4 w-4 items-center justify-center rounded-full border",
                active ? "border-accent" : "border-muted-foreground/60",
              )}
            >
              {active && <span className="h-2 w-2 rounded-full bg-accent" />}
            </span>
            {option.label}
          </button>
        );
      })}
    </div>
  );
  return (
    <fieldset className="pt-2">
      <legend className="sr-only">Confidence (optional)</legend>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <span aria-hidden className="text-sm text-foreground">
          Confidence <span className="text-muted-foreground">(optional)</span>
        </span>
        {radios}
      </div>
    </fieldset>
  );
}
