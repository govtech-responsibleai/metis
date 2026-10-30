import Link from '@docusaurus/Link';
import useBaseUrl from '@docusaurus/useBaseUrl';
import styles from './styles.module.css';

export function Hero({eyebrow, title, tagline, actions}) {
  return (
    <header className={styles.hero}>
      <div className={styles.heroText}>
        {eyebrow && <p className={styles.heroEyebrow}>{eyebrow}</p>}
        <h1 className={styles.heroTitle}>{title}</h1>
        <p className={styles.heroTagline}>{tagline}</p>
        <div className={styles.heroActions}>
          {actions.map(({label, to, primary}) => (
            <Link
              key={to}
              to={to}
              className={primary ? styles.buttonPrimary : styles.buttonSecondary}>
              {label}
            </Link>
          ))}
        </div>
      </div>
      <img
        className={styles.heroSeal}
        src={useBaseUrl('/img/metis-seal.webp')}
        alt=""
        width="280"
        height="280"
      />
    </header>
  );
}

function RepoLink({repo}) {
  return (
    <a className={styles.repo} href={`https://github.com/govtech-responsibleai/metis/tree/next/${repo}`}>
      <code>{repo}</code>
    </a>
  );
}

function trackPointer(event) {
  const box = event.currentTarget;
  const rect = box.getBoundingClientRect();
  box.style.setProperty('--x', `${event.clientX - rect.left}px`);
  box.style.setProperty('--y', `${event.clientY - rect.top}px`);
}

function Layer({name, purpose, repo, to, support}) {
  return (
    <div
      className={support ? styles.layerSupport : styles.layer}
      data-tone={support ? 'support' : 'layer'}
      onPointerMove={trackPointer}>
      {to ? (
        <Link to={to} className={styles.layerName}>
          {name}
        </Link>
      ) : (
        <span className={styles.layerName}>{name}</span>
      )}
      <span className={styles.layerPurpose}>{purpose}</span>
      <RepoLink repo={repo} />
    </div>
  );
}

function Tool({name, verb, purpose, repo, to, tone}) {
  return (
    <div className={styles.tool} data-tone={tone} onPointerMove={trackPointer}>
      <div className={styles.toolHeader}>
        <Link to={to} className={styles.toolName}>
          {name}
        </Link>
        <RepoLink repo={repo} />
      </div>
      <span className={styles.toolVerb}>{verb}</span>
      <span className={styles.toolPurpose}>{purpose}</span>
    </div>
  );
}

export function PartsMap({rows}) {
  return (
    <div className={styles.map}>
      {rows.map((row) =>
        row.tools ? (
          <div key="tools" className={styles.tools}>
            {row.tools.map((tool) => (
              <Tool key={tool.name} {...tool} />
            ))}
          </div>
        ) : (
          <Layer key={row.name} {...row} />
        ),
      )}
    </div>
  );
}

export function PathSteps({steps}) {
  return (
    <ol className={styles.steps}>
      {steps.map(({title, links}) => (
        <li key={title} className={styles.step}>
          <span className={styles.stepTitle}>{title}</span>
          <span className={styles.stepLinks}>
            {links.map(({label, to}, index) => (
              <span key={to}>
                {index > 0 && <span className={styles.stepOr}> or </span>}
                <Link to={to}>{label}</Link>
              </span>
            ))}
          </span>
        </li>
      ))}
    </ol>
  );
}
