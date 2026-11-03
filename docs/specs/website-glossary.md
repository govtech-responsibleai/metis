# Website glossary and term definitions

Status: proposed, not built.

## Purpose

`GLOSSARY.md` defines the terms that METIS uses, but it sits at the repository root and the
website does not publish it. A reader of the documentation, and above all a participant in the
STACK 2026 workshop, meets words such as target, specification, trial, trace, session, grader and
criterion with no way to look them up. This design adds a glossary page to the website, and a way
to show a term's definition where the term is used.

## Goals

1. A glossary page on the website that lists every term in `GLOSSARY.md`, with a stable anchor for
   each (`/glossary#trial`).
2. A way to mark a term in a documentation page so that it links to its glossary entry.
3. A definition that appears when the reader hovers over, or moves keyboard focus to, a marked
   term.
4. One copy of the definitions. The page and the hover text both come from `GLOSSARY.md`, so
   neither can drift from it.

## Non-goals

- Marking terms automatically. Underlining every occurrence of a word like "target" or "trace"
  would be noisy, and would catch uses that are not the glossary sense, such as "target
  connection".
- Rewording the glossary. This design shows `GLOSSARY.md` as it is; changes to wording belong in
  that file.
- Translating or versioning the glossary.

## Design

```
GLOSSARY.md ──read at build time──▶ parser ──┬──▶ Glossary page (every term, anchored)
  (only copy)                                └──▶ <Term> component (hover card + link)
```

### Reading the glossary

`GLOSSARY.md` cannot be imported with `?raw` the way the example YAML files are. Docusaurus
compiles every `.md` file as MDX before the raw-import rule sees it, so the import yields compiled
code rather than the file's text. Instead, `docusaurus.config.js` reads the file with Node and
passes its text to the bundle as a build-time constant (webpack `DefinePlugin`), which the parser
reads.

### Parser

`src/glossary/parse.js` handles only the Markdown that `GLOSSARY.md` uses: headings, paragraphs,
tables, and bulleted lists nested by two spaces. It returns the blocks in order, and the terms
defined by every table whose first column is "Term". A new kind of block in the file needs a new
case in the parser. Each term gets a slug (`Test Case / Task` becomes `test-case-task`), and a
lookup that accepts either half of a combined name, and the plural of a name.

### Glossary page

`docs/glossary.mdx` renders a `Glossary` component, and is added to the end of the sidebar after
Examples.

- Each term is a definition-list entry with the term's slug as its id. The entry that a link points
  to is tinted.
- A bold word in a definition that names another term links to that term's entry, except inside
  the term's own entry.
- Headings from the file (Scope, Baseline and Feature-specific, Grader Types) keep their place
  after the tables. Their ids carry a `section-` prefix, because a heading and a term can share a
  name (`scope`).
- A link in the file that points to a repository file is mapped to the page that the website
  publishes for it, or shown as plain text when there is none. The link to
  `docs/guide/library/graders.md` maps to `/library`.

### The `<Term>` component

`<Term>trial</Term>` renders the word with a dotted underline. Hovering over it, or focusing it
with the keyboard, shows the glossary definition in a small card, and the word links to the
term's entry on the glossary page. The text between the tags is shown as written, so
`<Term name="trial">trials</Term>` can show a plural or a different case. An unknown name fails
the build, so that a renamed term is found at once.

The card appears only on hover and focus, so on a touch screen the link is the way to reach the
definition.

### Marking terms

Terms are marked by hand, at the first use in each step or section. For the STACK 2026 workshop
page the first candidates are target, specification, trial, trace, session, grader and criterion.

## Open questions

1. **Internal entries.** The glossary was written for contributors. The Interview turn, Interview
   message and Test-Time Evals entries, and the `max_turns` reference in the Simulated turn entry,
   may not suit a public page. The choices are to show the whole file, to skip a list of terms on
   the page, or to mark entries in `GLOSSARY.md` itself.
2. **Where the page goes in the sidebar.** The end of the list, or under the Intro, where a new
   reader would find it first.
3. **Hover cards on touch screens.** A tap could open the card instead of following the link, at
   the cost of a second tap to reach the glossary.

## Verification

- `npm run build` in `website/` passes, which also checks every internal link.
- The built glossary page has one entry for each term in `GLOSSARY.md`. Count the `<dt>` elements
  in `build/glossary.html`, because a page that compiles can still render empty.
- A term in the workshop page shows its definition on hover and on keyboard focus, in light and
  dark mode.
- Renaming a term in `GLOSSARY.md` makes the build fail wherever a `<Term>` still uses the old
  name.
