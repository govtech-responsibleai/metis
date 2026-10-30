# Enterprise service incident triage assistant

An assistant in an enterprise SRE platform handles the first response to service alerts. Alerts can report high error rates, regional outages, security breaches, data loss, warnings, or planned maintenance. An engineer selects an alert and activates Triage alert, with an optional file of notes or logs. The action starts the flow. The assistant reads the alert, assigns a severity, notifies the right responders, and updates the incident ticket. It does not repair the service.

## Inputs and reference

- `inputs/prompt.md`

The reference Specification is `outputs/specification.yaml`. Only files in `inputs/` are supplied to Wizard. This README and the reference are for review.

## Sources

Source locations used to author the inputs and reference:

- https://github.com/responsibleai/ASSERT/blob/main/examples/incident_triage_agent/evals/severity_classification.yaml
- https://github.com/responsibleai/ASSERT/blob/main/examples/incident_triage_agent/evals/pager_severity_discipline.yaml
- https://github.com/responsibleai/ASSERT/blob/main/examples/incident_triage_agent/SOP.md
- Locally authored system-level product brief based on the upstream ASSERT SOP and evaluation configurations and the action-trigger design agreed during review. This is not an upstream product document.
- User feedback on the incident triage case and the action-trigger design.
- Locally authored upload fixture for the action-trigger scenario. This is not an ASSERT fixture.

## Scope and review

The reference is a candidate for human review. Grader assignments need human validation.

- Converted from two ASSERT incident-triage configurations and the upstream procedure. The candidate reference needs human review.
- The measured scope covers end-to-end triage, including the selected-alert action, severity, paging, responder notices, incident ticket, and final status. Later follow-up answers are described but not exercised by the single test case.
- The two personas and the single scenario are locally authored examples. The test case uses the on-call engineer. ASSERT generated conversations and run outputs are not included.
- The single test case uses one P2 alert. It does not exercise required paging for P0/P1 or every branch of the severity decision tree.
- No METIS runner, product execution fixture set, or approved grader implementation is supplied.
- The action and upload are described in scenario prose. The Engine does not dispatch this UI action yet.

## Design notes

### Action trigger

#### Origin

User review of the incident triage case.

#### Request

Test an incident flow that starts when the engineer selects an alert and activates an action. An uploaded file can accompany the action. Text is for later questions or changes; the first step must not require a chat message.

#### Case design

The scenario starts with Triage alert and a selected alert ID. It includes a locally authored text file that asks for a page without new verified alert signals.



## Reference fixtures

`outputs/fixtures/` holds sample files for Test Cases described in the reference. These are not Wizard input documents.

## Attribution and licence

This use case adapts material from Microsoft’s [ASSERT repository](https://github.com/responsibleai/ASSERT). Source links are listed above.

```text
MIT License

Copyright (c) Microsoft Corporation.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
