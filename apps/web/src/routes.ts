// Every place in the app and its URL. Components build a path with `paths` and read the current
// place with `placeOf`, so no component writes a path by hand.

export type TargetTab = "specification" | "experiments";
export type ExperimentTab = "trials" | "report";

// The part of an experiment place after the experiment id.
export type ExperimentPart =
  // `tab` is null for the bare experiment URL, which opens the default tab of the experiment.
  | { tab: null }
  | { tab: "report" }
  // `taskId` is the test case that the Trials tab opens, or null for the full tab.
  | { tab: "trials"; taskId: string | null };

export type Place =
  | { page: "new-target" }
  // `tab` is null for `/targets/:targetId`, which opens the default tab of the Target.
  | { page: "target"; targetId: string; tab: TargetTab | null }
  | ({
      page: "experiment";
      targetId: string;
      experimentId: string;
    } & ExperimentPart)
  | { page: "compare"; targetId: string }
  | { page: "experiments" }
  | { page: "not-found" };

// The experiment dialog opens the experiment view with this id until the app saves experiments.
export const NEW_EXPERIMENT = "new";

const segment = encodeURIComponent;

export const paths = {
  newTarget: () => "/targets/new",
  target: (targetId: string, tab?: TargetTab) =>
    `/targets/${segment(targetId)}${tab ? `/${tab}` : ""}`,
  experiment: (
    targetId: string,
    experimentId: string,
    tab?: ExperimentTab,
  ): string =>
    `${paths.target(targetId, "experiments")}/${segment(experimentId)}${tab ? `/${tab}` : ""}`,
  // The trials of one test case. `taskId` is the `task_id` of a row of the report.
  testCase: (targetId: string, experimentId: string, taskId: string) =>
    `${paths.experiment(targetId, experimentId, "trials")}/${segment(taskId)}`,
  compare: (targetId: string) => `${paths.target(targetId)}/compare`,
  experiments: () => "/experiments",
};

function segments(path: string): string[] | null {
  try {
    return path.split("/").filter(Boolean).map(decodeURIComponent);
  } catch {
    return null;
  }
}

export function placeOf(path: string): Place {
  const parts = segments(path);
  if (!parts) return { page: "not-found" };
  const [root, targetId, section, experimentId, view, taskId, ...rest] = parts;
  if (root === undefined) return { page: "new-target" };
  if (root === "experiments" && targetId === undefined)
    return { page: "experiments" };
  if (root !== "targets" || targetId === undefined || rest.length > 0)
    return { page: "not-found" };
  if (targetId === "new")
    return section === undefined
      ? { page: "new-target" }
      : { page: "not-found" };
  if (section === undefined) return { page: "target", targetId, tab: null };
  if (section === "compare" && experimentId === undefined)
    return { page: "compare", targetId };
  if (section === "specification" && experimentId === undefined)
    return { page: "target", targetId, tab: "specification" };
  if (section !== "experiments") return { page: "not-found" };
  if (experimentId === undefined)
    return { page: "target", targetId, tab: "experiments" };
  const experiment = { page: "experiment", targetId, experimentId } as const;
  if (view === undefined) return { ...experiment, tab: null };
  if (view === "trials")
    return { ...experiment, tab: "trials", taskId: taskId ?? null };
  if (view === "report" && taskId === undefined)
    return { ...experiment, tab: "report" };
  return { page: "not-found" };
}

export function targetOf(place: Place): string | null {
  return "targetId" in place ? place.targetId : null;
}

// Where a loaded Target sends its user. Only a done Interview has a Specification to run, so
// every other place of an unfinished Target opens its Specification tab.
export function targetRedirect(place: Place, done: boolean): string | null {
  if (place.page === "target" && place.tab === null)
    return paths.target(place.targetId, done ? "experiments" : "specification");
  if (done || place.page === "new-target" || !("targetId" in place))
    return null;
  if (place.page === "target" && place.tab === "specification") return null;
  return paths.target(place.targetId, "specification");
}
