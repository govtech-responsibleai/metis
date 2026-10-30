"use strict";

const $ = (id) => document.getElementById(id);
let cases = [];
let current = 0;
let outputView = "structure";
let detailSelection = null;

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}

function metadataList(value) {
  if (value === null) return node("span", "Not specified");
  if (typeof value !== "object") return node("span", String(value));
  const entries = Object.entries(value);
  if (!entries.length) return node("span", "None");
  const list = node("ul", undefined, "persona-metadata");
  for (const [key, item] of entries) {
    const row = node("li");
    if (!Array.isArray(value)) {
      const label = key.replaceAll("_", " ");
      row.append(node("strong", `${label.charAt(0).toUpperCase()}${label.slice(1)}: `));
    }
    row.append(metadataList(item));
    list.append(row);
  }
  return list;
}

function renderCases() {
  const list = $("case-list");
  list.replaceChildren();
  cases.forEach((item, index) => {
    const title = item.specification.target.name;
    const button = node("button", undefined, "case-button");
    button.append(node("strong", title));
    if (index === current) button.setAttribute("aria-current", "page");
    button.addEventListener("click", () => selectCase(index));
    list.append(button);
  });
  if (!list.children.length) list.append(node("p", "No matching specifications.", "empty"));
}

function selectCase(index) {
  current = index;
  detailSelection = null;
  const item = cases[index];
  if (location.hash !== `#${item.id}`) location.hash = item.id;
  const behaviours = item.specification.features.flatMap((f) => f.behaviours);
  const criteria = behaviours.flatMap((b) => b.criteria);
  $("case-title").textContent = item.specification.target.name;
  const counts = $("case-summary");
  counts.replaceChildren();
  const measured = behaviours.filter((behaviour) => behaviour.measured).length;
  for (const [label, value] of [["Features", item.specification.features.length], ["Expected behaviours", `${measured} / ${behaviours.length} measured`], ["Graders assigned", `${criteria.filter((c) => c.grader_fqn).length} out of ${criteria.length}`]]) {
    const count = node("div");
    count.append(node("dt", `${label}:`), node("dd", String(value)));
    counts.append(count);
  }
  $("previous").disabled = index === 0;
  $("next").disabled = index === cases.length - 1;
  renderCases();
  renderPrompt();
  renderOutput();
}

function markdown(text, container) {
  let paragraph = [];
  let list = null;
  const flush = () => {
    if (paragraph.length) container.append(node("p", paragraph.join("\n")));
    paragraph = [];
  };
  text.split("\n").forEach((line) => {
    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    const bullet = line.match(/^\s*[-*]\s+(.+)$/);
    if (heading) {
      flush(); list = null;
      container.append(node(`h${Math.min(heading[1].length + 1, 4)}`, heading[2]));
    } else if (bullet) {
      flush();
      if (!list) { list = node("ul"); container.append(list); }
      list.append(node("li", bullet[1]));
    } else if (!line.trim()) { flush(); list = null; }
    else { paragraph.push(line); list = null; }
  });
  flush();
}

function renderPrompt() {
  const item = cases[current];
  const container = $("document");
  container.replaceChildren(); container.scrollTop = 0;
  $("open-documents").href = item.documents_url;
  $("open-documents").hidden = !item.has_documents;
  if (item.prompt.missing) {
    container.append(node("p", "Prompt not available. Restore inputs/prompt.md and rebuild the reviewer.", "empty"));
    return;
  }
  markdown(item.prompt.text, container);
}

function withId(tag, title, id) {
  const heading = node(tag, title);
  heading.append(node("span", id, "node-id"));
  return heading;
}

function criterionView(criterion) {
  const details = node("details", undefined, "criterion");
  const summary = withId("summary", criterion.name, criterion.id);
  details.append(summary);
  const description = node("dl");
  for (const [key, value] of Object.entries(criterion.description)) {
    description.append(node("dt", key[0].toUpperCase() + key.slice(1)), node("dd", value));
  }
  details.append(description);
  const grader = node("div", undefined, "grader");
  grader.append(node("strong", criterion.grader_fqn ? "Assigned grader" : "Grader not assigned"));
  if (criterion.grader_fqn) grader.append(node("code", criterion.grader_fqn));
  if (Object.keys(criterion.grader_args).length) grader.append(node("pre", JSON.stringify(criterion.grader_args, null, 2)));
  details.append(grader);
  return details;
}

function openDetail(selection) {
  detailSelection = selection;
  renderDetail();
  document.querySelector(".matrix-layout").classList.add("detail-open");
}

function renderDetail() {
  const spec = cases[current].specification;
  const body = $("detail-body");
  body.replaceChildren(); body.scrollTop = 0;
  document.querySelectorAll(".matrix-row").forEach((row) => { row.dataset.selected = String(row.dataset.behaviourId === detailSelection?.behaviourId); });
  document.querySelectorAll("[data-task-id]").forEach((cell) => { cell.dataset.selected = String(cell.dataset.taskId === detailSelection?.taskId); });
  document.querySelectorAll(".matrix-link").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.behaviourId === detailSelection?.behaviourId && button.dataset.taskId === detailSelection?.taskId));
  });
  $("expand-all").hidden = !detailSelection?.behaviourId;
  $("expand-all").textContent = "Expand criteria";
  if (!detailSelection) { body.append(node("p", "Select an expected behaviour, test case, or marked cell.", "empty")); return; }
  const behaviour = spec.features.flatMap((f) => f.behaviours).find((b) => b.id === detailSelection.behaviourId);
  const task = spec.tasks.find((t) => t.id === detailSelection.taskId);
  if (task) {
    const scenario = spec.scenarios.find((s) => s.id === task.scenario_ref);
    const persona = spec.personas.find((p) => p.id === task.persona_ref);
    body.append(withId("h3", scenario?.name || task.scenario_ref, task.id));
    if (behaviour) body.append(node("p", `This test case includes ${behaviour.name}.`, "selection-help"));
    const context = node("details", undefined, "task-context-detail");
    context.open = !behaviour;
    context.append(node("summary", "Test case details"), node("h4", "Scenario"), node("p", scenario?.description || task.scenario_ref));
    if (Object.keys(scenario?.metadata || {}).length) {
      context.append(node("h4", "Scenario metadata"), metadataList(scenario.metadata));
    }
    context.append(node("h4", "Persona"), node("p", persona?.name || task.persona_ref), node("p", persona?.description || ""));
    context.append(node("h4", "Persona metadata"), metadataList(persona?.metadata || {}));
    context.append(node("h4", "Execution"));
    const values = node("dl", undefined, "execution-values");
    for (const [label, value] of [["Trials", task.num_trials], ["Maximum turns", task.max_turns], ["Timeout (minutes)", task.timeout_minutes], ["Response wait (ms)", task.response_wait_ms], ["Run retries", task.max_run_retries ?? "Default"]]) values.append(node("dt", label), node("dd", String(value)));
    context.append(values, node("h4", "Fixtures"));
    if (!task.fixtures.length) context.append(node("p", "No fixtures."));
    task.fixtures.forEach((name) => context.append(node("p", name), node("p", spec.fixture_content_descriptions[name] || "")));
    context.append(node("h4", "Runner"), node("p", spec.runner_factory_ref || "Not assigned."));
    body.append(context);

  }
  if (behaviour) {
    const feature = spec.features.find((f) => f.behaviours.some((b) => b.id === behaviour.id));
    body.append(node("p", `[Feature] ${feature.name}`, "criteria-feature"), withId("h3", behaviour.name, behaviour.id));
    const description = node("details", undefined, "behaviour-context");
    description.append(node("summary", "Description"), node("p", behaviour.description));
    body.append(description);
    if (!behaviour.measured) body.append(node("p", "Not selected for measurement.", "selection-help"));
    body.append(node("h4", `Criteria · ${behaviour.criteria.length}`));
    behaviour.criteria.forEach((criterion) => body.append(criterionView(criterion)));

  }
}

function renderOutput() {
  const item = cases[current];
  const spec = item.specification;
  const container = $("output");
  container.replaceChildren(); container.scrollTop = 0;
  container.classList.toggle("structured", outputView === "structure");
  $("yaml-toggle").checked = outputView === "yaml";
  container.classList.toggle("yaml-console", outputView === "yaml");
  if (outputView === "yaml") {
    const download = node("a", "Download", "button");
    download.id = "download-output"; download.href = item.output.url; download.download = "specification.yaml";
    const actions = node("div", undefined, "yaml-actions"); actions.append(download);
    container.append(actions, node("pre", item.output.text));
    return;
  }
  const product = node("details", undefined, "product-summary");
  product.append(node("summary", "Target context"), node("p", spec.target.description), node("p", `Users: ${spec.target.users}`), node("p", spec.target.detail));
  container.append(product);
  const layout = node("div", undefined, "matrix-layout");
  const matrixArea = node("div", undefined, "matrix-area");
  const scroller = node("div", undefined, "matrix-scroll scroll-region"); scroller.id = "matrix-scroll"; scroller.tabIndex = 0; scroller.setAttribute("aria-label", "Expected behaviour and test case links");
  const table = node("table", undefined, "coverage-matrix");
  table.append(node("caption", "Rows are expected behaviours. Columns are test cases. A dot marks a link.", "sr-only"));
  const thead = node("thead"); const header = node("tr");
  for (const label of ["Expected behaviour", "Test cases"]) { const th = node("th", label); th.scope = "col"; header.append(th); }
  spec.tasks.forEach((task) => {
    const th = node("th"); th.scope = "col"; th.dataset.taskId = task.id;
    const button = node("button", task.id, "matrix-task"); button.title = spec.scenarios.find((s) => s.id === task.scenario_ref)?.name || task.id; button.setAttribute("aria-label", `View test case ${task.id}`); button.addEventListener("click", () => openDetail({ taskId: task.id })); th.append(button); header.append(th);
  });
  thead.append(header); table.append(thead);
  spec.features.forEach((feature) => {
    const tbody = node("tbody", undefined, "matrix-group");
    const featureRow = node("tr", undefined, "feature-row"); const label = node("th", `[Feature] ${feature.name}`); label.scope = "rowgroup"; label.title = feature.description; const rest = node("td"); rest.colSpan = spec.tasks.length + 1; featureRow.append(label, rest); tbody.append(featureRow);
    feature.behaviours.forEach((behaviour) => {
      const count = spec.tasks.filter((t) => t.behaviour_refs.includes(behaviour.id)).length;
      const row = node("tr", undefined, "matrix-row"); row.dataset.behaviourId = behaviour.id; row.dataset.count = String(count); row.dataset.measured = String(behaviour.measured);
      const name = node("th"); name.scope = "row";
      const button = node("button", behaviour.name, "matrix-behaviour"); button.addEventListener("click", () => openDetail({ behaviourId: behaviour.id })); name.append(button);
      const total = node("td", String(count), count ? "case-count" : "case-count zero-count"); row.append(name, total);
      spec.tasks.forEach((task) => {
        const cell = node("td"); cell.dataset.taskId = task.id;
        if (task.behaviour_refs.includes(behaviour.id)) {
          const dot = node("button", undefined, "matrix-link"); dot.dataset.behaviourId = behaviour.id; dot.dataset.taskId = task.id;
          dot.setAttribute("aria-label", `${task.id} includes ${behaviour.name}`); dot.append(node("span", undefined, "matrix-dot")); dot.addEventListener("click", () => openDetail({ taskId: task.id, behaviourId: behaviour.id })); cell.append(dot);
        } else cell.append(node("span", "No link", "sr-only"));
        row.append(cell);
      });
      tbody.append(row);
    });
    table.append(tbody);
  });
  scroller.append(table); matrixArea.append(scroller);
  const panel = node("aside", undefined, "matrix-detail"); panel.setAttribute("aria-label", "Selected item details");
  const expand = node("button", "Expand criteria", "quiet"); expand.id = "expand-all";
  expand.addEventListener("click", () => {
    const open = expand.textContent === "Expand criteria";
    $("detail-body").querySelectorAll(".criterion").forEach((detail) => { detail.open = open; });
    expand.textContent = open ? "Collapse criteria" : "Expand criteria";
  });
  panel.append(expand);
  const body = node("div", undefined, "detail-body scroll-region"); body.id = "detail-body"; body.tabIndex = 0; panel.append(body);
  layout.append(matrixArea, panel); container.append(layout);
  renderDetail();
  if (detailSelection) layout.classList.add("detail-open");
}

window.addEventListener("hashchange", () => {
  const index = cases.findIndex((item) => `#${item.id}` === location.hash);
  if (index >= 0 && index !== current) selectCase(index);
});
$("yaml-toggle").addEventListener("change", () => { outputView = $("yaml-toggle").checked ? "yaml" : "structure"; renderOutput(); });
$("previous").addEventListener("click", () => selectCase(current - 1));
$("next").addEventListener("click", () => selectCase(current + 1));
function start() {
  try {
    const data = JSON.parse($("case-data").textContent);
    cases = data.cases;
    if (!cases.length) throw new Error("No reference specifications found");
    $("case-count").textContent = String(cases.length);
    $("loading").hidden = true; $("case-workspace").hidden = false;
    selectCase(Math.max(0, cases.findIndex((item) => `#${item.id}` === location.hash)));
  } catch (error) {
    $("loading").replaceChildren(node("h2", "Could not load the reviewer"), node("p", "Rebuild the HTML file, then open it again."), node("pre", String(error)));
  }
}
start();
