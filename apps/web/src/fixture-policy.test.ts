import assert from "node:assert/strict";
import test from "node:test";
import {
  ACCEPTED_FIXTURE_EXTENSIONS,
  admitFiles,
  FIXTURE_MAX_BYTES,
  FIXTURE_MAX_FILES,
  normalizeFixtureName,
} from "./fixture-policy.ts";

const file = (name: string, size = 1) =>
  new File(["x".repeat(size)], name, { type: "text/plain", lastModified: 7 });
const names = (files: readonly File[]) => files.map((item) => item.name);

test("accepts each supported fixture extension without case sensitivity", () => {
  assert.equal(
    admitFiles(
      ACCEPTED_FIXTURE_EXTENSIONS.map((value) =>
        file(`sample.${value.toUpperCase()}`),
      ),
      [],
    ).length,
    ACCEPTED_FIXTURE_EXTENSIONS.length,
  );
});

test("rejects unsafe and unsupported fixture names", () => {
  for (const name of ["../sample.csv", "CON.txt", "sample.exe"]) {
    assert.throws(() => admitFiles([file(name)], []));
  }
  assert.equal(normalizeFixtureName("  résumé.md  "), "résumé.md");
});

test("a file with a name that is taken gets the next free number", () => {
  const taken = [file("policy.pdf"), file("policy (2).pdf")];
  const [admitted] = admitFiles([file("policy.pdf")], taken);

  assert.equal(admitted?.name, "policy (3).pdf");
  assert.equal(admitted?.type, "text/plain");
  assert.equal(admitted?.lastModified, 7);
});

test("names that differ only by case or Unicode fold are the same name", () => {
  assert.deepEqual(
    names(admitFiles([file("POLICY.pdf")], [file("policy.pdf")])),
    ["POLICY (2).pdf"],
  );
  assert.deepEqual(
    names(admitFiles([file("STRASSE.csv")], [file("straße.csv")])),
    ["STRASSE (2).csv"],
  );
});

test("a numbered name that is taken continues from its own number", () => {
  assert.deepEqual(
    names(admitFiles([file("report (2).pdf")], [file("report (2).pdf")])),
    ["report (3).pdf"],
  );
});

test("files in one selection get distinct names", () => {
  assert.deepEqual(
    names(
      admitFiles([file("notes.md"), file("NOTES.md"), file("notes.md")], []),
    ),
    ["notes.md", "NOTES (2).md", "notes (3).md"],
  );
});

test("a free name keeps its file", () => {
  const original = file("notes.md");
  assert.equal(admitFiles([original], [file("other.md")])[0], original);
});

test("enforces the fixture count and total byte limits", () => {
  const full = Array.from({ length: FIXTURE_MAX_FILES }, (_, index) =>
    file(`f-${index}.txt`),
  );
  assert.doesNotThrow(() => admitFiles(full, []));
  assert.throws(() => admitFiles([file("extra.txt")], full), /at most 20/);
  assert.throws(
    () =>
      admitFiles(
        [file("large.txt")],
        [{ name: "big.txt", size: FIXTURE_MAX_BYTES }],
      ),
    /MB in total/,
  );
});

test("applies configured document formats and limits", () => {
  const limits = {
    max_documents: 1,
    max_initial_bytes: 4,
    fixture_extensions: ["md"],
  };
  assert.deepEqual(names(admitFiles([file("notes.md", 4)], [], limits)), [
    "notes.md",
  ]);
  assert.throws(() => admitFiles([file("notes.txt")], [], limits));
  assert.throws(() => admitFiles([file("notes.md", 5)], [], limits));
  assert.throws(() =>
    admitFiles([file("notes.md")], [file("other.md")], limits),
  );
});
