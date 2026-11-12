// An in-memory copy of the store routes behind a stubbed `fetch`, for the browser tests. It
// keeps the record JSON and the file bytes the way the API does, and it records each request.

interface StoredTarget {
  record: Record<string, unknown>;
  files: Map<string, { blob: Blob; type: string }>;
  updated_at: string;
}

export interface StoreRequest {
  method: string;
  path: string;
  files: string[];
}

export interface FakeStore {
  targets: Map<string, StoredTarget>;
  problems: Array<{ id: string; message: string }>;
  requests: StoreRequest[];
  fetch: typeof fetch;
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function failure(status: number, code: string, message: string): Response {
  return json({ type: "failure", code, message, retryable: false }, status);
}

function refs(record: Record<string, unknown>): string[] {
  const names = (record.fixtures as Array<{ name: string }>).map(
    (ref) => ref.name,
  );
  for (const entry of record.transcript as Array<Record<string, unknown>>) {
    const outbound = entry.outbound as
      { files: Array<{ name: string }> } | undefined;
    for (const ref of outbound?.files ?? []) names.push(ref.name);
  }
  return names;
}

export function fakeStore(
  fallback?: (path: string, init?: RequestInit) => Promise<Response>,
): FakeStore {
  const targets = new Map<string, StoredTarget>();
  const problems: Array<{ id: string; message: string }> = [];
  const requests: StoreRequest[] = [];
  const handle = async (
    input: RequestInfo | URL,
    init?: RequestInit,
  ): Promise<Response> => {
    const path = String(input);
    const method = init?.method ?? "GET";
    if (!path.startsWith("/api/v1/targets")) {
      if (fallback) return fallback(path, init);
      throw new Error(`Unexpected API path: ${path}`);
    }
    const parts = path.split("/").slice(4).map(decodeURIComponent);
    const id = parts[0];
    const form = init?.body instanceof FormData ? init.body : undefined;
    requests.push({
      method,
      path,
      files: (form?.getAll("files") ?? []).map(
        (value) => `files/${(value as File).name}`,
      ),
    });
    if (id === undefined)
      return json({
        targets: [...targets.entries()]
          .sort(([, a], [, b]) => b.updated_at.localeCompare(a.updated_at))
          .map(([key, target]) => ({
            id: key,
            title: target.record.title,
            updated_at: target.updated_at,
          })),
        problems,
      });
    const target = targets.get(id);
    if (parts.length === 1 && method === "DELETE") {
      targets.delete(id);
      return new Response(null, { status: 204 });
    }
    if (parts[1] === "interview" && parts.length === 2 && method === "PUT") {
      const record = JSON.parse(
        await (form?.get("record") as Blob).text(),
      ) as Record<string, unknown>;
      if (target && target.record.created_at !== record.created_at)
        return failure(409, "target_exists", `Another Interview uses ${id}.`);
      const files = new Map(target?.files ?? []);
      for (const value of (form?.getAll("files") ?? []) as File[])
        files.set(value.name, { blob: value, type: value.type });
      const referenced = refs(record);
      const missing = referenced.find((name) => !files.has(name));
      if (missing)
        return failure(400, "validation_error", `${missing} was not uploaded.`);
      for (const name of [...files.keys()])
        if (!referenced.includes(name)) files.delete(name);
      targets.set(id, {
        record,
        files,
        updated_at: new Date(Number(record.updated_at)).toISOString(),
      });
      return new Response(null, { status: 204 });
    }
    if (!target) return failure(404, "not_found", `No Target ${id}.`);
    if (parts[1] === "interview" && parts.length === 2)
      return json(target.record);
    if (parts[1] === "interview" && parts[2] === "files") {
      const file = target.files.get(parts[3] ?? "");
      if (!file) return failure(404, "not_found", "No such file.");
      return new Response(file.blob, {
        status: 200,
        headers: { "content-type": file.type || "application/octet-stream" },
      });
    }
    throw new Error(`Unexpected store request: ${method} ${path}`);
  };
  return { targets, problems, requests, fetch: handle as typeof fetch };
}
