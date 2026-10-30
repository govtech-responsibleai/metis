"""Hand-authored specifications used across the tests.

Writing one by hand is the point of `Specification` carrying no step, no history and no
interview id: this file proves the document is a pure artefact by building one without an
interview ever having run.
"""

from metis.wizard.contracts import (
    Behaviour,
    Criterion,
    Feature,
    Persona,
    Scenario,
    Specification,
    Target,
    Task,
)

TURN_BUDGET = "metis.library.graders.demo.DemoTraceBudgetGrader"
CITATION_GRADER = "tests.unit.engine.graders_for_tests.FixedScoreGrader"
BOUNDED_TROUBLESHOOTING = "metis.library.graders.demo.DemoTraceBudgetGrader"


def desk_handover() -> Specification:
    """A rich target handover whose separate facts must survive clarify."""
    return Specification(
        target=Target(
            name="Helpdesk",
            users="Support managers",
            description=(
                "A coordinator that hands support questions to specialist agents for "
                "support managers."
            ),
            detail=(
                "Current specialists:\n"
                "- Data Analyst runs ticket queries and reports the figures.\n"
                "- Report Writer turns figures into a finished report from a template.\n"
                "- Report Reviewer checks a generated report and returns revision feedback.\n\n"
                "Workflow and coordination:\n"
                "The coordinator interprets the request, routes each part to the relevant "
                "specialist and returns their outputs within one workflow. A report workflow "
                "can pass a generated report from Report Writer to Report Reviewer before "
                "returning it.\n\n"
                "Current limits:\n"
                "These three specialists are the capabilities live today."
            ),
        )
    )


def research_assistant() -> Specification:
    """A specification exercising every shape the compiler has to handle.

    Deliberately contains: a ticked behaviour with several criteria, an unticked behaviour
    that still has criteria (dormant, not deleted), a criterion the user typed by hand, one
    scenario covering two behaviours, and a scenario with two personas.
    """
    return Specification(
        target=Target(
            name="Research assistant",
            description=(
                "An agent that answers research questions over an internal document "
                "library, citing what it used."
            ),
            users=(
                "Policy analysts and their managers. Some know exactly what they want; "
                "others are exploring and do not."
            ),
            detail=(
                "A router agent with a document search tool and a summariser subagent. "
                "Search can time out. Nothing is carried between interviews."
            ),
        ),
        features=[
            Feature(
                id="F-1",
                name="Answer quality",
                description="Answer research questions accurately and with useful evidence.",
                behaviours=[
                    Behaviour(
                        id="EB-1",
                        name="Cite factual claims",
                        description="Cites a source for every factual claim",
                        measured=True,
                        criteria=[
                            Criterion(
                                id="AC-1-1",
                                name="Cite supported answers",
                                description="Given a question answerable from the library, when the answer is returned, then every factual claim names the document it came from.",
                                grader_fqn=CITATION_GRADER,
                            ),
                            Criterion(
                                id="AC-1-2",
                                name="Do not cite unrelated sources",
                                description="Given a question the library cannot answer, when the answer is returned, then it says so rather than citing an unrelated document.",
                                grader_fqn=CITATION_GRADER,
                            ),
                        ],
                    ),
                    Behaviour(
                        id="EB-2",
                        name="Keep answers concise",
                        description="Keeps answers under a page unless asked otherwise",
                        measured=False,  # dormant criteria remain available
                        criteria=[
                            Criterion(
                                id="AC-2-1",
                                name="Default length limit",
                                description="Given a question with no length instruction, when the answer is returned, then it is under 500 words.",
                                grader_fqn=TURN_BUDGET,
                            ),
                        ],
                    ),
                ],
            ),
            Feature(
                id="F-2",
                name="Recovery",
                description="Recover safely when document search cannot complete.",
                behaviours=[
                    Behaviour(
                        id="EB-3",
                        name="Stop repeated failures",
                        description=(
                            "Stops after repeated search failures and says what it tried"
                        ),
                        measured=True,
                        criteria=[
                            Criterion(
                                id="AC-3-1",
                                name="Report failed retries",
                                description="Given a document search that times out repeatedly, when the agent has retried three times, then it stops and reports what it attempted.",
                                grader_fqn=BOUNDED_TROUBLESHOOTING,
                            ),
                        ],
                    ),
                ],
            ),
        ],
        personas=[
            Persona(
                id="cooperative-delegator",
                name="Cooperative delegator",
                description=(
                    "A policy analyst comfortable with AI tools who engages fully, "
                    "answers questions willingly, and redirects gently if things stall."
                ),
            ),
            Persona(
                id="impatient-executive",
                name="Impatient executive",
                description=(
                    "A time-poor director who writes in curt imperatives, will not "
                    "answer clarifying questions, and abandons the work quickly."
                ),
            ),
        ],
        scenarios=[
            Scenario(
                id="S-1",
                name="Supported literature review",
                description=(
                    "Ask for a literature review on a topic the library covers well, "
                    "then ask a follow-up that needs a second document."
                ),
            ),
            Scenario(
                id="S-2",
                name="Repeated search timeout",
                description=(
                    "Ask a question whose documents live behind a search that will "
                    "time out, forcing the retry path."
                ),
            ),
        ],
        tasks=[
            Task(
                id="TC-001",
                scenario_ref="S-1",
                persona_ref="cooperative-delegator",
                behaviour_refs=["EB-1"],
                num_trials=3,
            ),
            Task(
                id="TC-002",
                scenario_ref="S-1",
                persona_ref="impatient-executive",
                behaviour_refs=["EB-1"],
                num_trials=3,
            ),
            Task(
                id="TC-003",
                scenario_ref="S-2",
                persona_ref="cooperative-delegator",
                behaviour_refs=["EB-3"],
                fixtures=["policy.pdf"],
                num_trials=3,
            ),
        ],
    )
