# Graders

This package holds every grader that a criterion can name in `grader_fqn`, such as
`metis.library.graders.TaskSuccessGrader`. Each grader measures one attribute of the METIS
taxonomy and gives a binary score. For how a grader works and how to write one, see the
[grader guide](../../../../../../docs/guide/library/graders.md).

Some graders adapt the judge prompt of a metric from another evaluation package. Each link
goes to the upstream file at the commit that METIS copied. The module docstring of each grader
names that file and the changes made for METIS. For the copyright notices and license texts,
see [EXTERNAL_SOURCES.md](../EXTERNAL_SOURCES.md). A grader marked METIS uses a rubric written
for METIS.

## Task and Output Quality

| Grader | Adapted from |
|---|---|
| `TaskSuccessGrader` | [DeepEval Task Completion](https://github.com/confident-ai/deepeval/blob/d6cd78ac44da4623ff07c73310dfca474c212068/deepeval/metrics/task_completion/templates/extract_task_and_outcome_from_trace.txt) ([verdict](https://github.com/confident-ai/deepeval/blob/d6cd78ac44da4623ff07c73310dfca474c212068/deepeval/metrics/task_completion/templates/generate_verdict.txt)) |
| `OutputCorrectnessGrader` | [MLflow Correctness](https://github.com/mlflow/mlflow/blob/ad8419718140a5d9957722d8196ced9a1d77c14a/mlflow/genai/judges/prompts/correctness.py) |
| `FactualAccuracyGrader` | [Braintrust Factuality](https://github.com/braintrustdata/autoevals/blob/586cc167eb625d84b11581936b1e11619ec0d15a/templates/factuality.yaml), [OpenAI Evals fact](https://github.com/openai/evals/blob/8eac7a7de5215c907fbddc30efdaf316913eccdd/evals/registry/modelgraded/fact.yaml) |
| `RequiredComponentCompletenessGrader` | [Phoenix completeness](https://github.com/Arize-ai/phoenix/blob/d5f5e054756e98d05172a1651c6ffa3fc6f2ff27/js/packages/phoenix-evals/src/__generated__/default_templates/COMPLETENESS_CLASSIFICATION_EVALUATOR_CONFIG.ts), [MLflow Completeness](https://github.com/mlflow/mlflow/blob/ad8419718140a5d9957722d8196ced9a1d77c14a/mlflow/genai/judges/prompts/completeness.py) |
| `TaskConstraintAdherenceGrader` | [MLflow Guidelines](https://github.com/mlflow/mlflow/blob/ad8419718140a5d9957722d8196ced9a1d77c14a/mlflow/genai/judges/prompts/guidelines.py) |
| `FormatSchemaComplianceGrader` | METIS |
| `ClaimSupportByEvidenceGrader` | [DeepEval Faithfulness](https://github.com/confident-ai/deepeval/blob/d6cd78ac44da4623ff07c73310dfca474c212068/deepeval/metrics/faithfulness/templates/generate_claims.txt), [Braintrust Faithfulness](https://github.com/braintrustdata/autoevals/blob/586cc167eb625d84b11581936b1e11619ec0d15a/py/autoevals/ragas.py) |
| `EvidenceSourceSuitabilityGrader` | METIS |
| `SpeechRecognitionAccuracyGrader` | [DeepEval Transcription Accuracy](https://github.com/confident-ai/deepeval/blob/d6cd78ac44da4623ff07c73310dfca474c212068/deepeval/metrics/transcription_accuracy/templates/generate_verdicts.txt) |
| `ContentFidelityGrader` | METIS |
| `AttributionAccuracyGrader` | [DeepEval Citation Faithfulness](https://github.com/confident-ai/deepeval/blob/d6cd78ac44da4623ff07c73310dfca474c212068/deepeval/metrics/community/citation_faithfulness/template.py) |

## Execution and Decision Quality

| Grader | Adapted from |
|---|---|
| `PlanningQualityGrader` | [DeepEval Plan Quality](https://github.com/confident-ai/deepeval/blob/d6cd78ac44da4623ff07c73310dfca474c212068/deepeval/metrics/plan_quality/templates/evaluate_plan_quality.txt) |
| `ActionChoiceAppropriatenessGrader` | METIS |
| `ToolChoiceAppropriatenessGrader` | [Phoenix tool_selection](https://github.com/Arize-ai/phoenix/blob/d5f5e054756e98d05172a1651c6ffa3fc6f2ff27/js/packages/phoenix-evals/src/__generated__/default_templates/TOOL_SELECTION_CLASSIFICATION_EVALUATOR_CONFIG.ts) |
| `ToolArgumentCorrectnessGrader` | [Phoenix tool_invocation](https://github.com/Arize-ai/phoenix/blob/d5f5e054756e98d05172a1651c6ffa3fc6f2ff27/js/packages/phoenix-evals/src/__generated__/default_templates/TOOL_INVOCATION_CLASSIFICATION_EVALUATOR_CONFIG.ts) |
| `StateTrackingGrader` | METIS |
| `UseOfPriorInformationGrader` | [MLflow KnowledgeRetention](https://github.com/mlflow/mlflow/blob/ad8419718140a5d9957722d8196ced9a1d77c14a/mlflow/genai/judges/prompts/knowledge_retention.py), [DeepEval Knowledge Retention](https://github.com/confident-ai/deepeval/blob/d6cd78ac44da4623ff07c73310dfca474c212068/deepeval/metrics/knowledge_retention/templates/generate_verdict.txt) |
| `ErrorDetectionGrader` | METIS |
| `ErrorRecoveryGrader` | METIS |
| `AdaptationToChangedConditionsGrader` | METIS |
| `StoppingAppropriatenessGrader` | METIS |
| `AvoidingUnproductiveRepetitionGrader` | METIS |
| `AppropriateHandlingOfCapabilityLimitsGrader` | METIS |
| `OutcomeVerificationGrader` | METIS |
| `ReasoningValidityGrader` | METIS |
| `CoordinationQualityGrader` | METIS |

## Interaction Quality

| Grader | Adapted from |
|---|---|
| `RelevanceGrader` | [DeepEval Turn Relevancy](https://github.com/confident-ai/deepeval/blob/d6cd78ac44da4623ff07c73310dfca474c212068/deepeval/metrics/turn_relevancy/templates/generate_verdicts.txt) |
| `CommunicationClarityGrader` | [Phoenix conciseness](https://github.com/Arize-ai/phoenix/blob/d5f5e054756e98d05172a1651c6ffa3fc6f2ff27/js/packages/phoenix-evals/src/__generated__/default_templates/CONCISENESS_CLASSIFICATION_EVALUATOR_CONFIG.ts), for the padding check only |
| `CrossTurnCoherenceGrader` | METIS |
| `ClarificationAppropriatenessGrader` | METIS |
| `UserCorrectionSupportGrader` | [Phoenix user_friction](https://github.com/Arize-ai/phoenix/blob/d5f5e054756e98d05172a1651c6ffa3fc6f2ff27/js/packages/phoenix-evals/src/__generated__/default_templates/USER_FRICTION_CLASSIFICATION_EVALUATOR_CONFIG.ts) |
| `ActionStatusTransparencyGrader` | METIS |
| `ExplanationUsefulnessGrader` | METIS |
| `ToneAppropriatenessGrader` | METIS |
| `OutputNaturalnessGrader` | METIS |

## Reliability and Robustness

| Grader | Adapted from |
|---|---|
| `RobustnessToToolFailuresGrader` | [Phoenix tool_response_handling](https://github.com/Arize-ai/phoenix/blob/d5f5e054756e98d05172a1651c6ffa3fc6f2ff27/js/packages/phoenix-evals/src/__generated__/default_templates/TOOL_RESPONSE_HANDLING_CLASSIFICATION_EVALUATOR_CONFIG.ts), for the error-handling rules only |
| `LongTaskPerformanceStabilityGrader` | METIS |
| `RobustnessToContextDegradationGrader` | METIS |

## Fallback judge

`CriterionJudgeGrader` has no measure. It uses the criterion description as its rubric. The
guided Interview selects it when no grader above matches a criterion. See
[the Criterion Judge guide](../../../../../../docs/guide/library/criterionjudge.md).

The example graders in `demo/` are not in this catalogue, and the wizard does not offer them.

## Keep this list current

When you add a grader, add a row to the table for its sub-dimension. When a grader adapts an
upstream prompt, link the file at the pinned commit. Write the metric name exactly as the
upstream package writes it, and add the project to `EXTERNAL_SOURCES.md` if it is new there.
Then run `make generate-grader-docs`. It writes the grader's docs page from its docstring, its
arguments, its `criteria()` prompt, and the "Adapted from" column of this file.
