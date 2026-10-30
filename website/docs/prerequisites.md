---
title: Pre-requisites
---

Prepare your application and Langfuse before you run an evaluation.
You can build a specification before this setup is complete.

## Connect your application

<p className="draft-note">
  Draft. Write this section when the user simulation work defines the target binding.
</p>

## Connect Langfuse

Your application must send its traces to Langfuse. Group the traces of each trial
under the session ID that the runner returns. The Engine uses this ID to get the
conversation for grading.

Add the Langfuse credentials to `.env`:

```dotenv
LANGFUSE_PUBLIC_KEY=your-public-key
LANGFUSE_SECRET_KEY=your-secret-key
LANGFUSE_BASE_URL=https://your-langfuse-host
```

Make sure that a test conversation shows in Langfuse before you run the graders.

## Check your environment

Run the check before your first evaluation:

```bash
make check-env    # or: metis doctor
```

It confirms that `OPENAI_API_KEY` is set and accepted by the model gateway, that the install
is sound, and that the `LANGFUSE_*` keys work. It prints one line per check, never prints a
key, and exits non-zero if a required check fails. A missing `LANGFUSE_*` variable is a
warning, not a failure: you can still simulate, but you cannot run `metis engine evaluate`.

## Next step

[Build your specification](wizard.md).
