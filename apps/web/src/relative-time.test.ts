import assert from "node:assert/strict";
import test from "node:test";
import { relativeTime } from "./relative-time.ts";

test("renders epoch-millisecond record times in the correct unit", () => {
  const now = Date.UTC(2026, 0, 2, 12, 0, 0);
  assert.equal(relativeTime(now - 90_000, now), "1 min ago");
  assert.equal(relativeTime(now - 2 * 60 * 60_000, now), "2 h ago");
});
