import {useLocation} from '@docusaurus/router';
import useBrokenLinks from '@docusaurus/useBrokenLinks';
import Table from '@site/docs/src/components/Table';

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

/**
 * One term. Docusaurus checks a link's anchor against the ids that components register, so the
 * entry registers its own. Without it, the build cannot tell a link to `/glossary#trial` from a
 * link to a term that no longer exists.
 */
function Entry({term, name, children}) {
  useBrokenLinks().collectAnchor(term.slug);
  // The browser's `:target` does not update when the site changes the address without a page load,
  // as a link from another docs page does, so the entry reads the address from the router.
  const targeted = useLocation().hash === `#${term.slug}`;
  return (
    <div id={term.slug} className={targeted ? 'glossary-entry glossary-entry--targeted' : 'glossary-entry'}>
      <dt>{name}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function SectionHeading({block}) {
  useBrokenLinks().collectAnchor(block.id);
  const Heading = `h${block.level}`;
  return (
    <Heading id={block.id}>
      <Inline text={block.text} />
    </Heading>
  );
}

function TermTable({rows}) {
  return (
    <dl className="glossary-terms">
      {rows.map(([name, definition]) => {
        const term = glossary.find(name);
        return (
          <Entry key={term.slug} term={term} name={name}>
            <Inline text={definition} ownSlug={term.slug} />
          </Entry>
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
    case 'heading':
      return <SectionHeading block={block} />;
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
