import assert from "node:assert/strict";
import test from "node:test";
import { parseThemeChoice, resolveTheme } from "./theme.ts";

test("a stored choice of light or dark is kept and anything else is system", () => {
  assert.equal(parseThemeChoice("light"), "light");
  assert.equal(parseThemeChoice("dark"), "dark");
  assert.equal(parseThemeChoice(null), "system");
  assert.equal(parseThemeChoice("sepia"), "system");
});

test("system follows the browser setting and an explicit choice ignores it", () => {
  assert.equal(resolveTheme("system", true), "dark");
  assert.equal(resolveTheme("system", false), "light");
  assert.equal(resolveTheme("light", true), "light");
  assert.equal(resolveTheme("dark", false), "dark");
});
