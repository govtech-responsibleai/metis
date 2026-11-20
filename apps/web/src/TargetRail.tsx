// The left rail: "New target", the list of Targets, and at its foot the colour theme. With
// login on, the foot has the account menu of the current user, and the colour theme is in that
// menu. The selected row follows the URL.

import {
  Check,
  ChevronsUpDown,
  CirclePlus,
  Copy,
  FolderClosed,
  LogOut,
  Monitor,
  Moon,
  PanelLeft,
  SquareTerminal,
  Sun,
  SunMoon,
  Trash2,
  UsersRound,
} from "lucide-react";
import {
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { Link } from "wouter";
import { useLoginSession, type LoginSession } from "./LoginGate";
import type { TargetSummary } from "./targets";
import { useThemeChoice, type ThemeChoice } from "./theme";
import type { StorageProblem } from "./storage/repository";
import type { WorkshopVariable } from "./transport/api";
import { relativeTime } from "./relative-time";
import { paths } from "./routes";
import { Avatar, Button, buttonClass, cn, Modal } from "./ui";

export function TargetRail({
  targets,
  problems,
  selectedId,
  activeIds,
  onNew,
  onDelete,
  onCollapse,
}: {
  targets: TargetSummary[];
  problems: readonly StorageProblem[];
  // The Target of the URL, which is the selected row.
  selectedId: string | null;
  activeIds: ReadonlySet<string>;
  onNew: () => void;
  onDelete: (id: string) => void;
  onCollapse?: () => void;
}) {
  const session = useLoginSession();
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
          const active = selectedId === target.id;
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
      <div className="flex flex-col gap-2 border-t border-border p-3">
        {session ? <AccountMenu /> : <ThemeSwitch />}
      </div>
    </nav>
  );
}

// The rail when the user hides it: a strip that shows the rail again, and the account menu at
// its foot, so the user can still log out.
export function CollapsedRail({ onExpand }: { onExpand: () => void }) {
  return (
    <div className="flex h-full w-8 shrink-0 flex-col border-r border-border bg-muted/30">
      <button
        type="button"
        aria-label="Show targets"
        title="Show targets"
        onClick={onExpand}
        className="flex flex-1 items-start justify-center pt-4 text-muted-foreground hover:bg-muted hover:text-foreground"
      >
        <PanelLeft size={16} strokeWidth={1.75} aria-hidden />
      </button>
      <AccountMenu compact />
    </div>
  );
}

// The user account of the login session, as a button that opens a menu above it. With login
// off, the app has no user account and this shows nothing. `compact` shows only the avatar, for
// the strip of a hidden rail.
function AccountMenu({ compact = false }: { compact?: boolean }) {
  const session = useLoginSession();
  // The menu holds the theme choice while it is closed, so a System choice keeps following the
  // operating system setting.
  const [theme, setTheme] = useThemeChoice();
  const [open, setOpen] = useState(false);
  const [envOpen, setEnvOpen] = useState(false);
  const host = useRef<HTMLDivElement | null>(null);
  const trigger = useRef<HTMLButtonElement | null>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    const outside = (event: MouseEvent) => {
      if (host.current?.contains(event.target as Node)) return;
      setOpen(false);
      trigger.current?.focus();
    };
    document.addEventListener("mousedown", outside);
    return () => document.removeEventListener("mousedown", outside);
  }, [open]);

  if (!session) return null;
  const close = () => {
    setOpen(false);
    trigger.current?.focus();
  };
  const { username } = session.user;
  return (
    <div
      ref={host}
      className={cn("relative", compact && "flex justify-center pb-3")}
    >
      <button
        ref={trigger}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        aria-label={compact ? `Account menu of ${username}` : undefined}
        title={username}
        onClick={() => setOpen(!open)}
        onKeyDown={(event) => {
          if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
          event.preventDefault();
          setOpen(true);
        }}
        className={cn(
          "flex items-center rounded-md text-foreground transition-colors duration-150 hover:bg-background",
          open && "bg-background",
          compact ? "p-0.5" : "w-full gap-2 px-2 py-1.5",
        )}
      >
        {compact ? (
          <Avatar username={username} size="sm" />
        ) : (
          <>
            <Avatar username={username} size="sm" />
            <span className="min-w-0 flex-1 truncate text-left text-sm font-medium">
              {username}
            </span>
            <ChevronsUpDown
              size={14}
              strokeWidth={1.75}
              aria-hidden
              className="shrink-0 text-muted-foreground"
            />
          </>
        )}
      </button>
      {open && (
        <AccountMenuList
          id={menuId}
          session={session}
          theme={theme}
          onTheme={setTheme}
          className={cn(
            "absolute bottom-full mb-1",
            compact ? "left-1 w-56" : "inset-x-0",
          )}
          onClose={close}
          onCliSettings={() => {
            close();
            setEnvOpen(true);
          }}
        />
      )}
      {envOpen && session.workshopEnv && (
        <CliSettingsDialog
          variables={session.workshopEnv}
          onClose={() => setEnvOpen(false)}
        />
      )}
    </div>
  );
}

// The text that the Copy button puts on the clipboard: one `NAME=value` line for each variable.
export function envText(variables: WorkshopVariable[]): string {
  return variables.map(({ name, value }) => `${name}=${value}\n`).join("");
}

export function CliSettingsDialog({
  variables,
  onClose,
}: {
  variables: WorkshopVariable[];
  onClose: () => void;
}) {
  const titleId = useId();
  const [copied, setCopied] = useState(false);
  const text = envText(variables);
  const copy = () => {
    void navigator.clipboard?.writeText(text);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };
  return (
    <Modal
      labelledBy={titleId}
      onCancel={onClose}
      className="max-w-lg gap-4 p-5"
    >
      <div className="flex flex-col gap-1">
        <h2 id={titleId} className="text-base font-semibold">
          CLI settings
        </h2>
        <p className="text-sm text-muted-foreground">
          Paste these lines into <code className="font-mono">.env</code> to use
          the METIS CLI.
        </p>
      </div>
      <pre className="overflow-x-auto rounded-md border border-border bg-muted px-3 py-2 font-mono text-sm">
        {text}
      </pre>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" autoFocus onClick={copy}>
          {copied ? (
            <Check size={14} strokeWidth={1.75} aria-hidden />
          ) : (
            <Copy size={14} strokeWidth={1.75} aria-hidden />
          )}
          {copied ? "Copied" : "Copy"}
        </Button>
        <Button type="button" variant="primary" onClick={onClose}>
          Done
        </Button>
      </div>
    </Modal>
  );
}

// The username, then the items of the account menu. Arrow Up and Arrow Down move between the
// rows, and Home and End go to the first and the last. On the Appearance row, Arrow Left and Arrow
// Right move between the three themes, and a theme applies at once with the menu still open.
// Escape and Tab close the menu.
export function AccountMenuList({
  id,
  session,
  theme,
  onTheme,
  className,
  onClose,
  onCliSettings,
}: {
  id?: string;
  session: LoginSession;
  theme: ThemeChoice;
  onTheme: (choice: ThemeChoice) => void;
  className?: string;
  onClose: () => void;
  onCliSettings: () => void;
}) {
  const menu = useRef<HTMLDivElement | null>(null);
  const rows = () => [
    ...(menu.current?.querySelectorAll<HTMLElement>(
      '[role="menuitem"], [role="group"]',
    ) ?? []),
  ];
  useEffect(() => {
    focusRow(rows()[0]);
  }, []);

  const move = (event: KeyboardEvent<HTMLDivElement>) => {
    const all = rows();
    const at = all.findIndex((row) => row.contains(document.activeElement));
    const next = {
      ArrowDown: (at + 1) % all.length,
      ArrowUp: (at - 1 + all.length) % all.length,
      Home: 0,
      End: all.length - 1,
    }[event.key];
    const side = { ArrowRight: 1, ArrowLeft: -1 }[event.key];
    const row = all[at];
    if (next !== undefined) {
      event.preventDefault();
      focusRow(all[next]);
    } else if (side !== undefined && row?.getAttribute("role") === "group") {
      event.preventDefault();
      const options = [
        ...row.querySelectorAll<HTMLElement>('[role="menuitemradio"]'),
      ];
      const from = options.indexOf(document.activeElement as HTMLElement);
      options[(from + side + options.length) % options.length]?.focus();
    } else if (event.key === "Escape") {
      event.preventDefault();
      onClose();
    } else if (event.key === "Tab") {
      onClose();
    } else if (
      event.key === " " &&
      document.activeElement instanceof HTMLAnchorElement
    ) {
      event.preventDefault();
      document.activeElement.click();
    }
  };

  return (
    <div
      className={cn(
        "animate-arrive z-50 flex flex-col rounded-lg border border-border bg-card p-1 text-card-foreground shadow-lg",
        className,
      )}
    >
      <p className="flex items-center gap-2 px-2 py-1.5 text-sm font-medium">
        <Avatar username={session.user.username} size="sm" />
        <span className="min-w-0 truncate">{session.user.username}</span>
      </p>
      <div
        ref={menu}
        id={id}
        role="menu"
        aria-label="Account"
        onKeyDown={move}
        className="flex flex-col"
      >
        {session.user.admin && (
          <Link
            href={paths.admin()}
            role="menuitem"
            tabIndex={-1}
            onClick={onClose}
            className={MENU_ITEM}
          >
            <MenuIcon>
              <UsersRound size={15} strokeWidth={1.75} aria-hidden />
            </MenuIcon>
            Manage accounts
          </Link>
        )}
        {session.workshopEnv && session.workshopEnv.length > 0 && (
          <button
            type="button"
            role="menuitem"
            tabIndex={-1}
            onClick={onCliSettings}
            className={MENU_ITEM}
          >
            <MenuIcon>
              <SquareTerminal size={15} strokeWidth={1.75} aria-hidden />
            </MenuIcon>
            CLI settings
          </button>
        )}
        <AppearanceRow choice={theme} onChoose={onTheme} />
        <div role="separator" className="-mx-1 my-1 h-px bg-border" />
        <button
          type="button"
          role="menuitem"
          tabIndex={-1}
          onClick={session.logout}
          className={MENU_ITEM}
        >
          <MenuIcon>
            <LogOut size={15} strokeWidth={1.75} aria-hidden />
          </MenuIcon>
          Log out
        </button>
      </div>
    </div>
  );
}

// A group row of the menu takes the focus on its chosen theme.
function focusRow(row: HTMLElement | undefined) {
  if (row?.getAttribute("role") === "group") {
    row.querySelector<HTMLElement>('[aria-checked="true"]')?.focus();
  } else {
    row?.focus();
  }
}

// The colour theme as one row of the account menu.
export function AppearanceRow({
  choice,
  onChoose,
}: {
  choice: ThemeChoice;
  onChoose: (choice: ThemeChoice) => void;
}) {
  return (
    <div
      role="group"
      aria-label="Appearance"
      className="flex items-center gap-2 px-2 py-1 text-sm text-foreground"
    >
      <MenuIcon>
        <SunMoon size={15} strokeWidth={1.75} aria-hidden />
      </MenuIcon>
      <span aria-hidden className="flex-1">
        Appearance
      </span>
      <ThemeOptions choice={choice} onChoose={onChoose} role="menuitemradio" />
    </div>
  );
}

const MENU_ITEM =
  "flex items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm text-foreground outline-none transition-colors duration-150 hover:bg-muted focus:bg-muted";

function MenuIcon({ children }: { children: ReactNode }) {
  return <span className="shrink-0 text-muted-foreground">{children}</span>;
}

const THEMES: Array<{ id: ThemeChoice; label: string; Icon: typeof Sun }> = [
  { id: "system", label: "System", Icon: Monitor },
  { id: "light", label: "Light", Icon: Sun },
  { id: "dark", label: "Dark", Icon: Moon },
];

// The colour theme at the foot of the rail, when login is off and the rail has no account menu.
function ThemeSwitch() {
  const [choice, setChoice] = useThemeChoice();
  return (
    <div role="radiogroup" aria-label="Colour theme">
      <ThemeOptions choice={choice} onChoose={setChoice} role="radio" />
    </div>
  );
}

// The three themes as icon buttons. The chosen one takes the muted fill, and the others stay
// muted text.
function ThemeOptions({
  choice,
  onChoose,
  role,
}: {
  choice: ThemeChoice;
  onChoose: (choice: ThemeChoice) => void;
  role: "radio" | "menuitemradio";
}) {
  return (
    <div className="flex w-fit items-center gap-0.5 rounded-md border border-border bg-background p-0.5">
      {THEMES.map(({ id, label, Icon }) => (
        <button
          key={id}
          type="button"
          role={role}
          aria-checked={choice === id}
          aria-label={label}
          title={label}
          tabIndex={role === "menuitemradio" ? -1 : undefined}
          onClick={() => onChoose(id)}
          className={cn(
            "rounded p-1 transition-colors",
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
