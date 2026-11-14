import {glossary} from '@site/docs/src/components/Glossary/data';
import Inline from '@site/docs/src/components/Glossary/Inline';

import TermHover from './TermHover';

/**
 * Marks a word as a glossary term. The word links to the term's entry on the glossary page, and
 * its definition appears in a card on hover and on keyboard focus.
 *
 * The text between the tags is shown as written, so `<Term name="trial">trials</Term>` can show a
 * plural or a different case. Without `name`, the text itself names the term. An unknown name
 * throws, which fails the build, so a renamed term is found at once.
 */
export default function Term({name, children}) {
  const lookup = name ?? (typeof children === 'string' ? children : undefined);
  if (lookup === undefined) {
    throw new Error('<Term> needs a name prop when its content is not plain text');
  }
  const term = glossary.find(lookup);
  if (!term) {
    throw new Error(`<Term>: "${lookup}" is not a term in GLOSSARY.md`);
  }

  return (
    <TermHover
      term={term}
      href={`/glossary#${term.slug}`}
      card={<Inline text={term.definition} ownSlug={term.slug} linkTerms={false} />}
    >
      {children}
    </TermHover>
  );
}
