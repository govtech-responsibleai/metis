import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';

import {parseGlossary, slugify} from './parse.js';

const glossaryText = readFileSync(new URL('../../../GLOSSARY.md', import.meta.url), 'utf8');
const glossary = parseGlossary(glossaryText);

test('slugify turns a combined name into a url-safe slug', () => {
  assert.equal(slugify('Test Case / Task'), 'test-case-task');
  assert.equal(slugify('Feature-specific'), 'feature-specific');
  assert.equal(slugify('Test-Time Evals'), 'test-time-evals');
});

test('every term in a "Term" table is found, and no other table adds terms', () => {
  // 30 terms in the opening table and 5 in the Scope table. The "Kind" table is not a term table.
  assert.equal(glossary.terms.length, 35);
  assert.equal(glossary.terms[0].name, 'Target');
  assert.equal(glossary.terms.at(-1).name, 'Observation');
});

test('a term keeps its definition as written, with inline markdown intact', () => {
  const trial = glossary.terms.find((t) => t.name === 'Trial');
  assert.equal(trial.slug, 'trial');
  assert.equal(
    trial.definition,
    'One execution of a **test case** against a **target**, producing a **trace** and evaluation outputs.',
  );
});

test('blocks keep the file order: terms, note, headings, paragraphs, lists, tables', () => {
  const outline = glossary.blocks.map((b) => (b.type === 'heading' ? `h${b.level}:${b.text}` : b.type));
  assert.deepEqual(outline, [
    'table',
    'paragraph', // Note: Expected Behaviour corresponds to ...
    'h2:Scope',
    'paragraph',
    'paragraph',
    'paragraph',
    'table',
    'paragraph',
    'paragraph',
    'h2:Baseline and Feature-specific',
    'paragraph',
    'list',
    'paragraph',
    'paragraph',
    'list',
    'h2:Grader Types',
    'paragraph',
    'list',
    'paragraph',
    'table',
    'paragraph',
  ]);
});

test('headings get a section- id so they cannot clash with a term of the same name', () => {
  const scope = glossary.blocks.find((b) => b.type === 'heading' && b.text === 'Scope');
  assert.equal(scope.id, 'section-scope');
  assert.ok(glossary.terms.some((t) => t.slug === 'scope'));
});

test('a list nests items by two spaces', () => {
  const graderTypes = glossary.blocks.filter((b) => b.type === 'list').at(-1);
  assert.equal(graderTypes.items.length, 2);
  assert.match(graderTypes.items[0].text, /^\*\*Code-based grader\*\*/);
  assert.deepEqual(
    graderTypes.items[0].children.map((c) => c.text),
    ['slide count equals the requested number', 'font size at least the minimum', 'response is valid JSON'],
  );
});

test('the non-term table keeps its header and rows', () => {
  const kind = glossary.blocks.filter((b) => b.type === 'table').at(-1);
  assert.equal(kind.isTermTable, false);
  assert.deepEqual(kind.header, ['Kind', 'Grader type values']);
  assert.equal(kind.rows.length, 2);
});

test('lookup accepts a name in any case', () => {
  assert.equal(glossary.find('trial').name, 'Trial');
  assert.equal(glossary.find('Expected Behaviour').slug, 'expected-behaviour');
});

test('lookup accepts either half of a combined name', () => {
  assert.equal(glossary.find('Test Case').slug, 'test-case-task');
  assert.equal(glossary.find('task').slug, 'test-case-task');
});

test('lookup accepts the plural of a name', () => {
  assert.equal(glossary.find('trials').slug, 'trial');
  assert.equal(glossary.find('Graders').slug, 'grader');
  assert.equal(glossary.find('criteria').slug, 'criterion');
  assert.equal(glossary.find('Subsessions').slug, 'subsession');
  assert.equal(glossary.find('Test Cases').slug, 'test-case-task');
});

test('lookup returns undefined for an unknown name', () => {
  assert.equal(glossary.find('nonsense'), undefined);
});

test('a block the parser does not know fails loudly', () => {
  assert.throws(() => parseGlossary('1. an ordered list'), /ordered list/);
  assert.throws(() => parseGlossary('```\ncode\n```'), /code fence/);
  assert.throws(() => parseGlossary('> a quote'), /block quote/);
});

test('two terms with the same slug fail loudly', () => {
  const text = '| Term | Definition |\n|---|---|\n| Run | a |\n| run | b |\n';
  assert.throws(() => parseGlossary(text), /duplicate/i);
});
