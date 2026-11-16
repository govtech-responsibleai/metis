import CodeBlock from '@theme-original/CodeBlock';
import Terminal from '@site/src/components/Terminal';

const SHELL_LANGUAGES = new Set(['bash', 'sh', 'shell', 'zsh']);

function languageOf({language, className = ''}) {
  return language ?? className.match(/language-(\w+)/)?.[1];
}

export default function CodeBlockWrapper(props) {
  if (SHELL_LANGUAGES.has(languageOf(props)) && typeof props.children === 'string') {
    return <Terminal command={props.children} />;
  }
  return <CodeBlock {...props} />;
}
