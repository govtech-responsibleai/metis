/**
 * Reads `GLOSSARY.md` for the glossary page and the `<Term>` component.
 *
 * It understands only the Markdown that the file uses: headings, paragraphs, tables, and bulleted
 * lists nested by two spaces. A new kind of block in the file needs a new case here, and until
 * then the parser stops with an error rather than guess.
 */

/** Turns a name into a url-safe slug: `Test Case / Task` becomes `test-case-task`. */
export function slugify(name) {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

const HEADING = /^(#{1,6})\s+(.*)$/;
const BULLET = /^(\s*)[-*]\s+(.*)$/;
const TABLE_ROW = /^\s*\|/;
const TABLE_RULE = /^[\s|:-]+$/;

// Plurals that dropping an "s" does not undo.
const IRREGULAR_SINGULAR = {criteria: 'criterion'};

function splitRow(line) {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim());
}

function rejectUnknownBlock(line) {
  if (/^\s*\d+[.)]\s/.test(line)) throw new Error(`GLOSSARY.md: the parser has no ordered list case: "${line}"`);
  if (/^\s*(```|~~~)/.test(line)) throw new Error(`GLOSSARY.md: the parser has no code fence case: "${line}"`);
  if (/^\s*>/.test(line)) throw new Error(`GLOSSARY.md: the parser has no block quote case: "${line}"`);
}

function startsBlock(line) {
  return HEADING.test(line) || BULLET.test(line) || TABLE_ROW.test(line);
}

function parseList(lines, start) {
  const items = [];
  const stack = [];
  let i = start;
  for (; i < lines.length; i += 1) {
    const match = BULLET.exec(lines[i]);
    if (!match) break;
    const depth = Math.floor(match[1].length / 2);
    const item = {text: match[2].trim(), children: []};
    while (stack.length > 0 && stack.at(-1).depth >= depth) stack.pop();
    if (stack.length === 0) items.push(item);
    else stack.at(-1).item.children.push(item);
    stack.push({depth, item});
  }
  return {block: {type: 'list', items}, next: i};
}

function parseTable(lines, start) {
  const rows = [];
  let i = start;
  for (; i < lines.length && TABLE_ROW.test(lines[i]); i += 1) {
    if (!TABLE_RULE.test(lines[i])) rows.push(splitRow(lines[i]));
  }
  const [header, ...body] = rows;
  return {block: {type: 'table', header, rows: body, isTermTable: header[0] === 'Term'}, next: i};
}

function parseParagraph(lines, start) {
  const text = [];
  let i = start;
  for (; i < lines.length && lines[i].trim() !== '' && (i === start || !startsBlock(lines[i])); i += 1) {
    text.push(lines[i].trim());
  }
  return {block: {type: 'paragraph', text: text.join(' ')}, next: i};
}

function parseBlocks(markdown) {
  const lines = markdown.split(/\r?\n/);
  const blocks = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.trim() === '') {
      i += 1;
      continue;
    }
    rejectUnknownBlock(line);
    const heading = HEADING.exec(line);
    let parsed;
    if (heading) {
      const text = heading[2].trim();
      parsed = {block: {type: 'heading', level: heading[1].length, text, id: `section-${slugify(text)}`}, next: i + 1};
    } else if (TABLE_ROW.test(line)) {
      parsed = parseTable(lines, i);
    } else if (BULLET.test(line)) {
      parsed = parseList(lines, i);
    } else {
      parsed = parseParagraph(lines, i);
    }
    blocks.push(parsed.block);
    i = parsed.next;
  }
  return blocks;
}

function collectTerms(blocks) {
  const terms = [];
  const slugs = new Set();
  for (const block of blocks) {
    if (block.type !== 'table' || !block.isTermTable) continue;
    for (const [name, definition] of block.rows) {
      const slug = slugify(name);
      if (slugs.has(slug)) throw new Error(`GLOSSARY.md: duplicate term "${name}" (slug "${slug}")`);
      slugs.add(slug);
      terms.push({name, slug, definition});
    }
  }
  return terms;
}

/** Each term answers to its whole name and to either half of a combined name such as `Test Case / Task`. */
function buildLookup(terms) {
  const byKey = new Map();
  for (const term of terms) {
    for (const part of [term.name, ...term.name.split('/')]) {
      const key = part.trim().toLowerCase();
      if (byKey.has(key) && byKey.get(key) !== term) {
        throw new Error(`GLOSSARY.md: "${part.trim()}" names both "${byKey.get(key).name}" and "${term.name}"`);
      }
      byKey.set(key, term);
    }
  }

  return function find(name) {
    const key = name.trim().toLowerCase();
    const candidates = [key, IRREGULAR_SINGULAR[key], key.replace(/ies$/, 'y'), key.replace(/es$/, ''), key.replace(/s$/, '')];
    for (const candidate of candidates) {
      if (candidate && byKey.has(candidate)) return byKey.get(candidate);
    }
    return undefined;
  };
}

/**
 * Parses the text of `GLOSSARY.md`.
 *
 * Returns `blocks` in file order, `terms` from every table whose first column is "Term", and
 * `find(name)`, which returns the term for a name, either half of a combined name, or a plural.
 */
export function parseGlossary(markdown) {
  const blocks = parseBlocks(markdown);
  const terms = collectTerms(blocks);
  return {blocks, terms, find: buildLookup(terms)};
}
