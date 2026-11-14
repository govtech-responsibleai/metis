import {parseGlossary} from '@site/docs/src/glossary/parse';

// `docusaurus.config.js` defines this constant from the text of `GLOSSARY.md`.
/* global __GLOSSARY_MARKDOWN__ */
export const glossary = parseGlossary(__GLOSSARY_MARKDOWN__);

export const sectionIds = new Set(glossary.blocks.filter((b) => b.type === 'heading').map((b) => b.id));
