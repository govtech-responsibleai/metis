export type Destination = { kind: "new" } | { kind: "interview"; id: string };
export interface TabEntry {
  metis: 1;
  token: string;
  entry: string;
  destination: Destination;
}

export function parseEntry(value: unknown): TabEntry | undefined {
  if (!value || typeof value !== "object") return;
  const candidate = value as Partial<TabEntry>;
  const destination = candidate.destination;
  if (
    candidate.metis !== 1 ||
    typeof candidate.token !== "string" ||
    typeof candidate.entry !== "string" ||
    !destination ||
    !(
      destination.kind === "new" ||
      (destination.kind === "interview" &&
        typeof destination.id === "string" &&
        destination.id.length > 0)
    )
  )
    return;
  return candidate as TabEntry;
}

// Navigation owns selection only. Records and running operations live independently.
export class TabNavigation {
  current: TabEntry;
  private channel?: BroadcastChannel;
  private completed = new Map<string, Destination>();
  private listener: () => void;
  private changed: (entry: TabEntry) => void;
  private browser: Window & typeof globalThis;

  constructor(
    browser: Window & typeof globalThis,
    changed: (entry: TabEntry) => void,
  ) {
    this.browser = browser;
    this.changed = changed;
    const saved = parseEntry(browser.history.state);
    this.current = saved ?? this.entry({ kind: "new" }, crypto.randomUUID());
    browser.history.replaceState(this.current, "");
    this.listener = () => {
      const entry = parseEntry(browser.history.state);
      // Copied older entries must not restore the source tab's Interview.
      this.current =
        entry?.token === this.current.token
          ? entry
          : this.entry({ kind: "new" });
      this.current = {
        ...this.current,
        destination:
          this.completed.get(this.current.entry) ?? this.current.destination,
      };
      browser.history.replaceState(this.current, "");
      changed(this.current);
    };
    browser.addEventListener("popstate", this.listener);
  }

  private entry(
    destination: Destination,
    token = this.current.token,
  ): TabEntry {
    return { metis: 1, token, entry: crypto.randomUUID(), destination };
  }

  async initialize(): Promise<void> {
    if (typeof this.browser.BroadcastChannel === "function") {
      try {
        this.channel = new this.browser.BroadcastChannel("metis-tabs");
        const nonce = crypto.randomUUID();
        let duplicate = false;
        let probing = true;
        this.channel!.onmessage = ({ data }) => {
          if (!data || data.token !== this.current.token) return;
          if (data.type === "probe") {
            // Existing owners win. Simultaneous probes elect one owner deterministically.
            if (!probing || nonce < data.nonce)
              this.channel?.postMessage({
                type: "owner",
                token: this.current.token,
                nonce: data.nonce,
              });
          } else if (data.type === "owner" && data.nonce === nonce)
            duplicate = true;
        };
        this.channel!.postMessage({
          type: "probe",
          token: this.current.token,
          nonce,
        });
        await new Promise((resolve) => setTimeout(resolve, 150));
        probing = false;
        if (duplicate) {
          this.current = this.entry({ kind: "new" }, crypto.randomUUID());
          this.browser.history.replaceState(this.current, "");
        }
      } catch {
        /* Navigation remains usable when channels are blocked. */
      }
    }
    this.changed(this.current);
  }

  go(destination: Destination): void {
    this.current = this.entry(destination);
    this.browser.history.pushState(this.current, "");
    this.changed(this.current);
  }

  started(origin: string, id: string): void {
    const destination: Destination = { kind: "interview", id };
    this.completed.set(origin, destination);
    if (this.current.entry !== origin) return;
    this.current = { ...this.current, destination };
    this.browser.history.replaceState(this.current, "");
    this.changed(this.current);
  }

  dispose(): void {
    this.channel?.close();
    this.browser.removeEventListener("popstate", this.listener);
  }
}
