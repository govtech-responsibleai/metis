import styles from './styles.module.css';

export default function Table({className, children, ...props}) {
  return (
    <div className={styles.wrapper}>
      <table className={[styles.table, className].filter(Boolean).join(' ')} {...props}>
        {children}
      </table>
    </div>
  );
}
