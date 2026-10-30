import Link from '@docusaurus/Link';
import {useDocById} from '@docusaurus/plugin-content-docs/client';
import Table from '@site/src/components/Table';
import data from '@site/src/data/graders.json';
import styles from './styles.module.css';

const GRADERS = new Map(
  data.groups.flatMap(({graders}) => graders.map((grader) => [grader.name, grader])),
);

function grader(name) {
  const found = GRADERS.get(name);
  if (!found) {
    throw new Error(`${name} is not in graders.json. Run make generate-grader-docs.`);
  }
  return found;
}

function Breakable({words}) {
  return words.map((word, index) => (
    <span key={index}>
      {index > 0 && <wbr />}
      {word}
    </span>
  ));
}

const TAGS = [
  ['Measure', 'measure'],
  ['Scopes', 'scopes'],
  ['Grader type', 'grader_types'],
  ['Reference type', 'reference_types'],
  ['Judgment form', 'judgment_forms'],
  ['Aggregation', 'aggregations'],
];

export function GraderTags({name}) {
  const {fqn, taxonomy} = grader(name);
  return (
    <div className={styles.card}>
      <code className={styles.fqn}>{fqn}</code>
      <dl className={styles.tags}>
        {TAGS.map(([label, key]) => (
          <div key={key} className={styles.tag}>
            <dt>{label}</dt>
            <dd>
              {[taxonomy[key] ?? 'none'].flat().map((value) => (
                <span key={value} className={styles.chip} data-tone={key}>
                  <Breakable words={value.split(/(?<=_)/)} />
                </span>
              ))}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export function GraderCode({children}) {
  return <div className={styles.code}>{children}</div>;
}

const SOURCE_BASE = 'https://github.com/govtech-responsibleai/metis/blob/next/';

function Markdown({text}) {
  return text
    .split(/(\[[^\]]+\]\([^)]+\)|`[^`]+`)/)
    .map((part, index) => {
      const link = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      if (link) {
        return (
          <a key={index} href={link[2]}>
            {link[1]}
          </a>
        );
      }
      if (/^`[^`]+`$/.test(part)) return <code key={index}>{part.slice(1, -1)}</code>;
      return part;
    });
}

function GraderRow({grader: {name, slug, source_file, adapted_from}}) {
  const page = useDocById(`library/${slug}`);
  return (
    <tr>
      <td>
        <Link to={`/library/${slug}`}>
          <code>
            <Breakable words={name.split(/(?=[A-Z])/)} />
          </code>
        </Link>
        <a className={styles.sourceFile} href={`${SOURCE_BASE}${source_file}`}>
          Source file
        </a>
      </td>
      <td>{page.description}</td>
      <td>
        <Markdown text={adapted_from} />
      </td>
    </tr>
  );
}

export function GraderList() {
  return (
    <Table className={styles.graderTable}>
      <thead>
        <tr>
          <th>Grader</th>
          <th>What it checks</th>
          <th>Adapted from</th>
        </tr>
      </thead>
      <tbody>
        {data.groups.flatMap(({title, graders}) => [
          <tr key={title}>
            <th colSpan={3} scope="colgroup">
              {title}
            </th>
          </tr>,
          ...graders.map((item) => <GraderRow key={item.name} grader={item} />),
        ])}
      </tbody>
    </Table>
  );
}
