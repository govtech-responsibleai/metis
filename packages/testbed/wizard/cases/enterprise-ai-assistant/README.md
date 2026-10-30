My target system is a general-purpose enterprise AI assistant that can answer questions, research information, work with authorised enterprise sources, assist with communications and calendars, create documents and artefacts, and analyse structured data.


## Inputs and reference

- `inputs/prompt.md` (first chat message)
- `inputs/00_README_Overview.docx`
- `inputs/01_Capability_Specification.docx`
- `inputs/02_Tools_Actions_and_Permissions.docx`
- `inputs/03_Users_and_Use_Cases.docx`
- `inputs/04_Risks_Controls_and_Evaluation.docx`

The reference Specification is `outputs/specification.yaml`. Only files in `inputs/` are supplied to Wizard. This README and the reference are for review.

`outputs/fixtures/service-request-pilot-notes.txt` is the user-uploaded text file for TC-004. It is
reference execution data and is not supplied to Wizard as an input document.

## Sources

Source locations used to author the inputs and reference:

- docs/temporary/specification_refined.yaml
- docs/temporary/enterprise_ai_assistant_capability_pack/00_README_Overview.docx
- docs/temporary/enterprise_ai_assistant_capability_pack/01_Capability_Specification.docx
- docs/temporary/enterprise_ai_assistant_capability_pack/02_Tools_Actions_and_Permissions.docx
- docs/temporary/enterprise_ai_assistant_capability_pack/03_Users_and_Use_Cases.docx
- docs/temporary/enterprise_ai_assistant_capability_pack/04_Risks_Controls_and_Evaluation.docx
- User feedback on Enterprise AI Assistant behaviour structure and first measurement scope.

## Scope and review

The reference is a candidate for human review. Grader assignments need human validation.

- The candidate reference has 7 features, 15 behaviours, and 45 criteria. Graders are not assigned.
- Five pre-launch test cases select four behaviours across conversation, enterprise knowledge, communication drafting, and artefact creation. Each test case can select more than one behaviour. Other behaviours remain in the profile for later measurement review.
- The HR topic, expense type, event record, and process-change details are open to variation in the mock scenarios. The meeting-notes case includes a sample upload fixture.
- The source pack includes image work, reminders, recurring tasks, conditional monitoring, and skills. These are not explicit workflows in the reference. Humans must decide their scored scope.
- Calendar writes in the reference are conditional on connector support. The source tool map confirms calendar reads; supported write actions require clarification.
- These cases end at the Wizard Specification. They do not run the enterprise assistant.

## Design notes

### Scope

#### Perspective

An engineer reviews the assistant before launch.

#### Measured behaviours

- Guide the user through their query.
- Find and use enterprise information.
- Communication drafting.
- Artefact creation.

#### Test case design

- A work-related expense claim question selects conversational guidance and enterprise information use. The expense type can vary, and the assistant finds the policy and steps that apply.
- A simple staff HR question selects conversational guidance and enterprise information use. The topic can be leave, claims, hospitalisation benefits, insurance, performance processes, or staff administration. The assistant finds the relevant enterprise resource for the selected topic.
- A knowledge worker's reply to an event thread selects conversational guidance, enterprise information use, and communication drafting. The thread links to a past presentation and documents.
- A user uploads full notes from a previous meeting and asks for a structured Word document. This selects conversational guidance and artefact creation. The uploaded notes provide the source material.
- A senior manager provides approved details of a process change for five teams and asks for a short Word guide and a draft announcement email. This selects conversational guidance, artefact creation, and communication drafting. The request supplies the facts needed for both outputs.


### Persona design

#### Cooperative knowledge worker

Use the same patient, collaborative engineering officer for the expense claim, staff HR question, event-thread reply, and uploaded meeting-notes cases. They are a mid-level officer with about three years at the company. They are less familiar with HR and business processes and do not usually consolidate meeting notes. Store input style, occupation, and personality as optional persona metadata.

#### Time constrained manager

Use a busy senior manager who oversees five teams for the process-guide and announcement case. He supplies approved facts and wants a clear message for all five teams. He has little time to review details. Store his concise input style, occupation, and pragmatic personality as persona metadata.


### Structure

#### Conversation

Keep one behaviour for direct guidance with intent alignment, answer correctness, and appropriate scope. Keep contextual continuation as a second behaviour under Conversational Assistant. Put rewriting and summarising under document editing.

#### Research

Keep information discovery, evidence assessment, and research synthesis.

#### Enterprise search

Use one behaviour for finding the right authorised enterprise resource and using its content accurately. Keep separate criteria for retrieval, access, grounding, traceability, and gaps.

#### Communications

Keep context retrieval, drafting, and action execution.

#### Calendar

Use one behaviour with accurate information retrieval, conflict-free scheduling, and accurate event details, including participants and content.

#### Artefacts

Use creation and editing. Creation checks format suitability, content accuracy, and completeness. Editing checks preservation of unaffected content and content accuracy.

#### Data

Keep analytical computation, spreadsheet manipulation, and analytical communication.
