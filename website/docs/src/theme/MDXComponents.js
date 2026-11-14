import MDXComponents from '@theme-original/MDXComponents';
import Table from '@site/docs/src/components/Table';
import Terminal from '@site/docs/src/components/Terminal';
import TerminalOutput from '@site/docs/src/components/TerminalOutput';
import OptionSwitch, {Option} from '@site/docs/src/components/OptionSwitch';
import AnnotatedYaml, {YamlHide, YamlNote} from '@site/docs/src/components/AnnotatedYaml';
import AnnotatedTree, {TreeNote} from '@site/docs/src/components/AnnotatedTree';
import SystemDiagram from '@site/docs/src/components/SystemDiagram';
import StepControls from '@site/docs/src/components/StepControls';
import TocToggle from '@site/docs/src/components/TocToggle';
import Term from '@site/docs/src/components/Term';

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
  StepControls,
  TocToggle,
  Term,
};
