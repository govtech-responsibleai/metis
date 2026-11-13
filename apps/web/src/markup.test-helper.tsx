// Readers of static markup for the tests of routed components.

import assert from "node:assert/strict";
import type { ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { Router } from "wouter";

export function at(path: string, node: ReactNode): string {
  return renderToStaticMarkup(<Router ssrPath={path}>{node}</Router>);
}

export function tab(markup: string, label: string): string {
  const found = [
    ...markup.matchAll(/<(a|button)[^>]*role="tab"[^>]*>(.*?)<\/\1>/g),
  ].find(([, , inner]) => inner === label);
  assert.ok(found, `no ${label} tab`);
  return found[0];
}

export const text = (markup: string) => markup.replace(/<[^>]+>/g, "");

// The opening tag of the first link or button whose text starts with `label`. A Target row
// also shows its time.
export function control(markup: string, label: string): string {
  const found = [...markup.matchAll(/(<(a|button)\b[^>]*>)(.*?)<\/\2>/g)].find(
    ([, , , inner]) => text(inner ?? "").startsWith(label),
  );
  assert.ok(found, `no ${label} control`);
  return found[1] ?? "";
}
