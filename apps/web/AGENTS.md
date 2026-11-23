# metis-web

This is the standalone browser client for the wizard. It talks to `apps/api` through the versioned
REST routes only. It does not import Python packages, read Python files, or read the files of the API store.

The app shell has the Target rail (`TargetRail.tsx`) and Target pages with two tabs
(`TargetPage.tsx`). The Specification tab holds the Interview, its Profile pane, and for a new
Target the opening screen with the manual form. The Experiments tab and the "Start an experiment" button stay
off until the Interview is done. The button opens the experiment dialog (`ExperimentDialog.tsx`). `src/routes.ts` owns every URL: build a path with `paths` and read
the current place with `placeOf`. Do not write a path string in a component. The router is
`wouter` with the browser location. Render a routed component in a test inside
`<Router ssrPath="...">`. The shell reads Targets through `src/targets.ts` only.

The experiment dialog runs the checks of `GET /api/v1/doctor`. It lists only the checks that warn
or fail, and shows one line when every check passes. `startExperiment` in
`src/experiment-start.ts` starts an Experiment in two requests. It reads the `input_dir` of the
Specification, then sends it to `POST /api/v1/engine/simulate`. The
Experiments tab and the All experiments page show the Experiments of
`GET /api/v1/engine/experiments`. Delete on the experiment view deletes the Experiment folder and
its results with `DELETE /api/v1/engine/{experiment_id}`. The All
experiments page shows them with `ExperimentList` (`src/ExperimentList.tsx`). The Experiments tab
shows them with `ExperimentTable` (`src/ExperimentTable.tsx`), which sorts by a column. Only
`SORT_COLUMNS` in `src/experiment-sort.ts` gives the sort rule of a column. The phase and the
progress of a row come from the engine status and events routes, and the last update of a row is
the time of its newest event. Only `experimentState` in `src/experiment-status.ts` changes
them into the state that the app shows.

The experiment view follows one Experiment with `useExperimentWatch` (`src/experiment-watch.ts`).
It reads every event from seq 0 when the page opens, then the new events with `after`, every two
seconds while the run is alive or queued. The server starts the evaluate after a simulate, so the
page never starts one on its own. A queued run shows "Queued" with its
place (`queueText`): Stop is on, and Resume and Delete are off. "Waiting for evaluate" is a
simulate that completed with no evaluate, for example after an API restart, and its Resume starts
the evaluate. `ACTIONS` in `experiment-status.ts` gives the actions that are on in each state, and
`resume` of the state gives the engine step that Resume starts. Polling stops when no run is
alive, so another tab can change the Experiment after the last poll. `startStep` therefore reads
the status again before it starts a step. When the state now needs a different step, or none, it
starts nothing, and the page shows `STALE_STEP` and polls again. When the start gives
`run_in_progress`, a run of the Experiment is alive already, so `startStep` gives no error and the
next poll shows that run.
The web app never sends `regrade` to the evaluate route. `trialRows` in `src/trials.ts`
makes the rows of the Trials tab from the plan of the Specification and the events. It is a pure
function: change it, not the component, when the events change. The Trials tab shows no grades.

The Report tab of an experiment (`ReportTab.tsx`) shows the results of `report.html`. Only
`src/report.ts` reads report.json. `reportPage` changes it into the `ReportPage` view model, and a
component shows that model and never the wire `Report` type. Do not compute an average or a rate
in the browser: `report.ts` copies each number and does only the arithmetic of `report.html`.
`loadReport` changes the answer of the report route into one `ReportLoad` state, which is the only
signal for "evaluate is done" until the app has an experiment store. `experimentScreen` gives the
tab that an experiment opens on and the state of the Report tab control. `ExperimentPage` owns the
load, and `ExperimentView` draws one load state, so a test can render each state.

The Report tab has the layout of `report.html`. `src/report.css` follows `REPORT_CSS` in
`packages/insights/src/metis/insights/_report_styles.py` with the same class names, and makes each
colour from a token of `globals.css`. When the layout of `report.html` changes, change
`ReportTab.tsx` and `report.css` to match. A test case of the Criterion panel moves the page to its
row in the table. A test case of the table opens the trial drawer (`CaseDrawer.tsx`), which is
the drawer of `report.html` inside the `Modal` of `ui.tsx`. `CaseDrawerView` draws one state of
the drawer. `ReportSections` draws one state of the list, the tree and the Criterion panel, so a
test can render each state.

`LoginGate.tsx` wraps the app in `main.tsx`. It reads `GET /api/v1/auth/me` first. With login
off, it shows the app with no login UI. With login on, it shows the login page until the person
has a login session. `responseFor` in `src/transport/api.ts` tells the gate when a request gets
401 `login_required`, so do not handle that status in a component. A component reads the current
user and the logout action with `useLoginSession`, which gives null when login is off. The
browser never reads the login cookie.

The admin page (`AdminPage.tsx`) at `/admin` lists the user accounts, makes one, and resets a
password. Only an admin sees it and the link to it at the foot of the rail. Each other person
gets the not-found view. The API decides who is an admin, from the login session, so the page
sends no token. `adminReducer` holds the state of the page. A new password is only in the
`shown` task, so it goes when the admin closes it or leaves the page.

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

The user adds documents to an Interview in two places: the opening message, and the composer of
an open Interview. Both use `useDocumentIntake` in `src/document-intake.ts`, which admits each
file, reads its text through the extract route, and holds the files until the user sends the
message. `documentsForRequest` makes the `documents` of the start request or the turn request.
The documents of the composer go only with a typed message (`sendText` in `App.tsx`), so the user
says in the same message what the wizard must do with them. `InterviewOperations.send` keeps them
in `outbound.documents` until the wizard accepts the answer. Then the transcript entry keeps
their names in `documents` for display. The opening entry of the transcript keeps the names of
the opening documents in the same way. `src/Documents.tsx` has the plus menu of the composer and
the document chips. The file upload of the Test Case form is a different
control: it adds a file for one Test Case and no document.

The id of an Interview is its Target id and the name of its folders in `evaluations/interviews/`
and `evaluations/specifications/`. `interviewId` makes it from the local time when the user sends
the first message: `YYYYMMDD-HHMMSS-interview-<random>`, the same form as a `metis wizard init` id. The random
part is the five characters of `randomPart`, so two people who start in the same second get different
ids. When the store
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
