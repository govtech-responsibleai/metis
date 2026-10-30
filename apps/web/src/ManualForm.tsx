import {
  ArrowLeft,
  Check,
  ChevronRight,
  Download,
  FilePen,
  Pencil,
  Plus,
  Search,
  Upload,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ConnectionForm, ModePicker } from "./ConnectionStep";
import { startConnection, type ConnectionDraft } from "./connection";
import { downloadArchive } from "./download";
import {
  ACCEPTED_FIXTURE_EXTENSIONS,
  validateFixtureSelection,
} from "./fixture-policy";
import { Field, NumberInput, SelectInput, TextArea, TextInput } from "./fields";
import {
  emptyManualExperiment,
  emptyManualPersona,
  emptyManualScenario,
  emptyManualTestCase,
  deselectGrader,
  keepReferencedFixtures,
  manualFieldErrors,
  manualGraders,
  replaceTaskReference,
  graderGroups,
  selectGrader,
  synthesizeManualSpecification,
  taxonomyLabel,
  updateGrader,
  type ManualExperiment,
  type ManualFixture,
  type ManualPersona,
  type ManualMetadataEntry,
  type ManualScenario,
  type ManualGrader,
  type ManualTestCase,
} from "./manual";
import {
  api,
  TransportError,
  type ConnectionCheckResult,
  type GraderSetting,
  type GraderSpec,
  type TargetConnection,
} from "./transport/api";
import { Button, cn, formatTrials, Mono } from "./ui";

function KeyValueEditor({
  title,
  entries = [],
  rowLabel,
  addLabel,
  errorFor,
  onChange,
}: {
  title: string;
  entries?: ManualMetadataEntry[];
  /** Names one row for assistive technology, such as `Persona analyst, context 1`. */
  rowLabel: (row: number) => string;
  addLabel: string;
  errorFor: (row: number) => string | undefined;
  onChange: (entries: ManualMetadataEntry[]) => void;
}) {
  const edit = (index: number, patch: Partial<ManualMetadataEntry>) =>
    onChange(
      entries.map((row, i) => (i === index ? { ...row, ...patch } : row)),
    );
  return (
    <div
      role="group"
      aria-label={title}
      className="flex min-w-0 flex-col gap-1.5"
    >
      <div className="flex h-5 shrink-0 items-center justify-between gap-2">
        <span className="text-xs font-medium text-muted-foreground">
          {title}
        </span>
        <IconButton
          label={addLabel}
          size="small"
          onClick={() => onChange([...entries, { key: "", value: "" }])}
        >
          <Plus size={14} strokeWidth={1.75} aria-hidden />
        </IconButton>
      </div>
      {entries.length === 0 && (
        <p className="text-sm text-muted-foreground">None</p>
      )}
      <div className="flex max-h-44 flex-col gap-1.5 overflow-y-auto">
        {entries.map((entry, index) => {
          const error = errorFor(index);
          const label = rowLabel(index + 1);
          return (
            <div key={index} className="flex flex-col gap-1">
              <div className="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)_auto] items-center gap-2">
                <TextInput
                  ariaLabel={`${label} key`}
                  value={entry.key}
                  placeholder="key"
                  spellCheck={false}
                  density="inline"
                  invalid={Boolean(error)}
                  className="font-mono"
                  onChange={(key) => edit(index, { key })}
                />
                <TextInput
                  ariaLabel={`${label} value`}
                  value={entry.value}
                  placeholder="value"
                  spellCheck={false}
                  density="inline"
                  className="font-mono"
                  onChange={(value) => edit(index, { value })}
                />
                <RemoveButton
                  label={`Remove ${label}`}
                  size="small"
                  onClick={() =>
                    onChange(entries.filter((_, i) => i !== index))
                  }
                />
              </div>
              {error && <p className="text-xs text-destructive">{error}</p>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function ManualAuthoringEntry({ onOpen }: { onOpen: () => void }) {
  return (
    <button
      type="button"
      aria-label="Skip the interview and write it yourself"
      onClick={onOpen}
      className="group flex w-full items-center gap-3 rounded-lg border border-border bg-card p-4 text-left text-card-foreground transition-colors hover:bg-muted active:bg-border"
    >
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-border bg-background text-muted-foreground transition-colors group-hover:text-foreground">
        <FilePen size={17} strokeWidth={1.75} aria-hidden />
      </span>
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="text-sm font-medium text-foreground">
          Skip the interview and write it yourself
        </span>
      </span>
      <ChevronRight
        size={16}
        strokeWidth={1.75}
        aria-hidden
        className="text-muted-foreground transition-transform group-hover:translate-x-0.5"
      />
    </button>
  );
}

type CollectionKind = "Persona" | "Scenario" | "Test case";
type FocusTarget = {
  kind: "persona" | "scenario" | "task";
  index: number;
} | null;
export type ManualFocusTarget = Exclude<FocusTarget, null>;

export function itemHeading(kind: CollectionKind, id: string): string {
  return id.trim() || `New ${kind}`;
}

function itemContext(kind: CollectionKind, index: number, id: string): string {
  return `${kind} ${id.trim() || index + 1}`;
}

function openItem(indexes: readonly number[], index: number): number[] {
  return indexes.includes(index) ? [...indexes] : [...indexes, index];
}

function closeItem(indexes: readonly number[], index: number): number[] {
  return indexes.filter((value) => value !== index);
}

function removeItemIndex(
  indexes: readonly number[],
  removedIndex: number,
): number[] {
  return indexes.flatMap((index) => {
    if (index === removedIndex) return [];
    return [index > removedIndex ? index - 1 : index];
  });
}

export function focusManualInput(
  target: ManualFocusTarget | null,
  personaRefs: ReadonlyArray<Pick<HTMLInputElement, "focus"> | null>,
  scenarioRefs: ReadonlyArray<Pick<HTMLInputElement, "focus"> | null>,
  taskRefs: ReadonlyArray<Pick<HTMLInputElement, "focus"> | null> = [],
): boolean {
  if (!target) return false;
  const refs =
    target.kind === "persona"
      ? personaRefs
      : target.kind === "scenario"
        ? scenarioRefs
        : taskRefs;
  const element = refs[target.index];
  if (!element) return false;
  element.focus();
  return true;
}

// Compile the manual Experiment and package it. In run mode `connection` gives the target
// connection, and a null connection stops the download before any request. `onCompiled` gets the
// Task IDs that compile assigned, so the form keeps them even when packaging fails.
export async function packageManualExperiment(
  experiment: ManualExperiment,
  files: readonly ManualFixture[],
  connection: (() => Promise<TargetConnection | null>) | null,
  onCompiled: (taskIds: Array<string | undefined>) => void,
): Promise<Awaited<ReturnType<typeof api.package>> | null> {
  const target = connection ? await connection() : null;
  if (connection && !target) return null;
  const submitted = synthesizeManualSpecification(experiment);
  const compiled = await api.compile(submitted);
  const assigned = compiled.specification.tasks ?? [];
  onCompiled(assigned.map((task) => task.id ?? undefined));
  return api.package(
    {
      specification: {
        ...submitted,
        tasks: assigned.map((task) => ({
          ...task,
          fixtures: task.fixtures ?? [],
          behaviour_refs: task.behaviour_refs ?? [],
          num_trials: task.num_trials ?? 3,
        })),
      },
      ...(target ? { connection: target } : {}),
    },
    files,
  );
}

// The opening owns the mode and the connection draft, so the mode carries between the two views.
export type ManualFormProps = {
  onBack: () => void;
  connectionDraft: ConnectionDraft;
  onConnectionDraft: (draft: ConnectionDraft) => void;
  connectionResult: ConnectionCheckResult | null;
  onTestConnection: () => void;
  // Checks the draft and stores the result. Download calls it when no result is current.
  checkConnection: () => Promise<ConnectionCheckResult>;
};

export function ManualForm({
  onBack,
  connectionDraft,
  onConnectionDraft,
  connectionResult,
  onTestConnection,
  checkConnection,
}: ManualFormProps) {
  const [experiment, setExperiment] = useState<ManualExperiment>(
    emptyManualExperiment,
  );
  const [library, setLibrary] = useState<ManualFixture[]>([]);
  const [graders, setGraders] = useState<GraderSpec[] | null>(null);
  const [catalogueError, setCatalogueError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [focusTarget, setFocusTarget] = useState<FocusTarget>(null);
  const [editingPersonas, setEditingPersonas] = useState<number[]>([]);
  // Field errors stay hidden until the first download attempt, then update as the user types.
  const [showErrors, setShowErrors] = useState(false);
  const [submitAttempt, setSubmitAttempt] = useState(0);
  const formRef = useRef<HTMLDivElement | null>(null);
  const connectionRef = useRef<HTMLElement | null>(null);
  const runMode = connectionDraft.mode === "run";
  const connectionInvalid = runMode && connectionResult?.binding === null;

  const personaIdRefs = useRef<Array<HTMLInputElement | null>>([]);
  const scenarioIdRefs = useRef<Array<HTMLInputElement | null>>([]);
  const taskPersonaRefs = useRef<Array<HTMLSelectElement | null>>([]);

  const loadGraders = useCallback(() => {
    let live = true;
    setCatalogueError(null);
    void api.graders().then(
      (rows) => {
        if (live) setGraders(manualGraders(rows));
      },
      (cause) => {
        if (!live) return;
        setCatalogueError(
          cause instanceof TransportError
            ? cause.message
            : "Could not load the grader library. Try again.",
        );
      },
    );
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => loadGraders(), [loadGraders]);

  useEffect(() => {
    if (
      focusManualInput(
        focusTarget,
        personaIdRefs.current,
        scenarioIdRefs.current,
        taskPersonaRefs.current,
      )
    ) {
      setFocusTarget(null);
    }
  }, [
    experiment.personas.length,
    experiment.scenarios.length,
    experiment.tasks.length,
    focusTarget,
  ]);

  const fieldErrors = useMemo(
    () => manualFieldErrors(experiment, library),
    [experiment, library],
  );
  const ready = fieldErrors.length === 0;
  const errorFor = (field: string): string | undefined =>
    showErrors
      ? fieldErrors.find((value) => value.field === field)?.message
      : undefined;

  useEffect(() => {
    if (!submitAttempt) return;
    formRef.current
      ?.querySelector<HTMLElement>('[aria-invalid="true"]')
      ?.focus();
  }, [submitAttempt]);
  const personaIds = useMemo(
    () =>
      experiment.personas.map((persona) => persona.id.trim()).filter(Boolean),
    [experiment.personas],
  );

  const updatePersona = (index: number, patch: Partial<ManualPersona>) => {
    setExperiment((current) => {
      const previousId = current.personas[index]?.id ?? "";
      const personas = current.personas.map((persona, position) =>
        position === index ? { ...persona, ...patch } : persona,
      );
      const nextId = personas[index]?.id ?? "";
      return {
        ...current,
        personas,
        tasks:
          patch.id === undefined
            ? current.tasks
            : replaceTaskReference(
                current.tasks,
                "persona_ref",
                previousId,
                nextId,
              ),
      };
    });
  };

  const removePersona = (index: number) => {
    setEditingPersonas((current) => removeItemIndex(current, index));
    setExperiment((current) => {
      const removedId = current.personas[index]?.id ?? "";
      return {
        ...current,
        personas: current.personas.filter((_, position) => position !== index),
        tasks: replaceTaskReference(
          current.tasks,
          "persona_ref",
          removedId,
          "",
        ),
      };
    });
  };

  const updateScenario = (index: number, patch: Partial<ManualScenario>) => {
    setExperiment((current) => ({
      ...current,
      scenarios: current.scenarios.map((scenario, position) =>
        position === index ? { ...scenario, ...patch } : scenario,
      ),
      tasks:
        patch.id === undefined
          ? current.tasks
          : replaceTaskReference(
              current.tasks,
              "scenario_ref",
              current.scenarios[index].id,
              patch.id,
            ),
    }));
  };
  const removeScenario = (index: number) => {
    setExperiment((current) => ({
      ...current,
      scenarios: current.scenarios.filter((_, position) => position !== index),
      tasks: replaceTaskReference(
        current.tasks,
        "scenario_ref",
        current.scenarios[index].id,
        "",
      ),
    }));
  };
  const updateTask = (index: number, patch: Partial<ManualTestCase>) => {
    const tasks = experiment.tasks.map((task, position) =>
      position === index ? { ...task, ...patch } : task,
    );
    setExperiment((current) => ({ ...current, tasks }));
    setLibrary((current) => keepReferencedFixtures(tasks, current));
  };
  const removeTask = (index: number) => {
    const tasks = experiment.tasks.filter((_, position) => position !== index);
    setExperiment((current) => ({ ...current, tasks }));
    setLibrary((current) => keepReferencedFixtures(tasks, current));
  };

  const uploadFiles = (index: number, files: File[]) => {
    const names = validateFixtureSelection(files, library);
    const added = files.map((file, position) => ({
      name: names[position] ?? file.name,
      size: file.size,
      blob: file,
    }));
    const tasks = experiment.tasks.map((task, position) =>
      position === index
        ? {
            ...task,
            fixtures: [
              ...task.fixtures,
              ...names.filter((name) => !task.fixtures.includes(name)),
            ],
          }
        : task,
    );
    setExperiment((current) => ({ ...current, tasks }));
    setLibrary((current) => [...current, ...added]);
  };

  const download = async () => {
    if (busy) return;
    if (!ready) {
      setShowErrors(true);
      // A closed Persona editor cannot show its field errors, so open it.
      const invalidPersonas = fieldErrors.flatMap((value) => {
        const match = /^persona\.(\d+)\./.exec(value.field);
        return match ? [Number(match[1])] : [];
      });
      setEditingPersonas((current) => [
        ...new Set([...current, ...invalidPersonas]),
      ]);
      setSubmitAttempt((value) => value + 1);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const archive = await packageManualExperiment(
        experiment,
        keepReferencedFixtures(experiment.tasks, library),
        runMode
          ? async () =>
              startConnection(
                connectionDraft,
                connectionResult ?? (await checkConnection()),
              )
          : null,
        (taskIds) =>
          setExperiment((current) =>
            current === experiment
              ? {
                  ...current,
                  tasks: current.tasks.map((task, index) => ({
                    ...task,
                    id: taskIds[index] ?? task.id,
                  })),
                }
              : current,
          ),
      );
      if (!archive) {
        connectionRef.current?.focus();
        return;
      }
      downloadArchive(archive);
    } catch (cause) {
      setError(
        cause instanceof TransportError
          ? cause.message
          : "Could not build the specification. Try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  const addPersona = () => {
    const index = experiment.personas.length;
    setFocusTarget({ kind: "persona", index });
    setEditingPersonas((current) => openItem(current, index));
    setExperiment((value) => ({
      ...value,
      personas: [...value.personas, emptyManualPersona()],
    }));
  };
  const addScenario = () => {
    setFocusTarget({ kind: "scenario", index: experiment.scenarios.length });
    setExperiment((current) => ({
      ...current,
      scenarios: [...current.scenarios, emptyManualScenario()],
    }));
  };
  const addTask = () => {
    setFocusTarget({ kind: "task", index: experiment.tasks.length });
    setExperiment((current) => ({
      ...current,
      tasks: [...current.tasks, emptyManualTestCase()],
    }));
  };

  return (
    <div className="quiet-scrollbar flex-1 overflow-y-auto [scrollbar-gutter:stable] px-5 py-5 sm:px-10 sm:py-6">
      <div
        ref={formRef}
        className="mx-auto flex w-full max-w-4xl flex-col gap-7 pb-6"
      >
        <header className="flex flex-col gap-3">
          <button
            type="button"
            onClick={onBack}
            className="flex w-fit items-center gap-2 text-sm text-muted-foreground transition-colors hover:text-foreground"
          >
            <ArrowLeft size={15} strokeWidth={1.75} aria-hidden />
            Return to the opening screen
          </button>
          <div className="max-w-2xl">
            <h1 className="text-2xl font-semibold tracking-tight text-foreground">
              Write the experiment yourself
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Define what to run and how to score it. METIS will build a
              ready-to-use experiment package.
            </p>
          </div>
        </header>

        {/* The mode and the download stay in view while the user scrolls the long form. */}
        <div className="sticky -top-5 z-10 -mx-1 -mt-3 flex flex-col gap-2 border-b border-border bg-background px-1 py-3 sm:-top-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <ModePicker
              mode={connectionDraft.mode}
              disabled={busy}
              onSelect={(mode) =>
                onConnectionDraft({ ...connectionDraft, mode })
              }
            />
            {/* An incomplete form greys the button out, but a click still marks the fields to fix,
                so the button is only aria-disabled. */}
            <Button
              variant="primary"
              disabled={busy}
              aria-disabled={!ready}
              className="aria-disabled:cursor-not-allowed aria-disabled:opacity-45"
              title={
                ready
                  ? "Extract the download into experiments/design/."
                  : "Complete the marked fields first."
              }
              onClick={() => void download()}
            >
              <Download size={15} strokeWidth={1.75} aria-hidden />
              {busy ? "Building specification…" : "Download specification"}
            </Button>
          </div>
          {connectionInvalid && (
            <p role="alert" className="text-right text-sm text-destructive">
              The target connection is not valid.
            </p>
          )}
          {error && (
            <p role="alert" className="text-right text-sm text-destructive">
              {error}
            </p>
          )}
        </div>

        <section
          aria-labelledby="manual-specification"
          className="flex flex-col gap-7"
        >
          <h2
            id="manual-specification"
            className="text-lg font-semibold text-foreground"
          >
            Specification
          </h2>
          <FormSection
            id="manual-experiment-details"
            title="Experiment details"
          >
            <div className={cn(CARD, "flex flex-col gap-3 p-4")}>
              <Field label="ID" error={errorFor("experiment.id")}>
                <TextInput
                  id="manual-experiment-id"
                  invalid={Boolean(errorFor("experiment.id"))}
                  ariaLabel="Experiment ID"
                  value={experiment.id}
                  placeholder="research-assistant"
                  spellCheck={false}
                  onChange={(id) =>
                    setExperiment((value) => ({ ...value, id }))
                  }
                />
              </Field>
              <Field
                label="Description"
                error={errorFor("experiment.description")}
              >
                <TextArea
                  id="manual-experiment-description"
                  invalid={Boolean(errorFor("experiment.description"))}
                  ariaLabel="Experiment description"
                  value={experiment.description}
                  placeholder="What this Experiment evaluates."
                  rows={2}
                  onChange={(description) =>
                    setExperiment((value) => ({ ...value, description }))
                  }
                />
              </Field>
            </div>
          </FormSection>

          <FormSection
            id="manual-personas"
            title="Personas"
            action={
              <IconButton label="Add Persona" onClick={addPersona}>
                <Plus size={16} strokeWidth={1.75} aria-hidden />
              </IconButton>
            }
          >
            {experiment.personas.length === 0 && (
              <EmptyRow error={errorFor("personas")}>No Personas yet.</EmptyRow>
            )}
            {experiment.personas.map((persona, index) => {
              const itemLabel = itemContext("Persona", index, persona.id);
              const isEditing = editingPersonas.includes(index);
              const canFinish = Boolean(
                persona.id.trim() && persona.description.trim(),
              );
              return (
                <ItemCard
                  key={index}
                  headingId={`manual-persona-${index}-heading`}
                  heading={itemHeading("Persona", persona.id)}
                  actions={
                    <>
                      <IconButton
                        size="small"
                        disabled={isEditing && !canFinish}
                        hint={
                          isEditing && !canFinish
                            ? "Enter an ID and description first."
                            : undefined
                        }
                        label={
                          isEditing
                            ? `Finish editing ${itemLabel}`
                            : `Edit ${itemLabel}`
                        }
                        onClick={() => {
                          if (isEditing) {
                            setEditingPersonas((current) =>
                              closeItem(current, index),
                            );
                            return;
                          }
                          setFocusTarget({ kind: "persona", index });
                          setEditingPersonas((current) =>
                            openItem(current, index),
                          );
                        }}
                      >
                        {isEditing ? (
                          <Check size={14} strokeWidth={1.75} aria-hidden />
                        ) : (
                          <Pencil size={14} strokeWidth={1.75} aria-hidden />
                        )}
                      </IconButton>
                      <RemoveButton
                        label={`Remove ${itemLabel}`}
                        onClick={() => removePersona(index)}
                      />
                    </>
                  }
                >
                  {isEditing ? (
                    <DefinitionFields
                      kind="persona"
                      index={index}
                      itemLabel={itemLabel}
                      value={persona}
                      idPlaceholder="policy-analyst"
                      descriptionPlaceholder="How this person acts during the evaluation."
                      idRef={(element) => {
                        personaIdRefs.current[index] = element;
                      }}
                      errorFor={errorFor}
                      onChange={(patch) => updatePersona(index, patch)}
                    />
                  ) : (
                    <DefinitionSummary value={persona} />
                  )}
                </ItemCard>
              );
            })}
          </FormSection>

          <FormSection
            id="manual-scenarios"
            title="Scenarios"
            action={
              <IconButton label="Add Scenario" onClick={addScenario}>
                <Plus size={16} strokeWidth={1.75} aria-hidden />
              </IconButton>
            }
          >
            {!experiment.scenarios.length && (
              <EmptyRow error={errorFor("scenarios")}>
                No Scenarios yet.
              </EmptyRow>
            )}
            {experiment.scenarios.map((scenario, index) => {
              const unused =
                scenario.id.trim() &&
                !experiment.tasks.some(
                  (task) => task.scenario_ref === scenario.id.trim(),
                );
              return (
                <ItemCard
                  key={index}
                  headingId={`manual-scenario-${index}-heading`}
                  heading={itemHeading("Scenario", scenario.id)}
                  actions={
                    <RemoveButton
                      label={`Remove Scenario ${scenario.id || index + 1}`}
                      onClick={() => removeScenario(index)}
                    />
                  }
                >
                  <DefinitionFields
                    kind="scenario"
                    index={index}
                    itemLabel={`Scenario ${index + 1}`}
                    value={scenario}
                    idPlaceholder="supported-answer"
                    descriptionPlaceholder="Describe the situation and expected work."
                    idRef={(element) => {
                      scenarioIdRefs.current[index] = element;
                    }}
                    errorFor={errorFor}
                    onChange={(patch) => updateScenario(index, patch)}
                  />
                  {unused && (
                    <p
                      className={
                        errorFor(`scenario.${index}.tasks`)
                          ? "text-xs text-destructive"
                          : "text-xs text-muted-foreground"
                      }
                    >
                      Select this Scenario in at least one test case.
                    </p>
                  )}
                </ItemCard>
              );
            })}
          </FormSection>

          <FormSection
            id="manual-tasks"
            title="Test cases"
            action={
              <IconButton label="Add test case" onClick={addTask}>
                <Plus size={16} strokeWidth={1.75} aria-hidden />
              </IconButton>
            }
          >
            {!experiment.tasks.length && (
              <EmptyRow error={errorFor("tasks")}>
                No test cases yet. Add Personas and Scenarios first.
              </EmptyRow>
            )}
            {experiment.tasks.map((task, index) => {
              const itemLabel = itemContext("Test case", index, task.id);
              const prefix = `task.${index}`;
              return (
                <ItemCard
                  key={index}
                  heading={itemLabel}
                  actions={
                    <RemoveButton
                      label={`Remove ${itemLabel}`}
                      onClick={() => removeTask(index)}
                    />
                  }
                >
                  <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_10rem]">
                    <Field
                      label="Persona"
                      error={errorFor(`${prefix}.persona`)}
                    >
                      <SelectInput
                        invalid={Boolean(errorFor(`${prefix}.persona`))}
                        selectRef={(element) => {
                          taskPersonaRefs.current[index] = element;
                        }}
                        ariaLabel={`${itemLabel}, Persona`}
                        value={task.persona_ref}
                        placeholder="Select a Persona"
                        choices={personaIds.map((id) => ({
                          value: id,
                          label: id,
                        }))}
                        onChange={(persona_ref) =>
                          updateTask(index, { persona_ref })
                        }
                      />
                    </Field>
                    <Field
                      label="Scenario"
                      error={errorFor(`${prefix}.scenario`)}
                    >
                      <SelectInput
                        invalid={Boolean(errorFor(`${prefix}.scenario`))}
                        ariaLabel={`${itemLabel}, Scenario`}
                        value={task.scenario_ref}
                        placeholder="Select a Scenario"
                        choices={experiment.scenarios
                          .filter((s) => s.id.trim())
                          .map((s) => ({
                            value: s.id.trim(),
                            label: s.id.trim(),
                          }))}
                        onChange={(scenario_ref) =>
                          updateTask(index, { scenario_ref })
                        }
                      />
                    </Field>
                    <Field label="Trials" error={errorFor(`${prefix}.trials`)}>
                      <NumberInput
                        value={task.num_trials}
                        min={1}
                        max={20}
                        ariaLabel={`${itemLabel}, Trials`}
                        onChange={(num_trials) =>
                          updateTask(index, { num_trials })
                        }
                      />
                    </Field>
                  </div>
                  <GraderPicker
                    itemLabel={itemLabel}
                    searchId={`manual-task-${index}-grader-search`}
                    graders={graders}
                    error={catalogueError}
                    invalid={errorFor(`${prefix}.graders`)}
                    selected={task.graders.map((grader) => grader.spec.fqn)}
                    onRetry={() => loadGraders()}
                    onToggle={(grader) =>
                      updateTask(
                        index,
                        task.graders.some(
                          (selected) => selected.spec.fqn === grader.fqn,
                        )
                          ? deselectGrader(task, grader.fqn)
                          : selectGrader(task, grader),
                      )
                    }
                  />
                  {task.graders.map((grader) => (
                    <GraderSettings
                      key={grader.spec.fqn}
                      itemLabel={itemLabel}
                      grader={grader}
                      errorFor={(field) =>
                        errorFor(
                          `${prefix}.settings.${grader.spec.fqn}.${field}`,
                        )
                      }
                      onChange={(patch) =>
                        updateTask(
                          index,
                          updateGrader(task, grader.spec.fqn, patch),
                        )
                      }
                      onRemove={() =>
                        updateTask(index, deselectGrader(task, grader.spec.fqn))
                      }
                    />
                  ))}
                  <FixturePicker
                    itemLabel={itemLabel}
                    inputId={`manual-task-${index}-files`}
                    names={task.fixtures}
                    invalid={errorFor(`${prefix}.files`)}
                    onAdd={(files) => uploadFiles(index, files)}
                    onRemove={(name) =>
                      updateTask(index, {
                        fixtures: task.fixtures.filter(
                          (value) => value !== name,
                        ),
                      })
                    }
                  />
                </ItemCard>
              );
            })}
            <p className="text-sm text-muted-foreground">
              Total:{" "}
              {formatTrials(
                experiment.tasks.reduce(
                  (total, task) => total + task.num_trials,
                  0,
                ),
              )}
            </p>
          </FormSection>
        </section>

        {runMode && (
          // The download moves the focus here when the connection is not valid.
          <section
            ref={connectionRef}
            tabIndex={-1}
            aria-labelledby="manual-connection"
            className="mt-4 flex flex-col gap-3 border-t border-border pt-8 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <h2
              id="manual-connection"
              className="text-lg font-semibold text-foreground"
            >
              Target connection
            </h2>
            <div className="rounded-lg border border-border bg-muted/40 p-4">
              <ConnectionForm
                draft={connectionDraft}
                onDraft={onConnectionDraft}
                result={connectionResult}
                busy={busy}
                onTest={onTestConnection}
              />
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

// A top-level part of the form: a plain heading row over its cards.
function FormSection({
  id,
  title,
  action,
  children,
}: {
  id: string;
  title: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="flex flex-col gap-3">
      <div className="flex min-h-9 items-center justify-between gap-3">
        <h3 id={id} className="text-base font-semibold text-foreground">
          {title}
        </h3>
        {action}
      </div>
      {children}
    </section>
  );
}

const CARD = "overflow-hidden rounded-lg border border-accent/25 bg-background";

function ItemCard({
  heading,
  headingId,
  actions,
  children,
}: {
  heading: string;
  headingId?: string;
  actions: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <article aria-labelledby={headingId} className={CARD}>
      <div className="flex min-h-11 items-center justify-between gap-3 border-b border-accent/25 bg-accent/[0.06] px-4 py-1.5">
        <h4
          id={headingId}
          className="min-w-0 truncate text-sm font-semibold text-accent"
        >
          {heading}
        </h4>
        <div className="flex shrink-0 items-center gap-1">{actions}</div>
      </div>
      <div className="flex flex-col gap-3 p-4">{children}</div>
    </article>
  );
}

type Definition = ManualPersona | ManualScenario;

function DefinitionFields({
  kind,
  index,
  itemLabel,
  value,
  idPlaceholder,
  descriptionPlaceholder,
  idRef,
  errorFor,
  onChange,
}: {
  kind: "persona" | "scenario";
  index: number;
  itemLabel: string;
  value: Definition;
  idPlaceholder: string;
  descriptionPlaceholder: string;
  idRef: (element: HTMLInputElement | null) => void;
  errorFor: (field: string) => string | undefined;
  onChange: (patch: Partial<Definition>) => void;
}) {
  const prefix = `${kind}.${index}`;
  return (
    <>
      <Field label="ID" error={errorFor(`${prefix}.id`)}>
        <TextInput
          id={`manual-${kind}-${index}-id`}
          invalid={Boolean(errorFor(`${prefix}.id`))}
          inputRef={idRef}
          ariaLabel={`${itemLabel}, ID`}
          value={value.id}
          placeholder={idPlaceholder}
          spellCheck={false}
          onChange={(id) => onChange({ id })}
        />
      </Field>
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Description" error={errorFor(`${prefix}.description`)}>
          <TextArea
            id={`manual-${kind}-${index}-description`}
            invalid={Boolean(errorFor(`${prefix}.description`))}
            ariaLabel={`${itemLabel}, Description`}
            value={value.description}
            placeholder={descriptionPlaceholder}
            rows={3}
            onChange={(description) => onChange({ description })}
          />
        </Field>
        <KeyValueEditor
          title="Metadata (Optional)"
          entries={value.metadata}
          rowLabel={(row) => `${itemLabel}, metadata ${row}`}
          addLabel={`Add metadata to ${itemLabel}`}
          errorFor={(row) => errorFor(`${prefix}.metadata.${row}.key`)}
          onChange={(metadata) => onChange({ metadata })}
        />
      </div>
    </>
  );
}

function DefinitionSummary({ value }: { value: Definition }) {
  const metadata = value.metadata ?? [];
  return (
    <div className="grid gap-3 md:grid-cols-2">
      <p className="text-sm text-muted-foreground">
        {value.description.trim()}
      </p>
      {metadata.length > 0 && (
        <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-0.5">
          {metadata.map((entry, row) => (
            <div key={row} className="contents">
              <dt>
                <Mono>{entry.key}</Mono>
              </dt>
              <dd className="truncate">
                <Mono>{entry.value}</Mono>
              </dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

function GraderSettings({
  itemLabel,
  grader,
  errorFor,
  onChange,
  onRemove,
}: {
  itemLabel: string;
  grader: ManualGrader;
  /** Takes the field after the grader prefix, such as `description` or `values.threshold`. */
  errorFor: (field: string) => string | undefined;
  onChange: (
    patch: Partial<Pick<ManualGrader, "description" | "values">>,
  ) => void;
  onRemove: () => void;
}) {
  const name = grader.spec.name;
  const settings = grader.spec.settings ?? [];
  return (
    <div
      role="group"
      aria-label={`${itemLabel}, ${name} settings`}
      className="rounded-lg border border-border"
    >
      <div className="flex items-center justify-between gap-3 border-b border-border px-3 py-1.5">
        <span className="min-w-0 truncate text-sm font-medium text-foreground">
          {name}
        </span>
        <RemoveButton
          label={`Remove ${name} from ${itemLabel}`}
          size="small"
          onClick={onRemove}
        />
      </div>
      <div className="grid gap-3 p-3 md:grid-cols-2">
        <Field label="Description" error={errorFor("description")} fill>
          <TextArea
            ariaLabel={`${itemLabel}, ${name}, Description`}
            invalid={Boolean(errorFor("description"))}
            value={grader.description}
            rows={3}
            fill
            onChange={(description) => onChange({ description })}
          />
        </Field>
        <div
          role="group"
          aria-label="Settings"
          className="flex min-w-0 flex-col gap-1.5"
        >
          <span className="flex h-5 shrink-0 items-center text-xs font-medium text-muted-foreground">
            Settings
          </span>
          <div className="flex max-h-56 flex-col gap-1.5 overflow-y-auto">
            {/* The catalogue lists the common settings first, then the grader's own settings. */}
            {settings.map((setting) => (
              <GraderSettingRow
                key={setting.name}
                label={`${itemLabel}, ${name}, ${setting.name}`}
                setting={setting}
                value={grader.values[setting.name] ?? ""}
                error={errorFor(`values.${setting.name}`)}
                onChange={(value) =>
                  onChange({
                    values: { ...grader.values, [setting.name]: value },
                  })
                }
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// The text a setting shows when it is empty. A required setting has no default to fall back on.
const SETTING_PLACEHOLDERS: Record<GraderSetting["kind"], string> = {
  number: "number",
  integer: "integer",
  boolean: "true or false",
  text: "text",
  list: "list as JSON",
  choice: "choice",
  object: "object as JSON",
};

function GraderSettingRow({
  label,
  setting,
  value,
  error,
  onChange,
}: {
  /** Names the control for assistive technology, such as `Test case 1, Relevance, turn`. */
  label: string;
  setting: GraderSetting;
  value: string;
  error?: string;
  onChange: (value: string) => void;
}) {
  const choices =
    setting.kind === "boolean"
      ? ["true", "false"]
      : setting.kind === "choice"
        ? (setting.choices ?? [])
        : null;
  return (
    <div className="flex flex-col gap-1">
      <div className="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] items-center gap-2">
        <span
          title={setting.description ?? undefined}
          className="flex min-w-0 items-baseline gap-1.5"
        >
          <span className="truncate font-mono text-xs text-foreground">
            {setting.name}
          </span>
          {setting.required && (
            <span className="shrink-0 text-xs text-destructive">
              <span aria-hidden>*</span>
              <span className="sr-only">required</span>
            </span>
          )}
        </span>
        {choices ? (
          <SelectInput
            ariaLabel={label}
            value={value}
            choices={choices.map((choice) => ({
              value: choice,
              label: choice,
            }))}
            placeholder={setting.required ? undefined : "Default"}
            invalid={Boolean(error)}
            density="inline"
            onChange={onChange}
          />
        ) : (
          <TextInput
            ariaLabel={label}
            value={value}
            placeholder={
              setting.required ? "required" : SETTING_PLACEHOLDERS[setting.kind]
            }
            spellCheck={false}
            density="inline"
            invalid={Boolean(error)}
            className="font-mono"
            onChange={onChange}
          />
        )}
      </div>
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}

// The taxonomy fields that a grader row shows as chips. Each field has one colour, so the user can
// compare rows at a glance. The hover hint names the field, so the colour is not the only signal.
const TAXONOMY_CHIPS = [
  { field: "grader_types", label: "Grader type", tone: "tag-type" },
  { field: "scopes", label: "Scope", tone: "tag-scope" },
  { field: "reference_types", label: "Reference type", tone: "tag-reference" },
  { field: "judgment_forms", label: "Judgment form", tone: "tag-judgment" },
] as const;

function TaxonomyChips({ grader }: { grader: GraderSpec }) {
  const taxonomy = grader.taxonomy;
  if (!taxonomy) return null;
  const chips = TAXONOMY_CHIPS.flatMap(({ field, label, tone }) =>
    taxonomy[field].map((value) => ({
      key: `${field}.${value}`,
      label,
      tone,
      value,
    })),
  );
  if (chips.length === 0) return null;
  return (
    <span className="mt-1 flex flex-wrap gap-1">
      {chips.map((chip) => (
        <span
          key={chip.key}
          title={chip.label}
          className={cn("tag rounded px-1.5 py-px text-[11px]", chip.tone)}
        >
          <span className="sr-only">{chip.label}: </span>
          {taxonomyLabel(chip.value)}
        </span>
      ))}
    </span>
  );
}

function GraderPicker({
  itemLabel,
  searchId,
  graders,
  error,
  selected,
  invalid,
  onRetry,
  onToggle,
}: {
  itemLabel: string;
  searchId: string;
  graders: GraderSpec[] | null;
  error: string | null;
  /** The FQNs of the selected graders. */
  selected: string[];
  invalid?: string;
  onRetry: () => void;
  onToggle: (grader: GraderSpec) => void;
}) {
  const [query, setQuery] = useState("");
  const groups = useMemo(
    () => graderGroups(graders ?? [], query),
    [graders, query],
  );

  return (
    <fieldset
      aria-label={`${itemLabel}, Graders`}
      className="flex flex-col gap-2"
    >
      <legend className="text-xs font-medium text-muted-foreground">
        Graders
      </legend>
      {error ? (
        <div
          className="flex items-center gap-3 text-sm text-destructive"
          role="alert"
        >
          <span>{error}</span>
          <Button variant="ghost" className="text-xs" onClick={onRetry}>
            Retry
          </Button>
        </div>
      ) : graders === null ? (
        <p className="text-sm text-muted-foreground">Loading graders…</p>
      ) : (
        <>
          {/* One box: the search is its top row, and the list scrolls under it. The box clips
              the list, so the scrollbar stays inside the rounded corners. */}
          <div
            className={cn(
              "flex flex-col overflow-hidden rounded-md border focus-within:border-ring",
              invalid ? "border-destructive" : "border-input",
            )}
          >
            <label className="sr-only" htmlFor={searchId}>
              Search graders
            </label>
            <div className="flex items-center gap-2 border-b border-border px-3">
              <Search
                size={15}
                strokeWidth={1.75}
                aria-hidden
                className="shrink-0 text-muted-foreground"
              />
              <input
                id={searchId}
                type="search"
                aria-label={`${itemLabel}, Search graders`}
                aria-invalid={Boolean(invalid)}
                value={query}
                placeholder="Search"
                onChange={(event) => setQuery(event.target.value)}
                className="h-9 min-w-0 flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none"
              />
            </div>
            <div className="quiet-scrollbar max-h-[28rem] overflow-y-auto">
              {groups.map((group) => (
                <div
                  key={group.label}
                  role="group"
                  aria-label={group.label}
                  className="last:[&>label:last-child]:border-b-0"
                >
                  <p className="sticky top-0 z-10 border-b border-border bg-muted px-3 py-1.5 text-xs font-medium text-muted-foreground">
                    {group.label}
                  </p>
                  {group.graders.map((grader) => {
                    const checked = selected.includes(grader.fqn);
                    return (
                      <label
                        key={grader.fqn}
                        className="flex cursor-pointer items-start gap-3 border-b border-border px-3 py-2.5 hover:bg-muted/60"
                      >
                        <input
                          type="checkbox"
                          aria-label={`${itemLabel}, ${grader.name}`}
                          checked={checked}
                          onChange={() => onToggle(grader)}
                          className="mt-1 h-4 w-4 accent-[hsl(var(--accent))]"
                        />
                        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                          <span className="text-sm font-medium text-foreground">
                            {grader.name}
                          </span>
                          <span className="text-xs text-muted-foreground">
                            {grader.description}
                          </span>
                          <TaxonomyChips grader={grader} />
                        </span>
                      </label>
                    );
                  })}
                </div>
              ))}
              {groups.length === 0 && (
                <p className="px-3 py-3 text-sm text-muted-foreground">
                  No graders match this search.
                </p>
              )}
            </div>
          </div>
          {invalid && <p className="text-xs text-destructive">{invalid}</p>}
          {selected.length > 0 && (
            <p className="text-xs text-muted-foreground">
              {selected.length} {selected.length === 1 ? "grader" : "graders"}{" "}
              selected
            </p>
          )}
        </>
      )}
    </fieldset>
  );
}

function FixturePicker({
  itemLabel,
  inputId,
  names,
  invalid,
  onAdd,
  onRemove,
}: {
  itemLabel: string;
  inputId: string;
  names: string[];
  invalid?: string;
  onAdd: (files: File[]) => void;
  onRemove: (name: string) => void;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [error, setError] = useState<string | null>(null);
  return (
    <fieldset
      aria-label={`${itemLabel}, Fixtures`}
      className="flex flex-col gap-2"
    >
      <legend className="text-xs font-medium text-muted-foreground">
        Fixtures (files the target can use in each trial)
      </legend>
      <div className="flex flex-wrap items-center gap-2">
        <label className="inline-flex h-9 cursor-pointer items-center gap-2 rounded-md border border-input bg-background px-3 text-sm text-foreground transition-colors hover:bg-muted">
          <Upload size={14} strokeWidth={1.75} aria-hidden />
          Choose files
          <input
            ref={inputRef}
            id={inputId}
            type="file"
            multiple
            accept={ACCEPTED_FIXTURE_EXTENSIONS.map(
              (value) => `.${value}`,
            ).join(",")}
            aria-label={`${itemLabel}, Choose files`}
            className="sr-only"
            onChange={(event) => {
              const files = Array.from(event.target.files ?? []);
              setError(null);
              try {
                onAdd(files);
              } catch (cause) {
                setError(
                  cause instanceof Error
                    ? cause.message
                    : "Could not add the files.",
                );
              } finally {
                if (inputRef.current) inputRef.current.value = "";
              }
            }}
          />
        </label>
        {names.length === 0 && (
          <span className="text-sm text-muted-foreground">
            No files selected
          </span>
        )}
      </div>
      {names.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {names.map((name) => (
            <span
              key={name}
              className="inline-flex min-w-0 items-center gap-2 rounded-md border border-border px-2 py-1"
            >
              <Mono className="max-w-56 truncate">{name}</Mono>
              <button
                type="button"
                aria-label={`Remove ${name}`}
                onClick={() => onRemove(name)}
                className="text-muted-foreground hover:text-foreground"
              >
                <X size={13} strokeWidth={2} aria-hidden />
              </button>
            </span>
          ))}
        </div>
      )}
      {(error ?? invalid) && (
        <p role="alert" className="text-xs text-destructive">
          {error ?? invalid}
        </p>
      )}
    </fieldset>
  );
}

function EmptyRow({
  error,
  children,
}: {
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        "rounded-lg border border-dashed px-3 py-3 text-sm text-muted-foreground",
        error ? "border-destructive" : "border-border",
      )}
    >
      {children}
      {error && <p className="mt-1 text-xs text-destructive">{error}</p>}
    </div>
  );
}

function RemoveButton({
  label,
  size = "default",
  onClick,
}: {
  label: string;
  size?: "default" | "small";
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground active:bg-border",
        size === "small" ? "h-7 w-7" : "h-8 w-8",
      )}
    >
      <X size={size === "small" ? 14 : 16} strokeWidth={1.75} aria-hidden />
    </button>
  );
}

// A square button that shows only an icon. The label is the accessible name, and the hover hint
// when no other hint is given.
function IconButton({
  label,
  hint,
  size = "default",
  disabled,
  onClick,
  children,
}: {
  label: string;
  hint?: string;
  size?: "default" | "small";
  disabled?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={hint ?? label}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-md border border-border bg-background text-foreground transition-colors duration-150 hover:bg-muted active:bg-border disabled:cursor-not-allowed disabled:opacity-45",
        size === "small" ? "h-7 w-7" : "h-8 w-8",
      )}
    >
      {children}
    </button>
  );
}
