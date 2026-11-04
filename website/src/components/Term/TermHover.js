import Link from '@docusaurus/Link';
import {useId, useRef, useState} from 'react';

import styles from './styles.module.css';

const EDGE = 8; // px of space to keep between the card and the window edge

/**
 * A word that shows a glossary term's definition in a card on hover and on keyboard focus.
 *
 * The word is not a link, so that it does not look like one: it only reveals the definition. The
 * card holds the one link, to the term's entry on the glossary page. `children` is the word as
 * shown, `card` is the definition's content, and `href` is `#slug` on the glossary page itself or
 * `/glossary#slug` anywhere else.
 *
 * The card opens below the word and left-aligned. When it would run past the right or left edge of
 * the window, it slides sideways by the overflow, and when it would run past the bottom edge, it
 * opens above the word instead. Escape closes it.
 */
export default function TermHover({term, href, card, children}) {
  const definitionId = useId();
  const wordRef = useRef(null);
  const cardRef = useRef(null);
  const [placement, setPlacement] = useState({shift: 0, up: false});
  const [dismissed, setDismissed] = useState(false);

  // The card has no size while it is hidden, so measure it one frame after it opens. The measured
  // box already includes the current shift, so take that off to get the unshifted position.
  function place() {
    requestAnimationFrame(() => {
      if (!wordRef.current || !cardRef.current) return;
      const word = wordRef.current.getBoundingClientRect();
      const box = cardRef.current.getBoundingClientRect();
      if (box.width === 0) return;
      const left = box.left - placement.shift;
      let shift = Math.min(0, window.innerWidth - EDGE - (left + box.width));
      shift = Math.max(shift, EDGE - left);
      const room = window.innerHeight - word.bottom;
      setPlacement({
        shift: Math.round(shift),
        up: room < box.height + EDGE && word.top > box.height + EDGE,
      });
    });
  }

  function onKeyDown(event) {
    if (event.key === 'Escape') setDismissed(true);
  }

  const className = [
    styles.term,
    placement.up && styles.up,
    dismissed && styles.dismissed,
  ]
    .filter(Boolean)
    .join(' ');
  const onGlossaryPage = href.startsWith('#');

  return (
    <span
      className={className}
      onMouseEnter={place}
      onFocus={place}
      onMouseLeave={() => setDismissed(false)}
      onBlur={() => setDismissed(false)}
      onKeyDown={onKeyDown}
    >
      <span className={styles.word} ref={wordRef} tabIndex={0} aria-describedby={definitionId}>
        {children}
      </span>
      <span className={styles.card} ref={cardRef} style={{'--card-shift': `${placement.shift}px`}}>
        <strong className={styles.name}>{term.name}</strong>
        <span id={definitionId}>{card}</span>
        {onGlossaryPage ? (
          <a className={styles.more} href={href}>
            Go to this entry →
          </a>
        ) : (
          <Link className={styles.more} to={href}>
            See in glossary →
          </Link>
        )}
      </span>
    </span>
  );
}
