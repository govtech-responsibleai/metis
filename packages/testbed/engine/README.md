# METIS Engine cases

These cases run METIS's engine against the toy apps of
[Project Touchstone](https://github.com/govtech-responsibleai/project-touchstone). Each app
can be started with known flaws and keeps a private ledger of what really happened, so its
answer key can say how accurately METIS judged. The apps read verdicts in their own format,
which belongs to no evaluator; `metis-testbed touchstone-verdicts` writes METIS's results in
it.

## SkyDesk Run A

SkyDesk is a toy airline service desk. [skydesk/run-a/](skydesk/run-a/) holds its suite
written as a METIS Specification, the target binding for its HTTP API, and
`touchstone.yaml`, which maps the Specification's criterion and Scenario IDs to the suite's
check and scenario IDs.

1. In a Touchstone checkout, start SkyDesk's seven versions from `apps/skydesk`:
   `uv run skydesk serve-variants`. They listen on ports 8100 to 8106.
2. From the repository root, with METIS's `.env` set (user agent, runner agent and judge
   models, and the Langfuse project SkyDesk traces to), run Run A against each version:

   ```bash
   for port in 8100 8101 8102 8103 8104 8105 8106; do
     SKYDESK_URL=http://127.0.0.1:$port uv run metis engine run --no-tui \
       --input-dir packages/testbed/engine/skydesk/run-a/
   done
   ```

3. Write the runs as verdicts files:

   ```bash
   uv run metis-testbed touchstone-verdicts experiments/execute/skydesk-run-a-*/ \
     --out path/to/verdicts
   ```

4. From Touchstone's `apps/skydesk`, score them with SkyDesk's answer key. Its README
   explains the report.

   ```bash
   uv run skydesk answer-key path/to/verdicts/*.json --ledger-dir ledger --out results/run-a
   ```

Each run holds 12 conversations, three per Scenario, so the seven versions make 84. For a
first check of the setup, set `num_trials: 1` and run two versions.

### How METIS's results become verdicts

A criterion's verdict for a session is `fail` if any of its results failed, `pass` if none
failed and one passed, and `skipped` if every result was skipped. A criterion judge records
"does not apply" as an errored result with its own reason, so an errored result becomes
`n/a` unless its reason is one of METIS's own error messages, listed in
`metis.testbed.touchstone.METIS_ERRORS`; those become `errored`. A Trial that stopped with
`goal_achieved` counts as the simulated customer saying its goal was achieved.

### Grade again in another trace layout

`metis-testbed regrade` grades a run's saved sessions again, offline, with the same graders
and judge. `--layout turn_root` grades the traces as saved. `--layout http_root` first wraps
each trace the way FastAPI's request tracing does, with a request span and an endpoint span
above SkyDesk's turn span. Differences between the two come from the layout; differences
between two `turn_root` passes come from the judge.

```bash
uv run metis-testbed regrade experiments/execute/skydesk-run-a-<time>/ \
  --layout http_root --out path/to/regraded
uv run metis-testbed touchstone-verdicts path/to/regraded --out path/to/verdicts
```
