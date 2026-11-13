/**
 * Splits one line of `GLOSSARY.md` into tokens: bold, italic, code, links and plain text.
 *
 * It knows only the inline Markdown that the file uses, and stops with an error on anything else
 * (an image, an unclosed bold), the same as the block parser.
 */

const INLINE = /\*\*(.+?)\*\*|\*(.+?)\*|`(.+?)`|\[(.+?)\]\((.+?)\)/g;

// Repository files that the website publishes, so that a link in the glossary can follow them.
const PUBLISHED_PAGES = {
  'docs/guide/library/graders.md': '/library',
};

/** Returns the website page for a repository file, or `undefined` when the site has none. */
export function pageFor(repositoryPath) {
  return PUBLISHED_PAGES[repositoryPath];
}

export function parseInline(text) {
  if (/!\[/.test(text)) throw new Error(`GLOSSARY.md: the parser has no image case: "${text}"`);
  const tokens = [];
  let last = 0;
  for (const match of text.matchAll(INLINE)) {
    if (match.index > last) tokens.push({type: 'text', text: text.slice(last, match.index)});
    const [, bold, italic, code, label, href] = match;
    if (bold !== undefined) tokens.push({type: 'bold', text: bold});
    else if (italic !== undefined) tokens.push({type: 'italic', text: italic});
    else if (code !== undefined) tokens.push({type: 'code', text: code});
    else tokens.push({type: 'link', text: label, href});
    last = match.index + match[0].length;
  }
  if (last < text.length) tokens.push({type: 'text', text: text.slice(last)});
  for (const token of tokens) {
    if (token.type === 'text' && /\*/.test(token.text)) {
      throw new Error(`GLOSSARY.md: unclosed emphasis in: "${text}"`);
    }
  }
  return tokens;
}
