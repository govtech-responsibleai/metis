"""metis.library.graders.demo: example graders built on the shared trace processor (#431).

They show grader authors the full pattern on a real captured session: a taxonomy, the scope's
select and render functions, and ``metis.library.judge.judge`` for a model-based grader. Two are
model-based graders (session and subsession scope) and two are code-based. They are not a catalogue: this sub-package
is not re-exported from ``metis.library.graders``, so the wizard never offers them. A
criterion can still name one by its full path, e.g.
``metis.library.graders.demo.DemoTraceBudgetGrader``.
"""

from ._answer_helpfulness import (
    DemoAnswerHelpfulnessArgs as DemoAnswerHelpfulnessArgs,
)
from ._answer_helpfulness import (
    DemoAnswerHelpfulnessGrader as DemoAnswerHelpfulnessGrader,
)
from ._required_tool import DemoRequiredToolArgs as DemoRequiredToolArgs
from ._required_tool import DemoRequiredToolGrader as DemoRequiredToolGrader
from ._task_completion import DemoTaskCompletionGrader as DemoTaskCompletionGrader
from ._trace_budget import DemoTraceBudgetArgs as DemoTraceBudgetArgs
from ._trace_budget import DemoTraceBudgetGrader as DemoTraceBudgetGrader
