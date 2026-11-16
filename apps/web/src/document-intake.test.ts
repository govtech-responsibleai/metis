import assert from "node:assert/strict";
import test from "node:test";
import { documentsForRequest, type DocumentReads } from "./document-intake.ts";

const limits = { max_text_characters_total: 10 };
const files = [
  { name: "policy.txt", size: 1 },
  { name: "chart.png", size: 1 },
];

test("documents go with their text when each file is settled", () => {
  const reads: DocumentReads = {
    "policy.txt": { status: "read", text: "policy" },
    "chart.png": { status: "not_read" },
  };
  assert.deepEqual(documentsForRequest(files, reads, limits), {
    documents: [{ name: "policy.txt", text: "policy" }, { name: "chart.png" }],
  });
  assert.deepEqual(documentsForRequest([], {}, undefined), { documents: [] });
});

test("documents wait for each read and for the text limit of the Interview", () => {
  const blocked = (
    reads: DocumentReads,
    held: { name: string; text?: string }[],
  ) => "blocked" in documentsForRequest(files, reads, limits, held);
  const read: DocumentReads = {
    "policy.txt": { status: "read", text: "policy" },
    "chart.png": { status: "kept" },
  };

  assert.equal(
    blocked({ ...read, "chart.png": { status: "reading" } }, []),
    true,
  );
  assert.equal(
    blocked({ ...read, "chart.png": { status: "failed", message: "No" } }, []),
    true,
  );
  // The text that the Interview already has counts toward the same limit.
  assert.equal(blocked(read, [{ name: "held.txt", text: "12345" }]), true);
  assert.equal(blocked(read, [{ name: "held.txt", text: "1234" }]), false);
  assert.equal("blocked" in documentsForRequest(files, read, undefined), true);
});
