---
title: What you need
---

Prepare your application and Langfuse before you run an evaluation.
You can build a specification before this setup is complete.

## Make your application eval-friendly

An application that METIS can evaluate is **eval-friendly**. METIS needs two things from it: a
way to talk to it, and traces that it can read.

| Part | Requirement |
|---|---|
| [Expose an API or web UI](expose-an-api-or-web-ui.md) | METIS can interact with your application programmatically, through an API or through a web page. |
| [Set up observability](set-up-observability.md) | A Langfuse v4 server, a current Langfuse Client SDK in your application, and traces that follow Langfuse's instrumentation best practices. |

Each page shows how to provide its part, and how to check it.

## Check your environment

When your application is ready, [check your environment](check-environment.md). Confirm that your
keys and install work before your first evaluation.

## Next step

[Expose an API or web UI](expose-an-api-or-web-ui.md).
