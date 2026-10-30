"""Values and grader support declarations for the grader taxonomy.

The conceptual hierarchy for one judgment is:

    Measure
        Choose one subdimension, such as Task and Output Quality.
        Choose one attribute within it, such as factual_accuracy.
    Scope
        Choose one subdimension, such as Interaction.
        Choose one attribute within it, such as session.
    Mechanism
        For each subdimension, choose one attribute:
            Grader type, such as llm.
            Reference type, such as rubric_based.
            Judgment form, such as binary.
            Aggregation, such as none_single_score.

Measure and Scope are flat enums of attributes. Group comments name their
subdimensions. Dimension names the Measure subdimensions, and MEASURE_DIMENSIONS
gives the Dimension of each Measure. The mechanism subdimensions have separate enums.
GraderTaxonomy declares the values a grader supports. It does not select defaults
or validate combinations. A catch-all judge has no fixed Measure and uses None.

Update these enums directly when the taxonomy changes. Group comments mark V1
exclusions until the next group heading or enum class. Do not implement V1 graders
for excluded entries. Other entries are catalogue entries. Their presence does not
mean that an implementation exists.

An enum member is a taxonomy value. A taxonomy definition holds the shared metadata
and predefined behaviour for one value. ``metis.library.judgment_form`` contains the
working binary judgment-form definition. Definitions for the other groups remain
design work.

Graders assess recorded traces and linked artifacts with explicit references.
They cannot inspect live state. A Criterion stores settings in grader_args. Each
grader defines which settings it accepts. General taxonomy selection is not
implemented.
"""

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "MEASURE_DIMENSIONS",
    "Aggregation",
    "Dimension",
    "Measure",
    "Scope",
    "GraderType",
    "GraderTaxonomy",
    "JudgmentForm",
    "ReferenceType",
]


class Dimension(StrEnum):
    """Measure subdimensions, in display order."""

    TASK_AND_OUTPUT_QUALITY = "task_and_output_quality"
    EXECUTION_AND_DECISION_QUALITY = "execution_and_decision_quality"
    RESOURCE_USE = "resource_use"
    RELIABILITY_AND_ROBUSTNESS = "reliability_and_robustness"
    SAFETY = "safety"
    SECURITY = "security"
    INTERACTION_QUALITY = "interaction_quality"


class Measure(StrEnum):
    """Properties assessed by graders."""

    # Task and Output Quality
    TASK_SUCCESS = "task_success"
    OUTPUT_CORRECTNESS = "output_correctness"
    FACTUAL_ACCURACY = "factual_accuracy"
    REQUIRED_COMPONENT_COMPLETENESS = "required_component_completeness"
    TASK_CONSTRAINT_ADHERENCE = "task_constraint_adherence"
    FORMAT_AND_SCHEMA_COMPLIANCE = "format_and_schema_compliance"
    CLAIM_SUPPORT_BY_EVIDENCE = "claim_support_by_evidence"
    EVIDENCE_SOURCE_SUITABILITY = "evidence_source_suitability"
    INPUT_INTERPRETATION_ACCURACY = "input_interpretation_accuracy"
    SPEECH_RECOGNITION_ACCURACY = "speech_recognition_accuracy"
    LANGUAGE_IDENTIFICATION_ACCURACY = "language_identification_accuracy"
    CONTENT_FIDELITY = "content_fidelity"
    SPOKEN_CONTENT_FIDELITY = "spoken_content_fidelity"
    ATTRIBUTION_ACCURACY = "attribution_accuracy"

    # Execution and Decision Quality
    PLANNING_QUALITY = "planning_quality"
    ACTION_CHOICE_APPROPRIATENESS = "action_choice_appropriateness"
    TOOL_CHOICE_APPROPRIATENESS = "tool_choice_appropriateness"
    TOOL_ARGUMENT_CORRECTNESS = "tool_argument_correctness"
    USE_OF_OBSERVED_STATE = "use_of_observed_state"
    STATE_TRACKING = (  # Requires recorded observations.
        "state_tracking"
    )
    USE_OF_PRIOR_INFORMATION = "use_of_prior_information"
    ERROR_DETECTION = "error_detection"
    ERROR_RECOVERY = "error_recovery"
    ADAPTATION_TO_CHANGED_CONDITIONS = "adaptation_to_changed_conditions"
    STOPPING_APPROPRIATENESS = "stopping_appropriateness"
    AVOIDING_UNPRODUCTIVE_REPETITION = "avoiding_unproductive_repetition"
    APPROPRIATE_HANDLING_OF_CAPABILITY_LIMITS = (
        "appropriate_handling_of_capability_limits"
    )
    OUTCOME_VERIFICATION = "outcome_verification"
    REASONING_VALIDITY = (  # Requires recorded reasoning.
        "reasoning_validity"
    )
    COORDINATION_QUALITY = "coordination_quality"

    # Resource Use
    TOKEN_USAGE = "token_usage"  # Requires recorded token measurements.
    ELAPSED_TIME = "elapsed_time"
    MODEL_CALL_COUNT = "model_call_count"
    TOOL_CALL_COUNT = "tool_call_count"
    MONETARY_COST = (  # Requires recorded costs or an explicit pricing reference.
        "monetary_cost"
    )
    EXECUTION_STEP_COUNT = "execution_step_count"
    AGENT_COMPUTE_USE = (  # Requires recorded compute data.
        "agent_compute_use"
    )
    HUMAN_ASSISTANCE_REQUIRED = "human_assistance_required"

    # Reliability and Robustness
    ROBUSTNESS_TO_TOOL_FAILURES = (  # Assess recorded failures within the session.
        "robustness_to_tool_failures"
    )
    LONG_TASK_PERFORMANCE_STABILITY = (  # Assess the supplied session.
        "long_task_performance_stability"
    )
    ROBUSTNESS_TO_CONTEXT_DEGRADATION = (  # Requires recorded context within the session.
        "robustness_to_context_degradation"
    )

    # Out of scope in V1.
    ROBUSTNESS_TO_EQUIVALENT_INPUT_VARIATION = (  # Requires comparison across trials.
        "robustness_to_equivalent_input_variation"
    )
    ROBUSTNESS_TO_OPERATING_CONDITION_VARIATION = (  # Requires comparison across operating conditions.
        "robustness_to_operating_condition_variation"
    )
    SAFE_FAILURE_HANDLING = (  # Includes safety and harm-prevention claims.
        "safe_failure_handling"
    )
    REPEATED_RUN_CONSISTENCY = (  # A grader receives one session.
        "repeated_run_consistency"
    )
    FAILURE_CONTAINMENT = (  # Includes harm propagation across systems.
        "failure_containment"
    )
    CONFIDENCE_CALIBRATION = (  # Requires confidence and correctness across cases.
        "confidence_calibration"
    )

    # Safety. Out of scope in V1.
    INAPPROPRIATE_CONTENT = "inappropriate_content"
    HARMFUL_ASSISTANCE = "harmful_assistance"
    HARMFUL_ACTIONS = "harmful_actions"
    TRUTHFULNESS = "truthfulness"
    PRIVACY = "privacy"
    FAIRNESS_AND_AUTONOMY = "fairness_and_autonomy"
    AUTHORITY_BOUNDARIES = "authority_boundaries"
    OVERSIGHT_AND_SAFEGUARDS = "oversight_and_safeguards"
    REFUSAL_AND_CRISIS_RESPONSE = "refusal_and_crisis_response"
    POLICY_COMPLIANCE = "policy_compliance"

    # Security. Out of scope in V1.
    CONFIDENTIALITY_PROTECTION = "confidentiality_protection"
    DECISION_INTEGRITY_UNDER_MANIPULATION = "decision_integrity_under_manipulation"
    STORED_DATA_INTEGRITY = "stored_data_integrity"
    MODEL_ASSET_INTEGRITY = "model_asset_integrity"
    ACCESS_CONTROL_INTEGRITY = "access_control_integrity"
    EXECUTION_ENVIRONMENT_CONTAINMENT = "execution_environment_containment"
    RESOURCE_BOUND_ADHERENCE = "resource_bound_adherence"
    SERVICE_AVAILABILITY_PROTECTION = "service_availability_protection"
    TOOL_AND_COMPONENT_INTEGRITY = "tool_and_component_integrity"
    INTER_AGENT_COMMUNICATION_INTEGRITY = "inter_agent_communication_integrity"
    GENERATED_ARTIFACT_SECURITY = "generated_artifact_security"

    # Interaction Quality
    RELEVANCE = "relevance"
    COMMUNICATION_CLARITY = "communication_clarity"
    PERCEPTUAL_INTELLIGIBILITY = "perceptual_intelligibility"
    # "Turn" here is a recorded turn (GLOSSARY.md): coherence from one trace to the next.
    # The value is saved and published, so it keeps the bare word.
    CROSS_TURN_COHERENCE = "cross_turn_coherence"
    TURN_TAKING = "turn_taking"
    UNCERTAINTY_COMMUNICATION = "uncertainty_communication"
    CLARIFICATION_APPROPRIATENESS = "clarification_appropriateness"
    USER_CORRECTION_AND_OVERRIDE_SUPPORT = "user_correction_and_override_support"
    ACTION_STATUS_TRANSPARENCY = "action_status_transparency"
    EXPLANATION_USEFULNESS = "explanation_usefulness"
    TONE_APPROPRIATENESS = "tone_appropriateness"
    OUTPUT_NATURALNESS = "output_naturalness"
    SIGNAL_RENDERING_QUALITY = (  # Requires the recorded signal or rendering.
        "signal_rendering_quality"
    )
    ACOUSTIC_QUALITY = "acoustic_quality"  # Requires an available audio artifact.


MEASURE_DIMENSIONS: Mapping[Measure, Dimension] = MappingProxyType(
    {
        Measure.TASK_SUCCESS: Dimension.TASK_AND_OUTPUT_QUALITY,
        Measure.OUTPUT_CORRECTNESS: Dimension.TASK_AND_OUTPUT_QUALITY,
        Measure.FACTUAL_ACCURACY: Dimension.TASK_AND_OUTPUT_QUALITY,
        Measure.REQUIRED_COMPONENT_COMPLETENESS: Dimension.TASK_AND_OUTPUT_QUALITY,
        Measure.TASK_CONSTRAINT_ADHERENCE: Dimension.TASK_AND_OUTPUT_QUALITY,
        Measure.FORMAT_AND_SCHEMA_COMPLIANCE: Dimension.TASK_AND_OUTPUT_QUALITY,
        Measure.CLAIM_SUPPORT_BY_EVIDENCE: Dimension.TASK_AND_OUTPUT_QUALITY,
        Measure.EVIDENCE_SOURCE_SUITABILITY: Dimension.TASK_AND_OUTPUT_QUALITY,
        Measure.INPUT_INTERPRETATION_ACCURACY: Dimension.TASK_AND_OUTPUT_QUALITY,
        Measure.SPEECH_RECOGNITION_ACCURACY: Dimension.TASK_AND_OUTPUT_QUALITY,
        Measure.LANGUAGE_IDENTIFICATION_ACCURACY: Dimension.TASK_AND_OUTPUT_QUALITY,
        Measure.CONTENT_FIDELITY: Dimension.TASK_AND_OUTPUT_QUALITY,
        Measure.SPOKEN_CONTENT_FIDELITY: Dimension.TASK_AND_OUTPUT_QUALITY,
        Measure.ATTRIBUTION_ACCURACY: Dimension.TASK_AND_OUTPUT_QUALITY,
        Measure.PLANNING_QUALITY: Dimension.EXECUTION_AND_DECISION_QUALITY,
        Measure.ACTION_CHOICE_APPROPRIATENESS: Dimension.EXECUTION_AND_DECISION_QUALITY,
        Measure.TOOL_CHOICE_APPROPRIATENESS: Dimension.EXECUTION_AND_DECISION_QUALITY,
        Measure.TOOL_ARGUMENT_CORRECTNESS: Dimension.EXECUTION_AND_DECISION_QUALITY,
        Measure.USE_OF_OBSERVED_STATE: Dimension.EXECUTION_AND_DECISION_QUALITY,
        Measure.STATE_TRACKING: Dimension.EXECUTION_AND_DECISION_QUALITY,
        Measure.USE_OF_PRIOR_INFORMATION: Dimension.EXECUTION_AND_DECISION_QUALITY,
        Measure.ERROR_DETECTION: Dimension.EXECUTION_AND_DECISION_QUALITY,
        Measure.ERROR_RECOVERY: Dimension.EXECUTION_AND_DECISION_QUALITY,
        Measure.ADAPTATION_TO_CHANGED_CONDITIONS: Dimension.EXECUTION_AND_DECISION_QUALITY,
        Measure.STOPPING_APPROPRIATENESS: Dimension.EXECUTION_AND_DECISION_QUALITY,
        Measure.AVOIDING_UNPRODUCTIVE_REPETITION: Dimension.EXECUTION_AND_DECISION_QUALITY,
        Measure.APPROPRIATE_HANDLING_OF_CAPABILITY_LIMITS: Dimension.EXECUTION_AND_DECISION_QUALITY,
        Measure.OUTCOME_VERIFICATION: Dimension.EXECUTION_AND_DECISION_QUALITY,
        Measure.REASONING_VALIDITY: Dimension.EXECUTION_AND_DECISION_QUALITY,
        Measure.COORDINATION_QUALITY: Dimension.EXECUTION_AND_DECISION_QUALITY,
        Measure.TOKEN_USAGE: Dimension.RESOURCE_USE,
        Measure.ELAPSED_TIME: Dimension.RESOURCE_USE,
        Measure.MODEL_CALL_COUNT: Dimension.RESOURCE_USE,
        Measure.TOOL_CALL_COUNT: Dimension.RESOURCE_USE,
        Measure.MONETARY_COST: Dimension.RESOURCE_USE,
        Measure.EXECUTION_STEP_COUNT: Dimension.RESOURCE_USE,
        Measure.AGENT_COMPUTE_USE: Dimension.RESOURCE_USE,
        Measure.HUMAN_ASSISTANCE_REQUIRED: Dimension.RESOURCE_USE,
        Measure.ROBUSTNESS_TO_TOOL_FAILURES: Dimension.RELIABILITY_AND_ROBUSTNESS,
        Measure.LONG_TASK_PERFORMANCE_STABILITY: Dimension.RELIABILITY_AND_ROBUSTNESS,
        Measure.ROBUSTNESS_TO_CONTEXT_DEGRADATION: Dimension.RELIABILITY_AND_ROBUSTNESS,
        Measure.ROBUSTNESS_TO_EQUIVALENT_INPUT_VARIATION: Dimension.RELIABILITY_AND_ROBUSTNESS,
        Measure.ROBUSTNESS_TO_OPERATING_CONDITION_VARIATION: Dimension.RELIABILITY_AND_ROBUSTNESS,
        Measure.SAFE_FAILURE_HANDLING: Dimension.RELIABILITY_AND_ROBUSTNESS,
        Measure.REPEATED_RUN_CONSISTENCY: Dimension.RELIABILITY_AND_ROBUSTNESS,
        Measure.FAILURE_CONTAINMENT: Dimension.RELIABILITY_AND_ROBUSTNESS,
        Measure.CONFIDENCE_CALIBRATION: Dimension.RELIABILITY_AND_ROBUSTNESS,
        Measure.INAPPROPRIATE_CONTENT: Dimension.SAFETY,
        Measure.HARMFUL_ASSISTANCE: Dimension.SAFETY,
        Measure.HARMFUL_ACTIONS: Dimension.SAFETY,
        Measure.TRUTHFULNESS: Dimension.SAFETY,
        Measure.PRIVACY: Dimension.SAFETY,
        Measure.FAIRNESS_AND_AUTONOMY: Dimension.SAFETY,
        Measure.AUTHORITY_BOUNDARIES: Dimension.SAFETY,
        Measure.OVERSIGHT_AND_SAFEGUARDS: Dimension.SAFETY,
        Measure.REFUSAL_AND_CRISIS_RESPONSE: Dimension.SAFETY,
        Measure.POLICY_COMPLIANCE: Dimension.SAFETY,
        Measure.CONFIDENTIALITY_PROTECTION: Dimension.SECURITY,
        Measure.DECISION_INTEGRITY_UNDER_MANIPULATION: Dimension.SECURITY,
        Measure.STORED_DATA_INTEGRITY: Dimension.SECURITY,
        Measure.MODEL_ASSET_INTEGRITY: Dimension.SECURITY,
        Measure.ACCESS_CONTROL_INTEGRITY: Dimension.SECURITY,
        Measure.EXECUTION_ENVIRONMENT_CONTAINMENT: Dimension.SECURITY,
        Measure.RESOURCE_BOUND_ADHERENCE: Dimension.SECURITY,
        Measure.SERVICE_AVAILABILITY_PROTECTION: Dimension.SECURITY,
        Measure.TOOL_AND_COMPONENT_INTEGRITY: Dimension.SECURITY,
        Measure.INTER_AGENT_COMMUNICATION_INTEGRITY: Dimension.SECURITY,
        Measure.GENERATED_ARTIFACT_SECURITY: Dimension.SECURITY,
        Measure.RELEVANCE: Dimension.INTERACTION_QUALITY,
        Measure.COMMUNICATION_CLARITY: Dimension.INTERACTION_QUALITY,
        Measure.PERCEPTUAL_INTELLIGIBILITY: Dimension.INTERACTION_QUALITY,
        Measure.CROSS_TURN_COHERENCE: Dimension.INTERACTION_QUALITY,
        Measure.TURN_TAKING: Dimension.INTERACTION_QUALITY,
        Measure.UNCERTAINTY_COMMUNICATION: Dimension.INTERACTION_QUALITY,
        Measure.CLARIFICATION_APPROPRIATENESS: Dimension.INTERACTION_QUALITY,
        Measure.USER_CORRECTION_AND_OVERRIDE_SUPPORT: Dimension.INTERACTION_QUALITY,
        Measure.ACTION_STATUS_TRANSPARENCY: Dimension.INTERACTION_QUALITY,
        Measure.EXPLANATION_USEFULNESS: Dimension.INTERACTION_QUALITY,
        Measure.TONE_APPROPRIATENESS: Dimension.INTERACTION_QUALITY,
        Measure.OUTPUT_NATURALNESS: Dimension.INTERACTION_QUALITY,
        Measure.SIGNAL_RENDERING_QUALITY: Dimension.INTERACTION_QUALITY,
        Measure.ACOUSTIC_QUALITY: Dimension.INTERACTION_QUALITY,
    }
)
"""The Dimension of each Measure. The keys follow the Measure group comments."""


class Scope(StrEnum):
    """Evidence units that can each receive one grader result.

    Interaction scopes select traces. Trace covers one trace. Subsession covers
    a subset of a session's traces. Session covers all traces for one trial.
    """

    # Atomic
    MODEL_DECISION_GENERATION = "model_decision_generation"
    MODEL_REASONING = "model_reasoning"  # Recorded reasoning only.
    ARTIFACT = "artifact"
    TOOL_SELECTION = "tool_selection"
    TOOL_ARGUMENTS = "tool_arguments"
    TOOL_EXECUTION = "tool_execution"
    ENVIRONMENT_ACTION = (  # Recorded actions and effects only.
        "environment_action"
    )

    # Interaction
    TRACE = "trace"
    SUBSESSION = "subsession"
    SESSION = "session"


class GraderType(StrEnum):
    """Procedures that a grader can use to assess one scope item."""

    DETERMINISTIC = "deterministic"
    STATISTICAL_METRIC = "statistical_metric"
    LEARNED_DISCRIMINATIVE_MODEL = "learned_discriminative_model"
    EMBEDDING_SIMILARITY = "embedding_similarity"
    LLM = "llm"
    HYBRID = "hybrid"

    # Out of scope in V1.
    HUMAN = "human"  # Requires a live human-review workflow.


class ReferenceType(StrEnum):
    """Reference categories that a grader can use."""

    # Reference
    REFERENCELESS = "referenceless"
    RUBRIC_BASED = "rubric_based"
    EXPECTED_OUTPUT = "expected_output"
    EXPECTED_TRAJECTORY_ACTION = "expected_trajectory_action"
    POLICY_RULE = "policy_rule"
    ENVIRONMENT_STATE = (  # Recorded snapshots only.
        "environment_state"
    )
    PAIRWISE_CANDIDATE = (  # Requires an explicitly supplied comparison candidate.
        "pairwise_candidate"
    )
    HISTORICAL_BASELINE = (  # Requires an explicitly supplied baseline.
        "historical_baseline"
    )
    HUMAN_PREFERENCE = (  # Requires previously supplied human labels or rankings.
        "human_preference"
    )


class JudgmentForm(StrEnum):
    """Result forms that a grader can produce for one scope item."""

    # Judgment Form
    BINARY = "binary"
    CATEGORICAL = (  # Requires a numeric score mapping.
        "categorical"
    )
    SCALAR = "scalar"
    ORDINAL = (  # Requires a numeric score mapping.
        "ordinal"
    )
    PAIRWISE_PREFERENCE = (  # Requires a numeric score mapping.
        "pairwise_preference"
    )
    RATIONALE_JUDGEMENT = "rationale_judgement"
    DIAGNOSTIC_LABELS = (  # Encode the judgment in score and reason.
        "diagnostic_labels"
    )

    # Out of scope in V1.
    STRUCTURED_MULTI_FIELD_JUDGEMENT = (  # Results contain only status, score, and reason.
        "structured_multi_field_judgement"
    )


class Aggregation(StrEnum):
    """Rules for combining checks within one scope item."""

    # Aggregation
    NONE_SINGLE_SCORE = "none_single_score"
    WEIGHTED_AVERAGE = "weighted_average"
    PASS_IF_ALL = "pass_if_all"
    PASS_IF_ANY = "pass_if_any"
    THRESHOLDED = "thresholded"
    HIERARCHICAL_AGGREGATION = (  # Within-session aggregation only.
        "hierarchical_aggregation"
    )
    LEARNED_AGGREGATE = "learned_aggregate"  # Requires a supplied aggregation model.

    # Out of scope in V1.
    PARETO_MULTI_OBJECTIVE = (  # Requires a result model for objective trade-offs.
        "pareto_multi_objective"
    )


class GraderTaxonomy(BaseModel):
    """Taxonomy values that one grader supports.

    A grader has one measure, or None when it is a catch-all judge.
    Each other field lists one or more supported values. A one-value field is fixed
    for that grader. A field with several values can
    become a form choice when the grader's args model has the matching setting.
    This declaration records support only. Tuple order does not select a default.
    The grader must validate the combinations it implements. General runtime
    routing from selected values to definitions remains design work.
    """

    model_config = ConfigDict(frozen=True)

    measure: Measure | None
    scopes: tuple[Scope, ...] = Field(min_length=1)
    grader_types: tuple[GraderType, ...] = Field(min_length=1)
    reference_types: tuple[ReferenceType, ...] = Field(min_length=1)
    judgment_forms: tuple[JudgmentForm, ...] = Field(min_length=1)
    aggregations: tuple[Aggregation, ...] = Field(min_length=1)
