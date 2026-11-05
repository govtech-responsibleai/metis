import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';

import {parseInline, pageFor} from './inline.js';
import {parseGlossary} from './parse.js';

test('plain text is one text token', () => {
  assert.deepEqual(parseInline('no markup here'), [{type: 'text', text: 'no markup here'}]);
});

test('bold, italic and code are recognised between plain text', () => {
  assert.deepEqual(parseInline('a **b** c *d* e `f` g'), [
    {type: 'text', text: 'a '},
    {type: 'bold', text: 'b'},
    {type: 'text', text: ' c '},
    {type: 'italic', text: 'd'},
    {type: 'text', text: ' e '},
    {type: 'code', text: 'f'},
    {type: 'text', text: ' g'},
  ]);
});

test('a link keeps its label and target', () => {
  assert.deepEqual(parseInline('See [Scope](#scope).'), [
    {type: 'text', text: 'See '},
    {type: 'link', text: 'Scope', href: '#scope'},
    {type: 'text', text: '.'},
  ]);
});

test('a repository file maps to the page the website publishes for it', () => {
  assert.equal(pageFor('docs/guide/library/graders.md'), '/library');
  assert.equal(pageFor('docs/architecture.md'), undefined);
});

test('every inline construct in GLOSSARY.md is understood', () => {
  const text = readFileSync(new URL('../../../GLOSSARY.md', import.meta.url), 'utf8');
  const glossary = parseGlossary(text);
  const strings = [];
  const collectItems = (items) => items.forEach((i) => (strings.push(i.text), collectItems(i.children)));
  for (const block of glossary.blocks) {
    if (block.type === 'paragraph') strings.push(block.text);
    if (block.type === 'list') collectItems(block.items);
    if (block.type === 'table') strings.push(...block.rows.flat());
  }
  for (const s of strings) {
    for (const token of parseInline(s)) {
      if (token.type === 'text') {
        assert.doesNotMatch(token.text, /[*`]|\]\(/, `unparsed markup in: ${s}`);
      }
    }
  }
});

test('markup the tokenizer does not know fails loudly', () => {
  assert.throws(() => parseInline('an ![image](x.png)'), /image/);
  assert.throws(() => parseInline('an unclosed **bold'), /unclosed/);
});
