---
title: Check your environment
---

Run the check before your first evaluation:

```bash
make check-env    # or: metis doctor
```

It confirms that `OPENAI_API_KEY` is set and accepted by the model gateway, that the install
is sound, and that the `LANGFUSE_*` keys work. It prints one line per check, never prints a
key, and exits non-zero if a required check fails. A missing `LANGFUSE_*` variable is a
warning, not a failure: you can still simulate, but you cannot run `metis engine evaluate`.

If the Langfuse check fails, see
[Verify your setup yourself](make-app-eval-friendly.md#verify-your-setup).

## Next step

[Build your specification](wizard.md).
