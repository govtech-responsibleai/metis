import assert from "node:assert/strict";
import test from "node:test";
import { transitionFrames, wordFrames } from "./reveal.ts";

test("keeps unchanged text still", () => {
  assert.deepEqual(
    transitionFrames({
      displayed: "Already written",
      previous: "Already written",
      next: "Already written",
      reducedMotion: false,
    }),
    [],
  );
});

test("reveals a first value by word while preserving its exact whitespace", () => {
  const value = "First line\nsecond  line";
  assert.deepEqual(wordFrames(value), [
    "First ",
    "First line\n",
    "First line\nsecond  ",
    value,
  ]);
  assert.deepEqual(
    transitionFrames({
      displayed: "",
      previous: "",
      next: value,
      reducedMotion: false,
    }),
    ["First ", "First line\n", "First line\nsecond  ", value],
  );
});

test("animates only a replaced word", () => {
  assert.deepEqual(
    transitionFrames({
      displayed: "Helpdesk coordinates five specialists",
      previous: "Helpdesk coordinates five specialists",
      next: "Helpdesk coordinates four specialists",
      reducedMotion: false,
    }),
    [
      "Helpdesk coordinates specialists",
      "Helpdesk coordinates four specialists",
    ],
  );
});

test("animates an insertion without restarting the field", () => {
  const frames = transitionFrames({
    displayed: "Helpdesk coordinates specialists",
    previous: "Helpdesk coordinates specialists",
    next: "Helpdesk coordinates five specialists",
    reducedMotion: false,
  });
  assert.deepEqual(frames, ["Helpdesk coordinates five specialists"]);
  assert(
    frames.every(
      (frame) => frame.includes("Helpdesk") && frame.includes("specialists"),
    ),
  );
});

test("animates a deletion without restarting the field", () => {
  const frames = transitionFrames({
    displayed: "Helpdesk coordinates five specialists",
    previous: "Helpdesk coordinates five specialists",
    next: "Helpdesk coordinates specialists",
    reducedMotion: false,
  });
  assert.deepEqual(frames, ["Helpdesk coordinates specialists"]);
  assert(
    frames.every(
      (frame) => frame.includes("Helpdesk") && frame.includes("specialists"),
    ),
  );
});

test("keeps matching words between separated changes visible", () => {
  const frames = transitionFrames({
    displayed: "Helpdesk coordinates five specialists today",
    previous: "Helpdesk coordinates five specialists today",
    next: "Helpdesk routes four specialists securely",
    reducedMotion: false,
  });
  assert(
    frames.some(
      (frame) => frame.includes("Helpdesk") && frame.includes("specialists"),
    ),
  );
  assert(
    frames.every(
      (frame) => frame.includes("Helpdesk") && frame.includes("specialists"),
    ),
  );
  assert.equal(frames.at(-1), "Helpdesk routes four specialists securely");
});

test("treats punctuation and capitalisation as part of a changed word", () => {
  const frames = transitionFrames({
    displayed: "Helpdesk helps officers.",
    previous: "Helpdesk helps officers.",
    next: "Helpdesk helps Officers!",
    reducedMotion: false,
  });
  assert(frames.some((frame) => frame === "Helpdesk helps"));
  assert.equal(frames.at(-1), "Helpdesk helps Officers!");
});

test("restores exact whitespace and line breaks after a correction", () => {
  const next = "Helpdesk supports officers!\nToday";
  const frames = transitionFrames({
    displayed: "Helpdesk helps officers.\nToday",
    previous: "Helpdesk helps officers.\nToday",
    next,
    reducedMotion: false,
  });
  assert.equal(frames.at(-1), next);
});

test("shows the complete value immediately for reduced motion", () => {
  assert.deepEqual(
    transitionFrames({
      displayed: "Old text",
      previous: "Old text",
      next: "Complete new text",
      reducedMotion: true,
    }),
    ["Complete new text"],
  );
});

test("a newer value supersedes the visible frame of an in-flight reveal", () => {
  assert.deepEqual(
    transitionFrames({
      displayed: "Partly ",
      previous: "Partly revealed old value",
      next: "Newest value",
      reducedMotion: false,
    }),
    ["", "Newest", "Newest value"],
  );
});
