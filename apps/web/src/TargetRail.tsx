// The left rail: "New target", the list of Targets, and at its foot "All experiments" and the
// colour theme. The selected row follows the URL.

import {
  CirclePlus,
  FolderClosed,
  ListChecks,
  Monitor,
  Moon,
  PanelLeft,
  Sun,
  Trash2,
} from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "wouter";
import type { TargetSummary } from "./targets";
import { useThemeChoice, type ThemeChoice } from "./theme";
import type { StorageProblem } from "./storage/repository";
import { relativeTime } from "./relative-time";
import { paths } from "./routes";
import { buttonClass, cn } from "./ui";

// The selected row of the rail.
export type RailSelection =
  { kind: "target"; id: string } | { kind: "experiments" } | null;

export function TargetRail({
  targets,
  problems,
  selected,
  activeIds,
  onNew,
  onDelete,
  onCollapse,
}: {
  targets: TargetSummary[];
  problems: readonly StorageProblem[];
  selected: RailSelection;
  activeIds: ReadonlySet<string>;
  onNew: () => void;
  onDelete: (id: string) => void;
  onCollapse?: () => void;
}) {
  return (
    <nav className="flex h-full w-[15%] min-w-[14rem] flex-col border-r border-border bg-muted">
      <div className="flex items-center justify-between gap-2 px-3 pt-3">
        {/* The same mark and wordmark as the docs site's navbar. */}
        <span className="flex items-center gap-1.5">
          <img src="/metis-mark.png" alt="" className="h-7 w-7" />
          <span className="text-base font-black tracking-[0.14em] text-foreground">
            METIS
          </span>
        </span>
        {onCollapse && (
          <button
            type="button"
            aria-label="Hide targets"
            title="Hide targets"
            onClick={onCollapse}
            className="rounded p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <PanelLeft size={16} strokeWidth={1.75} aria-hidden />
          </button>
        )}
      </div>
      <div className="border-b border-border p-3">
        <Link
          href={paths.newTarget()}
          onClick={onNew}
          className={cn(
            buttonClass("ghost"),
            "w-full justify-start bg-background",
          )}
        >
          <CirclePlus size={15} strokeWidth={1.75} aria-hidden />
          New target
        </Link>
      </div>
      <ul className="quiet-scrollbar flex-1 overflow-y-auto p-3">
        {targets.map((target) => {
          const active =
            selected?.kind === "target" && selected.id === target.id;
          return (
            <li key={target.id}>
              {/* Inside the selected row, the icon and the time take the fill's foreground,
                  because muted text on the accent fill cannot be read. */}
              <div
                className={cn(
                  "group flex w-full items-center rounded-md transition-colors duration-150",
                  active
                    ? "bg-accent text-accent-foreground"
                    : "hover:bg-background",
                )}
              >
                <Link
                  href={paths.target(target.id)}
                  aria-current={active ? "page" : undefined}
                  className="flex min-w-0 flex-1 items-center gap-2 px-3 py-1.5 text-left"
                >
                  <FolderClosed
                    size={15}
                    strokeWidth={1.3}
                    aria-hidden
                    className={cn(
                      "shrink-0",
                      active
                        ? "text-accent-foreground"
                        : "text-muted-foreground",
                    )}
                  />
                  <span
                    className={cn(
                      "min-w-0 flex-1 truncate text-sm",
                      active ? "font-semibold" : "font-medium text-foreground",
                    )}
                  >
                    {target.title}
                  </span>
                  <span
                    className={cn(
                      "shrink-0 text-xs",
                      active
                        ? "text-accent-foreground/75"
                        : "text-muted-foreground",
                    )}
                  >
                    {relativeTime(target.updated)}
                  </span>
                </Link>
                <button
                  type="button"
                  aria-label={`Delete ${target.title}`}
                  title={
                    activeIds.has(target.id)
                      ? "Wait for this Interview to finish sending."
                      : "Delete target"
                  }
                  disabled={activeIds.has(target.id)}
                  className={cn(
                    "mr-2 shrink-0 rounded p-1 opacity-0 transition-opacity group-hover:opacity-100",
                    active
                      ? "text-accent-foreground/80 hover:text-accent-foreground"
                      : "text-muted-foreground hover:text-destructive",
                  )}
                  onClick={() => onDelete(target.id)}
                >
                  <Trash2 size={13} strokeWidth={1.75} aria-hidden />
                </button>
              </div>
            </li>
          );
        })}
        {problems.map((problem) => (
          <li key={`problem-${problem.id}`}>
            <div className="group flex items-center gap-2 rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm">
              <span className="min-w-0 flex-1 text-destructive">
                {problem.message}
              </span>
              <button
                type="button"
                aria-label={`Remove unreadable Interview ${problem.id}`}
                title="Remove saved record"
                className="shrink-0 rounded p-1 text-destructive hover:bg-destructive/10"
                onClick={() => onDelete(problem.id)}
              >
                <Trash2 size={13} strokeWidth={1.75} aria-hidden />
              </button>
            </div>
          </li>
        ))}
      </ul>
      <div className="flex flex-col gap-3 border-t border-border p-3">
        <RailLink
          href={paths.experiments()}
          active={selected?.kind === "experiments"}
        >
          <ListChecks
            size={15}
            strokeWidth={1.3}
            aria-hidden
            className="shrink-0"
          />
          <span className="flex-1 truncate">All experiments</span>
        </RailLink>
        <ThemeSwitch />
      </div>
    </nav>
  );
}

function RailLink({
  href,
  active,
  children,
}: {
  href: string;
  active: boolean;
  children: ReactNode;
}) {
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-left text-sm font-medium transition-colors duration-150",
        active ? "bg-accent text-accent-foreground" : "hover:bg-background",
      )}
    >
      {children}
    </Link>
  );
}

const THEMES: Array<{ id: ThemeChoice; label: string; Icon: typeof Sun }> = [
  { id: "system", label: "System theme", Icon: Monitor },
  { id: "light", label: "Light theme", Icon: Sun },
  { id: "dark", label: "Dark theme", Icon: Moon },
];

// The chosen option takes the background fill, and the others stay muted.
function ThemeSwitch() {
  const [choice, setChoice] = useThemeChoice();
  return (
    <div
      role="radiogroup"
      aria-label="Colour theme"
      className="flex w-fit items-center gap-0.5 rounded-md border border-border bg-background p-0.5"
    >
      {THEMES.map(({ id, label, Icon }) => (
        <button
          key={id}
          type="button"
          role="radio"
          aria-checked={choice === id}
          aria-label={label}
          title={label}
          onClick={() => setChoice(id)}
          className={cn(
            "rounded p-1.5 transition-colors",
            choice === id
              ? "bg-muted text-foreground"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          <Icon size={14} strokeWidth={1.75} aria-hidden />
        </button>
      ))}
    </div>
  );
}
