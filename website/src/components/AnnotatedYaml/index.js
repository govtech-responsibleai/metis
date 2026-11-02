import {Children, useEffect, useMemo, useRef, useState} from 'react';
import {usePrismTheme} from '@docusaurus/theme-common';
import {Highlight} from 'prism-react-renderer';
import styles from './styles.module.css';

const TOP_LEVEL_KEY = /^[A-Za-z_]/;
const indentOf = (text) => text.length - text.trimStart().length;

// One explanation for a part of the file. `match` is the start of the first line it explains,
// such as `transport:`. By default the note explains that one line. `section` extends it to the
// next key at the left margin, and `block` extends it to the next line that is indented no more
// than the first. A note without `match` explains something the file does not contain, so it
// lights up no line.
export function YamlNote({children}) {
  return <>{children}</>;
}

// A part of the file to hide until the reader asks for the whole file. `match`, `section` and
// `block` pick the lines as in YamlNote. `keep` is how many of them stay visible (default 0), so
// that `keep={1}` leaves the `- id: ...` line of an entry and hides its details. It shows nothing
// itself.
export function YamlHide() {
  return null;
}

// The lines [start, end) that `match`, `section` and `block` pick, or null when no line matches.
function rangeOf(texts, {match, section, block}) {
  const start = texts.findIndex((text) => text.trimStart().startsWith(match));
  if (start === -1) return null;
  let end = start + 1;
  if (section) {
    while (end < texts.length && !TOP_LEVEL_KEY.test(texts[end])) end += 1;
  } else if (block) {
    while (
      end < texts.length &&
      (texts[end].trim() === '' || indentOf(texts[end]) > indentOf(texts[start]))
    ) {
      end += 1;
    }
  }
  return [start, end];
}

// The notes that explain each line, the most specific (fewest lines) first.
function ownersOf(texts, notes) {
  const owners = texts.map(() => []);
  notes.forEach(({props}, index) => {
    const range = props.match && rangeOf(texts, props);
    if (!range) return;
    const [start, end] = range;
    for (let line = start; line < end; line += 1) {
      owners[line].push({index, size: end - start});
    }
  });
  return owners.map((list) => list.sort((a, b) => a.size - b.size).map(({index}) => index));
}

// For each line, the length of the hidden stretch that starts there, or 0 when the line is shown
// or is inside a stretch that started earlier.
function hiddenRuns(texts, hides) {
  const hidden = texts.map(() => false);
  hides.forEach(({props}) => {
    const range = rangeOf(texts, props);
    if (!range) return;
    for (let line = range[0] + (props.keep ?? 0); line < range[1]; line += 1) hidden[line] = true;
  });
  const runs = texts.map(() => 0);
  let runStart = -1;
  hidden.forEach((isHidden, line) => {
    if (!isHidden) {
      runStart = -1;
    } else if (runStart === -1) {
      runStart = line;
      runs[line] = 1;
    } else {
      runs[runStart] += 1;
    }
  });
  return {hidden, runs};
}

// A file shown as read-only YAML, with a note for each part worth explaining. Hovering or
// focusing a note lights up its lines and scrolls the file to them, and hovering a line lights
// up its note. `source` is the file's text, imported with `?raw`, so the page shows the real
// file. Notes and hidden parts are matched by the start of a line, so editing the file does not
// break them. `height` caps the height of the file, which then scrolls. Parts marked with
// YamlHide are replaced by a count of the lines left out, and a button in the title bar shows
// the whole file.
export default function AnnotatedYaml({source, title, height, children}) {
  const prismTheme = usePrismTheme();
  const [active, setActive] = useState(null);
  const [showAll, setShowAll] = useState(false);
  const codeRef = useRef(null);
  const lineRefs = useRef([]);
  const parts = Children.toArray(children);
  const notes = parts.filter((child) => child.type === YamlNote);
  const hides = parts.filter((child) => child.type === YamlHide);
  const code = source.trimEnd();
  const texts = code.split('\n');
  const owners = useMemo(() => ownersOf(texts, notes), [code, notes]);
  const {hidden, runs} = useMemo(() => hiddenRuns(texts, hides), [code, hides]);
  const hiddenTotal = hidden.filter(Boolean).length;

  // A note hovered far from the lines it explains scrolls the file to them. A line that is
  // already in view, or is hidden, is left alone.
  useEffect(() => {
    const pre = codeRef.current;
    const first = owners.findIndex((list) => list.includes(active));
    const line = lineRefs.current[first];
    if (active === null || !pre || !line) return;
    const top = line.offsetTop;
    if (top < pre.scrollTop || top + line.offsetHeight > pre.scrollTop + pre.clientHeight) {
      pre.scrollTo({top: Math.max(0, top - 16), behavior: 'smooth'});
    }
  }, [active, owners]);

  return (
    <div className={styles.wrapper}>
      <figure className={styles.window}>
        {title && (
          <figcaption className={styles.title}>
            <span>{title}</span>
            {hiddenTotal > 0 && (
              <button type="button" className={styles.showAll} onClick={() => setShowAll(!showAll)}>
                {showAll ? 'Fold again' : 'Show all'}
              </button>
            )}
          </figcaption>
        )}
        <Highlight theme={prismTheme} code={code} language="yaml">
          {({tokens, getLineProps, getTokenProps, style}) => (
            <pre
              ref={codeRef}
              className={styles.code}
              style={{...style, background: 'transparent', maxHeight: height}}>
              {tokens.map((line, index) => {
                if (hidden[index] && !showAll) {
                  return runs[index] > 0 ? (
                    <div
                      key={index}
                      className={
                        owners[index].includes(active) ? `${styles.gap} ${styles.lit}` : styles.gap
                      }>
                      … {runs[index]} {runs[index] === 1 ? 'line' : 'lines'} hidden
                    </div>
                  ) : null;
                }
                const lineProps = getLineProps({line});
                const [first] = owners[index];
                const explained = first !== undefined;
                return (
                  <div
                    key={index}
                    ref={(element) => {
                      lineRefs.current[index] = element;
                    }}
                    {...lineProps}
                    className={[
                      lineProps.className,
                      styles.line,
                      explained && styles.explained,
                      explained && owners[index].includes(active) && styles.lit,
                    ]
                      .filter(Boolean)
                      .join(' ')}
                    onMouseEnter={explained ? () => setActive(first) : undefined}
                    onMouseLeave={explained ? () => setActive(null) : undefined}>
                    {line.map((token, key) => (
                      <span key={key} {...getTokenProps({token})} />
                    ))}
                    {line.length === 0 && '\n'}
                  </div>
                );
              })}
            </pre>
          )}
        </Highlight>
      </figure>
      <ul className={styles.notes}>
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
