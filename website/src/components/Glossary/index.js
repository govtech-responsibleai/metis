import Table from '@site/src/components/Table';

import {glossary} from './data';
import Inline from './Inline';

function List({items}) {
  return (
    <ul>
      {items.map((item, index) => (
        <li key={index}>
          <Inline text={item.text} />
          {item.children.length > 0 && <List items={item.children} />}
        </li>
      ))}
    </ul>
  );
}

function TermTable({rows}) {
  return (
    <dl className="glossary-terms">
      {rows.map(([name, definition]) => {
        const term = glossary.find(name);
        return (
          <div key={term.slug} id={term.slug} className="glossary-entry">
            <dt>{name}</dt>
            <dd>
              <Inline text={definition} ownSlug={term.slug} />
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

function PlainTable({header, rows}) {
  return (
    <Table>
      <thead>
        <tr>
          {header.map((cell, index) => (
            <th key={index}>{cell}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, rowIndex) => (
          <tr key={rowIndex}>
            {row.map((cell, cellIndex) => (
              <td key={cellIndex}>
                <Inline text={cell} />
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

function Block({block}) {
  switch (block.type) {
    case 'heading': {
      const Heading = `h${block.level}`;
      return (
        <Heading id={block.id}>
          <Inline text={block.text} />
        </Heading>
      );
    }
    case 'paragraph':
      return (
        <p>
          <Inline text={block.text} />
        </p>
      );
    case 'list':
      return <List items={block.items} />;
    case 'table':
      return block.isTermTable ? <TermTable rows={block.rows} /> : <PlainTable {...block} />;
    default:
      throw new Error(`Glossary: no renderer for a "${block.type}" block`);
  }
}

/** The whole of `GLOSSARY.md`, in the file's order, with an anchor on every term. */
export default function Glossary() {
  return glossary.blocks.map((block, index) => <Block key={index} block={block} />);
}
