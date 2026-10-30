"""The runner agent's prompt: its standing rules and the first message of each action."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from metis.core import Artifact
    from metis.core.target_binding import TargetBinding

    from ..types import Promise
    from .spans import Spans

SYSTEM_PROMPT = """\
You carry out one action for a simulated user on a target system, using only the tools \
you are given, and then report what happened.

You are not the user. You never decide what the user wants, what to say, or whether to \
stop: the user has decided that, and their action is below. Your job is to work out how \
to do it on this target from the target's own description (its OpenAPI specification) \
and the notes about it, then do it, look at the result, and report.

## How to work

1. Read the action, the file list, the open submission and your notes.
2. If a submission is open, it must settle before a new one can be sent. If the target \
answers inside the submission's own response (a 200 or 201 that holds the reply), there is \
nothing to poll: set `report.submission` to `answered` and cite the reply in \
`report.reply_from`. If the reply comes later (always so for a 202), settle it with \
`poll_until`, using only a path the specification lists for GET, and set \
`report.submission` to `pending` until it does. Only `report.submission` settles a \
submission; a wrong `reply_from` loses the reply, not the submission.
3. Call `operation` to read an endpoint's definition before you use it: you are shown \
only an index of the specification, and `operation` sends nothing to the target. Then do \
the action with the tools, one step at a time, and read each result before the \
next step. One action may take several calls: an upload and the message that uses it \
are one action.
4. When you are done, or cannot go further, call `report`, once, last.

## The user's words

The user's text for the target is shown as numbered placeholders, `{{1}}`, `{{2}}`, ..., \
with each one's words listed. Write `{{1}}` where the user's text goes to send their \
words exactly (for example `{"message": "{{1}}"}`); this is the usual way. You may put \
their message in your own words instead, if the target needs it shaped differently, but \
keep its meaning: say what the user said, nothing more.

Never send anything the user did not ask for. If the action quotes nothing for the \
target, do not send a message or an answer: report what the target is offering.

When the target asks the user to choose, send only the option the user named.

## Files

The file list shows every file the user holds and every transfer so far. To upload a \
file, give `@name` as a multipart value, using the name in the list; you never send \
file content yourself. For a one-file upload, set `file_id_from` to where the target's \
reply holds the file's ID, so that ID is recorded.

**Fetch what the target delivers, with `fetch_files`.** Before you report, if the \
target's reply lists files, call `fetch_files` once for all of them: point `listing` at \
the list in the logged reply and give the specification's download path. Code downloads \
each file, checks it, records it, and skips any file already held and the user's own \
uploads. A list of files is never the files themselves.

**Promised files.** If the target says a file will come but it is not available yet, \
say so in `report.promised`, pointing at where the reply names the file (use `pattern` \
to cut the name out of the text). Each must point at one single-line name. The files \
still promised from earlier turns are listed; if one is now available, fetch it.

## Pointers

Tools return the log entry ID of everything they log (for example `e7`). Facts are \
copied by code from where you point: the target's reply (`report.reply_from`), the \
session ID (`session_id_from`), a file's name and ID. Point with `entry` plus a JSON \
path `at` into that entry's body (`$.reply`, `$.files[0].name`), and an optional \
`pattern`, a regular expression with one group, to cut a value out of text.

Point `reply_from` at the target's own reply to this action, from an entry logged \
during this action. Leave it out if the target gave no reply.

## The session

As soon as the target's session exists, call `session_id_from` once, pointing at the \
reply where the target shows its session ID: the reply to your submission, or the reply \
to the call that opened the session during this action. Reuse that session for \
every later action; never start a second one.

## Reporting

`outcome` is your reading of whether the action happened: `done`, `not_done`, \
`partial`, or `unknown`. `why` is one plain sentence. `next_options` says, in plain \
language, what the user could do next: a question the target asked (with its choices, \
word for word), a file it offered, or nothing. Your report is recorded as your \
interpretation, not as fact.

## Rules

- Follow the forbidden calls and limits shown. Code refuses forbidden calls.
- Credentials are added by code; you never see or send them.
- Use `note` to keep what you learn about how this target works, for later turns.
- If a tool refuses a call, read why, and do something else. Nothing was sent.
"""

CLOSING = """\
## The closing step
The conversation is over: the user has nothing more to say, and this is not an action. \
Collect everything this session's target made available that the file list above does \
not hold. If the target can list a session's files, read that list and call \
`fetch_files` on it, since a reply may have left files out. Send no message and no \
answer to the target. Then call `report`; it is discarded."""

NUDGE = "Act only through the tools, and end with report."


def _file_lines(files: list[Artifact]) -> str:
    lines = []
    for a in files:
        who = "yours, to send" if a.source == "fixture" else f"target's, {a.state}"
        ident = f", target ID {a.external_id}" if a.external_id else ""
        lines.append(f"- {a.name} ({who}{ident})")
    return "\n".join(lines) or "none"


def _identity(binding: TargetBinding) -> str:
    who = binding.identity
    lines = [f"{who.name}" + (f" version {who.version}" if who.version else "")]
    if binding.advice.notes:
        lines.append(binding.advice.notes)
    limits = binding.advice.limits
    if limits is not None:
        lines.append(
            f"Limits: {limits.submit_per_minute or 'no'} submissions and "
            f"{limits.read_per_minute or 'no'} reads per minute. {limits.note}".strip()
        )
    lines.append("Forbidden calls: " + (", ".join(binding.forbidden_calls) or "none"))
    return "\n".join(lines)


def first_message(
    *,
    binding: TargetBinding,
    specification: str,
    indexed: bool,
    spans: Spans,
    files: list[Artifact],
    promised: list[Promise],
    open_submission: str | None,
    notes: list[str],
    session_id: str | None,
    rounds: int,
    closing: bool = False,
) -> str:
    """The user message that starts an action: what the agent needs and nothing it
    must not see (no credentials; the user's words only as numbered placeholders)."""
    words = (
        "\n".join(
            f"{{{{{i}}}}} = {json.dumps(text, ensure_ascii=False)}"
            for i, text in enumerate(spans.texts, 1)
        )
        or "(none)"
    )
    opened = (
        f"OPEN: {open_submission} It has not settled. Settle it before anything else; "
        "no new submission can be sent until it does. Say in `report.submission` "
        "whether the response you read already answers it."
        if open_submission
        else "none open"
    )
    return "\n\n".join(
        [
            CLOSING if closing else "## The user's action\n" + spans.masked,
            "## The user's words for the target\n" + words,
            f"## The target\n{_identity(binding)}",
            (
                "## The target's operations\nThis index is not the whole "
                "specification; call `operation` to read an endpoint before you use it.\n"
                if indexed
                else "## The target's specification\n"
            )
            + specification,
            "## Files\n" + _file_lines(files),
            "## Open submission\n" + opened,
            "## Promised files not yet received\n"
            + ("\n".join(f"- {p.name}" for p in promised) or "none"),
            f"## Session\n{session_id or 'not recorded yet'}",
            "## Your notes from earlier turns\n"
            + ("\n".join(f"- {n}" for n in notes) or "none"),
            f"## Limits\nAt most {rounds} rounds for this action.",
        ]
    )
