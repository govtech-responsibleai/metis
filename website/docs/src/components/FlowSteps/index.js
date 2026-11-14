import {Children} from 'react';
import styles from './styles.module.css';

export function FlowStep({title, children}) {
  return (
    <div className={styles.step}>
      <div className={styles.title}>{title}</div>
      <div className={styles.body}>{children}</div>
    </div>
  );
}

export default function FlowSteps({children}) {
  const steps = Children.toArray(children);
  return (
    <div className={styles.flow}>
      {steps.map((step, index) => (
        <div key={index} className={styles.item}>
          {index > 0 && (
            <svg className={styles.arrow} viewBox="0 0 16 24" aria-hidden="true">
              <path d="M8 2v18M3 15l5 5 5-5" />
            </svg>
          )}
          {step}
        </div>
      ))}
    </div>
  );
}
