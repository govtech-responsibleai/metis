import Pane from './Pane';
import styles from './styles.module.css';

export default function Terminal({command, label = 'Terminal'}) {
  return (
    <figure className={styles.window}>
      <Pane label={label} command={command} />
    </figure>
  );
}
