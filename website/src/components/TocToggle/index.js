import {useEffect, useState} from 'react';
import styles from './styles.module.css';

const HIDDEN_CLASS = 'toc-hidden';

// The step headings of the page, such as `## Step 1: ... {#step-1}`.
const STEP_HEADINGS = 'h2[id^="step-"]';

// A heading's title without the controls that StepControls puts into it.
function titleOf(heading) {
  const copy = heading.cloneNode(true);
  copy.querySelectorAll('[data-step-controls]').forEach((controls) => controls.remove());
  return copy.textContent.trim();
}

// How far below the bottom of the progress bar a heading may sit and still count as reached.
const MARGIN = 24;

// The steps of the page, with the index of the one being read. A step is the current one once its
// heading has scrolled up to the bottom of the bars at the top of the window. Before the first
// heading nothing is current, and the index is -1.
function useSteps(enabled) {
  const [steps, setSteps] = useState([]);
  const [current, setCurrent] = useState(-1);

  useEffect(() => {
    if (!enabled) return undefined;
    const headings = Array.from(document.querySelectorAll(STEP_HEADINGS));
    setSteps(headings.map((heading) => ({id: heading.id, title: titleOf(heading)})));

    const update = () => {
      const navbar = document.querySelector('nav.navbar')?.offsetHeight ?? 0;
      const limit = navbar + (document.querySelector(`.${styles.bar}`)?.offsetHeight ?? 0) + MARGIN;
      let index = -1;
      headings.forEach((heading, i) => {
        if (heading.getBoundingClientRect().top <= limit) index = i;
      });
      setCurrent(index);
    };
    update();
    window.addEventListener('scroll', update, {passive: true});
    window.addEventListener('resize', update);
    return () => {
      window.removeEventListener('scroll', update);
      window.removeEventListener('resize', update);
    };
  }, [enabled]);

  return {steps, current};
}

// A row of circles under the navbar: a start circle that scrolls to the top of the page, then one
// for each step. It stands in for the contents list while that list is hidden, because the list
// doubles as a progress indicator. Circles already passed are filled, the current one has a ring,
// and each step's circle links to its step. The start circle is the current one until the reader
// reaches step 1.
function StepProgress() {
  const {steps, current} = useSteps(true);
  if (steps.length === 0) return null;

  const items = [
    {id: 'top', title: 'Back to the top of the page', label: '↑'},
    ...steps.map((step, index) => ({...step, label: index + 1})),
  ];
  const position = current + 1;

  return (
    <nav className={styles.bar} aria-label="Progress through the steps">
      <ol className={styles.steps}>
        {items.map((item, index) => {
          const state = index < position ? styles.done : index === position ? styles.current : '';
          const isTop = item.id === 'top';
          return (
            <li key={item.id} className={`${styles.step} ${state}`}>
              <a
                href={isTop ? '#' : `#${item.id}`}
                onClick={
                  isTop
                    ? (event) => {
                        event.preventDefault();
                        window.scrollTo({top: 0, behavior: 'smooth'});
                      }
                    : undefined
                }
                className={styles.circle}
                title={item.title}
                aria-label={item.title}
                aria-current={index === position ? 'step' : undefined}>
                {item.label}
              </a>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

// A button that hides or shows the table of contents on the right. It puts a class on the page,
// which `custom.css` uses to hide the list. While the list is hidden, a row of circles takes its
// place as a progress bar. The class is removed when the reader leaves the page, so that other
// pages keep their contents.
export default function TocToggle() {
  const [hidden, setHidden] = useState(false);

  useEffect(() => {
    document.documentElement.classList.toggle(HIDDEN_CLASS, hidden);
    return () => document.documentElement.classList.remove(HIDDEN_CLASS);
  }, [hidden]);

  return (
    <>
      <button
        type="button"
        className={styles.toggle}
        aria-pressed={hidden}
        onClick={() => setHidden(!hidden)}>
        {hidden ? 'Show contents' : 'Hide contents'}
      </button>
      {hidden && <StepProgress />}
    </>
  );
}
