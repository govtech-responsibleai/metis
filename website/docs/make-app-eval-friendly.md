---
title: Make your application eval-friendly
---

METIS needs two things from your application: a way to talk to it, and traces that it can read.
METIS does not read your application's answers from the simulation itself. It reads the traces
that your application sends to Langfuse, so if a trace is missing, or is recorded in an old
format, the graders have nothing to grade. This page shows how to provide both, and how to check
them.

## What makes an application eval-friendly

| Part | Requirement |
|---|---|
| [Expose an API or web UI](#expose-an-api-or-web-ui) | METIS can interact with your application programmatically, through an API or through a web page. |
| [Use Langfuse for observability](#use-langfuse-for-observability) | A Langfuse v4 server, a current Langfuse Client SDK in your application, and traces that follow Langfuse's instrumentation best practices. |

Each part has a section below, with how to check it.

## Expose an API or web UI

METIS simulates a user, so it needs a way to send messages to your application and read the
replies without a person at the keyboard. There are two ways to provide that:

- **An API with an OpenAPI description.** METIS calls the endpoints that the description lists.
  This is the one we recommend, because it is faster and more stable.
- **A web page.** METIS opens the page, signs in with a username and password, and then clicks and
  types like a user. Choose this if users can reach your application only through a web page.

Tell METIS which one you have, and where to find it, in a target connection. See
[Target connection](target-connection.md) for the fields and examples.

To check, select **Test connection** on the Target connection card in the browser wizard. It runs
a set of checks against your application with the details you gave, and shows which passed and
which failed.

## Use Langfuse for observability

METIS reads your application's traces from Langfuse, so your application must record them there.
Three things have to be right: the Langfuse Server that stores the traces, the Langfuse Client SDK
that sends them, and the way you instrument your code.

### Langfuse Server

Use Langfuse v4, self-hosted or Cloud. This is the version of the server, not of the Langfuse Client SDK.

A self-hosted Langfuse v4 server runs in `events_only` mode. In that mode, the server rejects the
legacy ingestion API and the `/api/public/traces`, `/spans`, `/generations` and `/events`
endpoints. It also no longer builds trace-level input, output and attributes for you.

Langfuse Cloud keeps accepting the legacy path until **2026-11-16**. If your application runs on
Cloud and you skip these rules, it breaks on that date, so make the change now.

### Langfuse Client SDK

The Langfuse Client SDK is the library inside your application that sends its traces to the
Langfuse server. Use the Python `langfuse` package at 4.7.0 or later, or the JS/TS `@langfuse/*`
packages at 5.4.0 or later. These versions send traces over OpenTelemetry, which a v4 server
needs.

To check, run `pip show langfuse` (Python) or `npm ls @langfuse/tracing` (JS/TS) in your
application's environment, and upgrade if the version is lower.

### Follow instrumentation best practices

Langfuse describes how to instrument an application in its
[best-practices page](https://langfuse.com/docs/observability/best-practices). Three of its
practices matter most to METIS, because they decide whether the graders can read the conversation:
a root observation for each turn, attributes on every step, and one session ID for the whole
trial. The `propagate_attributes()` call that sets the attributes comes from Langfuse's
[instrumentation guide](https://langfuse.com/docs/observability/sdk/instrumentation).

#### Root observation

Wrap each turn in one enclosing root observation, of type `agent` or `span`. Put the user message
in its `input`, and put the final answer in its `output`. Instrument fully and do not trim: any
grader may read any of it.

To check, search your code for `langfuse.trace(`, `update_trace(` and `set_current_trace_io(`.
A v4 server no longer supports these calls, and they are how legacy code recorded the input and
output of a trace. If you find any, replace them as shown below.

Before, the legacy pattern. It fails on a server in `events_only` mode:

```python
# Legacy. Do not use.
trace = langfuse.trace(
    name="support-agent",
    user_id=user_id,
    session_id=session_id,
    input=user_message,
)
span = trace.span(name="retrieval")
trace.update(output=final_answer)
```

After, the v4 pattern:

```python
from langfuse import get_client, propagate_attributes

langfuse = get_client()


def handle_turn(user_id: str, session_id: str, user_message: str) -> str:
    # Attributes set here are inherited by everything started inside the block.
    with propagate_attributes(
        user_id=user_id,
        session_id=session_id,
        tags=["metis"],
        trace_name="support-agent",
    ):
        # One enclosing root observation per turn.
        with langfuse.start_as_current_observation(
            name="support-agent",
            as_type="agent",
            input={"message": user_message},
        ) as root:
            final_answer = run_agent(user_message)  # your code; its steps nest under root
            root.update(output={"answer": final_answer})
            return final_answer
```

If you use the `@observe` decorator, put `@observe(as_type="agent")` on the function that handles
the whole turn, and make sure it records the user message as its input and the answer as its
output. The examples on this page are Python. For JS/TS, follow the same steps with
[Langfuse's own guide](https://langfuse.com/docs/observability/sdk/instrumentation).

#### Attributes

Propagate `user_id`, `session_id` and `tags` with `propagate_attributes()`, so that every child
step inherits them. The example above does this: `propagate_attributes()` wraps the root
observation, so the attributes are set before any child step starts.

To check, look for the right `userId` and `sessionId` on the root observation and on its child
steps. See [Verify your setup yourself](#verify-your-setup).

#### Session ID

The runner copies the session ID from your application's response, and METIS fetches every
trace that carries that ID. So your application must stamp the same ID on every trace of one
trial, and it must return that ID to the caller. If each turn gets a new ID, METIS finds one
turn instead of the conversation.

---

### Verify your setup yourself (optional) {#verify-your-setup}

This step is optional, and you do it by hand: METIS never runs it for you. It is worth doing
before your first evaluation, because without it a mistake shows up only after a full simulation,
when `metis engine evaluate` cannot find the traces.

The check tests all three Langfuse parts at once: the server, the Langfuse Client SDK and the
instrumentation.

1. Make sure `.env` holds the keys of the Langfuse project that your application sends its traces
   to. METIS reads the traces with the same keys. See [Installation and Setup](install.md#required-to-grade-a-run).
2. Send one test conversation to your application.
3. Ask Langfuse for its root observations. This loads `.env` into your shell first:

   ```bash
   set -a; source .env; set +a
   curl -s -u "$LANGFUSE_PUBLIC_KEY:$LANGFUSE_SECRET_KEY" \
     "$LANGFUSE_BASE_URL/api/public/v2/observations?isRootObservation=true&limit=5"
   ```

The test conversation should appear with:

- `isRootObservation` set to `true`,
- a populated `input` that holds the user message and a populated `output` that holds the answer,
- the right `userId` and `sessionId`.

You can also open the trace in the Langfuse web page and check the same three things. If they all
hold, your application is eval-friendly.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| The root `input` or `output` is empty | The turn is not wrapped in a root observation, or `output` is never set on it | Wrap the turn as shown above and call `update(output=...)` before the block ends. Replace `update_trace()` and `set_current_trace_io()` |
| Child steps show up as separate roots | They run outside the root observation, for example in a thread or task that lost the context | Start the work inside the `with` block, or pass the context to the worker |
| `userId`, `sessionId` or tags are missing | The attributes were set with a removed call, or set after the children started | Use `propagate_attributes()` around the root observation |
| `UnsupportedTraceError`, "recorded before this Langfuse server's v4 upgrade" | The trace was recorded before the server moved to v4 | Run that trial again. METIS still grades your other sessions |
| The session has fewer traces than turns | A framework overwrote the session ID on some of its spans | Compare the `sessionId` of the root and the child steps in the Langfuse web page. Set the session ID after the framework starts its spans, or turn off the framework's own session handling |
| Traces arrive minutes late | An older Langfuse Client SDK | Upgrade the Langfuse Client SDK first. See [Run the graders](run-graders.md#when-traces-are-missing) |

## Next step

[Check your environment](check-environment.md).
