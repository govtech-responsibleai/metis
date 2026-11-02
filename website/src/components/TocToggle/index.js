import {useEffect, useState} from 'react';
import styles from './styles.module.css';

const HIDDEN_CLASS = 'toc-hidden';

// A button that hides or shows the table of contents on the right. It puts a class on the page,
// which `custom.css` uses to hide the list. The class is removed when the reader leaves the page,
// so that other pages keep their contents.
export default function TocToggle() {
  const [hidden, setHidden] = useState(false);

  useEffect(() => {
    document.documentElement.classList.toggle(HIDDEN_CLASS, hidden);
    return () => document.documentElement.classList.remove(HIDDEN_CLASS);
  }, [hidden]);

  return (
    <button
      type="button"
      className={styles.toggle}
      aria-pressed={hidden}
      onClick={() => setHidden(!hidden)}>
      {hidden ? 'Show contents' : 'Hide contents'}
    </button>
  );
}
