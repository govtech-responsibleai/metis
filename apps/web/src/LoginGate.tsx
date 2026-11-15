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
import { navigate } from "wouter/use-browser-location";
import { Field, TextInput } from "./fields";
import {
  auth,
  onLoginRequired,
  TransportError,
  type UserAccount,
} from "./transport/api";
import { Button } from "./ui";

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

function Screen({ children }: { children: ReactNode }) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-background p-6">
      <div className="flex w-full max-w-sm flex-col gap-6 rounded-lg border border-border bg-card p-6">
        {/* The same mark and wordmark as the rail. */}
        <span className="flex items-center gap-1.5">
          <img src="/metis-mark.png" alt="" className="h-7 w-7" />
          <span className="text-base font-black tracking-[0.14em] text-foreground">
            METIS
          </span>
        </span>
        {children}
      </div>
    </main>
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
        <h1 className="text-lg font-semibold text-foreground">Log in</h1>
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
          <TextInput
            name="password"
            type="password"
            autoComplete="current-password"
            value={password}
            invalid={error !== null}
            required
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
    </Screen>
  );
}
