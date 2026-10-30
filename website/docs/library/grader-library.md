---
title: Grader library
slug: /library
description: Every library grader, what each one checks, and the open-source prompt that each one adapts.
---

import {GraderList} from '@site/src/components/Graders';

METIS graders assess a recorded session against one criterion. Each grader measures one
attribute of agent quality and gives a score. The grader's judgment form decides the form
of that score: every grader in the library today is `binary`, so it scores 0 or 1. When the
event that the criterion looks for does not happen in the session, the result is errored and
has no score.

To learn how the Wizard uses the library, which settings a grader takes, and how a grader turns
a session into scores, see [How graders work](how-graders-work.md).

METIS adapts battle-tested graders from other evaluation packages. It copies the upstream
prompt wording that fits the measure and keeps its own scoring rules. A grader marked METIS
uses a rubric written for METIS. Each "Adapted from" link goes to the upstream file at the
commit that METIS copied. For the licence of each upstream package, see
[EXTERNAL_SOURCES.md](https://github.com/govtech-responsibleai/metis/blob/next/packages/library/src/metis/library/EXTERNAL_SOURCES.md).

Select a grader to see its settings, an example criterion, how it is judged, and its limits.

<GraderList />
