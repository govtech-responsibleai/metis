# Use the Wizard CLI

The CLI runs the Interview in a terminal and writes the specification to local files. It does not
need the API server.

- It saves the Interview state after each turn. You can close the terminal and resume later.
- It accepts documents when the Interview starts. See [Add documents](#add-documents).
- It offers End user, Engineer, Compliance, and Security Perspectives.

See the [Wizard overview](../wizard.md) for the shared Interview flow and output concepts.

## Requirements

- Python 3.11 or later
- [uv](https://docs.astral.sh/uv/)
- GNU Make
- An OpenAI-compatible model provider

## Set up

1. From the repository root, install the workspace or only the Wizard package:

   ```bash
   make install
   # or
   make install-wizard
   ```

2. Copy the example environment file:

   ```bash
   cp .env.example .env
   ```

3. Add your provider values:

   | Variable | Required | Purpose |
   |---|---|---|
   | `OPENAI_API_KEY` | Yes | API key of the shared gateway. `INTERVIEW_API_KEY` overrides it for the Interview. |
   | `OPENAI_BASE_URL` | No | Full OpenAI-compatible provider endpoint. Unset uses the default OpenAI endpoint. |
   | `DEFAULT_MODEL` | No | Model of every chat role. Unset uses `gpt-6-luna`. |
   | `INTERVIEW_MODEL` | No | Interview model name. Unset uses `DEFAULT_MODEL`. |
   | `METIS_INTERNAL_LANGFUSE_PUBLIC_KEY`, `METIS_INTERNAL_LANGFUSE_SECRET_KEY`, `METIS_INTERNAL_LANGFUSE_BASE_URL` | No | Tracing of the Interview model calls to the METIS-internal Langfuse. Tracing is off unless all three are set. The wizard does not use the `LANGFUSE_*` variables, which name the Langfuse of the system under test. |

   An environment variable has priority over the value in `.env`. The command reads one `.env`
   file and prints its path. See the [model guide](../models.md) for the search and the
   variables of each role. When the run ends, the CLI lists the models that the run needs, where
   each one comes from, and whether its key is set. To change a model, set `USER_AGENT_MODEL` or
   `JUDGE_MODEL` in `.env`, or edit `specification.yaml`.

4. Verify the command:

   ```bash
   metis wizard init --help
   ```

   The package also installs the standalone `metis-wizard` command.

## Start an Interview

The steps below give the typed text menus, which the CLI uses when input or output is redirected.
In an interactive terminal, each question is a list that you answer with the arrow keys, Space,
Enter, Esc, and Tab. See [Use the keys in a terminal](#use-the-keys-in-a-terminal).

1. Start the Interview:

   ```bash
   metis wizard init
   ```

2. The Wizard asks you to describe the target. Give a plain description, for example
   "A research assistant that answers questions from internal documents and cites each source."
   You can also give the description as an argument. Then the Wizard does not ask for it:

   ```bash
   metis wizard init "A research assistant that cites each source."
   ```

3. Select a Perspective. Read its guiding question to choose the point of view.
4. Choose the mode: `1` to build a Specification only, or `2` to build it and run evals. In run
   mode, enter the target binding values. See [Connect the target](#connect-the-target).
5. The CLI shows the fixed ARC capability catalogue. Select known capabilities by number, name, or
   ID, separated by commas. Enter a blank line when you know none. Enter `skip` to omit
   capability evidence. Skipped evidence stays unspecified.
6. If you supply capabilities, enter one confidence value: `low`, `medium`, or `high`. The value
   states how complete the full selection is.
7. Answer the clarification questions.
8. Review the Features, Behaviours, Criteria, Personas, Scenarios, and Test Cases that the Wizard drafts.

Behaviour review groups items by Feature and shows selected counts. Select by number or by the
shown action key. Every review step moves on with **Continue**.

Each item has three actions with complete labels. **Add** (for example "Add a Behaviour to
Answer quality") opens a form under a heading. **Edit** opens a form with the current text.
**Delete** removes the item. The Wizard uses the exact text that you type in a form. When a
deletion also removes other items, the CLI names them and asks `Continue? [y/N]` first. For
example, a Feature takes its Behaviours and their Criteria, and a Persona takes its Test Cases.

The Wizard drafts the Scenarios. For each Scenario it picks the Personas that it runs with,
usually one or two, and the Behaviours that it really tests. It makes one selected Test Case
for each Persona pick, covering the picked Behaviours. A Behaviour that no selected Test Case
covers is named on the review. A Persona or Scenario that you add with a
form gets no Test Case by itself: add one with **Add a Test Case** or ask in the chat. A Test
Case that you delete does not come back. Select **Include** on a Test Case to clear
or select it. Only selected Test Cases count in the total and go into `specification.yaml`.

A Test Case form shows numbered Personas, Scenarios, Behaviours, and Files. Type a number to
choose. For Behaviours and Files, type several numbers separated by commas. Each Persona and
Scenario pair can have one Test Case only. Persona and Scenario forms have a **More information**
field for details such as a role or an opening request. Type one detail per line as
`name: value`, for example `Role: Policy analyst`, then a blank line to finish.

In a form field, press Enter to keep the current value. Enter `-` to clear an optional field. A
required field asks again until you type a value. In **More information**, a blank first line
keeps the current details, and `-` removes them all.

Enter `/feedback` to give a written change request for the review. The chat can also select
Behaviours and set Trials when you ask it to. Clear corrections update the content automatically.
Form-written content and unrelated selections are preserved. Enter `/cancel` in a form field to
return without saving, or `/back` to close the form and go to the step before.

## Use the keys in a terminal

When the CLI runs in an interactive terminal, each question is a list that you move through with
the arrow keys. A grey hint line under the list shows only the keys that the highlighted row
accepts, for example `Esc back | ↑↓ move | Space select | Enter Continue | Tab feedback`.
When the input or the output is redirected, or `TERM` is `dumb`, the CLI uses the typed text
menus that the sections above describe.

### Opening questions

`init` starts with a welcome box, which has a double cyan border and a centred title. Each opening question has its own header panel, in the same
style as the Interview steps: Your product, Perspective, Mode, and Capabilities. The Perspective list shows the guiding question of the highlighted Perspective. Press Enter to
choose. Then the mode, the binding source, and the binding fields come in turn. Press Esc to go
to the question before, with the answer that you gave kept. For example, Esc on the mode asks
the Perspective again. In the capability list, press Space to select a capability, then Enter on
**Continue**, or Enter on **Skip** to leave the capabilities unspecified. Esc on the confidence
asks the capabilities again with your selection kept.

### Review screens

Each review is one list. Each item is one row under its heading, with its text in grey under it.
The keys select, open details, give feedback, go back, and continue.

- Press Space on a row with a checkbox to select or clear it. The total beside **Continue**
  changes at once. Press Enter to send the changes. Only the rows that you changed are sent.
- Press Enter with no changes to continue.
- Press the right arrow to open the details of a row, for example the Grader of a Criterion.
  Press the left arrow to close them. The hint shows `→ details` only for a row that has them.
- The **Feedback** line is under **Back** and **Continue**, with an example in grey. Press Tab to
  write in it, and the list stays on the screen while you type. Press Enter to send it, or Esc
  or Tab to return to the list. Use feedback to add, change, or delete an item, for example
  "Delete the second criterion of EB-1".
- Press Esc on the list to go back to the step before.

The keys do not add, edit, or delete items. To change an item with a typed form, use the web
client, or run the CLI with redirected input, which shows the numbered **Add**, **Edit**, and
**Delete** actions.

The Test Case review is a table with Persona, Scenario, Behaviours, Trials, and Files columns.
Press Space to include or clear a Test Case. To change its Behaviours, Trials, or Files, give
feedback. When the terminal is too narrow for all the columns, each row takes two lines: Persona
and Scenario on the first, and the other columns in grey under them.

### Forms

A form opens when the Wizard asks for missing details. A dropdown is a list, and a field that takes several values is a list of checkboxes. A text field
shows its current value, so Enter keeps it. A choice that would make a Persona and Scenario pair
that another Test Case uses is shown as unavailable. In a form that you can cancel, Esc returns
without saving. In a form that you cannot cancel, for example the form that asks for missing
Target details, Esc on a later field asks the field before, and Esc on the first field goes back
to the step before.

## Go back to an earlier step

Each review step after Clarify has a **← Back** choice. Select its number to open the step
before it with its current content.

- Back from Behaviours shows the Target name, users, description, and detail. Press Enter to
  keep a value, or type a new value. A required field that you leave empty keeps its current
  value.
- Continue with no change returns to the later step. The Wizard drafts nothing again. Enter
  `/cancel` in the Target form to return to Behaviours with no change.
- If you change which Behaviours are selected, Continue updates the Test Cases to match. A Test
  Case drops a Behaviour that is no longer selected. A Test Case left with none covers all
  selected Behaviours. A newly selected Behaviour gets Criteria, but no Test Case covers it
  yet: the Test Case review names it, and you choose its Test Cases with a chip or the chat.
- If you change content that later content came from, the Wizard updates the later content
  automatically. It keeps form-written content and unrelated selections.

Clarify has no Back, because it is the first step. To correct the description, say so in your
answer, for example "The target is for staff only." To change the capabilities, start again with
`init --restart`.

The CLI saves state after each accepted turn in
`experiments/design/YYYYMMDD-HHMMSS-interview/inputs/interview_state.json`. The date and time are local to the
machine when `init` starts. Use `--out-dir` to select an exact experiment root:

```bash
metis wizard init --out-dir my-eval
```

## Add documents

Give `init` one `--document` option (short form `-d`) for each file. The Interview reads the text
of each file, in the same way as the web client and the API:

```bash
metis wizard init --document policy.pdf --document diagram.png
```

The CLI checks the files before it asks for capabilities or calls the model. It uses the same file
types, limits, and text reader as the web client. It shows one line for each file:

| Line | Meaning |
|---|---|
| `Read: policy.pdf` | The Interview uses the text of the file. |
| `Not read: diagram.png (no text reader for this file type)` | The file type has no text reader. The Interview knows the file by name only. |
| `Could not read: scan.pdf: <reason>` | The file has a text reader, but the CLI could not read the text. |

A file type that the Wizard does not accept stops the command with exit code 1.

When a file could not be read, the CLI asks `Keep unread files without text?` The default is No.
Answer Yes to keep the file by name only. Answer No to stop. Then remove the file from the
command and run `init` again. A run with no terminal, such as a script, stops with exit code 1.

The CLI keeps a copy of each document in `inputs/documents/`. A Test Case can send an opening
document to the target as a fixture file. `resume` uses this copy, so you can move the source
files after `init`.

## Connect the target

In run mode, the Wizard asks for the target binding before the capability questions. Choose how
to give it: fill in the fields in the CLI, or give the path to a binding YAML file. Each secret
field takes the name of an environment variable, never its value. The CLI reads `.env` and the
environment, then checks the binding on your computer:

- It validates the binding fields.
- It reports each named variable as set or not set. It never shows a value.
- For HTTP, it fetches the OpenAPI document. For a browser, it loads the start page.

After the test, choose **test again**, **fix the values**, or **continue**. If the fields are not
valid, fix them. To continue without a binding, run with `--mode spec`.

| Option | Effect |
|---|---|
| `--mode spec` | Write a Specification only. Ask no connection question. |
| `--mode run` | Ask for the binding values. |
| `--binding PATH` | Check the binding in a YAML file. This option implies `--mode run`. |

Without `--mode`, a terminal asks for the mode. When no terminal is available, the mode is
`spec`. With `--binding` and no terminal, the CLI checks the file once and asks nothing.
`--mode run` with no terminal and no `--binding` stops with exit code 1 before the Interview starts.

To add or replace the binding later, run:

```bash
metis wizard connect --out-dir my-eval
metis wizard connect --out-dir my-eval --binding my-binding.yaml
```

For a complete export, `connect` writes the Specification, `review.md`, and the binding again.
For an Interview in progress, it saves the connection, and `resume` writes the binding at the end.

## Resume or restart

Resume requires `--out-dir`, including when the Interview continues on another day. The CLI
prints the complete resume command when an Interview starts.

| To | Command |
|---|---|
| Resume a saved Interview | `metis wizard resume --out-dir my-eval` |
| Discard the Interview in progress and start again | `metis wizard init --out-dir my-eval --restart` |

Without `--restart`, `init` does not overwrite an Interview in progress. It directs you to
`resume`.

## Output files

When the Interview is complete, the CLI retains its final state and writes this layout:

| File | Contents |
|---|---|
| `outputs/specification.yaml` | Target, Features, Behaviours, Criteria and Grader settings, Personas, Scenarios, and Tasks |
| `outputs/review.md` | A human-readable review of the specification |
| `outputs/target-binding.yaml` | The target binding, in run mode only. It names environment variables and holds no secret value. |
| `inputs/interview_state.json` | The final state used to compile the Specification |
| `inputs/documents/` | A copy of the documents given to `init` |
| `outputs/fixtures/` | The documents that a Test Case uses. The CLI copies them from `inputs/documents/`. |

When a Test Case uses a file that is not in `inputs/documents/`, the CLI names the file. Put
that file in `outputs/fixtures/` before you run the Experiment.

The CLI removes a file from `outputs/fixtures/` when the file is a copy of a document in
`inputs/documents/` and no Test Case uses it. A copy has the same name and the same bytes as the
document. Other files in `outputs/fixtures/` stay there.

The CLI publishes `outputs/specification.yaml` after the other export files are saved.
Its presence marks a completed export. `resume` reports completion even though the final state
is retained. Use `--restart` to start again in the same directory. If export fails before the
Specification is published, `resume` can retry from the saved final state.

The CLI also shows the total trial count. For an Interview started on 2026-10-16 at 22:30:45, run the result with:

```bash
metis engine run --input-dir experiments/design/20261016-223045-interview/outputs/
```

See the [Engine guide](../engine.md) for the next steps.
