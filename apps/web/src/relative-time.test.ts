import assert from "node:assert/strict";
import test from "node:test";
import { absoluteTime, relativeTime } from "./relative-time.ts";

test("renders epoch-millisecond record times in the correct unit", () => {
  const now = Date.UTC(2026, 0, 2, 12, 0, 0);
  assert.equal(relativeTime(now - 90_000, now), "1 min ago");
  assert.equal(relativeTime(now - 2 * 60 * 60_000, now), "2 h ago");
});

test("an absolute time shows the local date and time to the second, and the year only when it is not this year", () => {
  const now = new Date(2026, 10, 19, 15, 0, 0).getTime();
  assert.equal(
    absoluteTime(new Date(2026, 10, 19, 14, 32, 5).getTime(), now),
    "19 Nov, 14:32:05",
  );
  assert.equal(
    absoluteTime(new Date(2025, 0, 3, 9, 2, 5).getTime(), now),
    "3 Jan 2025, 09:02:05",
  );
});
