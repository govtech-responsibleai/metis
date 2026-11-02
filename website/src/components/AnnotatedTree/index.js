import {Children, useState} from 'react';
import {usePrismTheme} from '@docusaurus/theme-common';
// The tree looks and behaves like AnnotatedYaml, so it borrows that component's styles, except
// for the layout, which is its own: the notes go under the tree.
import styles from '../AnnotatedYaml/styles.module.css';
import layout from './styles.module.css';

// One explanation for one entry of the tree. `match` is the end of the line it explains, such as
// `specification.yaml` or `fixtures/`. A line that no note matches is shown but does not light up.
export function TreeNote({children}) {
  return <>{children}</>;
}

// A folder tree shown as plain text, with a note for each entry worth explaining. Hovering or
// focusing a note lights up its line, and hovering a line lights up its note. `source` is the
// tree as text, as the `tree` command prints it.
export default function AnnotatedTree({source, title, children}) {
  const prismTheme = usePrismTheme();
  const [active, setActive] = useState(null);
  const notes = Children.toArray(children).filter((child) => child.type === TreeNote);
  const lines = source.trimEnd().split('\n');
  const noteOf = (text) =>
    notes.findIndex(({props}) => props.match && text.trimEnd().endsWith(props.match));

  return (
    <div className={layout.wrapper}>
      <figure className={styles.window}>
        {title && (
          <figcaption className={styles.title}>
            <span>{title}</span>
          </figcaption>
        )}
        <pre
          className={styles.code}
          style={{...prismTheme.plain, background: 'transparent'}}>
          {lines.map((text, index) => {
            const note = noteOf(text);
            const explained = note !== -1;
            return (
              <div
                key={index}
                className={[
                  styles.line,
                  explained && styles.explained,
                  explained && note === active && styles.lit,
                ]
                  .filter(Boolean)
                  .join(' ')}
                onMouseEnter={explained ? () => setActive(note) : undefined}
                onMouseLeave={explained ? () => setActive(null) : undefined}>
                {text}
              </div>
            );
          })}
        </pre>
      </figure>
      <ul className={layout.notes}>
        {notes.map((note, index) => (
          <li
            key={index}
            tabIndex={0}
            className={index === active ? `${styles.note} ${styles.lit}` : styles.note}
            onMouseEnter={() => setActive(index)}
            onMouseLeave={() => setActive(null)}
            onFocus={() => setActive(index)}
            onBlur={() => setActive(null)}>
            {note}
          </li>
        ))}
      </ul>
    </div>
  );
}
