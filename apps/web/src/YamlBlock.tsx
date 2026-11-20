// A read-only YAML block on CodeMirror 6. The theme reads the colour tokens of globals.css, so it
// follows the light and dark theme of the app with no second palette.

import { yaml } from "@codemirror/lang-yaml";
import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { EditorState } from "@codemirror/state";
import { EditorView, lineNumbers } from "@codemirror/view";
import { tags } from "@lezer/highlight";
import { Check, Copy } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { cn } from "./ui";

const token = (name: string) => `hsl(var(--${name}))`;

const theme = EditorView.theme({
  "&": {
    color: token("foreground"),
    backgroundColor: token("card"),
    fontSize: "12px",
  },
  ".cm-scroller": {
    fontFamily: '"JetBrains Mono", ui-monospace, monospace',
    lineHeight: "1.65",
  },
  ".cm-content": { padding: "12px 0" },
  ".cm-gutters": {
    backgroundColor: token("card"),
    color: token("muted-foreground"),
    border: "none",
  },
  ".cm-lineNumbers .cm-gutterElement": { padding: "0 12px 0 16px" },
  "&.cm-focused": { outline: "none" },
  ".cm-selectionBackground, &.cm-focused .cm-selectionBackground": {
    backgroundColor: `hsl(var(--accent) / 0.15)`,
  },
});

// Keys are grey, so the values carry the eye. Numbers and booleans take a data colour. The accent
// and the status colours stay out, because the YAML has no state and no result.
const highlight = HighlightStyle.define([
  {
    tag: [tags.propertyName, tags.definition(tags.propertyName)],
    color: token("muted-foreground"),
  },
  { tag: [tags.number, tags.bool, tags.null], color: token("tag-scope") },
  { tag: [tags.comment], color: token("skipped"), fontStyle: "italic" },
  { tag: [tags.punctuation, tags.separator], color: token("muted-foreground") },
]);

export function YamlBlock({ text, name }: { text: string; name: string }) {
  const host = useRef<HTMLDivElement>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!host.current) return;
    const view = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: text,
        extensions: [
          lineNumbers(),
          yaml(),
          syntaxHighlighting(highlight),
          theme,
          EditorState.readOnly.of(true),
          EditorView.editable.of(false),
        ],
      }),
    });
    return () => view.destroy();
  }, [text]);

  const copy = () => {
    void navigator.clipboard?.writeText(text);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-card">
      <div className="flex items-center justify-between border-b border-border py-1.5 pr-1.5 pl-4">
        <span className="font-mono text-xs text-muted-foreground">{name}</span>
        <button
          type="button"
          onClick={copy}
          aria-label={copied ? "Copied" : `Copy ${name}`}
          className={cn(
            "flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-muted-foreground transition-colors duration-150 hover:bg-muted hover:text-foreground",
            copied && "text-foreground",
          )}
        >
          {copied ? (
            <Check size={13} aria-hidden />
          ) : (
            <Copy size={13} aria-hidden />
          )}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <div
        ref={host}
        className="quiet-scrollbar max-h-[calc(100vh-17rem)] overflow-auto [&_.cm-editor]:h-full"
      />
    </div>
  );
}
