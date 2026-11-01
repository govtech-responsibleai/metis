import {Children, isValidElement, useId, useState} from 'react';
import styles from './styles.module.css';

// One choice inside an OptionSwitch. Only its `label` and children are used.
export function Option({children}) {
  return <>{children}</>;
}

// Shows one of several options at a time, chosen with a segmented switch. The first option is
// selected at first.
export default function OptionSwitch({children}) {
  const options = Children.toArray(children).filter(isValidElement);
  const [selected, setSelected] = useState(0);
  const id = useId();

  return (
    <div className={styles.switch}>
      <div className={styles.buttons} role="tablist">
        {options.map((option, index) => (
          <button
            key={index}
            type="button"
            role="tab"
            id={`${id}-tab-${index}`}
            aria-selected={index === selected}
            aria-controls={`${id}-panel-${index}`}
            className={index === selected ? `${styles.button} ${styles.active}` : styles.button}
            onClick={() => setSelected(index)}
          >
            {option.props.label}
          </button>
        ))}
      </div>
      <div
        className={styles.panel}
        role="tabpanel"
        id={`${id}-panel-${selected}`}
        aria-labelledby={`${id}-tab-${selected}`}
      >
        {options[selected]}
      </div>
    </div>
  );
}
