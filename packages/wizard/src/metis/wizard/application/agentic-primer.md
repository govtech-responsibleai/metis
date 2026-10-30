# How agentic systems go wrong

This is background reading, not a checklist. Nothing tracks which parts of it you used, you
are never asked to cover it, and you must never mention it, quote it, or name its ideas to
the person you are interviewing. It is strictly secondary to what they tell you: someone who
cares only about whether the answers are correct gets an answer-correctness evaluation, and
you do not argue with them about it.

Its only job is to make you curious about things you would not otherwise think to ask.

Two ways to misuse it. The first is reciting it — turning a paragraph below into a question
about a system that plainly does not work that way. A system with one search tool and no
memory does not need to be asked about delegation, credential leakage, or runaway loops, and
asking anyway makes you sound like you are reading from a form. The second is importing its
vocabulary. These are your categories, not theirs. You think *prompt injection*; you ask
whether a document it reads could tell it to do something. You think *blast radius*; you ask
what it can do that somebody would have to undo by hand.

## Why this exists

An agent is not a text generator with a longer prompt. It calls tools, delegates to other
agents, carries state between turns, and takes actions with consequences. Most of what can go
wrong happens on the way to the answer rather than in the answer, and none of it is visible
if you only ever ask about features.

A target owner will describe what their system does. They will rarely volunteer what it does
when a tool times out, because that is not how anyone thinks about their own target. Your
job in the interview is to get at the machinery underneath the description, and your job
afterwards is to turn it into situations that make the machinery show itself.

## How much of it is actually the model's decision

"Agent" covers a wide range, and where a target sits on that range changes what is worth
measuring. The useful question is how much the model's output controls what happens next.

At one end the model writes text and code decides everything else — there is no path to
measure, only an answer. A step up, the model picks a branch: which department, which
template, whether to escalate. Then it picks a function and its arguments. Then it decides
whether to keep going at all, looping until it judges itself done. At the far end one agentic
workflow can start another.

Each step up adds a class of failure the step below cannot have. Routing adds the wrong
branch. Tool calls add the wrong tool and the wrong arguments. Loops add never stopping and
stopping too early. Multi-agent adds everything that happens in a handoff. If you do not know
where the target sits, you do not know which of the paragraphs below are even relevant —
so find out early, in plain terms: does it decide what to do next, or does it just fill in
the text?

## What it can actually do

The sharpest interview question is not what the target is for but what it is able to do. An
ability exists only where an action and the thing that enables it are both present: the
ability to run code is executing plus an interpreter, the ability to search is querying plus
network access, the ability to change a record is writing plus a credential that permits it.
Terminal access with no permission to execute is not an ability. A search API with no network
is not an ability.

This matters because target owners describe purpose, not reach. "It answers policy
questions" tells you nothing about whether it can also read the shared drive, send mail under
the organisation's name, or restart a job. Ask what it is connected to and what those
connections let it do, and you usually learn about half the abilities on this list:

Planning and breaking work into steps. Handing work to other agents. Choosing among tools.
Talking to people, in text or images or voice. Sending communications that formally speak for
the organisation. Committing the organisation to something — a payment, a refund, a booking,
an order. Reading the open internet. Driving a screen the way a person would. Calling APIs
and other machine interfaces. Writing and running code. Creating, changing and deleting files
and records. Changing configuration, credentials, or the resources the target runs on.

Two things are worth noticing about that list. The abilities near the end are the ones people
forget to mention and the ones that make failures expensive. And the worst problems tend not
to live in any single ability but in a pair of them: reading the open internet is survivable,
and writing files is survivable, and doing both means a web page can end up deciding what
gets written. When someone names two abilities, ask yourself what the combination permits
that neither does alone.

## The three ways it breaks

Everything below is one of three things: the agent itself gets it wrong, someone deliberately
makes it get it wrong, or something it depends on fails or lies to it. The distinction is
worth holding onto because target owners can usually imagine the first, rarely think about
the second, and almost never think about the third.

### The agent gets it wrong on its own

**Tool use.** It picks the wrong tool, or the right tool with wrong arguments. It calls a tool
that was never going to help and reports its empty result as an answer. It calls five tools
where one would do, which is slow, expensive, and usually a sign it does not know what it is
doing. Interfaces it has not seen before are worse: it invents plausible parameters and
plausible functions that do not exist.

**Planning.** A plan that is coherent and does not answer what was asked. A plan that answers
what was asked and ignores something it should not have — the check that was skipped, the
approval that was not sought, the irreversible step placed before the verification step. The
plan reads well either way, which is what makes this hard to catch by eye.

**Delegation.** Routing to the wrong subagent, or handling something directly that should have
been routed. Losing context across the handoff, so the second agent re-asks what the user
already said. Passing along a subagent's output without checking it. Breaking work into
steps that do not add up to the original request. And the failure specific to chains: a small
early error that each subsequent agent treats as given, so that by the end it is load-bearing
and invisible.

**Memory and context.** Forgetting a constraint stated three turns ago. Re-asking for
information already given. Carrying a stale constraint into a new request after the goal
changed. Treating an early guess as established fact for the rest of the session. Carrying
something across a boundary it should not cross — one user's details surfacing in another
user's session, or in a context where they have no business being.

**Honesty about actions.** Claiming to have done something it cannot do — sent the email,
queried the live system, saved the file. Reporting partial work as complete. Presenting a
guess with the same confidence as a verified fact. Not flagging that a source was missing.
Answering in a specialised register it is not qualified for — medical, legal, financial — with
the fluency of something that is.

**Not stopping.** Retrying a failing call indefinitely. Two components triggering each other.
A loop that runs up cost or load without ever concluding, because nothing in the design says
when to give up.

### Someone makes it go wrong

**Instructions arriving as data.** Content the agent reads — a document, a web page, a tool
result, a file someone uploaded, something written into its memory earlier — containing text
that reads like an instruction. Whether the agent follows it. This is the one target owners
almost never raise on their own, and the more places a system reads from, the more surfaces it
has. Anything that takes input from outside the room is a surface: a search result, an
attachment, a screen it is looking at.

**Being talked out of its constraints.** A user who reframes, insists, or arrives at the same
request by a different route until the refusal stops holding.

### Something it depends on fails or lies

**Failure and recovery.** The interesting question is not whether something fails but what
happens next. Does it notice? Does it stop, or loop? Does it say what it tried, or produce a
confident answer built on a failed step? Does it tell the user something they can act on, or
just "an error occurred"? Timeouts, rate limits, empty results and partial results all count,
and they behave differently — an empty result is more dangerous than an error, because it
looks like an answer.

**Sources that are wrong rather than absent.** A page that is out of date, a document that was
superseded, a tool that returns something well-formed and false. The agent has no particular
reason to doubt any of them.

## What it costs when it breaks

Not every failure matters equally, and the interview should establish which ones do. Two
questions get most of the way there.

What can it do that cannot be taken back? Sending is irreversible. Paying is irreversible.
Deleting is usually irreversible. Publishing under the organisation's name is irreversible in
the way that matters even after a retraction. Everything reversible is a smaller problem than
it looks, and everything irreversible is a bigger one.

And who is exposed when it goes wrong? Harm to the person in front of it — bad advice acted
on, their data shown to someone else. Harm to people who are not in the room — a decision
applied unevenly across a group, a statement published about someone. Harm to the
organisation — a commitment it did not intend to make, a system taken down, a claim it now
has to stand behind. Target owners will name the first kind readily and need prompting for
the other two.

## What the transcript has to contain

An evaluation reads traces. Anything the target does not record cannot be measured, no matter
how well the criterion is written — if tool calls are not in the trace, no criterion about
tool selection can ever be checked. Worth knowing what gets captured, and worth preferring
criteria that rest on what will actually be there.

## What this means for the interview

Ask about the machinery, not just the features. What can it do. What is it connected to. What
does it do when one of those fails. What does it remember, and for how long. What does it do
without checking first. What happens when the user changes their mind halfway through. What
would somebody have to undo by hand.

Ask in their language. Every paragraph above can be turned into a question that contains none
of its vocabulary, and it should be.

## Behaviours

Machinery statements sit alongside feature statements — *stops after repeated failures and
says what it tried* next to *the refund amount is correct*. Both are things that should be
true; neither is more real than the other.

A behaviour is worth writing when the target could plausibly fail it. Statements that are
true by construction — it cannot send mail, so it will not send the wrong mail — measure
nothing.

## Scenarios

**This matters most and is easiest to forget.** A behaviour about bounded retry is untestable
unless some scenario actually makes a tool fail. A behaviour about carrying context is untestable
unless some scenario spans two subagents or changes direction mid-session. A behaviour about
resisting instructions in content is untestable unless some scenario puts them there. Happy-path
situations produce clean traces with nothing in them to measure, and no amount of well-written
criteria recovers from that.

Build the situation that forces the interesting path. The refund on an order that does not
exist. The question whose documents are behind a search that times out. The request that
changes after the work has started. The document that contains a line telling the agent to do
something else. The request that is one step past what the target is allowed to commit to.
The scenario that can be finished properly or finished fast, but not both.

Where two abilities meet, put a scenario there. That is where the failures nobody anticipated live.

## Personas

Personas do the same job from the other side. Someone who gives information in fragments,
someone who changes their mind, someone who will not answer a clarifying question, someone
who asks for slightly more than they should and then asks again differently — these stress the
machinery in ways a cooperative user never will.
