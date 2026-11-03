import Link from '@docusaurus/Link';
import {useId} from 'react';

import styles from './styles.module.css';

/**
 * A word that links to a glossary entry and shows the term's definition in a card on hover and on
 * keyboard focus. `children` is the word as shown, `card` is the definition's content, and `href`
 * is `#slug` on the glossary page itself or `/glossary#slug` anywhere else.
 */
export default function TermHover({term, href, card, children}) {
  const cardId = useId();
  const word = href.startsWith('#') ? (
    <a className={styles.word} href={href} aria-describedby={cardId}>
      {children}
    </a>
  ) : (
    <Link className={styles.word} to={href} aria-describedby={cardId}>
      {children}
    </Link>
  );
  return (
    <span className={styles.term}>
      {word}
      <span className={styles.card} role="tooltip" id={cardId}>
        <strong className={styles.name}>{term.name}</strong>
        {card}
      </span>
    </span>
  );
}
