# metis-web

This is the standalone browser client for the wizard. It talks to `apps/api` through the versioned
REST routes only. It does not import Python packages, read Python files, or read the files of the API store.

The app shell has the Target rail (`TargetRail.tsx`) and Target pages with two tabs
(`TargetPage.tsx`). The Specification tab holds the Interview, its Profile pane, and for a new
Target the opening screen with the manual form. The Experiments tab and the Run button stay off
until the Interview is done. `src/routes.ts` owns every URL: build a path with `paths` and read
the current place with `placeOf`. Do not write a path string in a component. The router is
`wouter` with the browser location. Render a routed component in a test inside
`<Router ssrPath="...">`. The shell reads Targets through `src/targets.ts` only.

The YAML view of the Profile pane sends `exportedSpecification(state)` (`src/export.ts`) to the
compile route. That function mirrors the export steps of the package route, so the YAML matches
the download. Change it when those steps change.

The browser saves Interview records, their files, and the display transcript through the store
routes of `apps/api` (`src/storage/repository.ts`). The browser keeps no copy. The JSON
`InterviewState` is sent back to the API unchanged; browser IDs, timestamps, and transcript entries
never enter that state.

Every file that enters the app goes through `admitFiles` in `src/fixture-policy.ts`. It returns
`AdmittedFile` values, and `addFixtures` and `InterviewOperations.send` accept only those. A file is
never replaced by name. A new file whose name is taken gets ` (n)` before its extension.
`fixtureNameIdentity` decides when two names are the same. Give `admitFiles` every file of the
Interview or library, and the files that wait to be sent in the same input. `App.tsx` gives the
Conversation upload controls this rule through `UploadContext`.

The id of an Interview is the `target_id` in the store routes and the name of its folder in
`experiments/design/`. The store saves the whole Interview record, including its Specification.
`interviewId` makes it from the local time when the user sends the first message:
`YYYYMMDD-HHMMSS-interview`, the same name as a `metis wizard init` folder. When the store
gives 409 `target_exists` on the first save, `putNew` saves again as `-2`, `-3`, and so on.

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

Colours, type, status themes, and dark mode follow [the design guide](../../docs/design.md).
Use the tokens in `src/globals.css`. Do not write a colour value directly in a component.

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
