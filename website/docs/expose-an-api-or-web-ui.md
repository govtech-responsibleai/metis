---
title: Expose an API or web UI
---

METIS simulates a user, so it needs a way to send messages to your application and read the
replies without a person at the keyboard. There are two ways to provide that:

- **An API with an OpenAPI description.** METIS calls the endpoints that the description lists.
  This is the one we recommend, because it is faster and more stable.
- **A web page.** METIS opens the page, signs in with a username and password, and then clicks and
  types like a user. Choose this if users can reach your application only through a web page.

Tell METIS which one you have, and where to find it, in a target connection. See
[Target connection](target-connection.md) for the fields and examples.

## Check the connection

Select **Test connection** on the Target connection card in the browser wizard. It runs a set of
checks against your application with the details you gave, and shows which passed and which
failed.

## Next step

[Set up observability](set-up-observability.md).
