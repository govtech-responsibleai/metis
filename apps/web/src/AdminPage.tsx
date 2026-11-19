// The admin page: the user accounts of the server, and dialogs that create a user account, reset
// a password, and delete a user account. The API decides who is an admin. The page uses the
// login session, never a token.

import { Check, Copy, LoaderCircle, Plus } from "lucide-react";
import { useEffect, useId, useReducer, useState, type ReactNode } from "react";
import { useLoginSession } from "./LoginGate";
import { relativeTime } from "./relative-time";
import { SettleText } from "./RevealText";
import { users, type NewUserAccount, type UserAccount } from "./transport/api";
import { Avatar, Button, Chip, cn, IconAction, Modal, Panel } from "./ui";

export type AdminLoad =
  | { status: "loading" }
  | { status: "failed"; message: string }
  | { status: "ready"; accounts: UserAccount[] };

// The one dialog of the page at a time. A password is only in a result step, so it goes when the
// admin closes the dialog or leaves the page. While a request runs, the dialog stays open, so each
// result has a dialog to show it. An error of the API takes the dialog back to the step that sent
// the request.
export type AdminTask =
  | { kind: "idle" }
  | { kind: "create-form"; admin: boolean; error?: string }
  | { kind: "creating"; admin: boolean }
  | { kind: "create-result"; account: NewUserAccount }
  | { kind: "confirm-reset"; username: string; error?: string }
  | { kind: "resetting"; username: string }
  | { kind: "reset-result"; account: NewUserAccount }
  | { kind: "confirm-delete"; username: string; error?: string }
  | { kind: "deleting"; username: string };

export interface AdminState {
  load: AdminLoad;
  task: AdminTask;
}

export type AdminEvent =
  | { type: "loaded"; accounts: UserAccount[] }
  | { type: "load-failed"; message: string }
  | { type: "open-create" }
  | { type: "choose"; admin: boolean }
  | { type: "create" }
  | { type: "created"; account: NewUserAccount }
  | { type: "ask-reset"; username: string }
  | { type: "reset" }
  | { type: "reset-done"; account: NewUserAccount }
  | { type: "ask-delete"; username: string }
  | { type: "delete" }
  | { type: "deleted"; username: string }
  | { type: "failed"; message: string }
  | { type: "close" };

export const initialAdminState: AdminState = {
  load: { status: "loading" },
  task: { kind: "idle" },
};

const IDLE: AdminTask = { kind: "idle" };

function listed({
  id,
  username,
  created_at,
  admin,
}: NewUserAccount): UserAccount {
  return { id, username, created_at, admin };
}

function withAccounts(
  load: AdminLoad,
  change: (accounts: UserAccount[]) => UserAccount[],
): AdminLoad {
  return load.status === "ready"
    ? { status: "ready", accounts: change(load.accounts) }
    : load;
}

function sending(task: AdminTask): boolean {
  return (
    task.kind === "creating" ||
    task.kind === "resetting" ||
    task.kind === "deleting"
  );
}

function nextTask(task: AdminTask, event: AdminEvent): AdminTask {
  switch (event.type) {
    case "open-create":
      return task.kind === "idle"
        ? { kind: "create-form", admin: false }
        : task;
    case "choose":
      return task.kind === "create-form"
        ? { kind: "create-form", admin: event.admin }
        : task;
    case "create":
      return task.kind === "create-form"
        ? { kind: "creating", admin: task.admin }
        : task;
    case "created":
      return { kind: "create-result", account: event.account };
    case "ask-reset":
      return task.kind === "idle"
        ? { kind: "confirm-reset", username: event.username }
        : task;
    case "reset":
      return task.kind === "confirm-reset"
        ? { kind: "resetting", username: task.username }
        : task;
    case "reset-done":
      return { kind: "reset-result", account: event.account };
    case "ask-delete":
      return task.kind === "idle"
        ? { kind: "confirm-delete", username: event.username }
        : task;
    case "delete":
      return task.kind === "confirm-delete"
        ? { kind: "deleting", username: task.username }
        : task;
    case "deleted":
      return IDLE;
    case "failed":
      switch (task.kind) {
        case "creating":
          return {
            kind: "create-form",
            admin: task.admin,
            error: event.message,
          };
        case "resetting":
          return {
            kind: "confirm-reset",
            username: task.username,
            error: event.message,
          };
        case "deleting":
          return {
            kind: "confirm-delete",
            username: task.username,
            error: event.message,
          };
        default:
          return task;
      }
    case "close":
      return sending(task) ? task : IDLE;
    case "loaded":
    case "load-failed":
      return task;
  }
}

export function adminReducer(state: AdminState, event: AdminEvent): AdminState {
  const task = nextTask(state.task, event);
  switch (event.type) {
    case "loaded":
      return { load: { status: "ready", accounts: event.accounts }, task };
    case "load-failed":
      return { load: { status: "failed", message: event.message }, task };
    case "created":
      return {
        load: withAccounts(state.load, (accounts) => [
          ...accounts,
          listed(event.account),
        ]),
        task,
      };
    case "deleted":
      return {
        load: withAccounts(state.load, (accounts) =>
          accounts.filter((account) => account.username !== event.username),
        ),
        task,
      };
    default:
      return task === state.task ? state : { ...state, task };
  }
}

// The text that the Copy button puts on the clipboard: one block that the admin sends as it is.
export function credentialsText({
  username,
  password,
}: NewUserAccount): string {
  return `Username: ${username}\nPassword: ${password}`;
}

export function accountCount(count: number): string {
  return `${count} ${count === 1 ? "user account" : "user accounts"}`;
}

function errorText(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}

// Only an admin sees the page. Each other person gets `fallback`, as for a page that does not
// exist.
export function AdminRoute({ fallback }: { fallback: ReactNode }) {
  const session = useLoginSession();
  return session?.user.admin ? <AdminPage /> : <>{fallback}</>;
}

function AdminPage() {
  const session = useLoginSession();
  const [state, dispatch] = useReducer(adminReducer, initialAdminState);
  useEffect(() => {
    let current = true;
    users.list().then(
      (list) => {
        if (current) dispatch({ type: "loaded", accounts: list.users });
      },
      (cause: unknown) => {
        if (current)
          dispatch({ type: "load-failed", message: errorText(cause) });
      },
    );
    return () => {
      current = false;
    };
  }, []);

  const failed = (cause: unknown) =>
    dispatch({ type: "failed", message: errorText(cause) });
  const { task } = state;

  return (
    <AdminView
      state={state}
      currentUserId={session?.user.id ?? null}
      dispatch={dispatch}
      onCreate={() => {
        if (task.kind !== "create-form") return;
        dispatch({ type: "create" });
        users
          .create(task.admin)
          .then((account) => dispatch({ type: "created", account }), failed);
      }}
      onReset={() => {
        if (task.kind !== "confirm-reset") return;
        dispatch({ type: "reset" });
        users
          .resetPassword(task.username)
          .then((account) => dispatch({ type: "reset-done", account }), failed);
      }}
      onDelete={() => {
        if (task.kind !== "confirm-delete") return;
        const { username } = task;
        dispatch({ type: "delete" });
        users
          .delete(username)
          .then(() => dispatch({ type: "deleted", username }), failed);
      }}
    />
  );
}

interface TaskActions {
  dispatch: (event: AdminEvent) => void;
  // Each sends the request of the open dialog.
  onCreate: () => void;
  onReset: () => void;
  onDelete: () => void;
}

export function AdminView({
  state,
  currentUserId,
  ...actions
}: TaskActions & {
  state: AdminState;
  // The page shows no Delete for this user account, because the API refuses it.
  currentUserId: string | null;
}) {
  const { load, task } = state;
  const { dispatch } = actions;
  const titleId = useId();
  return (
    <div className="quiet-scrollbar min-h-0 flex-1 overflow-y-auto px-6 py-6">
      <div className="mx-auto flex w-full flex-col gap-6 lg:max-w-[max(60%,36rem)]">
        <header className="flex items-center justify-between gap-4">
          <div className="flex min-w-0 flex-col gap-1">
            <h1 className="text-xl font-semibold">User accounts</h1>
            {load.status === "ready" && (
              <p className="text-sm text-muted-foreground">
                {accountCount(load.accounts.length)}
              </p>
            )}
          </div>
          <Button
            type="button"
            variant="primary"
            onClick={() => dispatch({ type: "open-create" })}
          >
            <Plus size={14} strokeWidth={1.75} aria-hidden />
            Add new user
          </Button>
        </header>
        <AccountTable
          load={load}
          currentUserId={currentUserId}
          dispatch={dispatch}
        />
      </div>
      {task.kind !== "idle" && (
        <Modal
          role={
            task.kind === "confirm-delete" || task.kind === "deleting"
              ? "alertdialog"
              : "dialog"
          }
          labelledBy={titleId}
          className="max-w-sm gap-4 p-5"
          onCancel={() => dispatch({ type: "close" })}
        >
          <AdminTaskBody task={task} titleId={titleId} {...actions} />
        </Modal>
      )}
    </div>
  );
}

// The content of the open dialog. A flow changes its step inside the same dialog, so the dialog
// does not close and open again between the question and the result.
export function AdminTaskBody({
  task,
  titleId,
  dispatch,
  onCreate,
  onReset,
  onDelete,
}: TaskActions & {
  task: Exclude<AdminTask, { kind: "idle" }>;
  titleId: string;
}) {
  const close = () => dispatch({ type: "close" });
  switch (task.kind) {
    case "create-form":
    case "creating":
      return (
        <CreateForm
          task={task}
          titleId={titleId}
          dispatch={dispatch}
          onCreate={onCreate}
        />
      );
    case "create-result":
      return (
        <ResultStep
          title="User account created"
          titleId={titleId}
          account={task.account}
          onDone={close}
        />
      );
    case "confirm-reset":
    case "resetting":
      return (
        <ConfirmStep
          titleId={titleId}
          text={`Reset the password of ${task.username}? ${task.username} is logged out, and the old password stops working.`}
          confirmLabel="Reset password"
          sending={task.kind === "resetting"}
          error={task.kind === "confirm-reset" ? task.error : undefined}
          onConfirm={onReset}
          onCancel={close}
        />
      );
    case "reset-result":
      return (
        <ResultStep
          title={`New password for ${task.account.username}`}
          titleId={titleId}
          account={task.account}
          reveal
          onDone={close}
        />
      );
    case "confirm-delete":
    case "deleting":
      return (
        <ConfirmStep
          titleId={titleId}
          text={`Delete the user account ${task.username}? This deletes the user account and all its Targets and Experiments. You cannot undo this.`}
          confirmLabel="Delete user account"
          sending={task.kind === "deleting"}
          error={task.kind === "confirm-delete" ? task.error : undefined}
          onConfirm={onDelete}
          onCancel={close}
        />
      );
  }
}

const ACCOUNT_TYPES = [
  {
    admin: false,
    label: "Participant",
    can: "Can make Targets and run Experiments.",
  },
  { admin: true, label: "Admin", can: "Can also manage all user accounts." },
] as const;

function CreateForm({
  task,
  titleId,
  dispatch,
  onCreate,
}: {
  task: Extract<AdminTask, { kind: "create-form" | "creating" }>;
  titleId: string;
  dispatch: (event: AdminEvent) => void;
  onCreate: () => void;
}) {
  const busy = task.kind === "creating";
  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        onCreate();
      }}
    >
      <div className="flex flex-col gap-1">
        <h2 id={titleId} className="text-base font-semibold">
          Add new user
        </h2>
        <p className="text-sm text-muted-foreground">
          METIS makes the username and the password.
        </p>
      </div>
      <fieldset className="flex flex-col gap-2" disabled={busy}>
        <legend className="sr-only">Account type</legend>
        {ACCOUNT_TYPES.map((type) => {
          const chosen = task.admin === type.admin;
          return (
            <label
              key={type.label}
              className={cn(
                "flex cursor-pointer items-start gap-3 rounded-md border px-3 py-2 transition-colors duration-150",
                chosen
                  ? "border-accent bg-accent/12"
                  : "border-border hover:bg-muted",
              )}
            >
              <input
                type="radio"
                name="account-type"
                value={type.label}
                checked={chosen}
                autoFocus={chosen}
                onChange={() => dispatch({ type: "choose", admin: type.admin })}
                className="mt-0.5 h-4 w-4 shrink-0 accent-[hsl(var(--accent))]"
              />
              <span className="flex flex-col">
                <span className="text-sm font-medium">{type.label}</span>
                <span className="text-sm text-muted-foreground">
                  {type.can}
                </span>
              </span>
            </label>
          );
        })}
      </fieldset>
      {task.kind === "create-form" && task.error && (
        <ErrorLine message={task.error} />
      )}
      <div className="flex justify-end gap-2">
        <Button
          type="button"
          variant="ghost"
          disabled={busy}
          onClick={() => dispatch({ type: "close" })}
        >
          Cancel
        </Button>
        <Button type="submit" variant="primary" disabled={busy}>
          {busy && <Progress />}
          Create
        </Button>
      </div>
    </form>
  );
}

function ConfirmStep({
  titleId,
  text,
  confirmLabel,
  sending,
  error,
  onConfirm,
  onCancel,
}: {
  titleId: string;
  text: string;
  confirmLabel: string;
  sending: boolean;
  error?: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <>
      <h2 id={titleId} className="sr-only">
        {confirmLabel}
      </h2>
      <p className="text-sm">{text}</p>
      {error && <ErrorLine message={error} />}
      <div className="flex justify-end gap-2">
        <Button
          type="button"
          variant="ghost"
          autoFocus
          disabled={sending}
          onClick={onCancel}
        >
          Cancel
        </Button>
        <Button
          type="button"
          variant="primary"
          disabled={sending}
          onClick={onConfirm}
        >
          {sending && <Progress />}
          {confirmLabel}
        </Button>
      </div>
    </>
  );
}

function ResultStep({
  title,
  titleId,
  account,
  reveal = false,
  onDone,
}: {
  title: string;
  titleId: string;
  account: NewUserAccount;
  // The characters of the password settle into place, because a reset changes only the password.
  reveal?: boolean;
  onDone: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    void navigator.clipboard?.writeText(credentialsText(account));
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };
  return (
    <>
      <div className="flex flex-col gap-1">
        <h2 id={titleId} className="text-base font-semibold">
          {title}
        </h2>
        <p className="text-sm text-muted-foreground">
          Copy these details and send them to the person as they are. You will
          not see the password again.
        </p>
      </div>
      <dl className="flex flex-col gap-1 rounded-md border border-border bg-muted px-3 py-2 font-mono text-sm">
        <div className="flex gap-3">
          <dt className="w-20 shrink-0 text-muted-foreground">Username</dt>
          <dd className="min-w-0 break-all">{account.username}</dd>
        </div>
        <div className="flex gap-3">
          <dt className="w-20 shrink-0 text-muted-foreground">Password</dt>
          <dd className="min-w-0 break-all">
            {reveal ? (
              <SettleText value={account.password} />
            ) : (
              account.password
            )}
          </dd>
        </div>
      </dl>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" autoFocus onClick={copy}>
          {copied ? (
            <Check size={14} strokeWidth={1.75} aria-hidden />
          ) : (
            <Copy size={14} strokeWidth={1.75} aria-hidden />
          )}
          {copied ? "Copied" : "Copy"}
        </Button>
        <Button type="button" variant="primary" onClick={onDone}>
          Done
        </Button>
      </div>
    </>
  );
}

function ErrorLine({ message }: { message: string }) {
  return (
    <p role="alert" className="text-sm text-destructive">
      {message}
    </p>
  );
}

function Progress() {
  return (
    <LoaderCircle
      size={14}
      strokeWidth={1.75}
      aria-hidden
      className="animate-spin"
    />
  );
}

function AccountTable({
  load,
  currentUserId,
  dispatch,
}: {
  load: AdminLoad;
  currentUserId: string | null;
  dispatch: (event: AdminEvent) => void;
}) {
  if (load.status === "loading")
    return (
      <p role="status" className="text-sm text-muted-foreground">
        Loading the user accounts
      </p>
    );
  if (load.status === "failed")
    return (
      <p role="alert" className="text-sm text-destructive">
        {load.message}
      </p>
    );
  if (load.accounts.length === 0)
    return (
      <p className="text-sm text-muted-foreground">No user accounts yet.</p>
    );
  return (
    <Panel className="overflow-hidden">
      <table className="w-full table-fixed text-left text-sm">
        <colgroup>
          <col />
          <col className="w-40" />
          <col className="w-48" />
        </colgroup>
        <thead>
          <tr className="border-b border-border bg-muted/60 text-muted-foreground">
            <th scope="col" className="px-4 py-2.5 font-medium">
              Username
            </th>
            <th scope="col" className="px-4 py-2.5 font-medium">
              Created
            </th>
            <th scope="col" className="px-4 py-2.5">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {load.accounts.map((account) => {
            const own = account.id === currentUserId;
            return (
              <tr
                key={account.id}
                className="border-b border-border transition-colors duration-150 last:border-b-0 hover:bg-muted"
              >
                <td className="px-4 py-2">
                  <span className="flex min-w-0 items-center gap-2">
                    <Avatar username={account.username} />
                    <span className="truncate font-mono font-medium">
                      {account.username}
                    </span>
                    {account.admin && <Chip>Admin</Chip>}
                  </span>
                </td>
                <td className="px-4 py-2.5 text-muted-foreground">
                  <time
                    dateTime={account.created_at}
                    title={new Date(account.created_at).toLocaleString()}
                  >
                    {relativeTime(Date.parse(account.created_at))}
                  </time>
                </td>
                <td className="px-4 py-1.5">
                  <span className="flex items-center justify-end gap-1">
                    <Button
                      type="button"
                      variant="ghost"
                      aria-label={`Reset password of ${account.username}`}
                      className="h-7 px-2.5 py-0 text-xs"
                      onClick={() =>
                        dispatch({
                          type: "ask-reset",
                          username: account.username,
                        })
                      }
                    >
                      Reset password
                    </Button>
                    {own ? (
                      <span aria-hidden className="h-7 w-7 shrink-0" />
                    ) : (
                      <IconAction
                        icon="trash"
                        label={`Delete ${account.username}`}
                        onClick={() =>
                          dispatch({
                            type: "ask-delete",
                            username: account.username,
                          })
                        }
                      />
                    )}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </Panel>
  );
}
