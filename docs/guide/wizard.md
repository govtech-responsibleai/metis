# METIS Wizard

The METIS Wizard turns a description of a target into an evaluation specification.
The METIS Engine runs that specification.

## Choose an interface

| Interface | Best for | Who saves Interview state? | Finished output |
|---|---|---|---|
| [CLI](wizard/cli.md) | A person working in a terminal | The CLI saves a local JSON file | Files in an output directory |
| [Web](wizard/web.md) | A person who wants a guided browser flow | The browser saves data in IndexedDB | `YYYYMMDD-HHMMSS-interview.zip` download |
| [API](wizard/api.md) | A service or custom client | Your client saves the returned JSON state | YAML strings or `YYYYMMDD-HHMMSS-interview.zip` |

- The CLI runs the Wizard logic on your computer. It does not need the API server.
- The web client uses the Wizard API.
- The API does not save an Interview between requests. A custom client must save each returned
  `state` object and send the whole object with the next request.

## What the Interview builds

Example evaluation details for a research assistant:

| Term | Example |
|---|---|
| Feature | Answer policy questions. |
| Behaviour | Cite sources in each answer. |
| Criterion | Each citation supports the answer. |
| Persona | A policy analyst who needs to check a new rule. |
| Scenario | Ask how a new leave policy applies to a part-time employee. |
| Grader | A check that compares the answer with its cited sources. |

The Interview produces one Specification with these related concepts:

| Concept | Contents |
|---|---|
| Profile | The target and its users, Features, Behaviours, Criteria, and their grader settings |
| Specification | The Profile and the configuration needed to conduct an Experiment |
| Experiment | A collection of Runs used to evaluate one or more targets across a set of Test Cases |

The interface guides give the exact files or archive that each interface produces.

## Interview flow

1. Choose the mode: build a Specification only, or build it and run evals. To run evals, connect
   the target. See [Connect the target](#connect-the-target).
2. Describe the target. You can also add documents.
3. Select the evaluation Perspective (who the evaluation is for, such as an end user or an
   engineer). Web and API only. The CLI always uses End user.
4. Select the known ARC capabilities and a confidence value. You can select no capabilities. The
   CLI and the API need a confidence value. In the web client, the confidence is optional, and
   with no value the web client sends Low.
5. Answer clarification questions.
6. Review the Behaviours to measure and their Criteria.
7. Review the Personas and Scenarios. Then review the Test Cases, which match each Scenario with
   its Personas and Behaviours.
8. Finish and validate the specification.
9. Compile or package the result.

Other paths:

- The web client and the API can finish early. See [web](wizard/web.md#finish-and-download) and
  [API](wizard/api.md#finish-early).
- The web client has a manual path for a user who already knows the Experiment to run. It does
  not use the Interview. See [Write the Experiment directly](wizard/web.md#write-the-experiment-directly).

The Wizard saves the description, Perspective, capabilities, documents, and target connection in
the Interview state. This context is separate from the Specification.

## Connect the target

The Engine must reach the target to run an evaluation. A **target binding** tells it how. For
example, a binding for a research assistant with a REST API names the OpenAPI document URL and
the environment variable that holds the API key. The binding is separate from the Target Profile:
the Profile states what METIS evaluates, and the binding states how METIS reaches the target.

1. Choose **HTTP API** for a target with an OpenAPI document, or **Browser** for a target with
   only a web page.
2. Enter the values that the target cannot supply:
   - HTTP: the target name, the OpenAPI URL, and the API key variable. Under **More options**:
     secret headers, refused calls, submissions, TLS verification, and runner notes.
   - Browser: the target name, the start page URL, and the sign-in steps with `{{secret:NAME}}`
     placeholders. Under **More options**: the sign-in variables and runner notes.
3. Select **Test connection** in the web client. The CLI tests the binding after the fields.
   Then choose test again, fix the values, or continue.

Each secret field takes the **name** of an environment variable, never its value. Set each value
in `.env` or in the environment before you run the Engine. Write `${NAME}` in a URL to read a
variable, for example `${APP_URL}/openapi.json`. The Wizard does not repeat a value in an error.

The test has two parts:

- It always checks the fields. They must have the correct shape, each `{{secret:NAME}}` must be in
  the sign-in variables, and a URL must not hold a user name or password.
- Where it can read your `.env`, it also reports each named variable as set or not set. For HTTP,
  it fetches the OpenAPI document, shows its title and endpoint count, and checks that the API
  server answers. For a browser, it loads the start page. The CLI always does this. The web
  client does this when the API runs on your computer.

The test sends no call to an API endpoint, so it cannot change your data. It does not test your
key or the browser sign-in. Only the Engine can, because it needs your secret values.

Run mode needs valid fields. If the fields are not valid, fix them, or choose Build Spec only. If
the fields are valid but the target does not answer, you can still continue. `review.md` then says
that the binding was not tested.

A download with a binding has `outputs/target-binding.yaml` next to `outputs/specification.yaml`.
The Specification names the generic runner in `runner_factory_ref` and the file in `target_binding`.
The binding file starts with a comment that lists the variables to set.

### Submissions

**Submissions** (`submissions` in the binding) are the calls that send the user's message. When
the list is empty, the Engine treats each `POST`, `PUT`, or `PATCH` with a JSON body as a
submission. A target that has other JSON writes, such as a settings change, needs the list.

When the test reads the OpenAPI document, it helps with this list:

- It suggests each write whose JSON body has exactly one required field, and that field is free
  text. A `{name}` path parameter becomes `*`, for example `POST /conversations/*/messages`.
- It warns about each submission that you wrote that matches no call in the document. The
  warning names the pattern. A warning does not stop the download.

The document does not say which field is the chat message, so a suggestion can be wrong. The
Wizard adds a suggestion to the binding only when you accept it. In the web client, select
**Use these submissions** under **More options**. In the CLI, answer `y`. A target with no
OpenAPI document, or with no matching write, gets no suggestion. The Engine uses only the binding
file. It does not guess submissions during a run.

## ARC capability catalogue

- 12 capabilities in three groups: Cognitive, Interaction, and Operational.
- METIS owns a fixed copy. It does not fetch the catalogue at run time.
- Source: the GovTech Singapore Agentic Risk & Capability Framework, with Apache-2.0 attribution.

## How the Interview uses your answers

- Clarification covers the main things the target does first, then asks for detail where needed.
  It does not ask again about what the description or documents already explain.
- Features are grouped by the work the target does for its users.
- The Perspective sets which Behaviours matter most. The capabilities show what the target can do
  in each Feature.
- The Wizard shows the grader library to the model through progressive disclosure. Each step
  gets only the detail that it needs. Personas, Scenarios, and Test Cases get the list of
  taxonomy Dimensions. Clarification and Behaviours also get the Measures in each Dimension, so
  the questions and Behaviours can cover checks such as resource use and error recovery.
  Criteria and later chat also get each library grader, so more Criteria fit a library grader.
  The taxonomy is incomplete. A Criterion outside it is valid and uses the criterion judge.

## Run the evaluation

The CLI writes files to `experiments/design/YYYYMMDD-HHMMSS-interview/` by default. The timestamp uses the machine's local date and 24-hour time, including seconds.
Extract browser or API downloads into `experiments/design/`.
Each ZIP contains its dated experiment folder. For an Interview created on 2026-10-16 at 22:30:45, run the specification with the
Engine:

```bash
metis engine run --input-dir experiments/design/20261016-223045-interview/outputs/
```

See the [Engine guide](engine.md) for the evaluation run and the [Report guide](report.md) for the
results.

## Review and edit Criteria

The Criteria under a Behaviour show how well that Behaviour performs. The report scores a
Behaviour from the pass rates of its Criteria. Read each Criterion description, then expand
**Grader details** to inspect its settings.
Ask the Wizard to revise the assessment and settings together, or select
the pencil (**Edit <Criterion name>**) to change them directly. Keep directly edited fields consistent.
The Wizard validates the fields and grader arguments before it saves the edit.

## Edit fallback grading instructions

When no specific grader matches a criterion, the Interview selects the criterion fallback judge.
The judge uses the criterion description as its instructions. To change what the judge checks,
edit the Criterion in the Interview or change its description in the exported YAML before the next run. For the settings and the
evidence that the judge reads, see [Edit the criterion fallback judge](library/criterionjudge.md).
