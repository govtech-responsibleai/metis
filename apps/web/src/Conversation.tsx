import {
  ArrowUp,
  ChevronDown,
  FileText,
  PencilSparkles,
  Plus,
  Upload,
  X,
} from "lucide-react";
import {
  createContext,
  Fragment,
  useContext,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import type {
  TranscriptEntry,
  AnyCard,
  CardColumn,
  CardComponent,
  ReviewSection,
  ChoiceRequest,
  FormRequest,
  Option,
  UserResponse,
  Warning,
  WizardRequest,
} from "./transport/api";
import { optionKey } from "./transport/api";
import {
  Field,
  NumberInput,
  SelectInput,
  TextArea,
  TextInput,
  MultiChoice,
  PairsInput,
  type FieldDensity,
  type SelectChoice,
} from "./fields";
import { useKeepAnchor } from "./keep-in-place";
import {
  Button,
  cn,
  ConfirmDialog,
  Disclosure,
  DisclosureButton,
  formatTrials,
  IconAction,
  Mono,
  Panel,
  SelectBox,
  Tooltip,
} from "./ui";
import { groupTranscript } from "./wizard/transcript";

// What a block can send up. `null` from a resolved or read-only block.
type Emit = (
  response: UserResponse,
  files?: readonly File[],
  removedFixtures?: readonly string[],
) => void;
type CardFieldValue = number | string[];

const FormDraftContext = createContext<{
  values: Map<string, Record<string, string>>;
  prefix: string;
} | null>(null);

// ── whole transcript ─────────────────────────────────────────────────────────

export function Transcript({
  requests,
  entries,
  formDrafts,
  draftPrefix = "",
  onRetry,
  onEdit,
  busy,
  onRespond,
  profileForm = null,
}: {
  requests: WizardRequest[];
  entries?: TranscriptEntry[];
  formDrafts?: Map<string, Record<string, string>>;
  draftPrefix?: string;
  // The request id of a pending form that the Profile draws, with its send status and any
  // failure. The conversation draws none of it, so the form is never on screen twice.
  profileForm?: string | null;
  onRetry?: () => void;
  onEdit?: () => void;
  busy: boolean;
  onRespond: Emit;
}) {
  const items = groupTranscript(requests, entries);
  const block = (i: number) => {
    const request = requests[i];
    const entry = entries?.[i];
    const failed = entry?.kind === "interaction" && entry.status === "failed";
    const inProfile = profileForm != null && request.request_id === profileForm;
    return (
      <div key={request.request_id ?? i}>
        {!inProfile && (
          <RequestBlock request={request} busy={busy} onRespond={onRespond} />
        )}
        {failed && !inProfile && (
          <div role="alert" className="mt-2 flex items-center gap-3">
            <p>{entry.failure?.message}</p>
            {entry.failure?.retryable && (
              <Button disabled={busy} onClick={onRetry}>
                Retry
              </Button>
            )}
            {entry.failure?.kind !== "storage" && (
              <Button disabled={busy} onClick={onEdit}>
                Edit reply
              </Button>
            )}
          </div>
        )}
      </div>
    );
  };
  return (
    <FormDraftContext.Provider
      value={formDrafts ? { values: formDrafts, prefix: draftPrefix } : null}
    >
      <div className="flex flex-col gap-8">
        {items.map((item, n) => {
          const first = item.kind === "request" ? item.index : item.indices[0];
          const previous = items[n - 1];
          const before =
            previous?.kind === "request"
              ? previous.index
              : previous?.indices.at(-1);
          // A light rule ahead of the first item of each new step. The package stamps `step` on
          // each request; the door only notices when it changes between adjacent items.
          const step = requests[first]?.step;
          const startsStep =
            step != null &&
            before !== undefined &&
            step !== requests[before]?.step;
          return (
            <div
              key={requests[first]?.request_id ?? first}
              className={cn(startsStep && "border-t border-border pt-8")}
            >
              {item.kind === "request" ? (
                block(item.index)
              ) : (
                <Disclosure
                  tone="muted"
                  summary={`${item.indices.length} ${item.indices.length === 1 ? "action" : "actions"}`}
                  contentClassName="mt-3 flex flex-col gap-6"
                >
                  {item.indices.map(block)}
                </Disclosure>
              )}
            </div>
          );
        })}
      </div>
    </FormDraftContext.Provider>
  );
}

function RequestBlock({
  request,
  busy,
  onRespond,
}: {
  request: WizardRequest;
  busy: boolean;
  onRespond: Emit;
}) {
  const resolved = request.state === "resolved";
  return (
    <section
      className={cn(
        "flex flex-col gap-3",
        // A resolved block is a receipt: dimmed, and its controls are gone, not merely
        // disabled. The distinction is what stops a screen being answered twice.
        resolved && "opacity-55",
      )}
      aria-live={resolved ? undefined : "polite"}
    >
      {request.prompt && (
        <p className="whitespace-pre-wrap text-foreground">{request.prompt}</p>
      )}
      <RequestBody
        request={request}
        resolved={resolved}
        busy={busy}
        onRespond={onRespond}
      />
    </section>
  );
}

function RequestBody({
  request,
  resolved,
  busy,
  onRespond,
}: {
  request: WizardRequest;
  resolved: boolean;
  busy: boolean;
  onRespond: Emit;
}) {
  switch (request.type) {
    case "chat":
      // The prompt is the wizard's question; the live reply is typed in the composer at the
      // foot of the pane, so a live chat block draws nothing further. Once resolved, the reply
      // the package stamped onto the request is shown beneath the question, so the exchange
      // reads as a conversation rather than a one-sided list of prompts.
      return request.answer ? <UserSaid text={request.answer} /> : null;
    case "form":
      return (
        <FormBlock
          request={request}
          resolved={resolved}
          busy={busy}
          onRespond={onRespond}
        />
      );
    case "choice":
      if (request.profile_section_id)
        return request.feedback_answer ? (
          <UserSaid text={request.feedback_answer} />
        ) : null;
      return (
        <ChoiceBlock
          request={request}
          resolved={resolved}
          busy={busy}
          onRespond={onRespond}
        />
      );
  }
}

// ── choice ─────────────────────────────────────────────────────────────────────

function ChoiceBlock({
  request,
  resolved,
  busy,
  onRespond,
}: {
  request: ChoiceRequest;
  resolved: boolean;
  busy: boolean;
  onRespond: Emit;
}) {
  const send = (keys: string[]) =>
    onRespond({ type: "choice", selected: keys });
  const sendField = (
    key: string,
    value: CardFieldValue,
    files?: readonly File[],
    removedFixtures?: readonly string[],
  ) =>
    onRespond(
      { type: "choice", values: { [key]: value } },
      files,
      removedFixtures,
    );
  const disabled = resolved || busy;

  return (
    <div className="flex flex-col gap-3">
      {request.warnings.map((warning, i) => (
        <WarningBlock
          key={i}
          warning={warning}
          disabled={disabled}
          onPick={(k) => send([k])}
        />
      ))}

      {request.cards.length > 0 && (
        // A muted backing sits behind the whole run of cards — the grey the Jira columns and
        // the document sheet share — so a card-bearing screen reads as its own grouped surface,
        // set apart from the plain chat turns above and below it. It is drawn from the cards
        // alone, not the resolved flag, so it persists once the block becomes a receipt; the
        // receipt's dimming rides on top from the enclosing section.
        <div className="flex flex-col gap-3 rounded-lg bg-muted p-3">
          {request.cards.map((card, i) => {
            // The heading is emitted once per group, ahead of that group's cards — a header
            // is drawn only when this card's section differs from the one before it. The door
            // never learns what a section is; it only notices when the string changes.
            const prev = request.cards[i - 1]?.section;
            const startsGroup = card.section && card.section !== prev;
            return (
              <div key={card.id} className="flex flex-col gap-1.5">
                {startsGroup && (
                  <p className="pt-1 text-xs font-semibold text-muted-foreground">
                    {card.section}
                  </p>
                )}
                <Panel
                  className={cn(
                    "overflow-hidden",
                    card.blocking && "border-destructive/60",
                  )}
                >
                  <CardBlock
                    card={card}
                    disabled={disabled}
                    onPick={(k) => send([k])}
                    onFieldChange={sendField}
                  />
                </Panel>
              </div>
            );
          })}
        </div>
      )}

      {request.footer && (
        <p className="text-right text-muted-foreground">{request.footer}</p>
      )}

      {!resolved && (
        <div className="flex flex-wrap gap-2">
          {request.options.map((o) => (
            <ActionButton
              key={optionKey(o.id)}
              option={o}
              disabled={busy}
              onPick={(k) => send([k])}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// The live review, drawn in the Profile in place of the section it reviews. Cards that share a
// `section_id` form one group under a header. When every card has columns, the review is a table.
export interface FormFailure {
  message: string;
  onRetry?: () => void;
  onEdit?: () => void;
}

// The Profile sections that one review fills, in order. A review names them with its top-level
// `sections`; an older review names one through `profile_section_id`.
export function reviewParts(request: ChoiceRequest): string[] {
  const parts = (request.sections ?? [])
    .filter((section) => section.parent == null)
    .map((section) => section.id);
  if (parts.length > 0) return parts;
  return request.profile_section_id ? [request.profile_section_id] : [];
}

function partOf(request: ChoiceRequest, card: AnyCard): string {
  return card.profile_section_id ?? request.profile_section_id ?? "";
}

function componentOptions(components: readonly CardComponent[]): Option[] {
  return components.flatMap((component) =>
    component.type === "options"
      ? component.options
      : component.type === "details"
        ? componentOptions(component.components)
        : [],
  );
}

const hasColumns = (card: AnyCard) => (card.columns ?? []).length > 0;

// Where a pending form goes in the Profile. The form belongs to the item that offered the option
// that opened it: the option's action is the form's purpose and its target is the form's target.
// An edit of a card or a group heading takes the item's place; any other form opens below its
// item, or at the end of its group or Profile section. A form that no item offered (the Target
// review) has no place here, and the conversation draws it.
export interface FormPlace {
  part: string;
  owner: string;
  // "nested": the form edits a row inside the owner card (a Criterion inside its Behaviour);
  // `item` is the id that the row's option names.
  mode: "inline" | "below" | "end" | "nested" | "row";
  item?: string;
}

export function placeForm(
  review: ChoiceRequest,
  form: FormRequest,
): FormPlace | null {
  if (!form.target) return null;
  const purpose = form.purpose ?? "add";
  const offers = (option: Option) =>
    option.id.action === purpose && option.id.target === form.target;
  for (const section of review.sections ?? []) {
    if (!section.options.some(offers)) continue;
    if (section.parent == null)
      return { part: section.id, owner: section.id, mode: "end" };
    return {
      part: section.parent,
      owner: section.id,
      mode: purpose === "edit" ? "inline" : "end",
    };
  }
  for (const card of review.cards) {
    const part = partOf(review, card);
    if (card.options.some(offers))
      return {
        part,
        owner: card.id,
        mode:
          purpose !== "edit" ? "below" : hasColumns(card) ? "row" : "inline",
      };
    if (componentOptions(card.components).some(offers))
      return {
        part,
        owner: card.id,
        mode: purpose === "edit" ? "nested" : "below",
        item: form.target,
      };
  }
  return null;
}

// The actions on a Profile section heading, such as "+ Add a Persona". The Profile draws them in
// its own sticky heading.
export function ReviewSectionActions({
  request,
  part,
  busy,
  onRespond,
}: {
  request: ChoiceRequest;
  part: string;
  busy: boolean;
  onRespond: Emit;
}) {
  const keep = useKeepAnchor();
  const section = (request.sections ?? []).find(
    (item) => item.id === part && item.parent == null,
  );
  if (!section || section.options.length === 0) return null;
  return (
    <div data-keep-anchor={`part-${part}`} className="flex items-center gap-1">
      <OptionControls
        options={section.options}
        disabled={busy || request.state !== "pending"}
        onPick={(key) => {
          keep([`part-${part}`, "review-footer"], "send");
          onRespond({ type: "choice", selected: [key] });
        }}
      />
    </div>
  );
}

// One Profile section of the live review, drawn in place of that section of the document. A
// review that fills several sections is drawn once per section: the first one carries the
// title, instruction and warnings, and the last one carries Back and Continue.
export function ActiveReview({
  request,
  part,
  busy,
  onRespond,
  form,
  formFailure = null,
  formDrafts,
  draftPrefix = "",
}: {
  request: ChoiceRequest;
  // The Profile section to draw. Omit it to draw the whole review.
  part?: string;
  busy: boolean;
  onRespond: Emit;
  // The pending form, when the user opened one from this review. `placeForm` decides where it
  // goes. While it is open the review waits, and only Back stays available on the review.
  form?: FormRequest | null;
  // Why the last save of `form` failed, with the actions that recover it.
  formFailure?: FormFailure | null;
  formDrafts?: Map<string, Record<string, string>>;
  draftPrefix?: string;
}) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const keep = useKeepAnchor();
  const disabled = busy || request.state !== "pending";
  const parts = reviewParts(request);
  const current = part ?? parts[0] ?? "";
  const first = part == null || current === parts[0];
  const last = part == null || current === parts.at(-1);
  const inPart = (card: AnyCard) =>
    part == null || partOf(request, card) === part;
  const cards = request.cards.filter(inPart);
  // Every action keeps its item in place: the package composes the review again, and the item
  // the user clicked must stay where it was when the new review renders.
  // The anchors that hold the sheet still after an action on `owner`, best first. A deleted card
  // is gone when the new review renders, so its neighbours and its group follow it; a Profile
  // section falls back to its last card, then to the footer.
  const anchorsFor = (owner: string): string[] => {
    const i = cards.findIndex((card) => card.id === owner);
    if (i >= 0)
      return [
        owner,
        cards[i + 1]?.id,
        cards[i - 1]?.id,
        cards[i].section_id ?? undefined,
        "review-footer",
      ].filter((id): id is string => id != null);
    if (owner === current)
      return [cards.at(-1)?.id, "review-footer"].filter(
        (id): id is string => id != null,
      );
    return [owner, "review-footer"];
  };
  const respondFrom =
    (anchor: string): Emit =>
    (response, files, removed) => {
      keep(anchorsFor(anchor), "send");
      onRespond(response, files, removed);
    };
  const pickFrom = (anchor: string) => (key: string) =>
    respondFrom(anchor)({ type: "choice", selected: [key] });
  const fieldFrom =
    (anchor: string) =>
    (
      key: string,
      value: CardFieldValue,
      files?: readonly File[],
      removed?: readonly string[],
    ) =>
      respondFrom(anchor)(
        { type: "choice", values: { [key]: value } },
        files,
        removed,
      );
  const place = form ? placeForm(request, form) : null;
  // The package keeps a refused form open and puts the reason before its prompt. The first
  // prompt of a form for one target is its normal text; a later, different prompt is a notice.
  const firstPrompt = useRef(new Map<string, string>());
  if (!form) firstPrompt.current.clear();
  else {
    const key = `${form.purpose}:${form.target}`;
    if (!firstPrompt.current.has(key))
      firstPrompt.current.set(key, form.prompt);
  }
  const refused =
    form &&
    form.prompt !== firstPrompt.current.get(`${form.purpose}:${form.target}`)
      ? form.prompt
      : null;
  const notice: ReactNode =
    formFailure != null ? (
      <span className="flex flex-wrap items-center gap-2">
        <span>{formFailure.message}</span>
        {formFailure.onRetry && (
          <Button
            type="button"
            className="px-2 py-0.5 text-xs"
            onClick={formFailure.onRetry}
          >
            Retry
          </Button>
        )}
        {formFailure.onEdit && (
          <Button
            type="button"
            className="px-2 py-0.5 text-xs"
            onClick={formFailure.onEdit}
          >
            Edit
          </Button>
        )}
      </span>
    ) : (
      refused
    );
  // After an inline edit closes, the focus goes back to the item's pencil.
  const lastInline = useRef<string | null>(null);
  const inlineOwner =
    form &&
    (place?.mode === "inline" ||
      place?.mode === "nested" ||
      place?.mode === "row")
      ? (place.item ?? place.owner)
      : null;
  useEffect(() => {
    const previous = lastInline.current;
    lastInline.current = inlineOwner;
    if (!previous || inlineOwner) return;
    const pencil = document.querySelector<HTMLElement>(
      `[data-keep-anchor="${CSS.escape(previous)}"] button:has(svg.lucide-pencil)`,
    );
    pencil?.focus({ preventScroll: true });
  }, [inlineOwner]);
  const here = place && (part == null || place.part === current) ? place : null;
  // The form opened from `owner` in the given mode, or nothing.
  const formAt = (owner: string, mode: FormPlace["mode"]) =>
    form && here?.owner === owner && here.mode === mode ? form : null;
  const formPanel = (owner: string, request: FormRequest) => (
    <div
      key={`form-${owner}`}
      data-keep-anchor={`form-${owner}`}
      className="flex flex-col gap-3 bg-muted/40 px-4 py-3"
    >
      {request.prompt && (
        <p
          role={refused ? "alert" : undefined}
          className={cn("text-sm", refused && "text-destructive")}
        >
          {request.prompt}
        </p>
      )}
      {formFailure && (
        <div role="alert" className="text-sm text-destructive">
          {notice}
        </div>
      )}
      <PendingForm
        request={request}
        busy={busy}
        onRespond={respondFrom(owner)}
      />
    </div>
  );

  // Groups: the headings of this section in the package's order, then any card that names no
  // heading as its own group.
  const headings = (request.sections ?? []).filter(
    (section) =>
      section.parent != null && (part == null || section.parent === part),
  );
  const groups: { id: string; heading?: ReviewSection; cards: AnyCard[] }[] =
    headings.map((heading) => ({
      id: heading.id,
      heading,
      cards: cards.filter((card) => card.section_id === heading.id),
    }));
  for (const card of cards) {
    if (groups.some((group) => group.cards.includes(card))) continue;
    const key = card.section_id ?? card.id;
    const group = groups.find((item) => item.id === key);
    if (group) group.cards.push(card);
    else groups.push({ id: key, cards: [card] });
  }
  const table = cards.length > 0 && cards.every(hasColumns);
  const endForm = formAt(current, "end");

  return (
    <FormDraftContext.Provider
      value={formDrafts ? { values: formDrafts, prefix: draftPrefix } : null}
    >
      <section
        aria-label={first ? (request.title ?? "Review") : current}
        className="flex flex-col gap-4"
      >
        {first && (
          <>
            {/* The Profile section heading already names the step, so the review shows only
                its instruction. */}
            <p className="text-sm text-muted-foreground">
              {request.instruction}
            </p>
            {request.warnings.map((warning, i) => (
              <WarningBlock
                key={i}
                warning={warning}
                disabled={disabled}
                onPick={pickFrom("review-footer")}
              />
            ))}
          </>
        )}
        {table ? (
          <ReviewTable
            cards={cards}
            disabled={disabled}
            pickFrom={pickFrom}
            rowForm={(id) => {
              const edit = formAt(id, "row");
              return edit
                ? { request: edit, busy, notice, onRespond: respondFrom(id) }
                : null;
            }}
            formRow={(id) => {
              const below = formAt(id, "below");
              return below && formPanel(id, below);
            }}
          />
        ) : (
          groups.map(({ id, heading, cards }) => {
            const open = !collapsed.has(id);
            const title = heading?.title ?? cards[0]?.section;
            const editing = formAt(id, "inline");
            const groupEnd = formAt(id, "end");
            const header = title && (
              <div
                data-keep-anchor={id}
                className="flex items-start gap-2 px-4 py-3"
              >
                {editing ? (
                  <div className="flex min-w-0 flex-1 items-start gap-2">
                    <DisclosureButton
                      open={open}
                      label={title}
                      onClick={() => toggleGroup(id)}
                    />
                    <div className="min-w-0 flex-1">
                      <InlineEdit
                        request={editing}
                        busy={busy}
                        notice={notice}
                        onRespond={respondFrom(id)}
                      />
                    </div>
                  </div>
                ) : (
                  <>
                    <DisclosureButton
                      open={open}
                      grow
                      onClick={() => toggleGroup(id)}
                    >
                      <span className="font-semibold">{title}</span>
                    </DisclosureButton>
                    <OptionControls
                      options={heading?.options ?? []}
                      disabled={disabled}
                      onPick={pickFrom(id)}
                    />
                  </>
                )}
              </div>
            );
            const body = [
              ...cards.flatMap((card) => {
                const below = formAt(card.id, "below");
                const inline = formAt(card.id, "inline");
                const nested = formAt(card.id, "nested");
                return [
                  <CardBlock
                    key={card.id}
                    card={card}
                    disabled={disabled}
                    onPick={pickFrom(card.id)}
                    onFieldChange={fieldFrom(card.id)}
                    editing={
                      inline
                        ? {
                            request: inline,
                            busy,
                            notice,
                            onRespond: respondFrom(card.id),
                          }
                        : undefined
                    }
                    rowEdit={
                      nested
                        ? {
                            request: nested,
                            busy,
                            notice,
                            onRespond: respondFrom(card.id),
                          }
                        : undefined
                    }
                  />,
                  ...(below ? [formPanel(card.id, below)] : []),
                ];
              }),
              ...(groupEnd ? [formPanel(id, groupEnd)] : []),
            ];
            return (
              <section
                key={id}
                className="overflow-hidden rounded-xl border border-border bg-card"
              >
                {header}
                <div
                  hidden={!open}
                  className={cn(
                    "divide-y divide-border",
                    header && body.length > 0 && "border-t border-border",
                  )}
                >
                  {body}
                </div>
              </section>
            );
          })
        )}
        {endForm && (
          <section className="overflow-hidden rounded-xl border border-border bg-card">
            {formPanel(current, endForm)}
          </section>
        )}
        {last && (
          <div
            data-keep-anchor="review-footer"
            className="flex flex-wrap items-center gap-2 pt-1"
          >
            <span className="mr-auto text-sm">{request.footer}</span>
            {request.options.map((option) => (
              <ActionButton
                key={optionKey(option.id)}
                option={option}
                // Back stays available while a form is open: the package closes the form and
                // goes back in one turn.
                disabled={
                  busy ||
                  (request.state !== "pending" &&
                    !(form && option.id.action === "back"))
                }
                onPick={pickFrom("review-footer")}
              />
            ))}
          </div>
        )}
      </section>
    </FormDraftContext.Provider>
  );

  function toggleGroup(id: string) {
    keep(id);
    setCollapsed((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }
}

// A review whose cards all carry columns: one table row per card. The row's checkbox is the
// card's tick option (selected = included). Each cell shows its column's value and accepts no
// edits. The pencil turns the row into its edit form (see RowEditor).
function ReviewTable({
  cards,
  disabled,
  pickFrom,
  rowForm,
  formRow,
}: {
  cards: AnyCard[];
  disabled: boolean;
  pickFrom: (anchor: string) => (key: string) => void;
  // The edit form of a row, when the user opened one, and how it answers.
  rowForm?: (id: string) => RowEdit | null;
  // Any other form opened from a row, drawn in a full-width row below it.
  formRow?: (id: string) => ReactNode;
}) {
  const columns = cards[0]?.columns ?? [];
  const kinds = columns.map((column) => columnKind(column));
  const ticks = cards.some((card) => tickOf(card));
  // The chip column is wide enough for two small id chips per line, and the Files column for the
  // Add file button and a short name. Both have fixed widths, so the text columns (Persona,
  // Scenario) share all the rest and names get the most room on every width. While a row is open
  // for editing, the actions column widens to hold Save and Cancel side by side, and the text
  // columns give up that room.
  const widths = kinds.map((kind) =>
    kind === "number"
      ? "w-12"
      : kind === "upload"
        ? "w-32"
        : kind === "chips"
          ? "w-[6rem]"
          : undefined,
  );
  const span = columns.length + (ticks ? 1 : 0) + 1;
  const editing = cards.some((card) => rowForm?.(card.id) != null);
  return (
    <table className="w-full table-fixed border-collapse text-left text-sm">
      <colgroup>
        {ticks && <col className="w-8" />}
        {widths.map((width, i) => (
          <col key={i} className={width} />
        ))}
        <col className={editing ? "w-[8.5rem]" : "w-14"} />
      </colgroup>
      <thead>
        <tr className="border-b border-border text-xs text-muted-foreground">
          {ticks && (
            <th className="py-2 pl-2">
              <span className="sr-only">Include</span>
            </th>
          )}
          {columns.map((column, i) => (
            <th
              key={column.title}
              className={cn(
                "truncate px-2 py-2 font-medium",
                kinds[i] === "number" && "text-right",
              )}
            >
              {column.title}
            </th>
          ))}
          <th className="py-2 pr-2">
            <span className="sr-only">Actions</span>
          </th>
        </tr>
      </thead>
      <tbody>
        {cards.map((card) => {
          const tick = tickOf(card);
          const edit = rowForm?.(card.id) ?? null;
          const icons = card.options.filter(
            (option) => option.icon && option !== tick,
          );
          const below = formRow?.(card.id);
          return (
            <Fragment key={card.id}>
              {edit ? (
                <RowEditor
                  card={card}
                  columns={columns}
                  kinds={kinds}
                  tick={tick}
                  edit={edit}
                  onPick={pickFrom(card.id)}
                />
              ) : (
                <tr
                  data-keep-anchor={card.id}
                  className={cn(
                    "border-b border-border align-top",
                    tick && !isSelected(card, tick) && "text-muted-foreground",
                  )}
                >
                  {ticks && (
                    <td className="py-1.5 pl-2">
                      {tick && (
                        <span className="flex h-7 items-center">
                          <SelectBox
                            label={`Include ${card.title}`}
                            checked={isSelected(card, tick)}
                            disabled={disabled}
                            onChange={() =>
                              pickFrom(card.id)(optionKey(tick.id))
                            }
                          />
                        </span>
                      )}
                    </td>
                  )}
                  {card.columns?.map((column, i) => (
                    <td
                      key={column.title}
                      className={cn(
                        "px-2 py-1.5",
                        kinds[i] === "number" && "text-right tabular-nums",
                      )}
                    >
                      <ColumnCell column={column} />
                    </td>
                  ))}
                  <td className="py-1.5 pr-2">
                    <div className="flex justify-end gap-1">
                      <OptionControls
                        options={icons}
                        disabled={disabled}
                        onPick={pickFrom(card.id)}
                      />
                    </div>
                  </td>
                </tr>
              )}
              {below && (
                <tr className="border-b border-border">
                  <td colSpan={span} className="p-0">
                    {below}
                  </td>
                </tr>
              )}
            </Fragment>
          );
        })}
      </tbody>
    </table>
  );
}

// A table row in edit mode. Each form field goes into the cell of the column it names, and a field
// that names no column goes into the first cell. Save and Cancel take the place of the row
// actions. A form cannot wrap table cells, so the form element sits in the actions cell and each
// control in the other cells joins it through its `form` attribute. An error notice goes in a
// full-width row below.
function RowEditor({
  card,
  columns,
  kinds,
  tick,
  edit,
  onPick,
}: {
  card: AnyCard;
  columns: readonly CardColumn[];
  kinds: readonly ColumnKind[];
  tick?: Option;
  edit: RowEdit;
  onPick: (key: string) => void;
}) {
  const { values, setValue } = useFormDraft(edit.request);
  const formId = `row-edit-${card.id}`;
  // Files the user uploads while the row is open. Each one becomes a selected choice of the
  // multi-choice field in the upload column, and the files go with the Save.
  const [uploads, setUploads] = useState<File[]>([]);
  const uploadColumn = columns.find((_, i) => kinds[i] === "upload")?.title;
  const fields = edit.request.fields.map((field) =>
    field.multiple && uploadColumn != null && field.column === uploadColumn
      ? {
          ...field,
          choices: [
            ...(field.choices ?? []),
            ...uploads
              .filter(
                (file) =>
                  !(field.choices ?? []).some(
                    (choice) => choice.value === file.name,
                  ),
              )
              .map((file) => ({ value: file.name, label: file.name })),
          ],
        }
      : field,
  );
  const uploadField = fields.find(
    (field) =>
      field.multiple && uploadColumn != null && field.column === uploadColumn,
  );
  const addUploads = (files: File[]) => {
    if (!uploadField || files.length === 0) return;
    setUploads((current) => [
      ...current.filter(
        (item) => !files.some((file) => file.name === item.name),
      ),
      ...files,
    ]);
    const chosen = (values[uploadField.id] ?? "").split(",").filter(Boolean);
    for (const file of files)
      if (!chosen.includes(file.name)) chosen.push(file.name);
    setValue(uploadField.id, chosen.join(","));
  };
  const used = edit.request.used_combinations ?? [];
  const cellOf = (field: FormFieldSpec) => {
    const named = columns.findIndex((column) => column.title === field.column);
    return named >= 0 ? named : 0;
  };
  const busy = edit.busy;
  return (
    <>
      <tr
        data-keep-anchor={card.id}
        className={cn(
          "bg-muted/40 align-top",
          !edit.notice && "border-b border-border",
        )}
        onKeyDown={(e) => {
          if (e.key === "Escape" && edit.request.cancellable && !busy) {
            e.preventDefault();
            cancelForm(edit.onRespond);
          }
        }}
      >
        {tick && (
          <td className="py-1.5 pl-2">
            <span className="flex h-8 items-center">
              <SelectBox
                label={`Include ${card.title}`}
                checked={isSelected(card, tick)}
                disabled
                onChange={() => onPick(optionKey(tick.id))}
              />
            </span>
          </td>
        )}
        {columns.map((column, i) => (
          <td
            key={column.title}
            className={cn(
              "px-1 py-1.5",
              // A number reads right-aligned in its box, the same as in the read-only row.
              kinds[i] === "number" && "[&_input]:text-right",
            )}
          >
            <div className="flex min-w-0 flex-col gap-1">
              {fields
                .filter((field) => cellOf(field) === i)
                .map((field) =>
                  field === uploadField ? (
                    <RowFiles
                      key={field.id}
                      field={field}
                      value={values[field.id] ?? ""}
                      disabled={busy}
                      onChange={(value) => setValue(field.id, value)}
                      onUpload={addUploads}
                    />
                  ) : (
                    <FormFieldControl
                      key={field.id}
                      field={field}
                      value={values[field.id] ?? ""}
                      values={values}
                      used={used}
                      fields={fields}
                      disabled={busy}
                      density="inline"
                      hideLabel
                      form={formId}
                      onChange={(value) => setValue(field.id, value)}
                    />
                  ),
                )}
            </div>
          </td>
        ))}
        <td className="py-1.5 pr-2">
          <form
            id={formId}
            aria-label={edit.request.prompt || "Edit"}
            onSubmit={(e) => {
              e.preventDefault();
              if (busy) return;
              const chosen = uploadField
                ? (values[uploadField.id] ?? "").split(",")
                : [];
              edit.onRespond(
                { type: "form", cancelled: false, values },
                uploads.filter((file) => chosen.includes(file.name)),
              );
            }}
            className="flex justify-end"
          >
            <span className="sr-only">{edit.request.prompt}</span>
            <FormActions
              request={edit.request}
              disabled={busy}
              values={values}
              compact
              onCancel={() => cancelForm(edit.onRespond)}
            />
          </form>
        </td>
      </tr>
      {edit.notice && (
        <tr className="border-b border-border bg-muted/40">
          <td
            colSpan={columns.length + (tick ? 1 : 0) + 1}
            className="px-2 pb-2"
          >
            <div role="alert" className="text-xs text-destructive">
              {edit.notice}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

// The Files cell of a row in edit mode. It lists the attached files, each with a remove button.
// Below them, one "Add file" button opens a menu: "Upload a file" first, then the uploaded
// documents that are not attached yet. The value is the attached names joined by commas.
export function RowFiles({
  field,
  value,
  disabled,
  onChange,
  onUpload,
}: {
  field: FormFieldSpec;
  value: string;
  disabled: boolean;
  onChange: (value: string) => void;
  onUpload: (files: File[]) => void;
}) {
  const names = value.split(",").filter(Boolean);
  const offered = (field.choices ?? [])
    .map((choice) => choice.value)
    .filter((name) => !names.includes(name));
  const [menu, setMenu] = useState<MenuPlace | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const close = (refocus: boolean) => {
    setMenu(null);
    if (refocus) trigger.current?.focus();
  };
  return (
    <div className="flex min-w-0 flex-col gap-1">
      {names.length > 0 && (
        <ul className="flex min-w-0 flex-col">
          {names.map((name) => (
            <li key={name} className="flex min-w-0 items-center gap-1">
              <span title={name} className="min-w-0 flex-1 truncate leading-7">
                {name}
              </span>
              <button
                type="button"
                aria-label={`Remove ${name}`}
                disabled={disabled}
                onClick={() =>
                  onChange(names.filter((item) => item !== name).join(","))
                }
                className="shrink-0 rounded-sm p-0.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-40"
              >
                <X size={12} strokeWidth={2} aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      )}
      <button
        ref={trigger}
        type="button"
        aria-haspopup="menu"
        aria-expanded={menu != null}
        disabled={disabled}
        onClick={(event) =>
          menu
            ? close(false)
            : setMenu(menuPlace(event.currentTarget.getBoundingClientRect()))
        }
        className={cn(
          "inline-flex h-8 w-fit max-w-full items-center gap-1 rounded-md border border-border bg-background px-2 text-xs font-medium transition-colors duration-150",
          "hover:bg-muted active:bg-border disabled:cursor-not-allowed disabled:opacity-45",
          menu && "bg-muted",
        )}
      >
        <Plus size={14} strokeWidth={1.75} aria-hidden />
        <span className="truncate">Add file</span>
        <ChevronDown
          size={14}
          strokeWidth={1.75}
          aria-hidden
          className="text-muted-foreground"
        />
      </button>
      <input
        ref={picker}
        type="file"
        multiple
        tabIndex={-1}
        aria-hidden
        className="sr-only"
        onChange={(event) => {
          onUpload([...(event.currentTarget.files ?? [])]);
          event.currentTarget.value = "";
        }}
      />
      {menu &&
        typeof document !== "undefined" &&
        createPortal(
          <FileMenu
            place={menu}
            offered={offered}
            trigger={trigger}
            onUpload={() => {
              close(true);
              picker.current?.click();
            }}
            onAttach={(name) => {
              close(true);
              onChange([...names, name].join(","));
            }}
            onClose={close}
          />,
          document.body,
        )}
    </div>
  );
}

// Where a menu opens: under its trigger, with its left edge on the trigger's left edge. When that
// would push the menu off the right of the window, its right edge goes on the trigger's right edge.
// When the space under the trigger is short and the space above is larger, the menu opens above.
// Its height never passes the space on its side, and the list scrolls inside it.
type MenuPlace = {
  top?: number;
  bottom?: number;
  left?: number;
  right?: number;
  maxHeight: number;
};

const MENU_WIDTH = 288;
const MENU_GAP = 4;
const MENU_MARGIN = 8;

function menuPlace(bounds: DOMRect): MenuPlace {
  const below = window.innerHeight - bounds.bottom - MENU_GAP - MENU_MARGIN;
  const above = bounds.top - MENU_GAP - MENU_MARGIN;
  const vertical =
    below < 240 && above > below
      ? { bottom: window.innerHeight - bounds.top + MENU_GAP, maxHeight: above }
      : { top: bounds.bottom + MENU_GAP, maxHeight: below };
  return bounds.left + MENU_WIDTH + MENU_MARGIN > window.innerWidth
    ? { ...vertical, right: window.innerWidth - bounds.right }
    : { ...vertical, left: bounds.left };
}

// The menu of the Files cell. It floats above the page, so it takes a border and a soft shadow.
// It opens with the first item in focus. The arrow keys move between the items, and Escape, a
// click outside, or a scroll closes it.
export function FileMenu({
  place,
  offered,
  trigger,
  onUpload,
  onAttach,
  onClose,
}: {
  place: MenuPlace;
  offered: readonly string[];
  trigger?: { current: HTMLElement | null };
  onUpload: () => void;
  onAttach: (name: string) => void;
  onClose: (refocus: boolean) => void;
}) {
  const panel = useRef<HTMLDivElement>(null);
  // The listeners stay for the life of the menu; they read the latest close callback.
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    panel.current
      ?.querySelector<HTMLElement>('[role="menuitem"]')
      ?.focus({ preventScroll: true });
    const outside = (event: Event) => {
      const target = event.target as Node;
      if (panel.current?.contains(target) || trigger?.current?.contains(target))
        return;
      closeRef.current(false);
    };
    const away = () => closeRef.current(false);
    document.addEventListener("pointerdown", outside);
    window.addEventListener("scroll", away, true);
    window.addEventListener("resize", away);
    return () => {
      document.removeEventListener("pointerdown", outside);
      window.removeEventListener("scroll", away, true);
      window.removeEventListener("resize", away);
    };
  }, [trigger]);
  const item =
    "flex w-full min-w-0 shrink-0 items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm outline-none transition-colors duration-150 hover:bg-muted focus-visible:bg-muted";
  return (
    <div
      ref={panel}
      role="menu"
      aria-label="Add file"
      style={{ ...place, width: MENU_WIDTH }}
      onKeyDown={(event) => {
        // The row closes its form on Escape, so the menu keeps its keys to itself.
        event.stopPropagation();
        if (event.key === "Escape") {
          event.preventDefault();
          onClose(true);
          return;
        }
        if (event.key === "Tab") {
          onClose(false);
          return;
        }
        const step =
          event.key === "ArrowDown" ? 1 : event.key === "ArrowUp" ? -1 : 0;
        if (step === 0) return;
        event.preventDefault();
        const items = [
          ...(panel.current?.querySelectorAll<HTMLElement>(
            '[role="menuitem"]',
          ) ?? []),
        ];
        const index = items.indexOf(document.activeElement as HTMLElement);
        items[(index + step + items.length) % items.length]?.focus();
      }}
      className="animate-open-menu fixed z-[90] flex flex-col overflow-y-auto rounded-lg border border-border bg-card p-1.5 text-card-foreground shadow-lg"
    >
      <button type="button" role="menuitem" onClick={onUpload} className={item}>
        <Upload
          size={15}
          strokeWidth={1.75}
          aria-hidden
          className="shrink-0 text-muted-foreground"
        />
        <span>Upload a file</span>
      </button>
      {offered.length > 0 && (
        <>
          <div
            role="separator"
            className="-mx-1.5 my-1.5 border-t border-border"
          />
          <div className="px-2 pb-1 text-xs font-medium text-muted-foreground">
            Uploaded documents
          </div>
          {offered.map((name) => (
            <button
              key={name}
              type="button"
              role="menuitem"
              onClick={() => onAttach(name)}
              className={item}
            >
              <FileText
                size={15}
                strokeWidth={1.75}
                aria-hidden
                className="shrink-0 text-muted-foreground"
              />
              <span title={name} className="min-w-0 truncate">
                {name}
              </span>
            </button>
          ))}
        </>
      )}
    </div>
  );
}

// The tick option of a card: the one option that carries a `selected` flag and no icon.
function tickOf(card: AnyCard): Option | undefined {
  return card.options.find(
    (option) => typeof option.selected === "boolean" && !option.icon,
  );
}

function isSelected(card: AnyCard, tick: Option): boolean {
  return card.selected ?? tick.selected === true;
}

type ColumnKind = "text" | "number" | "chips" | "upload" | "rich";

function columnKind(column: CardColumn): ColumnKind {
  const components = column.components ?? [];
  if (components.length === 0) return "text";
  if (components.some((component) => component.type === "number"))
    return "number";
  if (components.some((component) => component.type === "upload"))
    return "upload";
  if (components.every((component) => component.type === "options"))
    return "chips";
  return "rich";
}

// One read-only table cell. The pencil opens the row's edit form, which holds every control, so
// a cell only shows values. A column with no components is its summary as plain text, cut to one
// line with the full text on hover. A chip group shows its selected chips; a chip's hint is its
// hover text. A number field shows its number, and an upload field its file names.
//
// Every cell starts with a 28px line, the height of the row checkbox and the row icons, so the
// first line of each cell sits at the same height across the row.
export function ColumnCell({ column }: { column: CardColumn }) {
  const kind = columnKind(column);
  const none = (
    <span className="block leading-7 text-muted-foreground">None</span>
  );
  if (kind === "chips") {
    const chosen = column.components
      .flatMap((component) =>
        component.type === "options" ? component.options : [],
      )
      .filter((option) => option.selected === true);
    if (chosen.length === 0) return none;
    return (
      <div className="flex min-h-7 min-w-0 flex-wrap items-center gap-0.5">
        {chosen.map((option) => (
          <span
            key={optionKey(option.id)}
            title={option.hint ?? option.label}
            className="rounded border border-accent bg-accent/12 px-1 py-px font-mono text-[10px] leading-tight tracking-tight"
          >
            {option.label}
          </span>
        ))}
      </div>
    );
  }
  if (kind === "upload") {
    const names = column.components.flatMap((component) =>
      component.type === "upload" ? component.value : [],
    );
    if (names.length === 0) return none;
    return (
      <ul className="flex min-w-0 flex-col">
        {names.map((name) => (
          <li key={name} title={name} className="min-w-0 truncate leading-7">
            {name}
          </li>
        ))}
      </ul>
    );
  }
  return (
    <span
      title={column.summary}
      className={cn(
        "block min-w-0 truncate leading-7",
        kind === "number" && "tabular-nums",
      )}
    >
      {column.summary}
    </span>
  );
}

// The options of one item or header. An option with an icon is a square icon action; any other
// option is a button with its label.
function OptionControls({
  options,
  disabled,
  onPick,
}: {
  options: readonly Option[];
  disabled: boolean;
  onPick: (key: string) => void;
}) {
  return (
    <>
      {options.map((option) => (
        <ActionButton
          key={optionKey(option.id)}
          option={option}
          disabled={disabled}
          onPick={onPick}
        />
      ))}
    </>
  );
}

// One option. Every option that the client sends goes through here, so an option with `confirm`
// always asks first: the dialog shows the package's text, and the option is sent only when the
// user agrees. `selected` on a screen option is rare, but honoured as the toggled look.
function ActionButton({
  option,
  disabled,
  onPick,
  variant,
  className,
}: {
  option: Option;
  disabled: boolean;
  onPick: (key: string) => void;
  variant?: "primary" | "secondary" | "ghost";
  className?: string;
}) {
  const [asking, setAsking] = useState(false);
  const key = optionKey(option.id);
  const off = disabled || !option.enabled;
  // A recomposed review or a send in progress closes the question: it asked about a state that
  // may be gone.
  useEffect(() => setAsking(false), [option, off]);
  const choose = () => (option.confirm ? setAsking(true) : onPick(key));
  const control = option.icon ? (
    <IconAction
      icon={option.icon}
      label={option.label}
      disabled={disabled || !option.enabled}
      onClick={choose}
    />
  ) : (
    <Button
      variant={variant ?? (option.primary ? "primary" : "secondary")}
      active={option.selected === true}
      disabled={disabled || !option.enabled}
      className={className}
      onClick={choose}
    >
      {option.label}
    </Button>
  );
  return (
    <>
      {control}
      {asking && option.confirm && (
        <ConfirmDialog
          text={option.confirm}
          confirmLabel={option.icon === "trash" ? "Delete" : option.label}
          onCancel={() => setAsking(false)}
          onConfirm={() => {
            setAsking(false);
            if (!off) onPick(key);
          }}
        />
      )}
    </>
  );
}

// ── cards ─────────────────────────────────────────────────────────────────────

interface RowEdit {
  request: FormRequest;
  busy: boolean;
  notice?: ReactNode;
  onRespond: Emit;
}

type FieldChange = (
  key: string,
  value: CardFieldValue,
  files?: readonly File[],
  removedFixtures?: readonly string[],
) => void;

function CardBlock({
  card,
  disabled,
  onPick,
  onFieldChange,
  editing,
  rowEdit,
}: {
  card: AnyCard;
  disabled: boolean;
  onPick: (key: string) => void;
  onFieldChange: FieldChange;
  // A pending edit of a row inside this card (a Criterion). The row it names takes the form.
  rowEdit?: RowEdit;
  // The pending edit form for this card. The checkbox and the id stay; the form's fields take
  // the title and body positions, and Save and Cancel take the place of the card's actions.
  editing?: {
    request: FormRequest;
    busy: boolean;
    notice?: ReactNode;
    onRespond: Emit;
  };
}) {
  // The checkbox is the card's tick option, the one option that carries `selected`. A card with
  // no tick option draws no box: a box that cannot change would only look broken.
  const tick = tickOf(card);
  const box = tick && (
    <SelectBox
      id={`review-${card.id}`}
      label={card.title}
      // `card.selected` is the item's own state. The tick option's flag is only a copy, and a
      // receipt overwrites it with "was this option the answer".
      checked={card.selected ?? tick.selected === true}
      disabled={disabled}
      onChange={() => onPick(optionKey(tick.id))}
    />
  );
  // The id shows only when it carries meaning to the user (a Behaviour id that other rows name).
  const id =
    card.show_id !== false ? (
      <Mono className="shrink-0 whitespace-nowrap">{card.id}</Mono>
    ) : null;
  const actions = card.options.filter((o) => o !== tick);
  const icons = actions.filter((o) => o.icon);
  const buttons = actions.filter((o) => !o.icon);
  return (
    <div
      data-keep-anchor={card.id}
      className={cn("px-4 py-3", card.blocking && "bg-destructive/5")}
    >
      {editing ? (
        <InlineEdit
          request={editing.request}
          busy={editing.busy}
          notice={editing.notice}
          onRespond={editing.onRespond}
          leading={box ?? undefined}
          trailing={id ?? undefined}
        />
      ) : (
        <div className="flex items-start gap-3">
          {box && <div className="flex h-6 items-center">{box}</div>}
          <div className="flex min-w-0 flex-1 flex-col gap-2">
            <div className="flex min-h-6 items-center justify-between gap-3">
              <label
                htmlFor={box ? `review-${card.id}` : undefined}
                className="min-w-0 font-medium text-foreground"
              >
                {card.title}
              </label>
              <div className="flex shrink-0 items-center gap-1">
                {id}
                <OptionControls
                  options={icons}
                  disabled={disabled}
                  onPick={onPick}
                />
              </div>
            </div>

            {card.components.map((component, i) => (
              <ComponentBlock
                key={i}
                component={component}
                trialCount={"trials" in card ? card.trials : undefined}
                disabled={disabled}
                onPick={onPick}
                onFieldChange={onFieldChange}
                rowEdit={rowEdit}
                nested
              />
            ))}

            {card.note && (
              <p className="text-sm text-muted-foreground">{card.note}</p>
            )}

            {buttons.length > 0 && (
              <div className="flex flex-wrap gap-2 pt-1">
                <OptionControls
                  options={buttons}
                  disabled={disabled}
                  onPick={onPick}
                />
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// The package marks supporting detail (grader settings, extra metadata) as `muted`; the client
// draws it quiet: small grey text.
function quiet(component: CardComponent) {
  return component.muted === true;
}

function ComponentBlock({
  component,
  trialCount,
  disabled,
  density = "form",
  nested = false,
  rowEdit,
  onPick,
  onFieldChange,
}: {
  component: CardComponent;
  trialCount?: number;
  disabled: boolean;
  density?: FieldDensity;
  // Drawn inside a card, where an open, non-muted details block is one row of the card.
  nested?: boolean;
  rowEdit?: RowEdit;
  onPick: (key: string) => void;
  onFieldChange: FieldChange;
}) {
  // The value alone, unlabelled. `FormRow` decides where the label goes: a labelled component
  // reads as a form field (label in a left column, value at the right), an unlabelled one runs
  // full-width. This is a *shape* choice — "does this component carry a label" — not a domain
  // one; only the scenario card composes labelled components, so this is what gives it its form look
  // without the door ever learning it is a scenario.
  const value = (() => {
    switch (component.type) {
      case "details": {
        // A row inside a card: an open details block that is not muted (a Criterion). Its
        // icon-only option group moves to the end of its title line, the same place as the
        // card's own actions, and an edit that one of those options opened takes the row.
        const row = nested && component.expanded && !quiet(component);
        const iconGroup = (child: CardComponent) =>
          child.type === "options" &&
          child.options.length > 0 &&
          child.options.every((option) => option.icon);
        const actions = row
          ? component.components.flatMap((child) =>
              iconGroup(child) && child.type === "options" ? child.options : [],
            )
          : [];
        const children = row
          ? component.components.filter((child) => !iconGroup(child))
          : component.components;
        const item = actions.find((option) => option.id.target)?.id.target;
        const editHere =
          row &&
          rowEdit != null &&
          actions.some(
            (option) =>
              option.id.action === (rowEdit.request.purpose ?? "add") &&
              option.id.target === rowEdit.request.target,
          );
        if (editHere)
          return (
            <div
              data-keep-anchor={item}
              className="rounded-md bg-muted/50 px-3 py-2"
            >
              <InlineEdit
                request={rowEdit.request}
                busy={rowEdit.busy}
                notice={rowEdit.notice}
                onRespond={rowEdit.onRespond}
              />
            </div>
          );
        return (
          <div
            data-keep-anchor={row ? item : undefined}
            className={cn(row && "rounded-md bg-muted/50 px-3 py-2")}
          >
            <Disclosure
              summary={
                <span className={cn(!quiet(component) && "font-medium")}>
                  {component.title}
                </span>
              }
              trailing={
                actions.length > 0 ? (
                  <div className="flex shrink-0 items-center gap-1">
                    <OptionControls
                      options={actions}
                      disabled={disabled}
                      onPick={onPick}
                    />
                  </div>
                ) : undefined
              }
              defaultOpen={component.expanded}
              tone={quiet(component) ? "muted" : "default"}
              contentClassName="mt-1.5 flex flex-col gap-1.5"
            >
              {children.map((child, i) => (
                <ComponentBlock
                  key={i}
                  component={child}
                  disabled={disabled}
                  density={quiet(component) ? "inline" : density}
                  onPick={onPick}
                  onFieldChange={onFieldChange}
                />
              ))}
            </Disclosure>
          </div>
        );
      }
      case "text":
        return (
          <p
            className={cn(
              "whitespace-pre-wrap",
              density === "inline" || quiet(component) ? "text-xs" : "text-sm",
              quiet(component) && "text-muted-foreground",
            )}
          >
            {component.text}
          </p>
        );

      case "options":
        // A chip row. Each chip carries its own `selected`, so it toggles in place and posts its
        // action on click. An option with an icon is an icon action, the same as on a card.
        return (
          <div className="flex w-full flex-wrap items-center gap-1.5">
            {component.options.map((o) => (
              <ActionButton
                key={optionKey(o.id)}
                option={o}
                variant="ghost"
                disabled={disabled}
                className="px-2 py-0.5 text-xs"
                onPick={onPick}
              />
            ))}
          </div>
        );

      case "number":
        return trialCount === undefined ? (
          <NumberCardField
            component={component}
            disabled={disabled}
            density={density}
            onCommit={(value) => onFieldChange(optionKey(component.id), value)}
          />
        ) : (
          <div className="flex min-w-0 items-center gap-3">
            <NumberCardField
              component={component}
              disabled={disabled}
              onCommit={(value) =>
                onFieldChange(optionKey(component.id), value)
              }
            />
            <span className="shrink-0 border-l border-border pl-3 text-xs text-muted-foreground">
              {formatTrials(trialCount)}
            </span>
          </div>
        );

      case "upload":
        return (
          <FixtureField
            component={component}
            disabled={disabled}
            onChange={(names, files, removedFixtures) =>
              onFieldChange(
                optionKey(component.id),
                names,
                files,
                removedFixtures,
              )
            }
          />
        );

      case "divider":
        // A hairline between two component groups. The package drops it between a behaviour's
        // acceptance criteria; the door draws the rule and never learns what it separates. It
        // spans the full card width, so it returns before FormRow's label column below.
        return <div className="border-t border-border" />;
    }
  })();

  // A divider owns the whole row — it carries no label, so it skips FormRow's label/value split
  // and rules straight across.
  if (component.type === "divider") return value;

  return <FormRow label={component.label}>{value}</FormRow>;
}

export function FixtureField({
  component,
  disabled,
  onChange,
}: {
  component: Extract<CardComponent, { type: "upload" }>;
  disabled: boolean;
  onChange: (
    names: string[],
    files: readonly File[],
    removedFixtures: readonly string[],
  ) => void;
}) {
  const remove = (name: string) => {
    const next = component.value.filter((item) => item !== name);
    onChange(next, [], [name]);
  };

  const names = component.value;
  const available = component.available ?? [];
  const toggle = (name: string, checked: boolean) => {
    const next = checked
      ? [...names, name]
      : names.filter((item) => item !== name);
    const removed = names.filter((item) => !next.includes(item));
    onChange(next, [], removed);
  };

  const upload = (files: File[]) => {
    if (files.length === 0) return;
    const next = [...component.value];
    for (const file of files) {
      if (!next.includes(file.name)) next.push(file.name);
    }
    onChange(next, files, []);
  };

  return (
    <div className="flex min-w-0 flex-col gap-2">
      {names.length > 0 && (
        <ul className="flex flex-wrap gap-1.5">
          {names.map((name) => (
            <li
              key={name}
              className="flex items-center gap-1 rounded-md border border-border bg-muted px-2 py-1 text-xs"
            >
              <span className="max-w-48 truncate">{name}</span>
              <button
                type="button"
                aria-label={`Remove ${name}`}
                disabled={disabled}
                onClick={() => remove(name)}
                className="text-muted-foreground hover:text-foreground disabled:opacity-40"
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
      {available.length > 0 && (
        <fieldset className="flex flex-col gap-1.5 rounded-md border border-border p-2">
          <legend className="px-1 text-xs font-medium text-muted-foreground">
            Available early files
          </legend>
          {available.map((name) => (
            <label key={name} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={names.includes(name)}
                disabled={disabled}
                onChange={(event) => toggle(name, event.currentTarget.checked)}
                className="h-4 w-4 accent-[hsl(var(--accent))]"
              />
              <span>{name}</span>
            </label>
          ))}
        </fieldset>
      )}
      <input
        type="file"
        multiple
        disabled={disabled}
        onChange={(event) => {
          upload([...(event.currentTarget.files ?? [])]);
          event.currentTarget.value = "";
        }}
        className="block w-full min-w-0 text-xs text-muted-foreground file:mr-2 file:rounded-md file:border-0 file:bg-background file:px-2 file:py-1 file:text-xs file:font-medium file:text-foreground hover:file:bg-muted"
      />
    </div>
  );
}

function NumberCardField({
  component,
  disabled,
  density = "form",
  onCommit,
}: {
  component: Extract<CardComponent, { type: "number" }>;
  disabled: boolean;
  density?: FieldDensity;
  onCommit: (value: number) => void;
}) {
  const [draft, setDraft] = useState(component.value);

  useEffect(() => setDraft(component.value), [component.value]);

  const commit = (value: number) => {
    const bounded = Math.min(component.max, Math.max(component.min, value));
    setDraft(bounded);
    if (bounded === component.value) return;
    onCommit(bounded);
  };

  return (
    <NumberInput
      value={draft}
      min={component.min}
      max={component.max}
      disabled={disabled}
      density={density}
      ariaLabel={component.label ?? undefined}
      onChange={setDraft}
      onCommit={commit}
    />
  );
}

// One component's row. With a label it reads as a form field — the label in a fixed left column,
// the value aligned to the right of the row — which is what turns the scenario card's stack of
// labelled components into a two-column form. Without a label it runs full-width, so the
// behaviours', criteria' and personas' unlabelled text is untouched.
function FormRow({
  label,
  children,
}: {
  label?: string | null;
  children: ReactNode;
}) {
  if (!label) return <>{children}</>;
  return (
    <div className="flex items-baseline gap-4">
      {/* A fixed column keeps the values on one edge. A long label, such as a detail name with
          no spaces, wraps inside the column and never runs into its value. */}
      <span className="w-32 shrink-0 text-xs font-medium text-muted-foreground [overflow-wrap:anywhere]">
        {label}
      </span>
      {/* The value column: content left-aligned to a common edge just right of the label, so a
          list of chips forms a clean left rule and a scalar sits at the same start. "Fields on
          the right side" means this column, not text pushed to the far margin. */}
      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
        {children}
      </div>
    </div>
  );
}

// ── warnings ─────────────────────────────────────────────────────────────────

// Rendered by source. A document gate ("your document needs a scenario here") is the user's to
// clear and reads calm; a runtime event ("we couldn't reach the model") is not their fault
// and reads as ours. Same component, different skin — never the same skin.
function WarningBlock({
  warning,
  disabled,
  onPick,
}: {
  warning: Warning;
  disabled: boolean;
  onPick: (key: string) => void;
}) {
  const runtime = warning.source === "runtime";
  return (
    <div
      role="status"
      className={cn(
        "rounded-lg border p-2.5 text-sm",
        runtime
          ? "border-destructive/50 bg-destructive/8 text-foreground"
          : "border-gold/50 bg-gold/10 text-foreground",
      )}
    >
      <p>{warning.text}</p>
      {warning.options.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-2">
          {warning.options.map((o) => (
            <ActionButton
              key={optionKey(o.id)}
              option={o}
              disabled={disabled}
              onPick={onPick}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ── form ─────────────────────────────────────────────────────────────────────

// The values of one pending form. The draft survives a remount through the shared draft map,
// so a form that moves between the conversation and an inline edit keeps what the user typed.
export function useFormDraft(request: FormRequest) {
  const drafts = useContext(FormDraftContext);
  const key = `${drafts?.prefix}:${request.request_id}`;
  const [values, updateValues] = useState<Record<string, string>>(
    () =>
      drafts?.values.get(key) ??
      Object.fromEntries(
        request.fields.map((field) => [field.id, field.value ?? ""]),
      ),
  );
  const setValue = (id: string, value: string) => {
    const next = { ...values, [id]: value };
    drafts?.values.set(key, next);
    updateValues(next);
  };
  return { values, setValue };
}

type FormFieldSpec = FormRequest["fields"][number];

type Combinations = readonly Record<string, string>[];

// The used combinations that this choice would make, with the other fields of that combination
// at their current values. The choice stays available: the user can change the other field
// next. Save waits while the whole set of values repeats a used combination, and the package
// checks again when the form comes back.
function usedWith(
  fieldId: string,
  value: string,
  values: Record<string, string>,
  used: Combinations,
): Record<string, string> | undefined {
  return used.find(
    (combination) =>
      combination[fieldId] === value &&
      Object.entries(combination).every(
        ([id, wanted]) => id === fieldId || values[id] === wanted,
      ),
  );
}

// The label of a value in another field of the form, for the "already paired with" note.
function choiceLabel(
  fields: readonly FormFieldSpec[],
  id: string,
  value: string,
): string {
  const field = fields.find((item) => item.id === id);
  return (
    field?.choices?.find((choice) => choice.value === value)?.label ?? value
  );
}

function selectChoices(
  field: FormFieldSpec,
  values: Record<string, string> = {},
  used: Combinations = [],
  fields: readonly FormFieldSpec[] = [],
): SelectChoice[] | null {
  if (field.choices?.length)
    return field.choices.map((choice) => {
      const pair = usedWith(field.id, choice.value, values, used);
      const others = Object.entries(pair ?? {})
        .filter(([id]) => id !== field.id)
        .map(([id, value]) => choiceLabel(fields, id, value));
      return {
        value: choice.value,
        hint: choice.hint,
        label:
          pair && values[field.id] !== choice.value
            ? `${choice.label} (already paired with ${others.join(", ")})`
            : choice.label,
      };
    });
  // A multi-choice field with no choices yet (Files before any upload) is still a choice field.
  if (field.multiple === true) return [];
  if (field.input_type === "boolean")
    return [
      { value: "true", label: "true" },
      { value: "false", label: "false" },
    ];
  return null;
}

// One form field, drawn from its shape alone: a choice list is a select, a multiline field is a
// text area, everything else is a text or number input.
export function FormFieldControl({
  field,
  value,
  disabled,
  density = "form",
  hideLabel = false,
  autoFocus,
  values = {},
  used = [],
  fields = [],
  form,
  onChange,
}: {
  field: FormFieldSpec;
  value: string;
  disabled: boolean;
  // The id of the form element, when the control is outside it (a table cell).
  form?: string;
  density?: FieldDensity;
  hideLabel?: boolean;
  autoFocus?: boolean;
  // The whole form's values and its used combinations, for choices that would repeat a pair.
  values?: Record<string, string>;
  used?: Combinations;
  // All the fields of the form, for the names in an "already paired with" note.
  fields?: readonly FormFieldSpec[];
  onChange: (value: string) => void;
}) {
  const choices = selectChoices(field, values, used, fields);
  const taken = choices != null && usedWith(field.id, value, values, used);
  const control =
    field.input_type === "pairs" ? (
      <PairsInput
        ariaLabel={field.label}
        value={value}
        placeholder={field.placeholder}
        disabled={disabled}
        density={density}
        onChange={onChange}
      />
    ) : field.multiple === true ? (
      <MultiChoice
        ariaLabel={field.label}
        value={value}
        choices={choices ?? []}
        disabled={disabled}
        onChange={onChange}
      />
    ) : choices ? (
      <SelectInput
        form={form}
        ariaLabel={field.label}
        value={value}
        choices={choices}
        placeholder="Select a value"
        disabled={disabled}
        required={field.required}
        density={density}
        onChange={onChange}
      />
    ) : field.multiline ? (
      <TextArea
        form={form}
        ariaLabel={field.label}
        value={value}
        placeholder={field.placeholder}
        disabled={disabled}
        required={field.required}
        density={density}
        onChange={onChange}
      />
    ) : (
      <TextInput
        form={form}
        ariaLabel={field.label}
        type={
          field.input_type === "integer" || field.input_type === "number"
            ? "number"
            : "text"
        }
        step={field.input_type === "integer" ? 1 : "any"}
        value={value}
        placeholder={field.placeholder}
        disabled={disabled}
        required={field.required}
        autoFocus={autoFocus}
        density={density}
        onChange={onChange}
      />
    );
  return (
    <Field
      title={hideLabel ? field.help || undefined : undefined}
      label={field.label}
      // A field whose label is hidden (a table cell) keeps its help as hover text only.
      help={hideLabel ? undefined : field.help || undefined}
      error={taken ? "This combination is already used." : undefined}
      density={density}
      hideLabel={hideLabel}
      group={field.input_type === "pairs"}
    >
      {control}
    </Field>
  );
}

// The fields of a form, in order. Grouped fields go into one closed Disclosure per group.
export function FormFields({
  fields,
  values,
  disabled,
  density = "form",
  used = [],
  onChange,
}: {
  fields: readonly FormFieldSpec[];
  values: Record<string, string>;
  disabled: boolean;
  density?: FieldDensity;
  used?: Combinations;
  onChange: (id: string, value: string) => void;
}) {
  const control = (field: FormFieldSpec) => (
    <FormFieldControl
      key={field.id}
      field={field}
      value={values[field.id] ?? ""}
      values={values}
      used={used}
      fields={fields}
      disabled={disabled}
      density={density}
      onChange={(value) => onChange(field.id, value)}
    />
  );
  const groups = [
    ...new Set(
      fields.map((field) => field.group).filter((group) => group != null),
    ),
  ];
  return (
    <>
      {fields.filter((field) => !field.group).map(control)}
      {groups.map((group) => (
        <Disclosure
          key={group}
          tone="muted"
          summary={group}
          contentClassName="mt-3 flex flex-col gap-3"
        >
          {fields.filter((field) => field.group === group).map(control)}
        </Disclosure>
      ))}
    </>
  );
}

// The submit button with the package's label ("Save", or "Continue" on a Target form) and, when
// the form allows it, Cancel.
export function FormActions({
  request,
  disabled,
  onCancel,
  compact = false,
  vertical = false,
  values,
}: {
  request: FormRequest;
  disabled: boolean;
  onCancel: () => void;
  compact?: boolean;
  // Stack the buttons, for a narrow table cell.
  vertical?: boolean;
  // When given, Save waits while the values repeat a used combination.
  values?: Record<string, string>;
}) {
  const repeats =
    values != null &&
    (request.used_combinations ?? []).some((combination) =>
      Object.entries(combination).every(([id, value]) => values[id] === value),
    );
  const size = compact ? "px-2.5 py-1 text-xs" : undefined;
  return (
    <div
      className={cn(
        "flex shrink-0 gap-2",
        vertical ? "flex-col items-stretch gap-1" : "items-center",
      )}
    >
      <Button
        type="submit"
        variant="primary"
        disabled={disabled || repeats}
        className={size}
      >
        {request.submit_label ?? "Save"}
      </Button>
      {request.cancellable && (
        <Button
          type="button"
          variant="ghost"
          disabled={disabled}
          className={size}
          onClick={onCancel}
        >
          Cancel
        </Button>
      )}
    </div>
  );
}

function submitForm(
  onRespond: Emit,
  values: Record<string, string>,
  busy: boolean,
) {
  if (busy) return;
  onRespond({ type: "form", cancelled: false, values });
}

const cancelForm = (onRespond: Emit) =>
  onRespond({ type: "form", cancelled: true, values: {} });

function FormBlock({
  request,
  resolved,
  busy,
  onRespond,
}: {
  request: FormRequest;
  resolved: boolean;
  busy: boolean;
  onRespond: Emit;
}) {
  // A resolved form is a receipt: show what was submitted, labelled by field, the same way a
  // resolved chat shows its answer. The package stamped the values onto the request.
  if (resolved) {
    const submitted = request.fields
      .map((field) => ({ field, value: request.answer[field.id] }))
      .filter((row) => row.value);
    if (submitted.length === 0) return null;
    return (
      <div className="flex flex-col gap-2">
        {submitted.map(({ field, value }) => (
          <div key={field.id} className="flex flex-col gap-0.5">
            <span className="text-xs font-medium text-muted-foreground">
              {field.label}
            </span>
            <UserSaid text={value} />
          </div>
        ))}
      </div>
    );
  }
  return <PendingForm request={request} busy={busy} onRespond={onRespond} />;
}

function PendingForm({
  request,
  busy,
  onRespond,
}: {
  request: FormRequest;
  busy: boolean;
  onRespond: Emit;
}) {
  const { values, setValue } = useFormDraft(request);
  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        submitForm(onRespond, values, busy);
      }}
    >
      <FormFields
        fields={request.fields}
        values={values}
        used={request.used_combinations}
        disabled={busy}
        onChange={setValue}
      />
      <FormActions
        request={request}
        disabled={busy}
        values={values}
        onCancel={() => cancelForm(onRespond)}
      />
    </form>
  );
}

// An edit form drawn in the place of the item it edits. The first single-line field takes the
// title position, beside the checkbox and the id; the other fields take the body position; Save
// and Cancel take the place of the item's actions. This rule reads only the form's shape.
export function InlineEdit({
  request,
  busy,
  onRespond,
  leading,
  trailing,
  notice,
}: {
  request: FormRequest;
  busy: boolean;
  onRespond: Emit;
  // What stays from the item: its checkbox before the title, its id after it.
  leading?: ReactNode;
  trailing?: ReactNode;
  // Why the package refused the last save, when it did.
  notice?: ReactNode;
}) {
  const { values, setValue } = useFormDraft(request);
  const titleField = request.fields.find(
    (field) => !field.multiline && !field.group && !selectChoices(field),
  );
  // A form with no free-text title (a Test Case pair) has no title place to take.
  const rest = request.fields.filter((field) => field !== titleField);
  return (
    <form
      aria-label={request.prompt || "Edit"}
      className="flex flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        submitForm(onRespond, values, busy);
      }}
      onKeyDown={(e) => {
        if (e.key === "Escape" && request.cancellable && !busy) {
          e.preventDefault();
          cancelForm(onRespond);
        }
      }}
    >
      <div className="flex min-w-0 items-center gap-3">
        {leading}
        <div className="min-w-0 flex-1">
          {titleField && (
            <FormFieldControl
              field={titleField}
              value={values[titleField.id] ?? ""}
              disabled={busy}
              density="inline"
              hideLabel
              autoFocus
              onChange={(value) => setValue(titleField.id, value)}
            />
          )}
        </div>
        {trailing}
        <FormActions
          request={request}
          disabled={busy}
          values={values}
          compact
          onCancel={() => cancelForm(onRespond)}
        />
      </div>
      {notice && (
        <div
          role="alert"
          className={cn("text-xs text-destructive", leading != null && "pl-7")}
        >
          {notice}
        </div>
      )}
      {rest.length > 0 && (
        <div className={cn("flex flex-col gap-2", leading != null && "pl-7")}>
          <FormFields
            fields={rest}
            values={values}
            used={request.used_combinations}
            disabled={busy}
            density="inline"
            onChange={setValue}
          />
        </div>
      )}
    </form>
  );
}

// ── the user's own voice ───────────────────────────────────────────────────

// What the user typed, shown back in a resolved block. Set apart from the package's prompt —
// which is plain foreground text flush to the left — by a tint, a left rule and an indent, so
// the two sides of the exchange read as two sides without either being domain-aware. The
// package composed the question; this is the only text in the transcript the user wrote.
function UserSaid({ text }: { text: string }) {
  return (
    <div className="border-l-2 border-accent/40 bg-muted/40 pl-3 pr-2 py-1.5">
      <p className="whitespace-pre-wrap text-foreground">{text}</p>
    </div>
  );
}

// ── the composer ─────────────────────────────────────────────────────────────

// Whether the composer takes text for this request. A chat request does, and so does a review
// that asks for feedback, even while the review waits behind an open form: the user can always
// type a change.
export function acceptsChat(request: WizardRequest | undefined): boolean {
  if (!request) return false;
  if (request.type === "chat") return request.state === "pending";
  return request.type === "choice" && Boolean(request.feedback_placeholder);
}

// The placeholder: the package's own words for how this screen wants to be answered.
export function composerHint(request: WizardRequest | undefined): string {
  if (request?.type === "choice")
    return request.feedback_placeholder || request.instruction || "";
  if (request?.type === "chat") return "Type a reply";
  if (request?.type === "form") return "Save or cancel the form to continue";
  return "";
}

export function Composer({
  request,
  busy,
  onSend,
  alwaysEnabled = false,
  placeholder,
  initialText = "",
  value,
  onValueChange,
  roomy = false,
  leadingIcon = false,
  bare = false,
  sourceControl,
  sendBlockedReason,
}: {
  request: WizardRequest | undefined;
  busy: boolean;
  onSend: (text: string) => void;
  // The opening screen has no interview yet, so there is no request to derive from — it is a
  // way in, always open. Everywhere else the greying rule stands.
  alwaysEnabled?: boolean;
  placeholder?: string;
  // The opening flow can return from capability selection to the description without losing the
  // user's draft. Interview replies remain empty on mount.
  initialText?: string;
  value?: string;
  onValueChange?: (value: string) => void;
  // Give the opening target prompt enough room for a useful first description. Conversation
  // replies keep the smaller composer.
  roomy?: boolean;
  // A pencil-sparkles mark inside the input, left of the text. Only the opening screen's hero
  // composer asks for it; the in-conversation composer leaves it off, so the mark reads as "this
  // is where you begin" rather than decoration on every turn.
  leadingIcon?: boolean;
  // Drop the bottom-dock chrome — the outer padding and the composer's own max-width. The
  // opening screen already lays the composer inside a sized column alongside the entry cards, so
  // it should fill that column and match their width rather than re-centre itself narrower.
  bare?: boolean;
  sourceControl?: ReactNode;
  // When set, Send stays grey and shows this text on hover and focus. The user can still type.
  sendBlockedReason?: string;
}) {
  const [localText, setLocalText] = useState(initialText);
  const text = value ?? localText;
  const setText = (next: string) => {
    setLocalText(next);
    onValueChange?.(next);
  };
  // Typing stays open while a reply is in flight; only Send waits for it.
  const enabled = alwaysEnabled || acceptsChat(request);
  const hint = placeholder ?? composerHint(request);

  const submit = () => {
    const trimmed = text.trim();
    if (!trimmed || !enabled || busy || sendBlockedReason) return;
    onSend(trimmed);
    if (value === undefined) setText("");
  };

  const canSend =
    enabled && !busy && text.trim().length > 0 && !sendBlockedReason;

  // The box grows with what is being typed and only scrolls once it has run out of room. The
  // comment below the textarea has always claimed this; nothing implemented it, so `rows={3}` was
  // the whole story and a paragraph was written through a three-line slot that scrolled from the
  // second sentence onward. Measuring is the only way to do it: reset to `auto` first, or
  // `scrollHeight` reports the height already set rather than the height wanted.
  const field = useRef<HTMLTextAreaElement | null>(null);
  useLayoutEffect(() => {
    const el = field.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [text]);

  // Whether the field has been scrolled away from its first line. Once it has, the top edge takes
  // a short fade so the partial line at the cut reads as text continuing above rather than as text
  // sliced through — the hard clip a few pixels under a rounded border looked like a rendering
  // fault. At rest there is nothing to fade, and applying it then would wash out the first line.
  const [scrolled, setScrolled] = useState(false);

  const sendButton = (
    <button
      type="button"
      aria-label="Send"
      disabled={!canSend}
      onClick={submit}
      className={cn(
        "flex h-9 w-9 shrink-0 items-center justify-center rounded-full",
        "mb-0.5",
        "transition-colors",
        canSend
          ? "bg-primary text-primary-foreground hover:opacity-90"
          : "bg-muted text-muted-foreground",
      )}
    >
      <ArrowUp size={16} strokeWidth={1.75} aria-hidden />
    </button>
  );
  const send = sendBlockedReason ? (
    // A disabled button gets no pointer events, so the tooltip listens on its wrapper.
    <Tooltip label={sendBlockedReason} className="shrink-0">
      {sendButton}
    </Tooltip>
  ) : (
    sendButton
  );

  const textarea = (
    <textarea
      ref={field}
      className={cn(
        // Taller by default and a higher cap: the box showed barely a line, so a
        // paragraph scrolled out of sight while being written. Three lines to start,
        // grows to a comfortable draft before it scrolls.
        "max-h-64 flex-1 resize-none bg-transparent py-2.5",
        roomy ? "min-h-32" : "min-h-[4.5rem]",
        "placeholder:text-muted-foreground focus:outline-none",
        "disabled:cursor-not-allowed",
        // A hairline thumb instead of the platform's default bar, which sat wide and opaque
        // against the rounded edge of the composer and read as a piece of another interface.
        "quiet-scrollbar",
        scrolled && "faded-top",
      )}
      placeholder={hint}
      value={text}
      disabled={!enabled}
      rows={roomy ? 5 : 3}
      onScroll={(e) => setScrolled(e.currentTarget.scrollTop > 0)}
      onChange={(e) => setText(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          submit();
        }
      }}
    />
  );

  const leading = leadingIcon && (
    <PencilSparkles
      size={18}
      strokeWidth={1.75}
      aria-hidden
      // Top-left, centred on the first line of text. That line sits in a 1.6 line-height
      // box beginning after the textarea's py-2.5, so the icon takes a slightly larger top
      // offset to land level with it rather than riding above the caps.
      className="mt-[0.9rem] shrink-0 self-start text-muted-foreground"
    />
  );

  const pill = (
    <div
      className={cn(
        "flex rounded-2xl border border-input bg-card p-2 pl-4",
        sourceControl ? "flex-col gap-1" : "items-end gap-2",
        "transition-colors focus-within:border-accent",
        !enabled && "opacity-70",
      )}
    >
      {sourceControl ? (
        <>
          <div className="flex w-full items-start gap-2">
            {leading}
            {textarea}
          </div>
          <div className="flex w-full items-center justify-between gap-2">
            {sourceControl}
            {send}
          </div>
        </>
      ) : (
        <>
          {leading}
          {textarea}
          {send}
        </>
      )}
    </div>
  );

  // Bare: the caller owns width and spacing. Docked: float clear of the bottom edge, centred in an
  // 80%-wide column so the 10% gutters on each side match the transcript's and the input sits over
  // the same width as the conversation above it.
  if (bare) return pill;
  return (
    <div className="w-full pb-6 pt-2">
      <div className="mx-auto w-4/5">{pill}</div>
    </div>
  );
}
