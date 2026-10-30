"""SpeechRecognitionAccuracyGrader: whether recognized words accurately represent spoken input.

Prompt adapted from DeepEval transcription accuracy
(confident-ai/deepeval@d6cd78a, deepeval/metrics/transcription_accuracy/templates/
generate_verdicts.txt).
Copyright 2024 Confident AI Inc. Licensed under the Apache License, Version 2.0.
Changed for METIS: DeepEval judges each spoken and transcribed exchange; METIS compares the
recognition output with one reference transcript. The JSON output format is removed.
See metis/library/EXTERNAL_SOURCES.md for the license text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Literal

from pydantic import Field

from metis.core.grading import GradingOutput
from metis.core.trace_processing import Problem
from metis.library.grader import Grader, JudgeArgs
from metis.library.judge import judge
from metis.library.scope import SCOPE_DEFINITIONS, TraceArgs
from metis.library.taxonomy import (
    Aggregation,
    GraderTaxonomy,
    GraderType,
    JudgmentForm,
    Measure,
    ReferenceType,
    Scope,
)
from metis.library.text import NonEmptyText  # noqa: TC001 — a Pydantic field type

if TYPE_CHECKING:
    from metis.core.traces import GradingInput
    from metis.library.grader import LLMSettings


class SpeechRecognitionAccuracyArgs(JudgeArgs, TraceArgs):
    """Settings for the speech-recognition-accuracy assessment.

    ``reference_transcript`` is the authoritative human-verified reference.
    ``transcript_provenance`` optionally records how the reference was obtained.
    The judged reply must contain the recognition output to compare against the
    reference, not a conversational answer.
    """

    turn: Literal["each", "last"] = "last"
    """``last`` judges only the final reply. ``each`` judges every reply."""
    reference_transcript: NonEmptyText = Field(
        description="Human-verified reference transcript to compare against.",
    )
    transcript_provenance: str = Field(
        default="",
        description="How the reference transcript was obtained (e.g., 'human transcription of call recording').",
    )


class SpeechRecognitionAccuracyGrader(Grader[SpeechRecognitionAccuracyArgs]):
    """Assess whether recognized words accurately represent the spoken input.

    Compares the judged recognition output against a supplied human-verified
    reference transcript. This is an LLM-based qualitative assessment, not a
    computed word error rate. Does not require raw audio. Transcript-only support
    in this version.
    """

    args_model = SpeechRecognitionAccuracyArgs
    taxonomy: ClassVar[GraderTaxonomy] = GraderTaxonomy(
        measure=Measure.SPEECH_RECOGNITION_ACCURACY,
        scopes=(Scope.TRACE,),
        grader_types=(GraderType.LLM,),
        reference_types=(ReferenceType.EXPECTED_OUTPUT,),
        judgment_forms=(JudgmentForm.BINARY,),
        aggregations=(Aggregation.NONE_SINGLE_SCORE,),
    )

    def criteria(self) -> str:
        provenance_note = (
            f"\n\nReference provenance: {self.args.transcript_provenance}"
            if self.args.transcript_provenance
            else ""
        )
        return (
            "You are assessing whether recognized words accurately represent the "
            "spoken input by comparing a recognized transcript against a human-verified "
            "reference transcript."
            f"\n\n<reference_transcript>\n{self.args.reference_transcript}"
            "\n</reference_transcript>"
            + provenance_note
            + "\n\n<assessment_boundaries>\n"
            "Compare the recognition output (in the assessed evidence) against the "
            "reference transcript above. The assessed evidence must be the actual "
            "recognition output, not a conversational answer about the audio. Assess "
            "word-level accuracy.\n\n"
            "Do NOT count any of these as errors — they are the same utterance written "
            "differently:\n"
            '- Punctuation, capitalisation, and sentence splitting ("Yes, could you" vs '
            '"Yes. Could you").\n'
            '- Numbers written as digits or as words ("fifteen years" vs "15 years", '
            '"thirty days" vs "30 days").\n'
            "- Filler words, stutters, or backchannels that were dropped "
            '("um", "uh", "you know").\n'
            "- Spelling variants of the same word, contractions, and obvious formatting "
            "of dates, times, money or units.\n"
            "- The same words repeated twice, which some speech-to-text engines emit for "
            "one utterance.\n\n"
            "DO count these as errors — they change what the agent was told:\n"
            "- A name, place, company or other proper noun heard as a different word "
            '("Kavanagh" heard as "Cavanaugh").\n'
            "- A number, quantity, date or duration that differs in value "
            '("fifteen" heard as "fifty", "two weeks" heard as "two months").\n'
            '- A negation gained or lost ("I can\'t start" heard as "I can start").\n'
            "- Words or whole clauses missing or invented such that the meaning changes.\n"
            "- An empty recognition output when something was spoken, which means the "
            "agent heard nothing at all.\n\n"
            "Score 1 when the recognition output faithfully captures the reference "
            "transcript. Score 0 when it does not. When the score is 0, the reason "
            "quotes what was spoken and what was heard instead, and says what it "
            "changed.\n\n"
            "This is an LLM-based qualitative "
            "assessment of accuracy, not a computed word error rate. "
            "Language identification and interpretation are separate concerns."
            "\n</assessment_boundaries>"
        )

    async def grade(self, input: GradingInput, llm: LLMSettings) -> GradingOutput:
        scope = SCOPE_DEFINITIONS[self.scope]
        selected = scope.select(input, self.args)
        if isinstance(selected, Problem):
            return GradingOutput.errored(selected.detail)
        return GradingOutput(
            results=[
                await judge(self, llm, label, scope.render(thing), self.criteria())
                for label, thing in selected.items()
            ]
        )
