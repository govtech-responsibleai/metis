import styles from '../Terminal/styles.module.css';

const STATUS = /^(pass|warn|fail)(\s.*)?$/;
const STATUS_CLASS = {pass: styles.pass, warn: styles.warn, fail: styles.fail};

const RULE = /^\s*[#=]{10,}$/;
const SESSION = /^(\s*SESSION )(\d+\/\d+)(: .*)$/;
const PROGRESS = /^(.*?\s)(━+)(─*)(\s+\d+\/\d+)$/;
const LABEL = /^(\s*)(Selected experiment|Models|Specification|Log|Results|Report):( .*)$/;
const SUMMARY = /^(\s*EVALUATION COMPLETE)(.*)$/;

function OutputLine({text}) {
  if (RULE.test(text)) {
    return <span className={styles.comment}>{text}</span>;
  }
  let m = text.match(SESSION);
  if (m) {
    return (
      <>
        {m[1]}
        <span className={styles.accent}>{m[2]}</span>
        {m[3]}
      </>
    );
  }
  m = text.match(PROGRESS);
  if (m) {
    const done = m[3] === '';
    return (
      <>
        {m[1]}
        <span className={done ? styles.barDone : styles.bar}>{m[2]}</span>
        <span className={styles.barRest}>{m[3]}</span>
        {m[4]}
      </>
    );
  }
  m = text.match(SUMMARY);
  if (m) {
    return (
      <>
        <span className={`${styles.pass} ${styles.strong}`}>{m[1]}</span>
        {m[2]}
      </>
    );
  }
  m = text.match(LABEL);
  if (m) {
    return (
      <>
        {m[1]}
        <span className={styles.comment}>{m[2]}:</span>
        {m[3]}
      </>
    );
  }
  const status = text.match(STATUS);
  if (status) {
    return (
      <>
        <span className={STATUS_CLASS[status[1]]}>{status[1]}</span>
        {status[2]}
      </>
    );
  }
  if (/ is ready\.$/.test(text)) {
    return <span className={styles.pass}>{text}</span>;
  }
  return text;
}

// A command and the output it printed, shown as in a terminal. `pass`, `warn` and `fail` at the
// start of an output line are coloured. Unlike Terminal, the lines are not numbered, because
// output is not something to copy.
export default function TerminalOutput({command, output, label = 'Terminal'}) {
  return (
    <figure className={styles.window}>
      <div className={styles.header}>
        <span>{label}</span>
      </div>
      <pre className={styles.code}>
        <div className={styles.line}>
          <span className={styles.prompt}>$ </span>
          <span className={styles.program}>{command.split(' ')[0]}</span>
          {command.slice(command.split(' ')[0].length)}
        </div>
        {output
          .trim()
          .split('\n')
          .map((line, index) => (
            <div key={index} className={styles.line}>
              <OutputLine text={line} />
            </div>
          ))}
      </pre>
    </figure>
  );
}
