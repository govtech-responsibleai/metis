import {useEffect, useRef, useState} from 'react';
import {createPortal} from 'react-dom';
import {useLocation} from '@docusaurus/router';
import styles from './styles.module.css';

const DEFAULT_KEY = 'metis-walkthrough-steps';

// A step is `## Step 4: ... {#step-4}`, and a sub-step is `### 4c. ... {#step-4c}`.
const SECTION_HEADINGS = 'h2[id^="step-"], h3[id^="step-"]';

function load(key) {
  try {
    return JSON.parse(window.localStorage.getItem(key)) ?? {};
  } catch {
    return {};
  }
}

function save(key, state) {
  try {
    window.localStorage.setItem(key, JSON.stringify(state));
  } catch {}
}

// The elements under a heading, up to the next heading of the same or a higher level. The controls
// that StepControls adds are left out.
function bodyOf(heading) {
  const stops = heading.tagName === 'H2' ? ['H2'] : ['H2', 'H3'];
  const body = [];
  for (let el = heading.nextElementSibling; el && !stops.includes(el.tagName); el = el.nextElementSibling) {
    if (!el.hasAttribute('data-step-controls')) body.push(el);
  }
  return body;
}

function slot(tag, className) {
  const el = document.createElement(tag);
  el.className = className;
  el.setAttribute('data-step-controls', '');
  return el;
}

// Each step and sub-step has an arrow that collapses it. A step also has a Done checkbox at its end,
// which fades the step without moving anything on the page. Done is saved in the browser, and
// collapsing is not: a visit starts with the steps done earlier collapsed, and everything else
// expanded. A done step that is collapsed has its heading struck through.
export default function StepControls({storageKey} = {}) {
  const key = storageKey || DEFAULT_KEY;
  const [sections, setSections] = useState([]);
  const [done, setDone] = useState({});
  const [collapsed, setCollapsed] = useState({});
  const scrollTarget = useRef(null);
  const location = useLocation();

  useEffect(() => {
    const found = Array.from(document.querySelectorAll(SECTION_HEADINGS)).map((heading) => {
      const title = heading.textContent;
      const isStep = heading.tagName === 'H2';

      const arrowSlot = slot('span', styles.arrowSlot);
      heading.prepend(arrowSlot);
      heading.setAttribute('data-step-heading', '');

      if (!isStep) return {id: heading.id, title, heading, isStep, arrowSlot};

      // The tick in the heading, shown once the step is done.
      const tickSlot = slot('span', styles.tickSlot);
      heading.appendChild(tickSlot);

      // The Done checkbox at the end of the step.
      const doneSlot = slot('div', styles.doneSlot);
      const body = bodyOf(heading);
      (body[body.length - 1] ?? heading).after(doneSlot);

      return {id: heading.id, title, heading, isStep, arrowSlot, tickSlot, doneSlot};
    });
    setSections(found);
    const saved = load(key).done ?? {};
    setDone(saved);
    setCollapsed(Object.fromEntries(Object.keys(saved).filter((id) => saved[id]).map((id) => [id, true])));
    return () => {
      found.forEach(({heading, arrowSlot, tickSlot, doneSlot}) => {
        [arrowSlot, tickSlot, doneSlot].forEach((el) => el?.remove());
        heading.removeAttribute('data-step-heading');
        heading.removeAttribute('data-step-done');
        heading.removeAttribute('data-step-collapsed-heading');
        bodyOf(heading).forEach((el) => {
          el.removeAttribute('data-step-collapsed');
          el.removeAttribute('data-step-faded');
        });
      });
    };
  }, [key]);

  useEffect(() => {
    // Clear every mark first, because a sub-step can be hidden by its own arrow or by its step's.
    sections.forEach(({heading, doneSlot}) => {
      bodyOf(heading).forEach((el) => {
        el.removeAttribute('data-step-collapsed');
        el.removeAttribute('data-step-faded');
      });
      doneSlot?.removeAttribute('data-step-collapsed');
    });
    sections.forEach(({id, heading, isStep, doneSlot}) => {
      heading.toggleAttribute('data-step-collapsed-heading', Boolean(collapsed[id]));
      if (collapsed[id]) {
        bodyOf(heading).forEach((el) => el.setAttribute('data-step-collapsed', ''));
        doneSlot?.setAttribute('data-step-collapsed', '');
      }
      if (isStep) {
        heading.toggleAttribute('data-step-done', Boolean(done[id]));
        if (done[id]) bodyOf(heading).forEach((el) => el.setAttribute('data-step-faded', ''));
      }
    });
    if (sections.length > 0) save(key, {done});
    // A link target in a collapsed section was hidden when the browser tried to scroll to it.
    if (scrollTarget.current) {
      scrollTarget.current.scrollIntoView();
      scrollTarget.current = null;
    }
  }, [sections, done, collapsed, key]);

  // Following a link into a collapsed section, such as "step 4c" in step 5, expands every section
  // that holds the target.
  useEffect(() => {
    if (!location.hash || sections.length === 0) return;
    const target = document.getElementById(decodeURIComponent(location.hash.slice(1)));
    if (!target) return;
    const holders = sections.filter(
      ({heading}) => heading === target || bodyOf(heading).some((el) => el.contains(target)),
    );
    if (holders.length === 0) return;
    if (target.closest('[data-step-collapsed]')) scrollTarget.current = target;
    setCollapsed((current) => {
      const next = {...current};
      holders.forEach(({id}) => delete next[id]);
      return next;
    });
  }, [location, sections]);

  const toggleDone = (id) => setDone((current) => ({...current, [id]: !current[id]}));
  const toggleCollapsed = (id) => setCollapsed((current) => ({...current, [id]: !current[id]}));

  return sections.flatMap(({id, title, isStep, arrowSlot, tickSlot, doneSlot}) => {
    const isCollapsed = Boolean(collapsed[id]);
    const portals = [
      createPortal(
        <button
          type="button"
          className={styles.arrow}
          aria-expanded={!isCollapsed}
          aria-label={`${isCollapsed ? 'Expand' : 'Collapse'}: ${title}`}
          onClick={() => toggleCollapsed(id)}>
          <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
            <path d="M6 3.5 10.5 8 6 12.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>,
        arrowSlot,
        `${id}-arrow`,
      ),
    ];
    if (isStep) {
      portals.push(
        createPortal(<span className={styles.tick} aria-label="Done">✓</span>, tickSlot, `${id}-tick`),
        createPortal(
          <label className={styles.done}>
            <input
              type="checkbox"
              checked={Boolean(done[id])}
              aria-label={`Mark done: ${title}`}
              onChange={() => toggleDone(id)}
            />
            Done
          </label>,
          doneSlot,
          `${id}-done`,
        ),
      );
    }
    return portals;
  });
}
