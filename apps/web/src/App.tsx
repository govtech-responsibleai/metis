import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type CSSProperties,
} from "react";
import { PanelLeft, PanelRight, Puzzle, X } from "lucide-react";
import type {
  InterviewSummary,
  LocalInterviewRecord,
  CapabilityConfidence,
  CapabilityEvidence,
  InterviewDocument,
  ModelStatus,
  Perspective,
  UserResponse,
  ConnectionCheckResult,
  TargetConnection,
} from "./transport/api";
import { api, TransportError, toSummary } from "./transport/api";
import {
  ActiveReview,
  Composer,
  placeForm,
  reviewParts,
  ReviewSectionActions,
  Transcript,
} from "./Conversation";
import { ConnectionForm, ModePicker } from "./ConnectionStep";
import {
  bindingFromDraft,
  emptyConnectionDraft,
  startConnection,
  type ConnectionDraft,
} from "./connection";
import { AddDocuments, DocumentTray } from "./DocumentTray";
import { Done } from "./Done";
import {
  START_BLOCKED,
  interviewReady,
  RunSettings,
  runModels,
  runRoles,
  stateForDownload,
  type RunModels,
} from "./RunSettings";
import { SpecificationView, stepPosition } from "./SpecificationView";
import { InterviewRail } from "./InterviewRail";
import { PaneDivider, useChatWidth } from "./pane-divider";
import { Button, cn } from "./ui";
import {
  CapabilityConfidencePicker,
  CapabilityPicker,
  DEFAULT_PERSPECTIVE,
  FooterChip,
  PERSPECTIVE_ICONS,
  PerspectivePicker,
  UnderBoxSurface,
} from "./OpeningControls";
import {
  InterviewRepository,
  emptyRecord,
  addFixtures,
  fixturesForSpecification,
  type LocalStorageProblem,
} from "./storage/repository";
import {
  normalizeFixtureName,
  validateFixtureSelection,
} from "./fixture-policy";
import { specificationHasCriteria } from "./graders";
import { downloadArchive } from "./download";
import { ManualAuthoringEntry, ManualForm } from "./ManualForm";
import {
  activeReview,
  applyEnd,
  startTranscript,
  toPresentation,
} from "./wizard/transcript";

import { TabNavigation, type TabEntry } from "./wizard/navigation";
import { InterviewOperations, pendingEntry } from "./wizard/operations";

const repository = new InterviewRepository();
type WizardConfig = Awaited<ReturnType<typeof api.config>>;
export type OpeningControl = "perspective" | "capabilities";
type OpeningDocumentRead =
  | { status: "reading" | "not_read" | "kept" }
  | { status: "read"; text: string }
  | { status: "failed"; message: string };
export type WizardConfigState =
  | { status: "loading" }
  | { status: "ready"; config: WizardConfig }
  | { status: "error"; message: string };
export type CapabilityEvidenceDraft = Omit<CapabilityEvidence, "confidence"> & {
  confidence: CapabilityConfidence | null;
};

const emptyCapabilityEvidence = (): CapabilityEvidenceDraft => ({
  known_capability_ids: [],
  confidence: null,
});

function fileExtension(name: string): string {
  return name.split(".").at(-1)?.toLowerCase() ?? "";
}

function unicodeLength(value: string): number {
  return Array.from(value).length;
}

async function extractOpeningDocuments(
  file: File,
  maxFileBytes: number,
): Promise<string> {
  if (file.size > maxFileBytes)
    throw new Error(`${file.name} is larger than the text-reading limit.`);
  const result = await api.extractDocuments([file]);
  const document = result.documents.find((item) => item.name === file.name);
  if (!document) throw new Error(`No text was returned for ${file.name}.`);
  return document.text;
}

// Capabilities are optional. An untouched picker sends no evidence, so the Interview treats
// capabilities as unspecified. A selection with no confidence may be incomplete, which is what
// "low" tells the Interview.
export function completeCapabilityEvidence(
  draft: CapabilityEvidenceDraft,
): CapabilityEvidence | null {
  if (draft.known_capability_ids.length === 0 && draft.confidence === null)
    return null;
  return {
    known_capability_ids: draft.known_capability_ids,
    confidence: draft.confidence ?? "low",
  };
}

export function conversationScrollRevision(
  interviewId: string | null,
  requestCount: number,
  done: boolean,
  submission = "",
): string {
  return `${interviewId ?? "opening"}:${requestCount}:${done ? "complete" : "active"}:${submission}`;
}

export function App() {
  const [interviews, setInterviews] = useState<InterviewSummary[]>([]);
  const [storageProblems, setStorageProblems] = useState<
    readonly LocalStorageProblem[]
  >([]);
  const [record, setRecord] = useState<LocalInterviewRecord | null>(null);
  const [destination, setDestination] = useState<TabEntry | null>(null);
  const destinationRef = useRef<TabEntry | null>(null);
  const navigation = useRef<TabNavigation | null>(null);
  const refreshListRef = useRef<() => Promise<void>>(async () => {});
  const [operations] = useState(
    () =>
      new InterviewOperations(repository, (next) => {
        const current = destinationRef.current?.destination;
        if (current?.kind === "interview" && current.id === next.id)
          setRecord(next);
        void refreshListRef.current().catch(() => {});
      }),
  );
  useSyncExternalStore(operations.subscribe, operations.snapshot);
  const operationKey =
    destination?.destination.kind === "interview"
      ? destination.destination.id
      : `opening:${destination?.entry ?? "loading"}`;
  const busy = operations.active.has(operationKey);
  const feedback = operations.feedback.get(operationKey);
  const error = feedback?.message ?? null;
  const setError = useCallback(
    (message: string | null) => {
      if (message) operations.report(operationKey, message);
      else operations.dismiss(operationKey);
    },
    [operations, operationKey],
  );
  const drafts = useRef(new Map<string, string>());
  const [, setDraftRevision] = useState(0);
  const formDrafts = useRef(new Map<string, Record<string, string>>());
  const draftKey = `${record?.id ?? "new"}:${record?.state.pending?.type === "choice" && record.state.pending.feedback_placeholder ? `feedback-${record.state.pending.stage}` : (record?.state.pending?.request_id ?? "")}`;
  const [workingStatus, setWorkingStatus] = useState("Working…");
  const [wizardConfig, setWizardConfig] = useState<WizardConfigState>({
    status: "loading",
  });
  const [selectedPerspective, setSelectedPerspective] =
    useState<Perspective>(DEFAULT_PERSPECTIVE);
  const [openingControl, setOpeningControl] = useState<OpeningControl | null>(
    null,
  );
  // The default Perspective stays marked until the user first opens the Perspective control.
  const [perspectiveSeen, setPerspectiveSeen] = useState(false);
  const [openingDescription, setOpeningDescription] = useState("");
  const [openingDocuments, setOpeningDocuments] = useState<File[]>([]);
  // An extraction response belongs only to the opening session that requested it.
  const openingGeneration = useRef(0);
  const [documentTrayOpen, setDocumentTrayOpen] = useState(false);
  const [openingDocumentReads, setOpeningDocumentReads] = useState<
    Record<string, OpeningDocumentRead>
  >({});
  const [capabilityEvidence, setCapabilityEvidence] =
    useState<CapabilityEvidenceDraft>(emptyCapabilityEvidence);
  // The opening owns the connection in run mode. "add" is the Done pane's Connect target.
  const [connectionStep, setConnectionStep] = useState<"add" | null>(null);
  const [connectionDraft, setConnectionDraft] =
    useState<ConnectionDraft>(emptyConnectionDraft);
  const [connectionResult, setConnectionResult] =
    useState<ConnectionCheckResult | null>(null);

  const [loadingRecord, setLoadingRecord] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [railOpen, setRailOpen] = useState(true);
  const [chatWidth, setChatWidth] = useChatWidth();
  const panesRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const narrow = window.matchMedia("(max-width: 767px)");
    const closePanels = () => {
      if (narrow.matches) {
        setRailOpen(false);
      }
    };
    closePanels();
    narrow.addEventListener("change", closePanels);
    return () => narrow.removeEventListener("change", closePanels);
  }, []);
  const [manualOpen, setManualOpen] = useState(false);
  const [showGraders, setShowGraders] = useState(false);
  const [graderCatalogue, setGraderCatalogue] = useState<Awaited<
    ReturnType<typeof api.graders>
  > | null>(null);
  const [graderState, setGraderState] = useState<
    "idle" | "loading" | "ready" | "error"
  >("idle");
  const graderRequest = useRef<Promise<
    Awaited<ReturnType<typeof api.graders>>
  > | null>(null);
  const [modelStatuses, setModelStatuses] = useState<ModelStatus[]>([]);
  const [runModelDrafts, setRunModelDrafts] = useState<RunModels | null>(null);
  // The Interview whose finish waits on the run settings step. The download starts when the
  // user continues from that step.
  const [runSettingsFor, setRunSettingsFor] = useState<string | null>(null);

  const view = useMemo(() => record && toPresentation(record), [record]);
  const review = view && !view.done ? activeReview(view.requests) : null;
  const conversationScrollRef = useRef<HTMLDivElement | null>(null);
  const conversationRevision = conversationScrollRevision(
    view?.id ?? null,
    view?.requests.length ?? 0,
    view?.done ?? false,
    `${record?.submission_revision ?? 0}:${record ? (pendingEntry(record)?.status ?? "") : ""}`,
  );
  const pending = record?.state.pending ?? undefined;
  // The composer keeps one draft per review step, so a draft typed while a form is open stays
  // when the form closes.
  // A pending form that an item of the live review opened. The Profile draws it in place.
  const profileForm =
    review && pending?.type === "form" && placeForm(review, pending)
      ? pending
      : null;
  const failedEntry = record && profileForm ? pendingEntry(record) : undefined;
  const profileFailure =
    record && failedEntry?.status === "failed" && failedEntry.failure
      ? {
          message: failedEntry.failure.message,
          onRetry: failedEntry.failure.retryable
            ? () => void operations.retry(record)
            : undefined,
          onEdit:
            failedEntry.failure.kind !== "storage"
              ? () => {
                  const response = failedEntry.response;
                  if (response?.type === "form")
                    formDrafts.current.set(draftKey, response.values ?? {});
                  void operations.edit(record);
                }
              : undefined,
        }
      : null;
  const replyBusy =
    busy ||
    (record !== null &&
      (operations.pendingSaves.has(record.id) ||
        ["sending", "failed"].includes(pendingEntry(record)?.status ?? "")));
  const composerKey = review
    ? `${record?.id ?? "new"}:feedback-${review.stage}`
    : draftKey;
  const graderByFqn = useMemo(
    () =>
      new Map((graderCatalogue ?? []).map((grader) => [grader.fqn, grader])),
    [graderCatalogue],
  );
  const hasCriteria = view
    ? specificationHasCriteria(view.specification)
    : false;

  useEffect(() => {
    setShowGraders(false);
    setRunModelDrafts(null);
  }, [record?.id]);

  useEffect(() => {
    // A failed request leaves the statuses empty; the Interview routes still report missing
    // settings themselves.
    void api.models().then(setModelStatuses, () => setModelStatuses([]));
  }, []);

  const nearFoot = useRef(true);
  const scrollInterview = useRef<string | null>(null);
  useLayoutEffect(() => {
    const container = conversationScrollRef.current;
    // New content in the conversation (a reply, the working line, a failure with Retry) scrolls into
    // view when the user was at the foot, on review steps too.
    if (container && (nearFoot.current || scrollInterview.current !== view?.id))
      container.scrollTop = container.scrollHeight;
    scrollInterview.current = view?.id ?? null;
  }, [conversationRevision, view?.id]);

  const loadWizardConfig = useCallback(async () => {
    setWizardConfig({ status: "loading" });
    try {
      const config = await api.config();
      setWizardConfig({ status: "ready", config });
      setWorkingStatus(config.working_status);
    } catch (cause) {
      setWizardConfig({ status: "error", message: errorMessage(cause) });
    }
  }, []);

  useEffect(() => {
    void loadWizardConfig();
  }, [loadWizardConfig]);

  const refreshList = useCallback(async () => {
    const rows = await repository.list();
    setInterviews(rows.map(toSummary));
    setStorageProblems([...repository.problems]);
  }, []);

  refreshListRef.current = refreshList;
  useEffect(() => {
    let disposed = false;
    const nav = new TabNavigation(window, (entry) => {
      if (disposed) return;
      destinationRef.current = entry;
      setDestination(entry);
      setManualOpen(false);
      setConnectionStep(null);
      setRecord(null);
      setLoadingRecord(entry.destination.kind === "interview");
      void (async () => {
        try {
          if (entry.destination.kind === "interview") {
            const stored = await repository.read(entry.destination.id);
            const next = stored
              ? await operations.recover(
                  operations.latest.get(stored.id) ?? stored,
                )
              : null;
            if (!disposed && destinationRef.current?.entry === entry.entry)
              setRecord(next);
          }
        } catch (cause) {
          if (entry.destination.kind === "interview")
            operations.report(entry.destination.id, errorMessage(cause));
        } finally {
          if (!disposed && destinationRef.current?.entry === entry.entry) {
            setLoaded(true);
            setLoadingRecord(false);
          }
        }
      })();
    });
    navigation.current = nav;
    void refreshList().catch(() => {});
    void nav.initialize();
    return () => {
      disposed = true;
      nav.dispose();
    };
  }, [operations, refreshList]);
  useEffect(() => {
    if (!hasCriteria || graderRequest.current) return;
    setGraderState("loading");
    const request = api.graders();
    graderRequest.current = request;
    void request.then(
      (rows) => {
        setGraderCatalogue(rows);
        setGraderState("ready");
      },
      () => setGraderState("error"),
    );
  }, [hasCriteria]);

  const open = useCallback((id: string) => {
    navigation.current?.go({ kind: "interview", id });
  }, []);
  const startNew = useCallback(() => {
    openingGeneration.current += 1;
    navigation.current?.go({ kind: "new" });
    setOpeningControl(null);
    setPerspectiveSeen(false);
    setOpeningDescription("");
    setOpeningDocuments([]);
    setDocumentTrayOpen(false);
    setOpeningDocumentReads({});
    setCapabilityEvidence(emptyCapabilityEvidence());
    setConnectionStep(null);
    setConnectionDraft(emptyConnectionDraft());
    setConnectionResult(null);
  }, []);

  const addOpeningDocuments = useCallback(
    (files: readonly File[]) => {
      try {
        if (
          wizardConfig.status !== "ready" ||
          !wizardConfig.config.document_limits
        )
          throw new Error("Document limits are not available yet.");
        const limits = wizardConfig.config.document_limits;
        const names = validateFixtureSelection(files, openingDocuments, limits);
        const normalized = files.map((file, index) => {
          const name = names[index] ?? normalizeFixtureName(file.name);
          return name === file.name
            ? file
            : new File([file], name, {
                type: file.type,
                lastModified: file.lastModified,
              });
        });
        const reads: Record<string, OpeningDocumentRead> = {};
        for (const file of normalized) {
          const canRead = limits.extraction_extensions?.includes(
            fileExtension(file.name),
          );
          reads[file.name] = !canRead
            ? { status: "not_read" }
            : file.size > limits.max_extraction_file_bytes
              ? {
                  status: "failed",
                  message: "This file is larger than the text-reading limit.",
                }
              : { status: "reading" };
        }
        setOpeningDocuments((current) => [...current, ...normalized]);
        setOpeningDocumentReads((current) => ({ ...current, ...reads }));
        setError(null);
        for (const file of normalized) {
          if (reads[file.name]?.status !== "reading") continue;
          const generation = openingGeneration.current;
          void extractOpeningDocuments(
            file,
            limits.max_extraction_file_bytes,
          ).then(
            (text) => {
              if (generation !== openingGeneration.current) return;
              setOpeningDocumentReads((current) => ({
                ...current,
                [file.name]: { status: "read", text },
              }));
            },
            (cause: unknown) => {
              if (generation !== openingGeneration.current) return;
              setOpeningDocumentReads((current) => ({
                ...current,
                [file.name]: {
                  status: "failed",
                  message: errorMessage(cause),
                },
              }));
            },
          );
        }
      } catch (cause) {
        setError(errorMessage(cause));
      }
    },
    [openingDocuments, wizardConfig, setError],
  );

  const removeOpeningDocument = useCallback(
    (name: string) => {
      setOpeningDocuments((current) =>
        current.filter((file) => file.name !== name),
      );
      setOpeningDocumentReads((current) => {
        const next = { ...current };
        delete next[name];
        return next;
      });
      setError(null);
    },
    [setError],
  );

  const keepOpeningDocumentWithoutReading = useCallback(
    (name: string) => {
      setOpeningDocumentReads((current) => ({
        ...current,
        [name]: { status: "kept" },
      }));
      setError(null);
    },
    [setError],
  );

  const beginWithMessage = useCallback(
    async (
      description: string,
      perspective: Perspective,
      evidence: CapabilityEvidence | null,
      connection: TargetConnection | null = null,
    ) => {
      if (busy) return;
      const origin = destinationRef.current?.entry;
      const localId = crypto.randomUUID();
      await operations.run(operationKey, async () => {
        const limits =
          wizardConfig.status === "ready"
            ? wizardConfig.config.document_limits
            : undefined;
        if (openingDocuments.length > 0 && !limits)
          throw new Error("Document limits are not available yet.");
        if (limits) validateFixtureSelection(openingDocuments, [], limits);
        const unresolved = openingDocuments.filter((file) => {
          const status = openingDocumentReads[file.name]?.status;
          return status === "reading" || status === "failed";
        });
        if (unresolved.length > 0) {
          setConnectionStep(null);
          setOpeningControl(null);
          setDocumentTrayOpen(true);
          setError(
            "Wait for files to finish reading. For a file that could not be read, choose Keep without reading or remove it.",
          );
          return;
        }
        const totalText = openingDocuments.reduce((total, file) => {
          const read = openingDocumentReads[file.name];
          return (
            total + (read?.status === "read" ? unicodeLength(read.text) : 0)
          );
        }, 0);
        if (limits && totalText > limits.max_text_characters_total) {
          setConnectionStep(null);
          setOpeningControl(null);
          setDocumentTrayOpen(true);
          setError(
            `Document text is above ${limits.max_text_characters_total.toLocaleString()} characters. Remove a file or keep it without reading.`,
          );
          return;
        }
        const documents: InterviewDocument[] = openingDocuments.map((file) => {
          const read = openingDocumentReads[file.name];
          return {
            name: file.name,
            ...(read?.status === "read" ? { text: read.text } : {}),
          };
        });
        const result = await api.start(
          description,
          evidence,
          perspective,
          documents,
          connection,
        );
        const started = emptyRecord(
          localId,
          result.state,
          result.stage,
          startTranscript(description, result.state),
        );
        const next = addFixtures(started, openingDocuments);
        try {
          await repository.put(next);
        } catch (cause) {
          operations.report(
            operationKey,
            `The new Interview was not saved. ${errorMessage(cause)}`,
            () =>
              operations.run(operationKey, async () => {
                await repository.put(next);
                if (origin) navigation.current?.started(origin, next.id);
                await refreshList();
              }),
          );
          return;
        }
        if (origin) navigation.current?.started(origin, next.id);
        await refreshList();
      });
    },
    [
      busy,
      operations,
      operationKey,
      openingDocuments,
      openingDocumentReads,
      refreshList,
      setError,
      wizardConfig,
    ],
  );

  const packageAndDownload = useCallback(
    async (localRecord: LocalInterviewRecord) => {
      const archive = await api.package(
        { state: localRecord.state },
        fixturesForSpecification(localRecord),
      );
      downloadArchive(archive);
    },
    [],
  );

  const downloadCurrent = useCallback(
    async (localRecord: LocalInterviewRecord) => {
      await operations.run(localRecord.id, async () => {
        try {
          await packageAndDownload(localRecord);
        } catch (cause) {
          operations.report(localRecord.id, errorMessage(cause), () =>
            downloadCurrent(localRecord),
          );
        }
      });
    },
    [operations, packageAndDownload],
  );

  const send = useCallback(
    async (
      response: UserResponse,
      files: readonly File[] = [],
      removedFixtures: readonly string[] = [],
    ) => {
      if (!record) return;
      const key = `${record.id}:${record.state.pending?.request_id ?? ""}`;
      await operations.send(record, response, files, removedFixtures, () => {
        if (response.type === "chat") drafts.current.delete(draftKey);
        if (response.type === "choice" && response.feedback)
          drafts.current.delete(composerKey);
        formDrafts.current.delete(key);
        setDraftRevision((value) => value + 1);
      });
    },
    [operations, record, draftKey, composerKey],
  );

  // Typed text goes to the pending request. A review takes it as feedback. The package accepts only
  // a form response while a form is open, so text typed then first cancels the form and then goes
  // to the review that the package sends back. The text stays in the composer until the feedback
  // itself is accepted: if the cancel fails, the user retries it and then sends the same text.
  const sendText = useCallback(
    async (text: string) => {
      if (!record) return;
      if (pending?.type === "chat") return send({ type: "chat", text });
      if (pending?.type === "choice")
        return send({ type: "choice", feedback: text });
      if (pending?.type !== "form" || !pending.cancellable) return;
      await send({ type: "form", cancelled: true, values: {} });
      const latest = operations.latest.get(record.id);
      const next = latest?.state.pending;
      if (!latest || next?.type !== "choice" || !next.feedback_placeholder)
        return;
      await operations.send(
        latest,
        { type: "choice", feedback: text },
        [],
        [],
        () => {
          drafts.current.delete(composerKey);
          setDraftRevision((value) => value + 1);
        },
      );
    },
    [record, pending, send, operations, composerKey],
  );

  // Back from Run settings or Done reopens the last review of the completed Interview.
  const backFromDone = useCallback(async () => {
    if (!record) return;
    setRunSettingsFor(null);
    setRunModelDrafts(null);
    await operations.reopen(record);
  }, [record, operations]);

  const finish = useCallback(async () => {
    if (!record || operations.pendingSaves.has(record.id)) return;
    await operations.run(
      record.id,
      async () => {
        const result = await api.end(record.state);
        const next = applyEnd(record, result);
        await operations.save(next);
        // The run settings step comes first, so the first ZIP holds the chosen models.
        if (result.outcome === "done") setRunSettingsFor(next.id);
      },
      finish,
    );
  }, [record, operations]);

  // Check the binding. In the opening, Send starts the Interview only with a valid binding. On
  // the Done pane, Save adds it to the finished Interview.
  const connectionKey =
    connectionStep === "add" && record ? record.id : operationKey;
  const checkDraft = useCallback(async () => {
    const result = await api.checkConnection(bindingFromDraft(connectionDraft));
    setConnectionResult(result);
    return result;
  }, [connectionDraft]);
  const beginOpening = useCallback(
    async (
      description: string,
      perspective: Perspective,
      evidence: CapabilityEvidence | null,
    ) => {
      if (connectionDraft.mode === "spec") {
        void beginWithMessage(description, perspective, evidence, null);
        return;
      }
      // Reuse the last test when no field changed since; a field change clears the result.
      let connection: TargetConnection | null = null;
      await operations.run(operationKey, async () => {
        connection = startConnection(
          connectionDraft,
          connectionResult ?? (await checkDraft()),
        );
      });
      // On an invalid binding, the connection card under the box shows the marked fields.
      if (connection)
        void beginWithMessage(description, perspective, evidence, connection);
    },
    [
      connectionDraft,
      connectionResult,
      beginWithMessage,
      operations,
      operationKey,
      checkDraft,
    ],
  );
  const saveConnection = useCallback(async () => {
    if (!record) return;
    await operations.run(record.id, async () => {
      const connection = startConnection(
        connectionDraft,
        connectionResult ?? (await checkDraft()),
      );
      if (!connection) return;
      const state = await api.setConnection(record.state, connection);
      await operations.save({ ...record, state });
      setConnectionStep(null);
    });
  }, [record, operations, connectionDraft, connectionResult, checkDraft]);
  const openAddConnection = useCallback(() => {
    setConnectionDraft({ ...emptyConnectionDraft(), mode: "run" });
    setConnectionResult(null);
    setConnectionStep("add");
  }, []);

  const remove = useCallback(
    async (id: string) => {
      if (operations.active.has(id) || operations.pendingSaves.has(id)) return;
      try {
        await repository.delete(id);
        operations.latest.delete(id);
        if (
          destinationRef.current?.destination.kind === "interview" &&
          destinationRef.current.destination.id === id
        )
          setRecord(null);
        await refreshList();
      } catch (cause) {
        operations.report(id, errorMessage(cause));
      }
    },
    [operations, refreshList],
  );

  // Save the model names, if the user changed any, then start the download. With no change,
  // the record and the ZIP are the same as before the step.
  const continueToDownload = useCallback(async () => {
    if (!record) return;
    let next = record;
    await operations.run(record.id, async () => {
      const state = stateForDownload(record.state, runModelDrafts);
      if (state !== record.state) {
        next = { ...record, updated_at: Date.now(), state };
        await operations.save(next);
      }
      setRunSettingsFor(null);
      setRunModelDrafts(null);
      try {
        await packageAndDownload(next);
      } catch (cause) {
        operations.report(record.id, errorMessage(cause), () =>
          downloadCurrent(next),
        );
      }
    });
  }, [record, runModelDrafts, operations, packageAndDownload, downloadCurrent]);

  if (!loaded) return null;

  return (
    <div className="flex h-full w-full overflow-hidden">
      {railOpen ? (
        <InterviewRail
          interviews={interviews}
          problems={storageProblems}
          currentId={record?.id ?? null}
          activeIds={
            new Set([...operations.active, ...operations.pendingSaves.keys()])
          }
          onOpen={open}
          onNew={startNew}
          onDelete={remove}
          onCollapse={() => setRailOpen(false)}
        />
      ) : (
        <EdgeStrip
          side="left"
          label="Show interviews"
          onClick={() => setRailOpen(true)}
        />
      )}
      <main className="flex min-w-0 flex-1 flex-col">
        {error && (
          <Banner
            message={error}
            onDismiss={() => operations.dismiss(operationKey)}
            onRetry={
              feedback?.retry ? () => void feedback.retry?.() : undefined
            }
          />
        )}
        {manualOpen ? (
          <ManualForm
            onBack={() => setManualOpen(false)}
            connectionDraft={connectionDraft}
            onConnectionDraft={(next) => {
              setConnectionDraft(next);
              setConnectionResult(null);
            }}
            connectionResult={connectionResult}
            onTestConnection={() =>
              void operations.run(operationKey, async () => {
                await checkDraft();
              })
            }
            checkConnection={checkDraft}
          />
        ) : connectionStep === "add" && view !== null ? (
          <AddConnection
            draft={connectionDraft}
            onDraft={(next) => {
              setConnectionDraft(next);
              setConnectionResult(null);
            }}
            result={connectionResult}
            busy={busy || operations.active.has(connectionKey)}
            onTest={() =>
              void operations.run(connectionKey, async () => {
                await checkDraft();
              })
            }
            onSave={() => void saveConnection()}
            onCancel={() => setConnectionStep(null)}
          />
        ) : view === null && destination?.destination.kind === "interview" ? (
          <div className="m-auto flex flex-col gap-4 p-8" role="status">
            <p>
              {loadingRecord
                ? "Loading Interview…"
                : "This local Interview is unavailable. Choose an Interview from History or start a new evaluation."}
            </p>
            <Button onClick={startNew}>New evaluation</Button>
          </div>
        ) : view === null ? (
          <OpeningRoute
            configState={wizardConfig}
            onRetry={() => void loadWizardConfig()}
            busy={busy}
            canStart={interviewReady(modelStatuses)}
            description={openingDescription}
            onDescription={setOpeningDescription}
            perspective={selectedPerspective}
            onPerspective={setSelectedPerspective}
            documents={openingDocuments}
            documentTrayOpen={documentTrayOpen}
            onDocumentTrayOpen={(open) => {
              if (open) setOpeningControl(null);
              setDocumentTrayOpen(open);
            }}
            documentReads={openingDocumentReads}
            onAddDocuments={addOpeningDocuments}
            onRemoveDocument={removeOpeningDocument}
            onKeepDocumentUnread={keepOpeningDocumentWithoutReading}
            capabilityEvidence={capabilityEvidence}
            onCapabilityEvidence={setCapabilityEvidence}
            onBegin={(description, perspective, evidence) =>
              void beginOpening(description, perspective, evidence)
            }
            connectionDraft={connectionDraft}
            onConnectionDraft={(next) => {
              setConnectionDraft(next);
              setConnectionResult(null);
            }}
            connectionResult={connectionResult}
            onTestConnection={() =>
              void operations.run(operationKey, async () => {
                await checkDraft();
              })
            }
            onManualOpen={() => setManualOpen(true)}
            openControl={openingControl}
            onOpenControl={(control) => {
              if (control === "perspective") setPerspectiveSeen(true);
              if (control !== null) setDocumentTrayOpen(false);
              setOpeningControl(control);
            }}
            perspectiveSeen={perspectiveSeen}
          />
        ) : (
          <div
            ref={panesRef}
            className="flex min-h-0 flex-1 flex-col md:flex-row"
            style={{ "--chat-width": `${chatWidth}%` } as CSSProperties}
          >
            <div className="flex h-[35vh] min-h-40 min-w-0 shrink-0 flex-col md:h-auto md:min-h-0 md:w-[var(--chat-width)]">
              <div
                key={view.id}
                ref={conversationScrollRef}
                onScroll={(event) => {
                  const element = event.currentTarget;
                  nearFoot.current =
                    element.scrollHeight -
                      element.scrollTop -
                      element.clientHeight <
                    100;
                }}
                className="quiet-scrollbar min-h-0 flex-1 overflow-y-auto px-6 py-8"
              >
                <Transcript
                  requests={view.requests}
                  entries={record?.transcript}
                  formDrafts={formDrafts.current}
                  draftPrefix={view.id}
                  onRetry={() => {
                    if (record) void operations.retry(record);
                  }}
                  onEdit={() => {
                    if (!record) return;
                    const response = pendingEntry(record)?.response;
                    if (response?.type === "chat")
                      drafts.current.set(draftKey, response.text);
                    if (response?.type === "choice" && response.feedback)
                      drafts.current.set(composerKey, response.feedback);
                    if (response?.type === "form")
                      formDrafts.current.set(draftKey, response.values ?? {});
                    void operations.edit(record);
                  }}
                  busy={busy}
                  onRespond={send}
                  profileForm={profileForm?.request_id ?? null}
                />
                {busy && <ThinkingLine message={workingStatus} />}
                {view.done && runSettingsFor === view.id ? (
                  <RunSettings
                    roles={runRoles(view.specification)}
                    statuses={modelStatuses}
                    values={runModelDrafts ?? runModels(view.specification)}
                    busy={busy || operations.pendingSaves.has(view.id)}
                    onChange={(role, value) => {
                      setRunModelDrafts((current) => ({
                        ...(current ?? runModels(view.specification)),
                        [role]: value,
                      }));
                    }}
                    onContinue={() => void continueToDownload()}
                    onBack={() => void backFromDone()}
                  />
                ) : (
                  view.done && (
                    <Done
                      connection={record?.state.context.connection ?? null}
                      onConnect={openAddConnection}
                      busy={replyBusy}
                      onBack={() => void backFromDone()}
                    />
                  )
                )}
              </div>
              <Composer
                key={composerKey}
                request={review ?? pending}
                value={drafts.current.get(composerKey) ?? ""}
                onValueChange={(value) => {
                  drafts.current.set(composerKey, value);
                  setDraftRevision((revision) => revision + 1);
                }}
                busy={replyBusy}
                sendBlockedReason={
                  review && pending?.type === "form" && !pending.cancellable
                    ? "Save the form first"
                    : undefined
                }
                onSend={(text) => void sendText(text)}
              />
            </div>
            <PaneDivider
              rowRef={panesRef}
              width={chatWidth}
              onWidth={setChatWidth}
            />
            <aside
              className="min-h-0 min-w-0 flex-1 bg-muted"
              aria-label="Profile"
            >
              <SpecificationView
                key={view.id}
                specification={view.specification}
                excludedTasks={record?.state.excluded_tasks}
                position={stepPosition(view.requests)}
                interviewStep={view.stage}
                busy={busy || operations.pendingSaves.has(view.id)}
                showGraders={showGraders}
                onShowGradersChange={setShowGraders}
                graderByFqn={graderByFqn}
                gradersLoading={
                  graderState === "idle" || graderState === "loading"
                }
                gradersError={graderState === "error"}
                done={view.done}
                onFinish={() => void finish()}
                onDownload={() => {
                  if (record) void downloadCurrent(record);
                }}
                activeSections={review ? reviewParts(review) : []}
                renderReview={(part) =>
                  review && (
                    <ActiveReview
                      key={`${view.id}:${part}`}
                      request={review}
                      part={part}
                      busy={replyBusy}
                      onRespond={send}
                      form={profileForm}
                      formFailure={profileFailure}
                      formDrafts={formDrafts.current}
                      draftPrefix={view.id}
                    />
                  )
                }
                renderSectionActions={(part) =>
                  review && (
                    <ReviewSectionActions
                      request={review}
                      part={part}
                      busy={replyBusy}
                      onRespond={send}
                    />
                  )
                }
              />
            </aside>
          </div>
        )}
      </main>
    </div>
  );
}

type OpeningScreenProps = {
  config: WizardConfig;
  busy: boolean;
  // False while the interview role has no key. The start control stays grey and says why.
  canStart: boolean;
  description: string;
  onDescription?: (value: string) => void;
  perspective: Perspective;
  onPerspective: (perspective: Perspective) => void;
  documents: File[];
  documentTrayOpen: boolean;
  onDocumentTrayOpen: (open: boolean) => void;
  documentReads: Record<string, OpeningDocumentRead>;
  onAddDocuments: (files: readonly File[]) => void;
  onRemoveDocument: (name: string) => void;
  onKeepDocumentUnread: (name: string) => void;
  capabilityEvidence: CapabilityEvidenceDraft;
  onCapabilityEvidence: (evidence: CapabilityEvidenceDraft) => void;
  onManualOpen: () => void;
  openControl: OpeningControl | null;
  onOpenControl: (control: OpeningControl | null) => void;
  // False until the user first opens the Perspective control. Until then, the default is marked.
  perspectiveSeen: boolean;
  // "Build Spec only" or "Build Spec and connect target". Run mode shows the connection form.
  connectionDraft: ConnectionDraft;
  onConnectionDraft: (draft: ConnectionDraft) => void;
  connectionResult: ConnectionCheckResult | null;
  onTestConnection: () => void;
  onBegin: (
    description: string,
    perspective: Perspective,
    evidence: CapabilityEvidence | null,
  ) => void;
};

export function OpeningRoute({
  configState,
  onRetry,
  ...openingProps
}: Omit<OpeningScreenProps, "config"> & {
  configState: WizardConfigState;
  onRetry: () => void;
}) {
  if (configState.status !== "ready") {
    return <OpeningConfigurationState state={configState} onRetry={onRetry} />;
  }
  return <OpeningScreen config={configState.config} {...openingProps} />;
}

export function OpeningConfigurationState({
  state,
  onRetry,
}: {
  state: Exclude<WizardConfigState, { status: "ready" }>;
  onRetry: () => void;
}) {
  return (
    <div className="flex flex-1 items-center justify-center px-6 py-10">
      {state.status === "loading" ? (
        <p role="status" className="text-sm text-muted-foreground">
          Loading interview options…
        </p>
      ) : (
        <div
          role="alert"
          className="flex max-w-md flex-col items-start gap-3 rounded-lg border border-border bg-card p-5"
        >
          <p className="text-sm text-foreground">
            The interview options could not load. {state.message}
          </p>
          <button
            type="button"
            onClick={onRetry}
            className="rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground transition-colors duration-150 hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            Try again
          </button>
        </div>
      )}
    </div>
  );
}

// "Connect target" on the Done pane: the same form, with Save and Cancel.
function AddConnection({
  draft,
  onDraft,
  result,
  busy,
  onTest,
  onSave,
  onCancel,
}: {
  draft: ConnectionDraft;
  onDraft: (draft: ConnectionDraft) => void;
  result: ConnectionCheckResult | null;
  busy: boolean;
  onTest: () => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="quiet-scrollbar flex flex-1 overflow-y-auto px-6 py-10">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-6">
        <h1 className="text-2xl font-semibold text-foreground">
          Connect the target
        </h1>
        <ConnectionForm
          draft={draft}
          onDraft={onDraft}
          result={result}
          busy={busy}
          onTest={onTest}
        />
        <div className="flex justify-end gap-2">
          <Button type="button" disabled={busy} onClick={onCancel}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="primary"
            disabled={busy}
            onClick={onSave}
          >
            Save connection
          </Button>
        </div>
      </div>
    </div>
  );
}

// The opening is one view. The description box holds the setup controls along its bottom edge:
// documents, the Perspective, the capabilities, and the mode. Each control opens a panel under the
// box. Enter and Send both start the Interview. In run mode, Send first checks the binding.
export function OpeningScreen(props: OpeningScreenProps) {
  const {
    config,
    busy,
    description,
    onDescription,
    perspective,
    documents,
    documentTrayOpen,
    onDocumentTrayOpen,
    capabilityEvidence,
    onCapabilityEvidence,
    openControl,
    onOpenControl,
    perspectiveSeen,
    canStart,
    connectionDraft,
    onConnectionDraft,
    connectionResult,
    onTestConnection,
  } = props;
  const currentPerspective = config.perspectives.find(
    (item) => item.id === perspective,
  );
  const PerspectiveIcon = PERSPECTIVE_ICONS[perspective];
  const perspectiveOpen = openControl === "perspective";
  const capabilitiesOpen = openControl === "capabilities";
  const runMode = connectionDraft.mode === "run";
  const start = (text: string) => {
    onDescription?.(text);
    props.onBegin(
      text,
      perspective,
      completeCapabilityEvidence(capabilityEvidence),
    );
  };

  return (
    <div className="quiet-scrollbar flex flex-1 overflow-y-auto px-6 py-10 [scrollbar-gutter:stable] max-sm:px-4">
      <div className="animate-enter-opening-step mx-auto my-auto flex w-full max-w-3xl flex-col gap-8">
        <h1 className="text-center text-2xl font-semibold text-foreground">
          {config.opening_question}
        </h1>
        <ModePicker
          mode={connectionDraft.mode}
          disabled={busy}
          onSelect={(mode) => onConnectionDraft({ ...connectionDraft, mode })}
        />
        <div className="flex flex-col gap-4">
          <div className="flex flex-col">
            <div className="relative z-10">
              <Composer
                request={undefined}
                busy={busy}
                alwaysEnabled
                leadingIcon
                bare
                initialText={description}
                value={description}
                onValueChange={onDescription}
                roomy
                placeholder="A support bot for a retail bank…"
                onSend={start}
                sendBlockedReason={canStart ? undefined : START_BLOCKED}
                sourceControl={
                  <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                    <AddDocuments
                      onOpen={() => onDocumentTrayOpen(!documentTrayOpen)}
                      disabled={busy}
                      expanded={documentTrayOpen}
                    />
                    {documents.length > 0 && (
                      <button
                        type="button"
                        onClick={() => onDocumentTrayOpen(true)}
                        className="text-xs text-muted-foreground hover:text-foreground"
                      >
                        {documents.length}{" "}
                        {documents.length === 1 ? "document" : "documents"}
                      </button>
                    )}
                    <FooterChip
                      ariaLabel={`Perspective: ${currentPerspective?.label ?? perspective}`}
                      value={currentPerspective?.label ?? perspective}
                      icon={
                        <PerspectiveIcon
                          size={15}
                          strokeWidth={1.75}
                          aria-hidden
                          className="shrink-0 text-muted-foreground"
                        />
                      }
                      expanded={perspectiveOpen}
                      controls="opening-perspective"
                      marked={!perspectiveSeen}
                      disabled={busy}
                      onClick={() =>
                        onOpenControl(perspectiveOpen ? null : "perspective")
                      }
                    />
                    <FooterChip
                      value="Capabilities"
                      icon={
                        <Puzzle
                          size={15}
                          strokeWidth={1.75}
                          aria-hidden
                          className="shrink-0 text-muted-foreground"
                        />
                      }
                      expanded={capabilitiesOpen}
                      controls="opening-capabilities"
                      disabled={busy}
                      onClick={() =>
                        onOpenControl(capabilitiesOpen ? null : "capabilities")
                      }
                    />
                  </div>
                }
              />
            </div>
            {/* The cards under the box share one column. Only the first card starts under the box. */}
            <div className="under-box-stack relative z-0 mx-auto flex w-[95%] flex-col gap-2">
              {documentTrayOpen && (
                <DocumentTray onClose={() => onDocumentTrayOpen(false)}>
                  <InitialDocumentPicker
                    config={config}
                    documents={documents}
                    documentReads={props.documentReads}
                    disabled={busy}
                    onAdd={props.onAddDocuments}
                    onRemove={props.onRemoveDocument}
                    onKeepWithoutReading={props.onKeepDocumentUnread}
                  />
                </DocumentTray>
              )}
              {perspectiveOpen && (
                <UnderBoxSurface
                  id="opening-perspective"
                  label="Perspective"
                  onClose={() => onOpenControl(null)}
                >
                  {/* Equal side space keeps the cards clear of the close button and centred. */}
                  <div className="px-6">
                    <PerspectivePicker
                      perspectives={config.perspectives}
                      selected={perspective}
                      onSelect={props.onPerspective}
                      disabled={busy}
                    />
                  </div>
                </UnderBoxSurface>
              )}
              {capabilitiesOpen && (
                <UnderBoxSurface
                  id="opening-capabilities"
                  label="Capabilities"
                  onClose={() => onOpenControl(null)}
                  sheet
                >
                  <CapabilityPicker
                    categories={config.capability_categories}
                    selected={capabilityEvidence.known_capability_ids}
                    onChange={(knownCapabilityIds) =>
                      onCapabilityEvidence({
                        ...capabilityEvidence,
                        known_capability_ids: knownCapabilityIds,
                      })
                    }
                    disabled={busy}
                    hideLegend
                  />
                  {/* On a small screen, the confidence row stays at the foot of the sheet. */}
                  <div className="max-sm:sticky max-sm:-bottom-4 max-sm:-mx-4 max-sm:bg-card max-sm:px-4 max-sm:pb-4 max-sm:pt-2">
                    <CapabilityConfidencePicker
                      selected={capabilityEvidence.confidence}
                      onSelect={(confidence) =>
                        onCapabilityEvidence({
                          ...capabilityEvidence,
                          confidence,
                        })
                      }
                      disabled={busy}
                    />
                  </div>
                </UnderBoxSurface>
              )}
              {runMode && (
                // Run mode needs the binding, so this card stays open and is not a footer panel.
                <section
                  id="opening-connection"
                  aria-label="Target connection"
                  className="animate-open-under-box relative flex flex-col gap-3 rounded-2xl border border-border bg-card px-4 py-4"
                >
                  <h2 className="text-sm font-medium text-foreground">
                    Target connection
                  </h2>
                  <ConnectionForm
                    draft={connectionDraft}
                    onDraft={onConnectionDraft}
                    result={connectionResult}
                    busy={busy}
                    onTest={onTestConnection}
                  />
                </section>
              )}
            </div>
          </div>
          <ManualAuthoringEntry onOpen={props.onManualOpen} />
        </div>
      </div>
    </div>
  );
}

export function InitialDocumentPicker({
  config,
  documents,
  documentReads,
  disabled,
  onAdd,
  onRemove,
  onKeepWithoutReading,
}: {
  config: WizardConfig;
  documents: readonly File[];
  documentReads: Record<string, OpeningDocumentRead>;
  disabled: boolean;
  onAdd: (files: readonly File[]) => void;
  onRemove: (name: string) => void;
  onKeepWithoutReading: (name: string) => void;
}) {
  const limits = config.document_limits;
  if (!limits || !limits.fixture_extensions || !limits.extraction_extensions)
    return (
      <p role="alert" className="text-sm text-destructive">
        Document limits are not available. Try again before adding files.
      </p>
    );
  const fixtureExtensions = limits.fixture_extensions;
  const totalText = documents.reduce((total, file) => {
    const read = documentReads[file.name];
    return total + (read?.status === "read" ? unicodeLength(read.text) : 0);
  }, 0);
  const textLimitExceeded = totalText > limits.max_text_characters_total;

  return (
    <div className="flex min-w-0 flex-1 flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <label
          className={cn(
            "relative inline-flex items-center rounded-md border border-border px-3 py-1 text-xs font-medium text-foreground transition-colors hover:bg-muted focus-within:ring-2 focus-within:ring-ring",
            disabled ? "cursor-not-allowed opacity-45" : "cursor-pointer",
          )}
        >
          Choose documents
          <input
            type="file"
            multiple
            aria-label="Choose documents"
            disabled={disabled}
            accept={fixtureExtensions
              .map((extension) => `.${extension}`)
              .join(",")}
            onChange={(event) => {
              onAdd([...(event.currentTarget.files ?? [])]);
              event.currentTarget.value = "";
            }}
            className="sr-only"
          />
        </label>
        {documents.length === 0 && (
          <span className="text-xs text-muted-foreground">No files chosen</span>
        )}
      </div>
      {documents.length > 0 && (
        <ul className="flex flex-col divide-y divide-border">
          {documents.map((file) => {
            const read = documentReads[file.name] ?? { status: "not_read" };
            return (
              <li
                key={file.name}
                className="flex flex-wrap items-center gap-x-4 gap-y-2 py-2"
              >
                <span
                  className="min-w-0 flex-1 truncate text-sm text-foreground"
                  title={file.name}
                >
                  {file.name}
                </span>
                <div className="flex min-w-0 flex-1 flex-wrap items-center justify-end gap-2 text-xs text-muted-foreground">
                  {read.status === "failed" ? (
                    <span className="max-w-full text-destructive">
                      Could not read: {read.message}
                    </span>
                  ) : (
                    <span aria-live="polite">
                      {read.status === "reading"
                        ? "Reading…"
                        : read.status === "read"
                          ? "Read"
                          : read.status === "kept"
                            ? "Kept without reading"
                            : "Not read"}
                    </span>
                  )}
                  {(read.status === "failed" ||
                    (textLimitExceeded && read.status === "read")) && (
                    <button
                      type="button"
                      disabled={disabled}
                      onClick={() => onKeepWithoutReading(file.name)}
                      className="rounded-md px-2 py-1 text-foreground underline decoration-border underline-offset-2 hover:bg-background disabled:opacity-40"
                    >
                      Keep without reading
                    </button>
                  )}
                </div>
                <button
                  type="button"
                  disabled={disabled || read.status === "reading"}
                  onClick={() => onRemove(file.name)}
                  aria-label={`Remove ${file.name}`}
                  className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-background hover:text-foreground disabled:opacity-40"
                >
                  <X size={14} strokeWidth={1.75} aria-hidden />
                </button>
              </li>
            );
          })}
        </ul>
      )}
      <div className="flex flex-col gap-1 text-xs text-muted-foreground">
        <p>Accepted file types: {fixtureExtensions.join(", ")}.</p>
        <p>File size: {limits.max_initial_bytes / 1_000_000} MB total.</p>
      </div>
    </div>
  );
}

function EdgeStrip({
  side,
  label,
  onClick,
}: {
  side: "left" | "right";
  label: string;
  onClick: () => void;
}) {
  const Icon = side === "left" ? PanelLeft : PanelRight;
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className={cn(
        "flex h-full w-8 shrink-0 items-start justify-center bg-muted/30 pt-4 text-muted-foreground hover:bg-muted hover:text-foreground",
        side === "left" ? "border-r border-border" : "border-l border-border",
      )}
    >
      <Icon size={16} strokeWidth={1.75} aria-hidden />
    </button>
  );
}
function ThinkingLine({ message }: { message: string }) {
  return (
    <div
      aria-live="polite"
      className="my-4 flex items-center gap-2 py-2 text-sm font-medium text-accent"
    >
      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
      {message}
    </div>
  );
}
function Banner({
  message,
  onDismiss,
  onRetry,
}: {
  message: string;
  onDismiss: () => void;
  onRetry?: () => void;
}) {
  return (
    <div
      role="alert"
      className="flex items-center justify-between gap-3 border-b border-destructive/50 bg-destructive/10 px-6 py-2 text-sm"
    >
      <span>{message}</span>
      <div className="flex shrink-0 items-center gap-3">
        {onRetry && (
          <button
            className="text-xs font-medium text-foreground hover:text-accent"
            onClick={onRetry}
          >
            Retry
          </button>
        )}
        <button
          className="text-xs text-muted-foreground hover:text-foreground"
          onClick={onDismiss}
        >
          Dismiss
        </button>
      </div>
    </div>
  );
}
function errorMessage(error: unknown): string {
  return error instanceof TransportError || error instanceof Error
    ? error.message
    : "Something went wrong.";
}
