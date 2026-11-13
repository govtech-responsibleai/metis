import Link from '@docusaurus/Link';
import TermHover from '@site/docs/src/components/Term/TermHover';
import {parseInline, pageFor} from '@site/docs/src/glossary/inline';

import {glossary, sectionIds} from './data';

/**
 * Renders one line of the glossary. A bold word that names another term links to that term's
 * entry and shows its definition on hover, except inside the term's own entry (`ownSlug`).
 * `linkTerms={false}` leaves them as plain bold, for the text inside a hover card.
 */
export default function Inline({text, ownSlug, linkTerms = true}) {
  return parseInline(text).map((token, index) => {
    switch (token.type) {
      case 'bold': {
        const term = linkTerms ? glossary.find(token.text) : undefined;
        if (term && term.slug !== ownSlug) {
          return (
            <TermHover
              key={index}
              term={term}
              href={`#${term.slug}`}
              card={<Inline text={term.definition} ownSlug={term.slug} linkTerms={false} />}
            >
              <strong>{token.text}</strong>
            </TermHover>
          );
        }
        return <strong key={index}>{token.text}</strong>;
      }
      case 'italic':
        return <em key={index}>{token.text}</em>;
      case 'code':
        return <code key={index}>{token.text}</code>;
      case 'link':
        return linkTerms ? <GlossaryLink key={index} {...token} /> : token.text;
      default:
        return token.text;
    }
  });
}

/** A link in the file points to a heading in the file, or to a repository file. */
function GlossaryLink({text, href}) {
  if (href.startsWith('#')) {
    // A heading's id carries a `section-` prefix, because a heading and a term can share a name.
    const sectionId = `section-${href.slice(1)}`;
    return <a href={sectionIds.has(sectionId) ? `#${sectionId}` : href}>{text}</a>;
  }
  const page = pageFor(href);
  return page ? <Link to={page}>{text}</Link> : text;
}
