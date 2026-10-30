import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import type {
  Behaviour,
  GraderSpec,
  Specification,
  Feature,
  WizardRequest,
} from "./transport/api";
import { PanelRight } from "lucide-react";
import { RevealText } from "./RevealText";
import {
  KeepInPlaceContext,
  useKeepAnchor,
  useKeepInPlace,
} from "./keep-in-place";
import { Button, Chip, cn, Disclosure, formatTrials, Mono } from "./ui";

// ── where the interview has got to ───────────────────────────────────────────

// The package stamps a title, a one-based position and a total onto every request it composes.
// This is the door reading them, and it is the whole of the door's knowledge of the interview's
// shape: it holds no list of steps, counts no sections, and derives no position of its own, so it
// cannot drift from the package the way a second copy of the step order would.
export interface StepPosition {
  title: string | null;
  step: number;
  steps: number;
}

// The newest request carrying step metadata. Searched from the end because the pending request is
// the one that says where the interview is now, and older requests keep their own — stale —
// positions in the scrollback. Requests carrying none yield null: the terminal step is stamped
// with nothing, and a interview persisted before the metadata existed has nothing either, so both
// draw no position rather than a wrong one.
export function stepPosition(requests: WizardRequest[]): StepPosition | null {
  for (let i = requests.length - 1; i >= 0; i--) {
    const request = requests[i];
    if (request.step != null && request.steps != null) {
      return {
        title: request.title ?? null,
        step: request.step,
        steps: request.steps,
      };
    }
  }
  return null;
}

// Which section-level placeholder an in-flight model call is writing into.
//
// `config.yaml` is offset by one on purpose — the status for a step names the work that
// continuing *from* it starts. That offset is what lets the interview's current step alone identify
// the target, with no new field on the wire and no guessing.
//
// Criteria land *inside* the Behaviours section as per-behaviour blanks, not as a section-level
// placeholder. The blanks stay hidden while measurement selection is still pending, then appear
// after Continue and the arrival animation runs as each criterion mounts.
//
// Clarify now writes the Target section on every useful answer, so it follows the same rule as the
// later drafting steps instead of being a special case.
type WritingTarget =
  "target" | "behaviours" | "personas" | "scenarios" | "test-cases";

const WRITING_TARGET: Record<string, WritingTarget> = {
  clarify: "target",
  behaviours: "behaviours",
  criteria: "personas",
  personas: "scenarios",
  scenarios: "test-cases",
};

export function SpecificationView({
  specification,
  excludedTasks = [],
  position,
  interviewStep,
  busy,
  showGraders,
  onShowGradersChange,
  graderByFqn,
  gradersLoading,
  gradersError,
  onCollapse,
  onFinish,
  onDownload,
  done,
  activeSections = [],
  renderReview,
  renderSectionActions,
}: {
  // The Profile sections that the live review fills, in order.
  activeSections?: readonly string[];
  // The live review for one of those sections, drawn in place of its document content.
  renderReview?: (section: string) => ReactNode;
  // Actions for a Profile section heading, such as "+ Add a Persona".
  renderSectionActions?: (section: string) => ReactNode;
  specification: Specification;
  // Test Cases that the user cleared; they are shown, but they do not count or run.
  excludedTasks?: readonly string[];
  position?: StepPosition | null;
  interviewStep?: string;
  busy?: boolean;
  showGraders: boolean;
  onShowGradersChange: (show: boolean) => void;
  graderByFqn: ReadonlyMap<string, GraderSpec>;
  gradersLoading: boolean;
  gradersError: boolean;
  onCollapse?: () => void;
  // The shell owns whether the local Interview has reached its end.
  done?: boolean;
  onFinish?: () => void;
  onDownload?: () => void;
}) {
  const excluded = new Set(excludedTasks);
  const selectedTasks = specification.tasks.filter(
    (task) => !excluded.has(task.id),
  );
  const activeSection = activeSections[0] ?? null;
  const activeKey = activeSections.join(" ");
  const activeRef = useRef<HTMLDivElement>(null);
  const sheetRef = useRef<HTMLDivElement>(null);
  const keepInPlace = useKeepInPlace(sheetRef, Boolean(busy));
  // When a review opens on a section, bring its top into view once. A review already in view does
  // not move, and later size changes inside the sheet never scroll it: the user's place is theirs.
  useLayoutEffect(() => {
    const sheet = sheetRef.current;
    const active = activeRef.current;
    if (!sheet || !active || !activeSection) return;
    const spacer = sheet.querySelector<HTMLElement>("[data-keep-spacer]");
    if (spacer) spacer.style.height = "0px";
    const top =
      active.getBoundingClientRect().top - sheet.getBoundingClientRect().top;
    if (top >= 0 && top < sheet.clientHeight - 64) return;
    sheet.scrollTop += top - 64;
  }, [activeKey]);
  const reviewing = (section: string) => activeSections.includes(section);
  // The first reviewed section carries the ref that the one-time scroll above measures.
  const currentReview = (section: string) => (
    <div
      ref={section === activeSection ? activeRef : undefined}
      className="scroll-mt-16"
    >
      {renderReview?.(section)}
    </div>
  );
  const actions = (section: string) =>
    reviewing(section) ? renderSectionActions?.(section) : undefined;
  const mode = (section: string): SectionMode =>
    activeSections.length === 0
      ? "idle"
      : reviewing(section)
        ? "current"
        : "frozen";
  const { target } = specification;
  const { features } = specification;
  const writing =
    busy && interviewStep ? WRITING_TARGET[interviewStep] : undefined;
  const hasCriteria = features.some((feature) =>
    feature.behaviours.some((behaviour) => behaviour.criteria.length > 0),
  );
  const gradersAvailable = !gradersLoading && !gradersError;

  // The user is choosing which behaviours to measure on the combined Behaviours screen, and a
  // criteria blank must not appear until that choice is committed with Continue. The commit signal
  // is the *step*, not `busy`: a tick is a live server round-trip that recomposes the screen and
  // stays on it, so keying on `busy` would flash the blank on during every tick and off again when
  // the recomposed screen arrives. Keying on the step alone, the blank is suppressed for the whole
  // Behaviours step — idle or mid-tick — and appears only once Continue advances the interview off
  // it. (Continue is also what generates the criteria, so by the time the interview reports a later
  // step the blanks are usually already filled; one that remains is a behaviour whose criteria did
  // not draft, which is exactly what the blank should report.)
  const selecting = interviewStep === "behaviours";

  return (
    <div className="flex h-full min-h-0 flex-col p-4">
      <h1 className="mb-3 text-xl font-semibold">Profile</h1>
      {/* The strip above the sheet carries the pane's chrome — things that belong to the pane, not
          to the document. Progress sits on the left as six segments, one per interview step,
          filling left to right; the collapse control sits at the right. Both are outside the sheet
          so its corner stays free for the document header, and the segments read as a header for the
          page below rather than floating inside it. */}
      {(position || onCollapse) && (
        <div className="mb-2 flex shrink-0 items-center gap-3">
          {position && (
            <ProgressSegments
              step={position.step}
              steps={position.steps}
              title={position.title}
            />
          )}
          {onCollapse && (
            <button
              type="button"
              aria-label="Hide document"
              title="Hide document"
              onClick={onCollapse}
              className="ml-auto rounded p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <PanelRight size={16} strokeWidth={1.75} aria-hidden />
            </button>
          )}
        </div>
      )}

      {/* The sheet, not the pane, is the scroll container. Section headings stick to the top of
          the document as you scroll past them, and sticking is measured from the scrollport's
          edge — so the sheet has to be the thing that scrolls, or the headings would pin to the
          pane and float free of the page they belong to. The sheet's own padding moves inside,
          onto the content wrapper, leaving the scrollport's edge flush with the sheet's edge for
          the headings to meet. */}
      <div
        ref={sheetRef}
        className="quiet-scrollbar flex-1 overflow-y-auto overflow-x-hidden rounded-[12px] bg-card text-sm text-card-foreground shadow-sm"
      >
        <KeepInPlaceContext.Provider value={keepInPlace}>
          <div className="flex flex-col gap-8 px-5 pb-5">
            {/* The header carries only the pane's grader controls, pinned to the right. It draws
              nothing until there is a control to hold, so an early document opens straight onto
              Target rather than onto an empty strip. */}
            {!reviewing("behaviours") && (hasCriteria || gradersError) && (
              <header className="flex flex-wrap items-center justify-end gap-2 pt-5">
                {hasCriteria && (
                  <Button
                    type="button"
                    variant="ghost"
                    active={showGraders}
                    disabled={!gradersAvailable}
                    aria-pressed={showGraders}
                    title={
                      gradersError
                        ? "Grader details unavailable"
                        : "Show graders"
                    }
                    onClick={() => onShowGradersChange(!showGraders)}
                    className="px-2 py-1 text-xs"
                  >
                    Show graders
                  </Button>
                )}
                {gradersError && (
                  <span role="alert" className="text-xs text-destructive">
                    Grader details unavailable
                  </span>
                )}
              </header>
            )}

            <Section
              title="Target"
              writing={writing === "target"}
              mode={mode("target")}
            >
              <div className="flex flex-col gap-4">
                <TargetField label="Name" value={target.name} />
                <TargetField
                  label="Description"
                  value={target.description}
                  preserveLines
                />
                <TargetField label="Users" value={target.users} preserveLines />
                <TargetField
                  label="Details"
                  value={target.detail}
                  preserveLines
                />
              </div>
            </Section>

            {/* Sections run in the order the interview fills them, and every one of them is drawn
            whether or not it holds anything yet.

            Each heading is the package's own name for the step that fills it — "Behaviours",
            "Personas", "Scenarios" — so the document and the conversation use one vocabulary and the
            sheet reads as the interview's output section by section. They are entity names, all
            three of the same kind; "What should be true" was a sentence sitting between two nouns,
            which is what made it read as the odd one out. */}
            <Section
              title="Features / Expected Behaviours"
              actions={actions("behaviours")}
              mode={mode("behaviours")}
              writing={writing === "behaviours"}
            >
              {reviewing("behaviours") ? (
                currentReview("behaviours")
              ) : features.length > 0 ? (
                // Groups are set well apart from one another, so the section reads as a handful of
                // named groups rather than one long run of behaviours. The gap is the largest inside
                // the sheet: it is the boundary the eye chunks the list on.
                <div className="flex flex-col gap-6">
                  {features.map((feature) => (
                    <FeatureView
                      key={feature.id}
                      feature={feature}
                      selecting={selecting}
                      showGraders={showGraders}
                      graderByFqn={graderByFqn}
                    />
                  ))}
                </div>
              ) : (
                <Placeholder boxed />
              )}
            </Section>

            <Section
              title="Personas"
              actions={actions("personas")}
              mode={mode("personas")}
              writing={writing === "personas"}
            >
              {reviewing("personas") ? (
                currentReview("personas")
              ) : specification.personas.length > 0 ? (
                <ItemList items={specification.personas} />
              ) : (
                <Placeholder boxed />
              )}
            </Section>

            <Section
              title="Scenarios"
              actions={actions("scenarios")}
              mode={mode("scenarios")}
              writing={writing === "scenarios"}
            >
              {reviewing("scenarios") ? (
                currentReview("scenarios")
              ) : specification.scenarios.length > 0 ? (
                <ItemList items={specification.scenarios} />
              ) : (
                <Placeholder boxed />
              )}
            </Section>

            <Section
              title="Test Cases"
              actions={actions("test-cases")}
              mode={mode("test-cases")}
              writing={writing === "test-cases"}
            >
              {reviewing("test-cases") ? (
                currentReview("test-cases")
              ) : specification.tasks.length > 0 ? (
                <div>
                  <TestCaseTable
                    specification={specification}
                    excluded={excluded}
                  />
                  <p className="mt-3 text-right text-muted-foreground">
                    {selectedTasks.length} of {specification.tasks.length} Test
                    Cases selected,{" "}
                    {formatTrials(
                      selectedTasks.reduce(
                        (total, task) => total + task.num_trials,
                        0,
                      ),
                    )}
                  </p>
                </div>
              ) : (
                <Placeholder boxed />
              )}
            </Section>
          </div>
          {/* Holds the scroll position when a change near the end makes the content shorter. */}
          <div data-keep-spacer aria-hidden />
        </KeepInPlaceContext.Provider>
      </div>

      <SpecificationFooter
        done={done}
        busy={busy}
        onFinish={onFinish}
        onDownload={onDownload}
      />
    </div>
  );
}

// The pane's foot owns the one output action. Before completion it asks the API to finish the
// remaining interview and download the result. After completion it downloads the current result
// without doing more interview work.
function SpecificationFooter({
  done,
  busy,
  onFinish,
  onDownload,
}: {
  done?: boolean;
  busy?: boolean;
  onFinish?: () => void;
  onDownload?: () => void;
}) {
  return (
    <div className="mt-3 flex shrink-0 flex-wrap items-center justify-end gap-2">
      <p className="text-sm text-muted-foreground">
        Extract the download into <code>experiments/design/</code>.
      </p>
      <Button
        type="button"
        variant={done ? "primary" : "secondary"}
        disabled={busy}
        onClick={done ? onDownload : onFinish}
      >
        {done
          ? "Download specification"
          : "Skip interview and download specification"}
      </Button>
    </div>
  );
}

// ── the scaffold ─────────────────────────────────────────────────────────────

// What an unwritten section shows: ruled lines, framed for a list, bare for prose.
//
// The frame is the part that makes the lines work for a list. On its own a run of hairlines read as
// rules under the heading and debris below it — the lines looked like structure that had broken
// rather than space waiting to be filled. Enclosed, they are unambiguously the contents of a
// reserved region, and the dotted edge carries that message rather than the lines themselves.
//
// The frame specifically means "a list will grow here": Behaviours, Personas and Scenarios all fill
// with lists of items, so all three get the identical framed placeholder. A Target field is one
// piece of prose, not a list, so it takes the same lines without the frame — framing a single line
// would promise a growing region that never arrives.
//
// Every framed section is given the same lines at the same widths. Shaping each placeholder after
// the row it would hold was tried and dropped: it made an empty page busier than a written one, and
// the document's own headings already say what each section holds. Identical blanks read as one
// consistent kind of thing — space reserved — which is all the empty state needs to say.
//
// `aria-hidden` throughout: the section heading above already carries the meaning, and a screen
// reader should not hear a description of furniture.
const PLACEHOLDER_WIDTHS = ["w-full", "w-4/5", "w-3/5"];

function Placeholder({
  writing = false,
  boxed = false,
  widths = PLACEHOLDER_WIDTHS,
}: {
  writing?: boolean;
  boxed?: boolean;
  widths?: string[];
}) {
  // The lines carry `placeholder-rule`, so they take the travelling teal crest while the model is
  // writing into this section (`is-writing`, in globals.css). The frame stays still — it is
  // structure, and animating it would make the reserved region itself look unsettled.
  const rules = (
    <div className={cn("flex flex-col gap-2", writing && "is-writing")}>
      {widths.map((width, i) => (
        <span
          key={i}
          className={cn("placeholder-rule block h-px bg-border", width)}
        />
      ))}
    </div>
  );

  if (!boxed) return <div aria-hidden>{rules}</div>;
  return (
    <div
      aria-hidden
      className="rounded-lg border border-dotted border-border px-3 py-3"
    >
      {rules}
    </div>
  );
}

// The interview's position, as a row of segments — one per stage, in the document's order. It
// draws the package's own numbers and computes neither. Segments up to and including the current
// stage carry the accent; the
// rest stay on the border grey. The fill colour transitions rather than snapping, which marks the
// step advancing — the only reason a segment ever changes at all. It reads as a header for the page
// below: a full-width strip, not a puck floating in a corner.
function ProgressSegments({
  step,
  steps,
  title,
}: {
  step: number;
  steps: number;
  title?: string | null;
}) {
  // The caption falls back to the request title, then to a neutral label. The whole widget carries
  // one accessible label, so a screen reader hears "Behaviours, step 2 of 6" once rather than
  // reading the caption and the segments as two things.
  const caption = title ?? "Getting started";
  const label = title
    ? `${title}, step ${step} of ${steps}`
    : `Step ${step} of ${steps}`;
  return (
    <div role="img" aria-label={label} className="flex flex-1 flex-col gap-1.5">
      <div className="flex items-baseline justify-between gap-2 text-xs text-muted-foreground">
        <span aria-hidden className="min-w-0 truncate font-medium">
          {caption}
        </span>
        <span aria-hidden className="shrink-0 font-mono">
          {step}/{steps}
        </span>
      </div>
      <div className="flex items-center gap-1">
        {Array.from({ length: steps }, (_, i) => (
          <div
            key={i}
            className={cn(
              "h-1.5 flex-1 rounded-[2px] transition-colors duration-300",
              i < step ? "bg-accent" : "bg-border",
            )}
          />
        ))}
      </div>
    </div>
  );
}

// A section heading is a landmark, so it is drawn as one. It used to be the smallest, faintest
// text in the pane — `text-xs` in muted grey — which put the three names that give the document
// its structure *below* the content they contain in the visual order. Sections read as unclear
// for exactly that reason: the hierarchy was inverted. The heading now carries foreground weight
// at a size above the body, and a rule closing it off.
//
// It also sticks. Scrolling through a long Behaviours run, the heading stays until the next
// section pushes it out, so the answer to "what am I looking at" is never off-screen. The
// negative inline margin lets it span the sheet's padding and cover the content passing beneath,
// which is what a sticky heading over an opaque page has to do.
// While a review is open, the sections it fills are `current` and the other written sections are
// `frozen`. A current section gets a teal rule at the left of its heading and a "Now reviewing"
// label, so the user always sees where they work. A frozen section looks the same as an idle
// one; it only has no actions. With no review open, every section is `idle`.
type SectionMode = "idle" | "current" | "frozen";

function Section({
  title,
  writing = false,
  actions,
  mode = "idle",
  children,
}: {
  title: string;
  writing?: boolean;
  actions?: ReactNode;
  mode?: SectionMode;
  children: React.ReactNode;
}) {
  const current = mode === "current";
  return (
    <section
      aria-current={current ? "step" : undefined}
      className={cn("flex flex-col gap-3", writing && "is-writing")}
    >
      <div className="sticky top-0 z-10 -mx-5 flex min-h-12 items-end justify-between gap-3 border-b border-border bg-card px-5 pb-2 pt-4">
        <h2
          className={cn(
            "flex min-w-0 items-center gap-2 text-base font-semibold tracking-tight text-foreground",
          )}
        >
          {current && (
            <span
              aria-hidden
              className="h-4 w-1 shrink-0 rounded-full bg-accent"
            />
          )}
          <span className="min-w-0 truncate">{title}</span>
          {current && (
            <span className="shrink-0 text-xs font-medium text-accent">
              Now reviewing
            </span>
          )}
        </h2>
        <div className="flex shrink-0 items-center gap-2">
          {writing && (
            <span
              aria-hidden
              className="section-writing-marker h-1.5 w-1.5 rounded-full bg-accent"
            />
          )}
          {actions}
        </div>
      </div>
      <div className="flex flex-col gap-3">{children}</div>
    </section>
  );
}

function TargetField({
  label,
  value,
  preserveLines = false,
}: {
  label: string;
  value: string;
  preserveLines?: boolean;
}) {
  return (
    <div className="flex flex-col gap-1">
      <h3 className="text-xs font-medium text-muted-foreground">{label}</h3>
      {/* RevealText stays mounted under the placeholder. On the first response it therefore sees
          empty → written; on a resumed interview its initial value is already the completed text. */}
      <p
        className={cn(
          "text-muted-foreground",
          preserveLines && "whitespace-pre-line",
          !value && "hidden",
        )}
      >
        <RevealText value={value} />
      </p>
      {!value && <Placeholder />}
    </div>
  );
}

// Personas and Scenarios: each item leads with its name, with its description quieter below it,
// and a marker at the left edge so a run of them is countable at a glance. Metadata is secondary,
// so it sits in a closed, quiet Disclosure.
function ItemList({
  items,
}: {
  items: readonly {
    id: string;
    name: string;
    description: string;
    metadata?: Record<string, string> | null;
  }[];
}) {
  return (
    <ul className="flex flex-col gap-4">
      {items.map((item) => {
        const metadata = Object.entries(item.metadata ?? {});
        return (
          <li key={item.id} className="animate-arrive flex gap-3">
            <span
              aria-hidden
              className="mt-[0.4rem] h-1.5 w-1.5 shrink-0 rounded-full bg-border"
            />
            <div className="flex min-w-0 flex-col gap-0.5">
              <Mono className="text-foreground">{item.name}</Mono>
              <span className="text-muted-foreground">{item.description}</span>
              {metadata.length > 0 && (
                <Disclosure tone="muted" summary="More information">
                  <dl className="mt-1 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-0.5">
                    {metadata.map(([key, value]) => (
                      <div key={key} className="contents">
                        <dt className="font-medium">{key}</dt>
                        <dd className="whitespace-pre-wrap">{value}</dd>
                      </div>
                    ))}
                  </dl>
                </Disclosure>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

// The Test Cases as a compact table: Persona, Scenario, the Behaviours each one covers (id chips,
// with the Behaviour's name and description on hover), its trials, and its files. Fixed column
// widths keep long names from pushing the trials off the narrow pane; a name that does not fit is
// cut, with the full name on hover.
function TestCaseTable({
  specification,
  excluded,
}: {
  specification: Specification;
  excluded: ReadonlySet<string>;
}) {
  const behaviours = new Map(
    specification.features.flatMap((feature) =>
      feature.behaviours.map((behaviour) => [behaviour.id, behaviour] as const),
    ),
  );
  return (
    <table className="w-full table-fixed border-collapse text-left text-sm">
      <colgroup>
        <col className="w-[22%]" />
        <col className="w-[22%]" />
        <col />
        <col className="w-14" />
        <col className="w-[18%]" />
      </colgroup>
      <thead>
        <tr className="border-b border-border text-xs text-muted-foreground">
          <th className="px-2 py-2 font-medium">Persona</th>
          <th className="px-2 py-2 font-medium">Scenario</th>
          <th className="px-2 py-2 font-medium">Behaviours</th>
          <th className="px-2 py-2 text-right font-medium">Trials</th>
          <th className="px-2 py-2 font-medium">Files</th>
        </tr>
      </thead>
      <tbody>
        {specification.tasks.map((task) => {
          const persona = specification.personas.find(
            (item) => item.id === task.persona_ref,
          );
          const scenario = specification.scenarios.find(
            (item) => item.id === task.scenario_ref,
          );
          const personaName = persona?.name ?? task.persona_ref;
          const scenarioName = scenario?.name ?? task.scenario_ref;
          return (
            <tr
              key={task.id}
              data-keep-anchor={`task-${task.id}`}
              className={cn(
                "border-b border-border align-top",
                excluded.has(task.id) && "text-muted-foreground",
              )}
            >
              <td className="px-2 py-1.5">
                <span title={personaName} className="block truncate">
                  {personaName}
                </span>
              </td>
              <td className="px-2 py-1.5">
                <span title={scenarioName} className="block truncate">
                  {scenarioName}
                </span>
              </td>
              <td className="px-2 py-1.5">
                <div className="flex min-w-0 flex-wrap items-center gap-1">
                  {task.behaviour_refs.map((ref) => {
                    const behaviour = behaviours.get(ref);
                    return (
                      <span
                        key={ref}
                        title={
                          behaviour
                            ? `${behaviour.name}: ${behaviour.description}`
                            : ref
                        }
                      >
                        <Chip>{ref}</Chip>
                      </span>
                    );
                  })}
                </div>
              </td>
              <td className="px-2 py-1.5 text-right tabular-nums">
                {task.num_trials}
              </td>
              <td className="px-2 py-1.5">
                {task.fixtures.length > 0 ? (
                  <div className="flex min-w-0 flex-col gap-0.5 text-xs">
                    {task.fixtures.map((file) => (
                      <span key={file} title={file} className="truncate">
                        {file}
                      </span>
                    ))}
                  </div>
                ) : (
                  <span className="text-xs text-muted-foreground">None</span>
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

// Each feature is a disclosure: the header toggles its behaviours open and closed, so a long
// document collapses to a scannable list of feature names. Note this toggle is *view* state
// only: it opens and closes a section, it never edits the specification, so the document view stays
// read-only in the sense that matters — nothing here changes what the package built.
function FeatureView({
  feature,
  selecting,
  showGraders,
  graderByFqn,
}: {
  feature: Feature;
  selecting?: boolean;
  showGraders: boolean;
  graderByFqn: ReadonlyMap<string, GraderSpec>;
}) {
  // The open state lives here, so this component re-renders on a toggle and its keep-in-place
  // effect holds the header still while the content below it changes.
  const [open, setOpen] = useState(true);
  const keep = useKeepAnchor();
  // How much of this feature is measured, for screen readers.
  const measured = feature.behaviours.filter((b) => b.measured).length;
  return (
    <Disclosure
      className="animate-arrive"
      open={open}
      onOpenChange={(next) => {
        keep(`feature-${feature.id}`);
        setOpen(next);
      }}
      headerClassName="py-1"
      indent={false}
      label={`${feature.name}, ${measured} of ${feature.behaviours.length} measured`}
      summary={
        <span
          data-keep-anchor={`feature-${feature.id}`}
          className="flex min-w-0 items-center gap-2"
        >
          <span className="min-w-0 flex-1 font-medium">{feature.name}</span>
        </span>
      }
    >
      <div className="ml-1.5 mt-1 border-l border-border pb-1 pl-3">
        <p className="mb-3 whitespace-pre-wrap text-sm text-muted-foreground">
          {feature.description}
        </p>
        <ul className="flex flex-col gap-4">
          {feature.behaviours.map((b) => (
            <BehaviourView
              key={b.id}
              behaviour={b}
              selecting={selecting}
              showGraders={showGraders}
              graderByFqn={graderByFqn}
            />
          ))}
        </ul>
      </div>
    </Disclosure>
  );
}

function BehaviourView({
  behaviour,
  selecting,
  showGraders,
  graderByFqn,
}: {
  behaviour: Behaviour;
  selecting?: boolean;
  showGraders: boolean;
  graderByFqn: ReadonlyMap<string, GraderSpec>;
}) {
  // A behaviour the user hasn't ticked is dormant: its criteria are kept but won't be
  // measured, so it reads de-emphasised.
  const dormant = !behaviour.measured;
  // Criteria are the one part of the document that lands *inside* another section rather than as a
  // section of its own, so the scaffold reaches one level deeper here: a behaviour chosen to be
  // measured but not yet written up shows the blank where its criteria will go.
  //
  // The tick is what makes the blank honest, but only once the tick is committed. A tick flips
  // `measured` live — and is a server round-trip that recomposes the Behaviours screen — so while
  // the interview is on that screen the user is still choosing and any box can still be un-ticked.
  // Drawing the blank there promises content for a selection that has not been made. `selecting` is
  // true for the whole Behaviours step (keyed on the step, not on `busy`, so a tick's brief in-
  // flight window does not flicker the blank on and off), and holds it back until Continue advances
  // the interview off Behaviours. From then on "ticked, not yet written up" is a settled promise. A
  // dormant behaviour still shows no blank because no criteria are coming for it.
  const awaitingCriteria =
    behaviour.measured && behaviour.criteria.length === 0 && !selecting;
  return (
    // The id sits in a gutter at the left rather than trailing the description. Trailing, it landed
    // wherever the prose happened to stop wrapping, so a run of behaviours ended in a ragged
    // column of ids that competed with the text without ever lining up. In a fixed gutter the ids
    // form one straight edge to read down, which is what makes a scenario's `Behaviours EB-1 EB-3`
    // resolvable by eye — the only job the id has in this pane.
    <li
      className={cn(
        "animate-arrive grid grid-cols-[3.25rem_minmax(0,1fr)] gap-x-2 gap-y-0.5",
        dormant && "opacity-45",
      )}
    >
      {/* The id goes teal on a behaviour that is measured, and stays grey otherwise. Dimming
          the dormant rows says which ones are out; the teal ids say which are in, and they form
          a straight column to read down. */}
      <Mono
        tone={behaviour.measured ? "accent" : "muted"}
        className={cn(
          "pt-px tabular-nums",
          behaviour.measured && "font-semibold",
        )}
      >
        {behaviour.id}
      </Mono>
      <span className="min-w-0 text-foreground">
        <span className="font-medium">{behaviour.name}</span> —{" "}
        {behaviour.description}
      </span>
      {behaviour.criteria.length > 0 && (
        // The criteria are set apart from the description above them with a top gap, so a
        // behaviour and its criteria read as one labelled unit. Each criterion is spaced from the next for the same reason.
        <ul className="col-start-2 mt-1.5 flex flex-col gap-3 text-xs">
          {behaviour.criteria.map((c) => {
            const grader = c.grader_fqn
              ? graderByFqn.get(c.grader_fqn)
              : undefined;
            return (
              <li
                key={c.id}
                className="animate-arrive flex flex-col gap-1 [&:not(:first-child)]:border-t [&:not(:first-child)]:border-border [&:not(:first-child)]:pt-3"
              >
                <p className="text-foreground">{c.description}</p>
                <Disclosure tone="muted" summary="Grader details">
                  <div className="mt-1 flex flex-col gap-0.5">
                    <p>{c.name}</p>
                    <p>{grader?.name ?? c.grader_fqn ?? "Not selected"}</p>
                    {!grader && c.grader_fqn && (
                      <p>Unlisted settings use the grader defaults.</p>
                    )}
                    <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3">
                      {Object.entries({
                        ...Object.fromEntries(
                          (grader?.settings ?? [])
                            .filter((setting) => !setting.required)
                            .map((setting) => [setting.name, setting.default]),
                        ),
                        ...c.grader_args,
                      }).map(([key, value]) => (
                        <div key={key} className="contents">
                          <dt>{key}</dt>
                          <dd className="break-words font-mono">
                            {JSON.stringify(value)}
                          </dd>
                        </div>
                      ))}
                    </dl>
                  </div>
                </Disclosure>
                {showGraders && grader && (
                  <Mono className="block break-words rounded border border-border bg-muted px-2 py-1 leading-relaxed">
                    <span className="block text-foreground">{grader.name}</span>
                    <span className="block text-muted-foreground">
                      {grader.description}
                    </span>
                  </Mono>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {awaitingCriteria && (
        // One short rule per behaviour still to be written up. Not boxed and not the full
        // three-line placeholder: this repeats once per selected behaviour, so anything larger
        // would put the grey back on the page that the sections were kept spare to avoid. It never
        // shimmers: the criteria are drafted during the Continue that leaves Behaviours, before
        // this blank is allowed to appear, so there is no in-flight window to mark here.
        <div className="col-start-2 pt-0.5">
          <Placeholder widths={["w-28"]} />
        </div>
      )}
    </li>
  );
}
