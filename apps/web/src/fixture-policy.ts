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

export function validateFixtureSelection(
  files: readonly FixtureFileLike[],
  library: readonly FixtureFileLike[],
  limits: {
    max_documents: number;
    max_initial_bytes: number;
    fixture_extensions?: readonly string[];
  } = {
    max_documents: FIXTURE_MAX_FILES,
    max_initial_bytes: FIXTURE_MAX_BYTES,
    fixture_extensions: ACCEPTED_FIXTURE_EXTENSIONS,
  },
): string[] {
  const existing = new Set(
    library.map((item) => fixtureNameIdentity(item.name)),
  );
  const incoming = new Set<string>();
  const names: string[] = [];
  let total = library.reduce((sum, item) => sum + item.size, 0);
  for (const file of files) {
    const name = normalizeFixtureName(file.name);
    if (!limits.fixture_extensions?.includes(extension(name))) {
      throw new Error(
        `Unsupported file type. Accepted: ${limits.fixture_extensions?.join(", ") ?? "none"}.`,
      );
    }
    const key = fixtureNameIdentity(name);
    if (existing.has(key) || incoming.has(key)) {
      throw new Error(`A file named ${name} is already uploaded.`);
    }
    incoming.add(key);
    names.push(name);
    total += file.size;
  }
  if (library.length + files.length > limits.max_documents) {
    throw new Error(
      `An experiment can contain at most ${limits.max_documents} files.`,
    );
  }
  if (total > limits.max_initial_bytes) {
    throw new Error(
      `Fixture files can use at most ${limits.max_initial_bytes / 1_000_000} MB in total.`,
    );
  }
  return names;
}
