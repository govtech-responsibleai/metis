export const ACCEPTED_FIXTURE_EXTENSIONS = [
  "csv",
  "yaml",
  "yml",
  "pdf",
  "docx",
  "xlsx",
  "pptx",
  "txt",
  "json",
  "png",
  "jpg",
  "gif",
  "webp",
  "md",
  "html",
] as const;

export const FIXTURE_MAX_FILES = 20;
export const FIXTURE_MAX_BYTES = 100_000_000;

export interface FixtureFileLike {
  name: string;
  size: number;
}

export function normalizeFixtureName(raw: string): string {
  const name = raw.normalize("NFC").trim();
  if (
    !name ||
    name === "." ||
    name === ".." ||
    /[\\/\0\u0000-\u001f\u007f-\u009f<>:"|?*]/u.test(name) ||
    /[. ]$/u.test(name)
  ) {
    throw new Error("File names must be portable names without a path.");
  }
  const stem = name.split(".", 1)[0]?.toUpperCase() ?? "";
  if (/^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$/u.test(stem)) {
    throw new Error("File names cannot use a reserved device name.");
  }
  return name;
}

function extension(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot < 0 ? "" : name.slice(dot + 1).toLowerCase();
}

export function fixtureNameIdentity(name: string): string {
  // Uppercase first to cover Unicode folds such as German sharp s, then lower the result.
  return name.normalize("NFC").toUpperCase().toLowerCase();
}

export interface FixtureLimits {
  max_documents: number;
  max_initial_bytes: number;
  fixture_extensions?: readonly string[];
}

const DEFAULT_LIMITS: FixtureLimits = {
  max_documents: FIXTURE_MAX_FILES,
  max_initial_bytes: FIXTURE_MAX_BYTES,
  fixture_extensions: ACCEPTED_FIXTURE_EXTENSIONS,
};

declare const admitted: unique symbol;

// A File whose name is portable, has an accepted type, and is unique in its Interview or
// library. Only `admitFiles` and `readmitSavedFile` make one, so a file that skips admission
// cannot reach a store.
export type AdmittedFile = File & { readonly [admitted]: true };

function brand(file: File): AdmittedFile {
  return file as AdmittedFile;
}

const NUMBERED = /^(.*) \((\d+)\)$/u;

// The name itself when it is free. Else the stem gets " (n)" before the extension, with the
// first free n. A stem that already ends with " (k)" continues from k + 1.
function freeName(name: string, used: ReadonlySet<string>): string {
  if (!used.has(fixtureNameIdentity(name))) return name;
  const dot = name.lastIndexOf(".");
  const stem = dot < 0 ? name : name.slice(0, dot);
  const suffix = dot < 0 ? "" : name.slice(dot);
  const numbered = NUMBERED.exec(stem);
  const base = numbered ? numbered[1] : stem;
  for (let n = numbered ? Number(numbered[2]) + 1 : 2; ; n++) {
    const candidate = `${base ? `${base} ` : ""}(${n})${suffix}`;
    if (!used.has(fixtureNameIdentity(candidate))) return candidate;
  }
}

// Every file that enters the app comes through here. `taken` is every file that is already in
// the Interview or library, with the files that wait to be sent in the same input. A file is
// never replaced by name: a new file with a name that is taken gets the next free name.
export function admitFiles(
  incoming: readonly File[],
  taken: readonly FixtureFileLike[],
  limits: FixtureLimits = DEFAULT_LIMITS,
): AdmittedFile[] {
  const used = new Set(taken.map((item) => fixtureNameIdentity(item.name)));
  const files: AdmittedFile[] = [];
  let total = taken.reduce((sum, item) => sum + item.size, 0);
  for (const file of incoming) {
    const normalized = normalizeFixtureName(file.name);
    if (!limits.fixture_extensions?.includes(extension(normalized))) {
      throw new Error(
        `Unsupported file type. Accepted: ${limits.fixture_extensions?.join(", ") ?? "none"}.`,
      );
    }
    const name = freeName(normalized, used);
    used.add(fixtureNameIdentity(name));
    files.push(
      brand(
        name === file.name
          ? file
          : new File([file], name, {
              type: file.type,
              lastModified: file.lastModified,
            }),
      ),
    );
    total += file.size;
  }
  if (taken.length + incoming.length > limits.max_documents) {
    throw new Error(
      `An experiment can contain at most ${limits.max_documents} files.`,
    );
  }
  if (total > limits.max_initial_bytes) {
    throw new Error(
      `Fixture files can use at most ${limits.max_initial_bytes / 1_000_000} MB in total.`,
    );
  }
  return files;
}

// A file of a saved answer, made again for a retry. `admitFiles` admitted its name when the
// user added it, so it keeps its name.
export function readmitSavedFile(saved: {
  name: string;
  type: string;
  blob: Blob;
}): AdmittedFile {
  return brand(new File([saved.blob], saved.name, { type: saved.type }));
}
