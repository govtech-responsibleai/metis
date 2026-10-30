# The Runner Contract

**Status:** normative. RFC 2119 keywords (MUST, MUST NOT, SHOULD, MAY) carry
their usual force. This document is a peer of [architecture.md](architecture.md).
The how-to for writing a runner is [guide/engine.md](guide/engine.md), which is
explanatory and cites the invariants below rather than restating them.

**Applies to:** every implementation of `metis.engine.simulation.runner.Runner`,
in this repository or outside it.

## 1. What a runner is for

A runner is the only component that touches the target. It receives one
plain-language action from the user agent, carries it out on whatever transport
the target speaks, and returns an `Observation`: an account of what happened in
which the facts and the runner's own reading are kept apart.

Two principles govern every rule below.

**P1 — Facts are copied, never composed.** `Observation.reply` and
`Observation.promised` are copied by code from what the transport recorded. A
runner that is driven by an LLM may decide *how* to act, but it MUST NOT write
the reply, the session ID or a file's name from memory. The record can then say
the target said exactly what it says it said.

**P2 — Interpretation is labelled.** What the runner thinks happened goes in
`Observation.reading` and nowhere else. The user agent is told that the reading
is an interpretation. A runner MUST NOT judge whether the target's answer is
good, complete, on-topic or safe: that is what graders are for, and a runner
that editorialises puts its opinion into the evidence the evaluation is built
on.

## 2. Definitions and authority

| Term | Meaning | Whose obligation |
| --- | --- | --- |
| **caller** | The `Orchestrator`, which owns the user agent, the scenario and the trial | the turn loop; calling `act` at most once per turn; the `ArtifactLedger` |
| **callee** | The `Runner` implementation | the transport; the `Observation`; recording each file through the ledger |

A question answerable from the scenario definition alone belongs to the caller.
A question answerable only by touching the target belongs to the callee. Whether
`report.pdf` is a fixture this scenario staged is the caller's business; whether
the target accepted it is the callee's.

## 3. Invariants

### I1 — One action, one `act` call

The caller MUST call `act` at most once per action. When `act` raises, the
caller MUST NOT call it again for that action, whatever the exception type: a
raise carries no information the caller may use to conclude that the action was
not delivered. The next decision starts from what the user agent is told about
the failed turn.

How many transport operations a runner performs inside a single `act` call
(retries, polls, uploads) is the runner's own business and is not observable to
the caller. A `Runner` MUST NOT be required to tolerate a re-sent action: a
second `act` call carrying the same action MUST be assumed to deliver it to the
target a second time.

### I2 — Session post-condition

After `act` returns, and after it raises an exception that the trial layer
recovers from, the target session MUST be usable on the next turn.

A runner that knows its session is dead MUST raise rather than return, even
when it holds a perfectly good account of the turn. The account is lost; that
is the accepted cost of never handing the caller a session it cannot use. How a
runner keeps this promise is its own business: the contract states the
post-condition, not the mechanism.

### I3 — Files go through the ledger

The orchestrator owns the trial's `ArtifactLedger` and binds it with
`use_ledger` before `setup`. A runner MUST record every file it sends or
receives through `self.ledger` (`record_upload`, `record_download`,
`record_failure`), stamping `at_simulated_turn` with its own count of `act`
calls from 1. `end_chat` records under the last turn's number. A runner MUST
NOT write a downloaded file anywhere else.

The ledger checks that a download's bytes match its name, never keeps a partial
file, and never overwrites a file already saved. A fixture that is never
uploaded ends the trial as `system_error` with the failure
`fixture_never_uploaded`.

### I4 — A message is quoted, or nothing is sent

Text meant for the target sits between `⟦` and `⟧` in the action. A runner
MUST send only text the action quoted, word for word, and MUST NOT invent a
message. When the action tries to send a message but quotes none, the runner
MUST refuse the submission, send nothing, and return an `Observation` with
`sent_nothing=True`. That turn is not counted, and three in a row end the trial.

## 4. Return or raise

Returning an `Observation` asserts two things: *I have a first-hand account of
this turn*, and *the session is usable next turn* (I2). Raising asserts *I
cannot tell you what happened*.

Severity does not define the line. A turn in which the target answered nothing
is still a return, because the runner watched it happen. A turn that went
perfectly but left the browser page crashed is still a raise, because I2 cannot
be met.

The exception a runner raises decides what happens next:

| Raise | The orchestrator |
| --- | --- |
| `TurnRecoverableError` (or a subclass) or `ResponseTimeoutError` | tells the user agent the turn did not complete, and carries on. A second one in a row raises `ConsecutiveFailureEscalation` |
| `TrialRecoverableError` (or a subclass) | ends the attempt, and the experiment retries the trial |
| `TargetSessionEnded` | ends the trial as `target_exhausted` with a clean record |
| anything else | ends the trial as `system_error` |

A return in which the target replied with an error message MUST NOT be turned
into a raise. The target's unhappiness is content to grade, not a failure of
the runner.

## 5. The channels

One `Observation` carries distinct kinds of report, each with one owner.

| Field | Reports on | Owner |
| --- | --- | --- |
| `reply` | what the target said, or `None` if no reply was shown | the target, copied by code |
| `promised` | file names the reply promised | the target, copied by code |
| `reading` | what the runner thinks happened (`outcome`, `why`, `next_options`) | the runner |
| `observed` | `False` when nobody could check the target's state after the action | the runner |
| `notice` | a problem METIS itself found with the turn, such as a timeout | METIS |
| `submission_unresolved` | a submission never settled, so the target cannot take another | the runner |
| `sent_nothing` | the action quoted no message, so nothing was sent (I4) | the runner |

`observed` is three-state in spirit: a runner that looked and found nothing
reports `observed=True` with an empty `reply`, and a runner that could not look
reports `observed=False`. Reporting that it looked when it did not tells the
user agent a claim about the target that the runner never checked.

## 6. Edge cases

**The reply that is itself an error message.** A target answering "I cannot
process that file" has replied. `reply` carries it and the turn is a return. A
runner that demoted it to a failure would be interpreting (P2).

**`reply` contradicting `reading`.** A reading that disagrees with the reply is
not reconciled by the caller. The two describe different things: one what the
target said, the other what the runner made of it. Reconciling them is a
grader's job.

**A good account of a dead session.** A raise, and the account is lost. I2 is a
post-condition on the session, not on the quality of the report.

**A submission that never settles.** The runner returns with
`submission_unresolved=True`. The target cannot take another message, so the
trial ends as `system_error` after the closing step collects what it can.

**A user agent's repeated message is not a caller-directed retry.** I1 forbids
the *caller* from re-sending an action, but nothing stops the *user agent* from
choosing, as an ordinary next turn, a message that repeats the one that just
failed. That arrives at the runner as a plain `act` call. A runner's own
housekeeping between turns MUST trigger on the fact that a next `act` call
arrived, not on what it contains.

## 7. Conformance

The orchestrator enforces the exception table in section 4 and the
`fixture_never_uploaded` check in I3 at run time. The ledger enforces its byte
check and its no-overwrite rule when a file is recorded. I1, I2 and I4 are
reviewer-enforced: until an executable conformance suite exists for third-party
runners, a new runner is reviewed against this document by hand.
