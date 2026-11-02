import MDXComponents from '@theme-original/MDXComponents';
import Table from '@site/src/components/Table';
import Terminal from '@site/src/components/Terminal';
import TerminalOutput from '@site/src/components/TerminalOutput';
import OptionSwitch, {Option} from '@site/src/components/OptionSwitch';
import AnnotatedYaml, {YamlHide, YamlNote} from '@site/src/components/AnnotatedYaml';
import AnnotatedTree, {TreeNote} from '@site/src/components/AnnotatedTree';
import SystemDiagram from '@site/src/components/SystemDiagram';
import TocToggle from '@site/src/components/TocToggle';

export default {
  ...MDXComponents,
  table: Table,
  Table,
  Terminal,
  TerminalOutput,
  OptionSwitch,
  Option,
  AnnotatedYaml,
  YamlNote,
  YamlHide,
  AnnotatedTree,
  TreeNote,
  SystemDiagram,
  TocToggle,
};
