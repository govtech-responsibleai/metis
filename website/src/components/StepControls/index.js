import {useEffect, useState} from 'react';
import {createPortal} from 'react-dom';
import styles from './styles.module.css';

const STORAGE_KEY = 'metis-stack-2026-workshop-steps';

// The step headings of the page, such as `## Step 1: ... {#step-1}`.
const STEP_HEADINGS = 'h2[id^="step-"]';

// What the reader ticked and folded before, as {done: {<id>: true}, folded: {<id>: true}}. A
// browser that blocks storage simply starts empty each time.
function load() {
  try {
    return JSON.parse(window.localStorage.getItem(STORAGE_KEY)) ?? {};
  } catch {
    return {};
  }
}

function save(state) {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // Nothing to do: the choices last until the page is closed.
  }
}

// The elements of a step: everything after its heading, up to the next step heading.
function bodyOf(heading) {
  const body = [];
  for (let el = heading.nextElementSibling; el && el.tagName !== 'H2'; el = el.nextElementSibling) {
    body.push(el);
  }
  return body;
}

// Adds a "Done" checkbox and a fold button to each step heading of the page. Ticking a step marks
// it as finished, and folding hides everything under its heading, so that a finished step stops
// taking room. The two are independent. Both are remembered in the browser. The page text is
// rendered by Docusaurus, so the controls are placed into the headings after the page loads, and
// a folded step is marked with a `data-step-folded` attribute that `custom.css` hides.
export default function StepControls() {
  const [steps, setSteps] = useState([]);
  const [done, setDone] = useState({});
  const [folded, setFolded] = useState({});

  // Find the headings, and put an empty slot for the controls at the start of each.
  useEffect(() => {
    const found = Array.from(document.querySelectorAll(STEP_HEADINGS)).map((heading) => {
      const slot = document.createElement('span');
      slot.className = styles.slot;
      slot.setAttribute('data-step-controls', '');
      heading.setAttribute('data-step-heading', '');
      heading.insertBefore(slot, heading.firstChild);
      return {id: heading.id, title: heading.textContent, heading, slot};
    });
    setSteps(found);
    const saved = load();
    setDone(saved.done ?? {});
    setFolded(saved.folded ?? {});
    return () => {
      found.forEach(({heading, slot}) => {
        slot.remove();
        heading.removeAttribute('data-step-heading');
        heading.removeAttribute('data-step-done');
        bodyOf(heading).forEach((el) => el.removeAttribute('data-step-folded'));
      });
    };
  }, []);

  // Show the saved choices on the page, and save them again when they change.
  useEffect(() => {
    steps.forEach(({id, heading}) => {
      heading.toggleAttribute('data-step-done', Boolean(done[id]));
      bodyOf(heading).forEach((el) => el.toggleAttribute('data-step-folded', Boolean(folded[id])));
    });
    if (steps.length > 0) save({done, folded});
  }, [steps, done, folded]);

  const flip = (setter, id) => setter((current) => ({...current, [id]: !current[id]}));

  return steps.map(({id, title, slot}) =>
    createPortal(
      <>
        <label className={styles.done}>
          <input
            type="checkbox"
            checked={Boolean(done[id])}
            aria-label={`Mark done: ${title}`}
            onChange={() => flip(setDone, id)}
          />
          Done
        </label>
        <button
          type="button"
          className={folded[id] ? `${styles.chevron} ${styles.closed}` : styles.chevron}
          aria-expanded={!folded[id]}
          aria-label={`${folded[id] ? 'Show' : 'Fold'} ${title}`}
          title={folded[id] ? 'Show this step' : 'Fold this step'}
          onClick={() => flip(setFolded, id)}>
          ▾
        </button>
      </>,
      slot,
      id,
    ),
  );
}
