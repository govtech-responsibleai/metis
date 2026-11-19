// The login gate of the app. It asks the API if login is on. With login off, it shows the app
// as it is. With login on, it shows the login page until the person has a login session, and
// again when the API says that the login session ended.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import { Check, Copy, Eye, EyeOff } from "lucide-react";
import { navigate } from "wouter/use-browser-location";
import { Field, TextInput } from "./fields";
import { LoginArt } from "./LoginArt";
import {
  auth,
  onLoginRequired,
  TransportError,
  users,
  type NewUserAccount,
  type UserAccount,
} from "./transport/api";
import { Button, cn } from "./ui";

// The user account of the login session and the logout action. It is null when login is off.
export interface LoginSession {
  user: UserAccount;
  logout: () => void;
}

const LoginSessionContext = createContext<LoginSession | null>(null);

export const LoginSessionProvider = LoginSessionContext.Provider;

export function useLoginSession(): LoginSession | null {
  return useContext(LoginSessionContext);
}

type Gate =
  | { kind: "loading" }
  | { kind: "unreachable"; message: string }
  | { kind: "login" }
  | { kind: "open"; user: UserAccount | null };

// The page address can name a Target of the user account that had the last login session. A
// different user account does not have that Target, so its login starts at the first page.
export function startsAtFirstPage(
  lastUserId: string | null,
  userId: string,
): boolean {
  return lastUserId !== null && lastUserId !== userId;
}

const toFirstPage = () => navigate("/", { replace: true });

export function LoginGate({ children }: { children: ReactNode }) {
  const [gate, setGate] = useState<Gate>({ kind: "loading" });
  const lastUserId = useRef<string | null>(null);
  useEffect(() => {
    if (gate.kind === "open" && gate.user) lastUserId.current = gate.user.id;
  }, [gate]);

  const check = useCallback(() => {
    setGate({ kind: "loading" });
    auth.me().then(
      (current) => setGate({ kind: "open", user: current.user ?? null }),
      (error: unknown) => {
        if (error instanceof TransportError && error.status === 401) {
          setGate({ kind: "login" });
          return;
        }
        setGate({
          kind: "unreachable",
          message:
            error instanceof Error
              ? error.message
              : "Couldn't reach the METIS API.",
        });
      },
    );
  }, []);

  useEffect(check, [check]);
  // A request of the app can find that the login session ended. Then the login page comes back.
  useEffect(() => onLoginRequired(() => setGate({ kind: "login" })), []);

  // After a logout, the address does not keep the page of the user account that left.
  const logout = useCallback(() => {
    const leave = () => {
      toFirstPage();
      setGate({ kind: "login" });
    };
    auth.logout().then(leave, leave);
  }, []);

  if (gate.kind === "loading") return null;
  if (gate.kind === "unreachable")
    return <Unreachable message={gate.message} onRetry={check} />;
  if (gate.kind === "login")
    return (
      <LoginPage
        onLogin={(user) => {
          if (startsAtFirstPage(lastUserId.current, user.id)) toFirstPage();
          setGate({ kind: "open", user });
        }}
      />
    );
  return (
    <LoginSessionProvider
      value={gate.user ? { user: gate.user, logout } : null}
    >
      {children}
    </LoginSessionProvider>
  );
}

const NAVY =
  "bg-linear-135 from-brand-navy via-brand-navy-soft via-60% to-brand-navy";

function Brand({ onNavy = false }: { onNavy?: boolean }) {
  return (
    <span className="flex items-center gap-1.5">
      <img src="/metis-mark.png" alt="" className="h-7 w-7" />
      <span
        className={`text-base font-black tracking-[0.14em] ${onNavy ? "text-brand-paper" : "text-foreground"}`}
      >
        METIS
      </span>
    </span>
  );
}

const HEADLINE = (
  <>
    Evaluate your agent against{" "}
    <span className="text-gold">your specifications.</span>
  </>
);
const CAPTION =
  "Define what your agent should do, test the full trajectory, and know exactly what to fix before you ship.";

// On a wide window the form takes one half and the brand panel takes the other half. On a
// phone the brand is a banner at the top, and the form is a sheet that lies over its lower
// edge. The brand surface is navy in both themes.
function Screen({ children }: { children: ReactNode }) {
  return (
    <main className="flex h-full flex-col overflow-y-auto bg-brand-navy md:grid md:grid-cols-2 md:bg-background">
      <BrandBanner />
      <div className="relative -mt-5 flex flex-1 flex-col rounded-t-lg border-t border-border bg-background p-8 md:mt-0 md:min-h-full md:rounded-none md:border-t-0">
        <span className="hidden md:block">
          <Brand />
        </span>
        <div className="flex flex-1 justify-center py-2 md:items-center md:py-10">
          <div className="flex w-full max-w-sm flex-col gap-6">{children}</div>
        </div>
      </div>
      <div className="hidden min-h-0 p-3 md:flex">
        <BrandPanel />
      </div>
    </main>
  );
}

function BrandBanner() {
  return (
    <div
      className={`relative flex min-h-[40%] shrink-0 flex-col justify-between gap-10 overflow-hidden p-8 pb-14 md:hidden ${NAVY}`}
    >
      <LoginArt
        layout="banner"
        className="absolute inset-0 h-full w-full opacity-85"
      />
      <div className="absolute inset-0 bg-linear-to-t from-brand-navy/90 via-brand-navy/40 to-transparent" />
      <span className="relative">
        <Brand onNavy />
      </span>
      <div className="relative flex flex-col gap-3">
        <p className="text-2xl leading-tight font-semibold tracking-tight text-balance text-brand-paper">
          {HEADLINE}
        </p>
        <p className="text-sm text-brand-mist">{CAPTION}</p>
      </div>
    </div>
  );
}

function BrandPanel() {
  return (
    <aside
      className={`relative flex min-h-0 flex-1 flex-col justify-end overflow-hidden rounded-lg border border-white/10 p-8 lg:p-12 ${NAVY}`}
    >
      <LoginArt layout="panel" className="absolute inset-0 h-full w-full" />
      <div className="relative flex max-w-md flex-col gap-4">
        <h2 className="text-3xl leading-tight font-semibold tracking-tight text-balance text-brand-paper lg:text-4xl">
          {HEADLINE}
        </h2>
        <p className="text-brand-mist">{CAPTION}</p>
      </div>
    </aside>
  );
}

function Unreachable({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <Screen>
      <p role="alert" className="text-sm text-foreground">
        {message}
      </p>
      <Button variant="primary" className="self-start" onClick={onRetry}>
        Try again
      </Button>
    </Screen>
  );
}

export function LoginPage({
  onLogin,
  error: initialError = null,
}: {
  onLogin: (user: UserAccount) => void;
  // The message that the page starts with. The page sets it after a login that fails.
  error?: string | null;
}) {
  const [joined, setJoined] = useState<NewUserAccount | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(initialError);
  const [sending, setSending] = useState(false);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setSending(true);
    setError(null);
    auth.login(username, password).then(
      (current) => {
        if (current.user) onLogin(current.user);
      },
      (failure: unknown) => {
        setSending(false);
        setError(
          failure instanceof Error ? failure.message : "The login failed.",
        );
      },
    );
  };

  return (
    <Screen>
      <form className="flex flex-col gap-4" onSubmit={submit}>
        <h1 className="text-2xl font-semibold text-foreground">Log in</h1>
        <Field label="Username">
          <TextInput
            name="username"
            autoComplete="username"
            value={username}
            spellCheck={false}
            invalid={error !== null}
            required
            autoFocus
            onChange={setUsername}
          />
        </Field>
        <Field label="Password">
          <SecretInput
            name="password"
            autoComplete="current-password"
            label="password"
            value={password}
            invalid={error !== null}
            onChange={setPassword}
          />
        </Field>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <Button type="submit" variant="primary" disabled={sending}>
          Log in
        </Button>
      </form>
      <div
        role="separator"
        className={cn(
          "flex items-center text-xs text-muted-foreground before:h-px before:flex-1 before:bg-border after:h-px after:flex-1 after:bg-border",
          !joined && "gap-3",
        )}
      >
        {joined ? null : "or"}
      </div>
      {joined ? (
        <NewAccount account={joined} />
      ) : (
        <JoinWorkshop onJoined={setJoined} />
      )}
    </Screen>
  );
}

// A wrong join token gets 401. A server with no join token gives the same answer.
export function joinFailure(failure: unknown): string {
  if (failure instanceof TransportError && failure.status === 401)
    return "The join token is not correct. Try again.";
  return failure instanceof Error ? failure.message : "The join failed.";
}

function JoinWorkshop({
  onJoined,
}: {
  onJoined: (account: NewUserAccount) => void;
}) {
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setSending(true);
    setError(null);
    users.join(token.trim()).then(onJoined, (failure: unknown) => {
      setSending(false);
      setError(joinFailure(failure));
    });
  };

  return (
    <form
      className="rounded-lg border border-border bg-muted/40 p-4 flex flex-col gap-3"
      onSubmit={submit}
    >
      <div className="flex flex-col gap-1">
        <h2 className="text-sm font-semibold text-foreground">
          Joining a workshop?
        </h2>
        <p className="text-sm text-muted-foreground">
          Enter the join token to create an account.
        </p>
      </div>
      <div className="flex gap-2">
        <SecretInput
          ariaLabel="Workshop token"
          name="workshop-token"
          autoComplete="off"
          label="token"
          value={token}
          invalid={error !== null}
          onChange={setToken}
        />
        <Button
          type="submit"
          disabled={sending}
          className="h-10 bg-background px-4"
        >
          Join
        </Button>
      </div>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </form>
  );
}

// A password box with a button that shows and hides its text.
function SecretInput({
  label,
  ...input
}: {
  label: string;
  name: string;
  autoComplete: string;
  value: string;
  invalid: boolean;
  ariaLabel?: string;
  onChange: (value: string) => void;
}) {
  const [shown, setShown] = useState(false);
  const Icon = shown ? EyeOff : Eye;
  return (
    <div className="relative min-w-0 flex-1">
      <TextInput
        {...input}
        type={shown ? "text" : "password"}
        spellCheck={false}
        required
        className="w-full pr-10"
      />
      <button
        type="button"
        onClick={() => setShown(!shown)}
        aria-label={shown ? `Hide ${label}` : `Show ${label}`}
        aria-pressed={shown}
        className="absolute inset-y-0 right-0 flex w-10 items-center justify-center rounded-md text-muted-foreground transition-colors duration-150 hover:text-foreground"
      >
        <Icon size={16} aria-hidden />
      </button>
    </div>
  );
}

// The details of the new account take the place of the join, under the login form. The
// participant copies each value into its box, so the details are saved before they are needed.
function NewAccount({ account }: { account: NewUserAccount }) {
  return (
    <section
      aria-labelledby="new-account"
      className="animate-arrive rounded-lg border border-border bg-muted/40 p-4 flex flex-col gap-3"
    >
      <div className="flex flex-col gap-1">
        <h2 id="new-account" className="text-sm font-semibold text-foreground">
          Your account is ready
        </h2>
        <p className="text-sm text-muted-foreground">
          Save these details now. You will not see them again.
        </p>
      </div>
      <dl className="flex flex-col gap-1">
        <Credential label="Username" value={account.username} />
        <Credential label="Password" value={account.password} />
      </dl>
    </section>
  );
}

function Credential({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    void navigator.clipboard?.writeText(value);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };
  return (
    <div className="flex items-center gap-3">
      <dt className="w-18 shrink-0 text-sm text-muted-foreground">{label}</dt>
      <dd className="min-w-0 flex-1 truncate font-mono text-sm text-foreground">
        {value}
      </dd>
      <button
        type="button"
        onClick={copy}
        aria-label={
          copied
            ? `Copied the ${label.toLowerCase()}`
            : `Copy the ${label.toLowerCase()}`
        }
        className={cn(
          "flex shrink-0 items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-muted-foreground transition-colors duration-150 hover:bg-background hover:text-foreground",
          copied && "text-foreground",
        )}
      >
        {copied ? (
          <Check size={13} aria-hidden />
        ) : (
          <Copy size={13} aria-hidden />
        )}
        {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}
