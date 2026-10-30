// The house style, in as few primitives as the three panes need. Every rule the style
// checklist enforces lives here once — near-black primary (never teal), borders not shadows,
// the two radius tiers from the token file — `rounded-md` for small controls, `rounded-lg` for
// surfaces — sentence case left to the package's own strings.

import { ChevronRight, Pencil, Plus, Trash2 } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { createPortal } from "react-dom";

export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

export function formatTrials(count: number): string {
  return `${count} ${count === 1 ? "trial" : "trials"}`;
}

export function countTrials(personaCount: number, trials: number): number {
  return personaCount * trials;
}

type Variant = "primary" | "secondary" | "ghost";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  active?: boolean; // a toggled chip — the one place the accent fills anything
}

// The accent earns its scarcity here: it is a 1px ring and a tint on a *selected* chip, and
// it is nowhere else. A primary button is near-black.
//
// Every variant answers a press as well as a hover. Without the pressed state a click produced no
// acknowledgement at all — the button looked identical the whole way down, and whatever the click
// started took long enough that the only feedback was the result arriving. Hover and press are two
// steps of the same neutral ramp: the fill goes to `muted` under the pointer and on to `border`,
// one step darker again, while held. The solid variant shifts opacity instead, having no fill to
// deepen.
//
// It is a colour shift and nothing else. No scale, no spring: a button that shrinks under the
// cursor is the decorative kind of motion this product does without, and the press only has to
// report that the click landed.
const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-primary text-primary-foreground border border-primary hover:opacity-90 active:opacity-80",
  secondary:
    "bg-secondary text-secondary-foreground border border-border hover:bg-muted active:bg-border",
  ghost:
    "bg-transparent text-foreground border border-border hover:bg-muted active:bg-border",
};

export function Button({
  variant = "secondary",
  active = false,
  className,
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-md px-3 py-1.5",
        "text-sm font-medium transition-colors duration-150",
        "disabled:cursor-not-allowed disabled:opacity-45",
        active
          ? "border border-accent bg-accent/12 text-foreground"
          : VARIANTS[variant],
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}

// A small tooltip that works for both ordinary controls and disabled controls. Native disabled
// elements cannot receive focus, so callers can make this wrapper focusable and still expose the
// reason for the disabled state to keyboard users. Tooltips sit below their trigger so they do not
// cover the control being inspected.
export function Tooltip({
  label,
  children,
  className,
  focusable = false,
  ariaLabel,
  hoverOnly = false,
}: {
  label: string;
  children: ReactNode;
  className?: string;
  focusable?: boolean;
  ariaLabel?: string;
  hoverOnly?: boolean;
}) {
  const id = useId();
  const triggerRef = useRef<HTMLDivElement | null>(null);
  const [visible, setVisible] = useState(false);
  const [position, setPosition] = useState({ left: 0, top: 0 });

  const showBelowTrigger = () => {
    const bounds = triggerRef.current?.getBoundingClientRect();
    if (!bounds) return;
    setPosition({
      left: bounds.left + bounds.width / 2,
      top: bounds.bottom + 14,
    });
    setVisible(true);
  };

  return (
    <div
      ref={triggerRef}
      className={cn("group relative", className)}
      tabIndex={focusable ? 0 : undefined}
      aria-label={focusable ? ariaLabel : undefined}
      aria-describedby={focusable ? id : undefined}
      onPointerEnter={showBelowTrigger}
      onPointerLeave={() => setVisible(false)}
      onFocusCapture={hoverOnly ? undefined : showBelowTrigger}
      onBlurCapture={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
          setVisible(false);
        }
      }}
    >
      {children}
      {visible &&
        typeof document !== "undefined" &&
        createPortal(
          <div
            id={id}
            role="tooltip"
            style={{ left: position.left, top: position.top }}
            className={cn(
              "pointer-events-none fixed z-[100] w-max max-w-72 -translate-x-1/2",
              "rounded-[8px] border border-border bg-foreground px-3 py-2",
              "text-sm leading-5 text-background shadow-lg",
            )}
          >
            <span
              aria-hidden
              className="absolute left-1/2 -top-1.5 h-3 w-3 -translate-x-1/2 rotate-45 border-l border-t border-border bg-foreground"
            />
            <span className="relative">{label}</span>
          </div>,
          document.body,
        )}
    </div>
  );
}

// A bordered surface. Static cards get no shadow, ever — depth is a 1px line.
export function Panel({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      className={cn(
        "rounded-lg border border-border bg-card text-card-foreground",
        className,
      )}
    >
      {children}
    </div>
  );
}

// A chevron that points in one of the four directions. Used by the document pane's disclosures
// (the collapse affordances use lucide's panel icons instead). A thin wrapper over lucide's
// `ChevronRight`, rotated to face the asked-for direction, so every caller keeps the same `dir`
// API. Drawn in `currentColor` (lucide's default `stroke`), so it inherits its host text colour
// and never introduces the accent on its own.
export function Chevron({
  dir = "right",
  className,
}: {
  dir?: "up" | "down" | "left" | "right";
  className?: string;
}) {
  const rotation = {
    right: "",
    down: "rotate-90",
    left: "rotate-180",
    up: "-rotate-90",
  }[dir];
  return (
    <ChevronRight
      size={14}
      strokeWidth={1.75}
      aria-hidden
      className={cn("shrink-0", rotation, className)}
    />
  );
}

// A bordered monospace token: an id being referenced, a filename, a count.
//
// Neutral is the default and covers almost every chip, because most of them mark *what a thing
// refers to* — a behaviour, a persona, a file — and a reference is not a state. The accent tone is
// for the few that report one: a count that has become non-zero, something live. It is drawn as
// teal text and a teal edge rather than a teal fill, so a row of chips still reads as one family
// and the coloured one stands out by tone instead of by mass.
//
// This does not wrap `Mono`. Both would set a text colour, and two competing `text-*` utilities
// resolve by stylesheet order rather than by which was passed last, so the tone could silently
// lose. Setting the type here keeps the outcome deterministic.
export function Chip({
  tone = "neutral",
  className,
  children,
}: {
  tone?: "neutral" | "accent";
  className?: string;
  children: ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-block rounded-md border px-1.5 py-0.5",
        "font-mono text-xs tracking-tight tabular-nums",
        tone === "accent"
          ? "border-accent/40 text-accent"
          : "border-border text-muted-foreground",
        className,
      )}
    >
      {children}
    </span>
  );
}

// A small monospace token — an id, metric metadata, or a filename. JetBrains Mono is reserved for
// machine-facing data, so it reads as implementation detail rather than ordinary prose.
// `tone` picks the ink, because `cn` is a plain join rather than tailwind-merge: a `text-*` passed
// through `className` does not override the base colour, it just sits beside it and loses on source
// order. So the one colour a caller legitimately varies — muted by default, accent when the id
// marks a live/selected state — is a prop the component resolves itself, leaving `className` for
// everything that does not conflict.
export function Mono({
  className,
  children,
  tone = "muted",
}: {
  className?: string;
  children: ReactNode;
  tone?: "muted" | "accent";
}) {
  return (
    <span
      className={cn(
        "font-mono text-xs tracking-tight",
        tone === "accent" ? "text-accent" : "text-muted-foreground",
        className,
      )}
    >
      {children}
    </span>
  );
}

// ── shared CRUD controls ─────────────────────────────────────────────────────

export type IconName = "pencil" | "plus" | "trash";

const ICONS = { pencil: Pencil, plus: Plus, trash: Trash2 } as const;

// A square ghost button that holds one lucide icon. The label is the accessible name and the
// tooltip, so the same words reach a pointer user and a screen reader.
export function IconAction({
  icon,
  label,
  disabled = false,
  onClick,
}: {
  icon: IconName;
  label: string;
  disabled?: boolean;
  onClick: () => void;
}) {
  const Icon = ICONS[icon];
  return (
    <Tooltip label={label} hoverOnly className="inline-flex shrink-0">
      <button
        type="button"
        aria-label={label}
        disabled={disabled}
        onClick={onClick}
        className={cn(
          "inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors duration-150",
          "hover:bg-muted hover:text-foreground active:bg-border",
          "disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:bg-transparent",
        )}
      >
        <Icon size={15} strokeWidth={1.75} aria-hidden />
      </button>
    </Tooltip>
  );
}

// An interactive checkbox. There is no read-only variant: a box the user cannot change is not
// drawn at all, so every box on screen accepts a click.
export function SelectBox({
  id,
  label,
  checked,
  disabled = false,
  onChange,
}: {
  id?: string;
  label: string;
  checked: boolean;
  disabled?: boolean;
  onChange: () => void;
}) {
  return (
    <input
      id={id}
      type="checkbox"
      aria-label={label}
      checked={checked}
      disabled={disabled}
      onChange={onChange}
      className="h-4 w-4 shrink-0 accent-[hsl(var(--accent))] disabled:cursor-not-allowed"
    />
  );
}

// Every expandable in the client: a 14px chevron and a summary that toggle the content below.
// The content stays mounted and is only hidden, so a closed group keeps its field values.
//
// `summary` is the clickable text; `label` replaces it as the accessible name when given. When the
// caller must put a control in the summary's place, it passes `summaryControl` and a `label`: the
// button then holds the chevron only, and the control sits beside it. `trailing` is drawn at the right end of
// the header, outside the toggle. `tone="muted"` draws a quiet secondary block in small grey text.
export function Disclosure({
  summary,
  summaryControl,
  label,
  trailing,
  children,
  open: controlled,
  defaultOpen = false,
  onOpenChange,
  tone = "default",
  indent = true,
  className,
  headerClassName,
  contentClassName,
}: {
  summary?: ReactNode;
  summaryControl?: ReactNode;
  label?: string;
  trailing?: ReactNode;
  children: ReactNode;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  tone?: "default" | "muted";
  // Indent the content to the summary text, past the chevron.
  indent?: boolean;
  className?: string;
  headerClassName?: string;
  contentClassName?: string;
}) {
  const [uncontrolled, setUncontrolled] = useState(defaultOpen);
  const open = controlled ?? uncontrolled;
  const contentId = useId();
  const toggle = () => {
    setUncontrolled(!open);
    onOpenChange?.(!open);
  };
  const muted = tone === "muted";
  return (
    <div className={cn("flex min-w-0 flex-col", className)}>
      <div className={cn("flex min-w-0 items-start gap-2", headerClassName)}>
        <DisclosureButton
          open={open}
          controls={contentId}
          label={label}
          tone={tone}
          grow={!summaryControl}
          onClick={toggle}
        >
          {!summaryControl && summary}
        </DisclosureButton>
        {summaryControl && (
          <div className="min-w-0 flex-1">{summaryControl}</div>
        )}
        {trailing}
      </div>
      <div
        id={contentId}
        hidden={!open}
        className={cn(
          indent && "pl-5",
          muted && "text-xs text-muted-foreground",
          contentClassName,
        )}
      >
        {children}
      </div>
    </div>
  );
}

// The toggle of a Disclosure on its own, for a layout where the header and the content are not
// next to each other, such as a table row and the detail row below it.
export function DisclosureButton({
  open,
  controls,
  label,
  tone = "default",
  grow = false,
  onClick,
  children,
}: {
  open: boolean;
  controls?: string;
  label?: string;
  tone?: "default" | "muted";
  grow?: boolean;
  onClick: () => void;
  children?: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-expanded={open}
      aria-controls={controls}
      aria-label={label}
      onClick={onClick}
      className={cn(
        "flex min-h-7 min-w-0 items-center gap-1.5 rounded-md text-left transition-colors duration-150",
        tone === "muted"
          ? "text-xs text-muted-foreground hover:text-foreground"
          : "text-foreground hover:text-accent",
        grow && "flex-1",
      )}
    >
      <Chevron
        dir={open ? "down" : "right"}
        className="text-muted-foreground"
      />
      {children != null && children !== false && (
        <span className="min-w-0 flex-1">{children}</span>
      )}
    </button>
  );
}

// A modal question before a destructive action. The text is the package's own, and it names
// what else the action removes. Cancel has the focus at first, so Enter alone does not delete.
// The page behind is inert while it is open, Tab stays inside it, Escape closes it from anywhere,
// and the focus goes back to the control that opened it.
export function ConfirmDialog({
  text,
  confirmLabel,
  onConfirm,
  onCancel,
}: {
  text: string;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const id = useId();
  const dialog = useRef<HTMLDivElement | null>(null);
  const cancel = useRef(onCancel);
  cancel.current = onCancel;
  // Read during the first render, before Cancel takes the focus.
  const [trigger] = useState(() =>
    typeof document === "undefined"
      ? null
      : (document.activeElement as HTMLElement | null),
  );
  useEffect(() => {
    const host = dialog.current?.parentElement;
    const others = [...document.body.children].filter(
      (element): element is HTMLElement =>
        element instanceof HTMLElement && element !== host && !element.inert,
    );
    others.forEach((element) => (element.inert = true));
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      cancel.current();
    };
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("keydown", escape);
      others.forEach((element) => (element.inert = false));
      // The trigger can focus only once its tree is no longer inert.
      requestAnimationFrame(() => trigger?.focus?.({ preventScroll: true }));
    };
  }, [trigger]);
  if (typeof document === "undefined") return null;
  return createPortal(
    <div
      className="fixed inset-0 z-[90] flex items-center justify-center bg-foreground/20 p-4"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onCancel();
      }}
    >
      <div
        ref={dialog}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={`${id}-title`}
        aria-describedby={id}
        onKeyDown={(event) => {
          if (event.key !== "Tab") return;
          const buttons = [
            ...(dialog.current?.querySelectorAll("button") ?? []),
          ] as HTMLElement[];
          const first = buttons[0];
          const last = buttons.at(-1);
          if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last?.focus();
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first?.focus();
          }
        }}
        className="flex w-full max-w-sm flex-col gap-4 rounded-lg border border-border bg-card p-5 text-card-foreground shadow-lg"
      >
        <h2 id={`${id}-title`} className="sr-only">
          {confirmLabel}
        </h2>
        <p id={id} className="text-sm">
          {text}
        </p>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" autoFocus onClick={onCancel}>
            Cancel
          </Button>
          <Button type="button" variant="primary" onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
