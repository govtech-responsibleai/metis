# Use the Wizard in a browser

Use the web client to run a guided Interview in your browser and download the specification for
the Engine.

- The web client uses the Wizard API to process answers and build the download. The
  [API guide](api.md) shows how to use the same features in your own client.
- The browser stores Interview records, original documents, fixture files, and the display
  transcript in its IndexedDB database.

See the [Wizard overview](../wizard.md) for the shared Interview flow and output concepts.

## Start the web client

1. From the repository root, copy the environment template:

   ```bash
   cp .env.example .env
   ```

2. Set `OPENAI_API_KEY`, and `OPENAI_BASE_URL` when you do not use the default OpenAI endpoint.
   `INTERVIEW_MODEL` is optional. The API starts when a setting is missing.
   Without an interview key, Send is grey and shows "Configure API keys to start interview".
   The manual form calls no model, so it needs no key. **Test connection** also works with no key. See the [model guide](../models.md).
3. Install the full workspace, or install the API and web projects separately:

   ```bash
   make install
   # or
   make install-api
   make install-web
   ```

4. Start the API server and the web development server:

   ```bash
   make run-web
   ```

   Each line of output starts with the name of its server, `api` or `web`. Open the address that
   the `web` lines show, for example `http://localhost:5173`. Press Ctrl-C to stop the servers.
   If one server stops on its own, the other one stops too, and the last line names the server
   that stopped first.

   To start the API server only, run `make run-api`.

The API runs at `http://localhost:8001` by default. If the API uses another address, set
`METIS_API_ORIGIN` before you start the web development server. The web development server
forwards `/api` requests to that address.

## Start a guided Interview

The chat is on the left and the Profile is on the right. To change the chat width, drag the line
between them. You can also focus the line and use the arrow keys. Double-click the line to
return to the default width. The browser keeps the width for your next visit.

Above the opening box, choose the mode: **Build Spec only**, or **Build Spec and connect
target**. The bottom row of the box has the documents button, the Perspective control, and
**Capabilities**.

1. Enter a description of the target.
2. Select who the evaluation is for. The Perspective control shows the current Perspective. End
   user is the default, and the control marks it until you open the control. The panel under the
   box shows the guiding question of each Perspective.
3. Optional: select **Capabilities**. The ARC capabilities show in three columns, one for each
   group. Select each capability that you know the target has. On a small screen, the
   capabilities open in a full-width sheet. If you do not open Capabilities, the Wizard treats
   the capabilities as unspecified.
4. Optional: under **Confidence**, select Low, Medium, or High. The value states how complete the
   selection is. If you select capabilities with no confidence, the Wizard uses Low, because the
   selection may be incomplete.
5. The default mode is Build Spec only. In Build Spec and connect target, enter the target
   binding in the **Target connection** card under the box. See
   [Connect the target](#connect-the-target).
6. Select Send, or press Enter. In run mode, the Wizard first checks the binding. It starts the
   Interview only when the binding is valid. This sends all opening values in one request.

The web client gets the opening text, Perspectives, capability catalogue, and document limits from
the API. It keeps the returned Interview state and sends the whole state with each answer. The API
does not save the state.

## Go back to an earlier step

Each review step after Clarify shows **← Back**. Back opens the step before it with its current
content.

- Back from Behaviours shows a form with the Target name, users, description, and detail. A
  required field that you leave empty keeps its current value.
- Continue with no change returns to the later step. The Wizard drafts nothing again. Cancel
  on the Target form returns to Behaviours with no change.
- Back also works while a form is open. The form closes with no change, and the earlier step
  opens.
- Back on Run settings and on the completed Interview opens the Test Case review again. Continue
  completes the Interview again.
- If you change which Behaviours are selected, Continue updates the Test Cases to match. A Test
  Case drops a Behaviour that is no longer selected. A Test Case left with none covers all
  selected Behaviours. A newly selected Behaviour gets Criteria, but no Test Case covers it
  yet: the Test Case review names it, and you choose its Test Cases with a chip or the chat.
- If you change content that later content came from, the Wizard updates the later content
  automatically. It keeps form-written content and unrelated selections.

Clarify has no Back, because it is the first step. To correct the description, say so in your
answer, for example "The target is for staff only." To change the Perspective, capabilities, or
documents, select **New evaluation**. The earlier Interview stays in History.

## Connect the target

In run mode, select **HTTP API** or **Browser**, and enter the required fields. **More options**
holds the optional fields. Each secret field takes the name of an environment variable, never its
value. See [Connect the target](../wizard.md#connect-the-target) for the fields.

Select **Test connection** at the bottom of the card. Each passed check shows with ✓. Each problem
shows in red under the field to fix, such as "APP_API_KEY is not set. Set it in .env." under the
API key variable. Send uses the last test. If you change a field after the test, Send tests the
binding again. If the fields are not valid, Send marks them and does not start the Interview. Fix
the fields, or choose **Build Spec only**.

The API reads your `.env` and reaches the target only when it runs on your computer
(`make run-web` and `make run-api` listen on `127.0.0.1`). An API that other people can reach checks
the fields only, because it would fetch any URL that a user types. Then the card says "This server
checks the fields only". An operator can set `METIS_API_CONNECTION_CHECK=1` or `0` to choose.

To add a binding to a finished Interview, select **Connect target** in the completed message. The
next download includes the binding.

## Select Behaviours

The chat gives short instructions and is always open. Its placeholder text is an example of what
you can type, for example "Add a new feature that describes…". The Profile section **Features /
Expected Behaviours** groups Behaviours under their Features. Each group starts open. Collapse a group to reduce the amount on screen. Each row shows a checkbox,
name, and description. Select its checkbox to include it. Only selected Behaviours receive new
Criteria. Select 5 key Behaviours or fewer. You can select more, and then the review shows a
warning.

The review shows the total selected count. Select **Continue** when the selection is ready. Every
review step moves on with **Continue**.

Every item has the same actions. **+** adds an item: on the section heading it adds a Feature, on
a Feature heading it adds a Behaviour. The pen edits an item. The trash icon deletes it. A form
opens in the Profile with the current text. **Save** applies the exact text that you type, and
**Cancel** returns without a change. When a deletion also removes other items, the Wizard asks
first and names them. A Feature takes its Behaviours and their Criteria. A Behaviour takes its
Criteria and leaves the Test Cases that cover it. A Persona or Scenario takes its Test Cases.
The last Feature, Persona, or Scenario cannot be deleted.

Use the chat for a written change request. The chat can also select Behaviours and set Trials
when you ask it to. Content updates in place. Group expansion is retained. Corrections apply
automatically and keep unrelated content and form-written entries.

The Profile keeps earlier sections available. Criterion review uses the same Feature and Behaviour
groups, with no checkboxes: a selected Behaviour supplies all its Criteria. Select **+** on a
Behaviour to write a Criterion, or ask the chat to suggest one. The Wizard picks a Grader for each
new Criterion. A Criterion edits in its own row. Grader details are in quiet text. Expand a Grader summary to inspect its identifier
and settings, or select the pen on a Criterion to change them. See
[Review and edit Criteria](../wizard.md#review-and-edit-criteria).

Personas have no checkboxes. The Test Case table chooses which Personas run.

The Scenarios step lists each Scenario as a card in the **Scenarios** section. The Wizard
drafts the Scenarios. Check them, then select **Continue**.

On the Test Cases step, the Wizard matches each Scenario that has no Test Case yet. For each
Scenario it picks the Personas that it runs with, usually one or two, and the Behaviours that
each pair really tests. Each pick is one Test Case. Each new Test Case is selected and covers
the picked Behaviours. A Behaviour that no selected Test Case covers is named on the review, and
Continue waits until you cover it. A Scenario that already has a Test Case is not matched again,
so a Test Case that you delete does not come back. To match a Scenario that you add later,
select **Back**, then **Continue** on Scenarios. You can also select **+** on Test Cases, or ask
in the chat.

A Persona or Scenario can have extra details, such as a role or an opening request. They show
under **More information** on its card. In its edit form, each detail is one row with a name box
and a value box, for example **Role** and **Policy analyst**. Select **Add a detail** for another
row, and select **−** to remove one.

The **Test Cases** section is a table. Its columns are Persona, Scenario, Behaviours, Trials, and Files. The
Behaviours cell shows Behaviour IDs, such as EB-1. Hold the pointer on an ID to read the
Behaviour. The row checkbox includes the Test Case in the evaluation. The total under the table
counts only the selected Test Cases and their Trials. Only selected Test Cases go into the
download. Continue with no selected Test Case shows "Select at least one Test Case."

A row shows its values only. To change a Test Case, select the pen. The row then shows the
Persona and Scenario dropdowns, the Behaviour ID chips, the Trials number, and the Files cell. In
the Files cell, open **Add file**. Choose **Upload a file**, or choose an opening document. Select
**Save** to keep the changes. Each pair can have one Test Case only, so a pair
that is in use is not available. The **+** on Test Cases adds a row for a pair that has no Test
Case yet.

## Add documents

1. Select the plus button in the opening message.
2. If a file name does not make the purpose of a document clear, explain it in the same message.
3. Check the reading status of each file. Remove an unreadable file, or keep it without extracted
   text.

Document facts:

- The browser shows the accepted file types and size limits.
- The API extracts text from UTF-8 TXT, Markdown, YAML, JSON, CSV, PDF text layers, and DOCX files.
- The API does not run OCR. Scanned PDFs give no text.
- A Test Case has no files at first. Select its pen to add an opening document or upload a file
  in its **Files** cell.
- The final package contains only files that a Test Case uses.

## Finish and download

1. Answer each Interview screen.
2. Review the final Personas, Scenarios, and Test Cases.
3. Select **Continue** on the final review screen to complete the Interview.
4. On the **Run settings** step, type the user agent, runner agent, and judge model names, or leave
   a field empty to use the environment. These models affect scores, so the specification records
   them. The step takes model names only. Keys stay in `.env`. See the
   [model guide](../models.md).
5. Select **Continue and download**. The browser downloads `YYYYMMDD-HHMMSS-interview.zip`, with
   the models that you set. If you change no field, the download is the same as without the step.

To download the specification again later, select **Download specification** in the document pane.

To finish early, select **Skip interview and download specification**. The Wizard checks whether
the specification is ready. It can ask for more information or a document review before it
completes the Interview. Then the **Run settings** step comes before the download.

The archive contains:

```text
YYYYMMDD-HHMMSS-interview/
├── inputs/
│   └── interview_state.json
└── outputs/
    ├── specification.yaml
    ├── target-binding.yaml   (run mode only)
    └── fixtures/
```

The API compiles the Specification from the same final Interview state that it saves in the
archive. This state keeps document names, extracted text, and limited recent history. The full
display transcript stays in browser storage.

Extract the archive into `experiments/design/`. For an Interview exported on 2026-10-16 at 22:30:45, run:

```bash
metis engine run --input-dir experiments/design/20261016-223045-interview/outputs/
```

The browser sends only the original fixture files that the current Tasks use. The API builds
the archive for that request and does not keep the files.

## Write the Experiment directly

Use **Skip the interview and write it yourself** when you already know the Experiment to run.
This path does not use the Interview and creates no Interview record.

1. On the opening screen, choose the mode. Then select **Skip the interview and write it
   yourself**. The form keeps the mode that you chose. The mode toggle is also at the top of the
   form, so you can change the mode there.
2. Set the Experiment ID and description.
3. Define Personas and Scenarios in their sections.
4. Select **Add test case**. Select one Persona and one Scenario,
   and set its Trial count, graders, and fixtures. Fixtures are files that the target can use in
   each trial. Add more test cases as needed.
5. In **Build Spec and connect target**, fill in the **Target connection** part. It comes after the
   **Specification** part.
   It has the same fields and the same **Test connection** button as the card on the opening
   screen. See [Connect the target](#connect-the-target).
6. Select **Download specification** next to the mode picker. The mode picker and the download
   button stay at the top of the form while you scroll. Extract the download into
   `experiments/design/`.

In run mode, the download needs a valid binding. Download uses the last test. If you change a
field after the test, Download tests the binding again. If the binding is not valid, the
download does not start. The form shows "The target connection is not valid.", the card marks
each field to fix, and the focus moves to the card. There is no way to skip the binding in run
mode. To download without a binding, choose **Build Spec only**.

To add a binding to an earlier spec-only download, open the form again, choose **Build Spec and
Run Evals**, enter the binding, and download again.

**Download specification** stays grey until every field is complete. Select it anyway to find the
fields to fix: the form marks each field that needs a change in red and moves the focus to the
first one.
Each marked field tells you what to change. Every Scenario must be selected in at least one
test case.

Editor rules:

- Select the check button to close a Persona editor. Select the pencil button to open it again.
- Select the plus button in the Personas, Scenarios, or Test cases header to add an item.
- Each test case selects exactly one Persona and one Scenario.
- Multiple test cases can use the same pair with different settings or files.
- Renaming a Persona or Scenario updates its test case references. Removing one
  clears those selections. Select a replacement before you download.
- Each Scenario needs at least one test case.
- The grader list groups the graders by dimension, such as Task and Output Quality or
  Interaction Quality. Graders with no dimension are in the Other group.
- Each grader shows chips for the values that it declares: its grader types, scopes,
  reference types, and judgment forms. Each of these fields has one colour. Hover over a
  chip to see its field.
- The grader search finds text in the name, the description, the dimension, the measure,
  and each chip. For example, search for "session" to find the graders
  that judge a full session.
- Each selected grader shows a settings box below the list. The box has a description and a
  list of settings. The description starts as the grader description, and it becomes the
  description of the check in the download. It must not be empty.
- The settings list shows every setting that the grader accepts in one list. The common
  settings, such as `threshold` and `scope`, come first. The grader's own settings come after
  them. You cannot add other keys.
- Each setting starts from its default. A setting with a fixed list of values, such as `turn`
  or `scope`, has a dropdown. Select **Default** to use the grader default.
- A setting with a red `*` after its name is required. It has no default. Enter a value before you download.
  Otherwise, the download stops and shows "Enter a value." under the setting.
- Enter a number, a list, or an object as JSON. For example, enter `0.7` for `threshold` and
  `["Rates rose in 2024."]` for `ground_truth`. A text setting stays text. An empty value is
  omitted, so the grader uses its default.

The manual export uses `YYYYMMDD-HHMMSS-manual.zip` and a matching root folder. It contains an empty `inputs/` folder, `outputs/specification.yaml`, and the
selected files under `outputs/fixtures/`. It contains no Interview state. In run mode, it also
contains `outputs/target-binding.yaml`, and `outputs/specification.yaml` names the generic runner
and the binding file. This is the same export as an Interview with the same binding.

## Browser storage and current limits

- Unsent drafts are lost on refresh or page closure.
- Edit each Interview in one tab at a time.
- Failed or interrupted replies require a manual retry. Use **Edit reply** to correct the input.
- Browser data belongs to the exact web origin. For example, `http://localhost:5173` and
  `http://127.0.0.1:5173` have separate Interview lists.
- The web client does not provide:
  - hosted or cross-device Interview storage;
  - authentication or multi-user access;
  - source-code or trace analysis; or
  - evaluation execution.

## Development checks

- `make check-web` runs the web checks.
- `make build-web` makes a production build.

The downloaded document stores the grader description and settings on Criteria. Each test case becomes one Task in the YAML. The form retains Task IDs returned
by the backend through later edits.

In the manual form, use the **Metadata (Optional)** list of a Persona or Scenario to add
optional metadata. Enter a unique key and a text value for each row. The
downloaded Specification preserves these values. Remove a row to omit it.
