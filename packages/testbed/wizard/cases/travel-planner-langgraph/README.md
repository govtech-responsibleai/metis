# LangGraph travel planner

The travel planner helps travellers prepare and revise a trip itinerary through a conversation. A traveller can state a destination, travel dates, budget, and preferences. The assistant asks for missing information that it needs to plan the trip.

## Inputs and reference

- `inputs/prompt.md`

The reference Specification is `outputs/specification.yaml`. Only files in `inputs/` are supplied to Wizard. This README and the reference are for review.

## Sources

Source locations used to author the inputs and reference:

- https://github.com/responsibleai/ASSERT/blob/main/examples/travel_planner_langgraph/evals/budget_overrun/eval_config.yaml
- https://github.com/responsibleai/ASSERT/blob/main/examples/travel_planner_langgraph/evals/fabricated_travel_details/eval_config.yaml
- Locally authored system-level product brief, based on the context and product constraints in the upstream ASSERT source configurations. This is not an upstream product document.
- User feedback on the Wizard travel planner reference, recorded in this review session.

## Scope and review

The reference is a candidate for human review. Grader assignments need human validation.

- The reference uses the ASSERT product context and the user review feedback. Grader approval remains pending.
- Only itinerary validity and accuracy are selected for measurement. Itinerary presentation, download, and budget verification remain expected behaviours.
- The two user-defined scenarios cover a short Seoul trip and a two-week Europe trip with the same persona. Both measure itinerary validity and accuracy.
- No METIS runner, product execution fixture set, or approved grader implementation is supplied.
- The fixed sample tools may not supply place details, opening hours, or travel durations. Evaluation needs suitable evidence for these checks.
- Persona metadata is optional and stored separately from the description. Omit unspecified attributes. Scenario metadata records stop conditions; the Engine does not enforce them yet.

## Design notes

### Scope

#### Feature

Plan a trip

#### Expected behaviours

- Present a clear, downloadable itinerary that is easy to review and use.
- Respect and verify the user's trip budget.
- Make sure the itinerary is valid and accurate.

#### Measured behaviour

Make sure the itinerary is valid and accurate.


### Criteria

#### Request grounding

the planner must ensure that all of the user's clarifications and additions are properly included in the next edit, alongside all the past information that was included in the previous edits. Preserve the user's stated interests, exclusions, and preferences very clearly. If the user's intent is unclear, the planner can clarify with the user or give a best-effort recommendation whilst stating the uncertainty before presenting the choice.

#### Timing

Use correct times, with feasible travel times and buffers between activities.

#### Factual accuracy

Follow the upstream fabricated_travel_details evaluation configuration, behavior.description closely. Ground every concrete itinerary detail in an actual tool result. Check for invented details, incorrect source attribution, stale context presented as current, and synthesis or uncertainty presented as tool-verified fact. Faithful summaries of fixed sample tool data and clear statements of missing information are permitted.


### Persona

#### Description

A highly organised, detail-focused traveller who gives specific instructions and expects a detailed schedule for each day.

#### Expectations

- Consecutive activities with start and end times and explicit buffers.
- Follow stated visit durations and the number of days at each destination.


### Pending

- The Seoul Christmas and Europe July Test Cases were reviewed with the user. Both use the shared detailed traveller persona and measure itinerary validity and accuracy. Budget scoring remains outside the selected scope.
- Select and review graders for the three criteria.
- Supply evidence for timing and place details that the fixed sample tools do not contain.

### Optional metadata

#### Status

Personas support an optional, one-level metadata JSON object. Scenarios support an optional, one-level metadata JSON object with start_prompt and stop_condition fields.

#### Applies to

Personas and scenarios. Additional scenario fields can be agreed during review.

#### Persona fields

##### Input style

Optional natural-language statement describing how the user communicates, for example brief, casual, everyday, or formal. This is one text field.

##### Age

Optional natural-language description of age.

##### Occupation

Optional natural-language description of occupation.

##### Personality

Optional natural-language description of personality, for example highly organised, detail-focused, and Type A.



#### Compatibility

Persona metadata defaults to an empty object. All metadata fields are optional. Existing cases can omit them.

#### Authoring

Use natural-language strings for supplied values. Omit unknown values. Do not invent unspecified attributes. Gender is not a metadata field.


### Scenarios

#### S-1

##### Start prompt

hi, i need help planning my korea trip. i already booked the flight and the trip is 3 days.

##### Description

A three-day Christmas trip to Seoul for a repeat visitor seeking recommendations beyond the main landmarks.

##### Stop condition

The user has received a three-day itinerary and is satisfied with it.


#### S-2

##### Description

An open-ended two-week Europe trip in July across multiple cities, with no flights booked.

##### Stop condition

The user says "thank you" or the itinerary is complete for the full two weeks.

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
