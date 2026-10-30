# metis-web

This is the standalone browser client for the wizard. It talks to `apps/api` through the versioned
REST routes only. It does not import Python packages, read Python files, or depend on API storage.

The browser owns local Interview records and the display transcript in IndexedDB. The JSON
`InterviewState` is sent back to the API unchanged; browser IDs, timestamps, and transcript entries
never enter that state.

The client has two authoring paths. The Interview is the guided path. The manual form
(`ManualForm.tsx`, with its pure logic in `manual.ts` and its file rules in `fixture-policy.ts`) is
the direct path for a user who already knows the graders to run. Keep the manual form flat: do not
show Feature, Behaviour, or Criterion. It builds a `Specification` in the browser and sends it to the
existing package route, so it needs no new route and no Interview record.
`docs/guide/wizard/web.md` describes it for the user.

The manual form builds the complete `Specification` for `specification.yaml`. Both execution
and reporting use that document. Compile assigns IDs to new Tasks. Retain the returned IDs
for later edits and packaging. Grader settings are stored on Criteria in the exported Specification.

Render requests by their discriminator and supplied fields. Do not derive stages, apply patches, or
recreate wizard validation rules in TypeScript. Regenerate `src/generated/api.ts` from FastAPI's
runtime OpenAPI document with `npm run generate:api`; `npm run check:api` fails when the committed
module is stale.

Useful commands:

```bash
npm install
npm run dev          # use a separate `PORT=8001 uv run metis-api` process
                     # `make run-web` at the repository root starts this server and the API
npm run format:check
npm run typecheck
npm test
npm run build
npm run generate:api # update the committed OpenAPI types
npm run check:api
```
