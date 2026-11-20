import {useEffect, useState} from 'react';
import {createPortal} from 'react-dom';
import styles from './styles.module.css';

const DEFAULT_KEY = 'metis-walkthrough-steps';

const STEP_HEADINGS = 'h2[id^="step-"]';

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

function bodyOf(heading) {
  const body = [];
  for (let el = heading.nextElementSibling; el && el.tagName !== 'H2'; el = el.nextElementSibling) {
    body.push(el);
  }
  return body;
}

export default function StepControls({storageKey} = {}) {
  const key = storageKey || DEFAULT_KEY;
  const [steps, setSteps] = useState([]);
  const [done, setDone] = useState({});

  useEffect(() => {
    const found = Array.from(document.querySelectorAll(STEP_HEADINGS)).map((heading) => {
      const body = bodyOf(heading);

      // Slot at the end of the section body (the primary Done button)
      const bottomSlot = document.createElement('div');
      bottomSlot.className = styles.bottomSlot;
      bottomSlot.setAttribute('data-step-controls', '');
      const lastBodyEl = body[body.length - 1];
      if (lastBodyEl) {
        lastBodyEl.after(bottomSlot);
      } else {
        heading.after(bottomSlot);
      }

      // Slot in the heading (the inline checkbox that appears when collapsed)
      const headingSlot = document.createElement('span');
      headingSlot.className = styles.headingSlot;
      headingSlot.setAttribute('data-step-controls', '');
      heading.setAttribute('data-step-heading', '');
      heading.appendChild(headingSlot);

      return {id: heading.id, title: heading.textContent, heading, bottomSlot, headingSlot};
    });
    setSteps(found);
    const saved = load(key);
    setDone(saved.done ?? {});
    return () => {
      found.forEach(({heading, bottomSlot, headingSlot}) => {
        bottomSlot.remove();
        headingSlot.remove();
        heading.removeAttribute('data-step-heading');
        heading.removeAttribute('data-step-done');
        bodyOf(heading).forEach((el) => el.removeAttribute('data-step-folded'));
      });
    };
  }, [key]);

  useEffect(() => {
    steps.forEach(({id, heading}) => {
      const isDone = Boolean(done[id]);
      heading.toggleAttribute('data-step-done', isDone);
      bodyOf(heading).forEach((el) => el.toggleAttribute('data-step-folded', isDone));
    });
    if (steps.length > 0) save(key, {done});
  }, [steps, done, key]);

  const toggle = (id) => setDone((current) => ({...current, [id]: !current[id]}));

  const checkbox = (id, title, className) => (
    <label className={className}>
      <input
        type="checkbox"
        checked={Boolean(done[id])}
        aria-label={`Mark done: ${title}`}
        onChange={() => toggle(id)}
      />
      Done
    </label>
  );

  return steps.flatMap(({id, title, bottomSlot, headingSlot}) => [
    createPortal(checkbox(id, title, styles.bottomDone), bottomSlot, `${id}-bottom`),
    createPortal(checkbox(id, title, styles.headingDone), headingSlot, `${id}-heading`),
  ]);
}
