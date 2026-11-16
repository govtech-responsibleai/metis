import {useState} from 'react';
import styles from './styles.module.css';

function CopyButton({text}) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <button type="button" className={styles.copy} onClick={copy} aria-label="Copy commands">
      {copied ? (
        <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 8.5l3 3 6-7" /></svg>
      ) : (
        <svg viewBox="0 0 16 16" aria-hidden="true">
          <rect x="5.5" y="5.5" width="8" height="8" rx="1.5" />
          <path d="M10.5 3.5v-.5a1 1 0 0 0-1-1h-6a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h.5" />
        </svg>
      )}
    </button>
  );
}

function Line({text}) {
  if (text.trimStart().startsWith('#')) {
    return <span className={styles.comment}>{text}</span>;
  }
  const [, indent, program, rest] = text.match(/^(\s*)(\S*)(.*)$/);
  return (
    <>
      {indent}
      <span className={styles.program}>{program}</span>
      {rest}
    </>
  );
}

export default function Pane({label, command}) {
  const text = command.trim();
  return (
    <div>
      <div className={styles.header}>
        <span>{label}</span>
        <CopyButton text={text} />
      </div>
      <pre className={styles.code}>
        {text.split('\n').map((line, index) => (
          <div key={index} className={styles.line}>
            <span className={styles.lineNumber}>{index + 1}</span>
            <Line text={line} />
          </div>
        ))}
      </pre>
    </div>
  );
}
