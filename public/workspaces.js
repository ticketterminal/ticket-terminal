// Workspaces: one install, several named boards, switched — never merged.
// There is deliberately NO cross-workspace view anywhere: the picker changes
// which single workspace the board is showing, and that is the whole feature.
//
// The workspace lives in the route (`#/w/<slug>/…`) so a pasted link carries it
// and the back button works, and every REST call carries `?w=<slug>` — which is
// added once, in api.js's apiJson, not at each call site. A BARE route (`#/…`,
// i.e. every link that existed before this feature) means the default
// workspace, so `state.workspaceSlug` is "" on a one-workspace install and no
// `?w=` is sent at all: that install's traffic is byte-for-byte what it was.
import { state } from "./state.js";
import { detachAllTerminals } from "./terminal-controller.js";
import { el } from "./dom-utils.js";
import { apiJson } from "./api.js";
import { reloadBoard } from "./polling.js";
import { buildCategoryUI } from "./lanes.js";
import { initCategoryManagement } from "./category-management.js";

// Sentinel <option> value — no real slug can collide with it (slugs are
// lowercase letters, digits and hyphens).
const NEW_WORKSPACE = "__new__";
const SLUG_RE = /^[a-z0-9-]+$/;

/* ---- routes ---------------------------------------------------------- */

// "#/w/ticket-terminal/category/api" -> {slug:"ticket-terminal", path:"/category/api"}
// "#/category/api"                   -> {slug:"", path:"/category/api"}
export function parseRoute(hash){
  const match = /^#\/w\/([a-z0-9-]+)(\/.*)?$/.exec(hash || "");
  if (!match) return { slug: "", path: (hash || "").replace(/^#/, "") };
  return { slug: match[1], path: match[2] || "/" };
}

// Re-prefixes one of the board's own hashes ("#/settings", "#/memory/x", "")
// with the workspace the board is currently showing. Every `location.hash = …`
// in the codebase goes through this, otherwise clicking a lane on workspace B
// would silently drop you back onto the default one.
export function routeHash(hash){
  // Deliberately the LITERAL current slug, not the canonical one: if the route
  // spells out a workspace, every link the board then builds keeps spelling it
  // out, so navigating never quietly rewrites the URL you are standing on.
  return hashFor(state.workspaceSlug, hash);
}

// The same, for an arbitrary target workspace — used when switching. The
// default workspace gets a bare hash, so switching back to it leaves exactly
// the URLs a single-workspace install has always had.
export function workspaceRouteHash(slug, hash){
  return hashFor(slug === state.defaultWorkspace ? "" : slug, hash);
}

function hashFor(slug, hash){
  const path = (hash || "").replace(/^#/, "");
  if (!slug) return path === "" || path === "/" ? "" : "#" + path;
  return "#/w/" + slug + (path === "/" ? "" : path);
}

// The slug actually in effect: a bare route means the registry's default.
export function activeWorkspaceSlug(){
  return state.workspaceSlug || state.defaultWorkspace || "";
}

function workspaceName(slug){
  const found = state.workspaces.find(w => w.slug === slug);
  return (found && found.name) || slug || "this workspace";
}

// Called once, before init()'s first fetch, so that a `#/w/<slug>/…` deep link
// is already reflected in `?w=` on the very first request.
export function initWorkspaceFromRoute(){
  state.workspaceSlug = parseRoute(location.hash).slug;
}

/* ---- registry -------------------------------------------------------- */

export async function loadWorkspaces(){
  let res = null;
  try {
    res = await apiJson("/api/workspaces");
  } catch (error) {
    // An unknown slug 404s every single request, so a link naming a workspace
    // this install doesn't have would otherwise render a permanently dead
    // board. Drop back to the default one instead, once.
    if (!state.workspaceSlug) { renderWorkspacePicker(); return; }
    state.workspaceSlug = "";
    if (location.hash) location.hash = "";
    try { res = await apiJson("/api/workspaces"); } catch (retryError) { renderWorkspacePicker(); return; }
  }
  if (res && res.ok){
    state.workspaces = res.workspaces || [];
    state.defaultWorkspace = res.defaultWorkspace || "";
  }
  renderWorkspacePicker();
}

/* ---- the picker ------------------------------------------------------ */

// Rendered ONLY when more than one workspace exists: a person with one
// workspace must not see any workspace UI at all.
export function renderWorkspacePicker(){
  const wrap = document.getElementById("workspaceWrap");
  const sel = document.getElementById("workspaceSel");
  if (!wrap || !sel) return;
  if (state.workspaces.length < 2){
    wrap.hidden = true;
    sel.replaceChildren();
    return;
  }
  const active = activeWorkspaceSlug();
  sel.replaceChildren();
  for (const workspace of state.workspaces){
    const option = el("option", null, (workspace.name || workspace.slug) + (workspace.syncing ? " · syncing…" : ""));
    option.value = workspace.slug;
    if (workspace.slug === active) option.selected = true;
    sel.appendChild(option);
  }
  const create = el("option", null, "New workspace…");
  create.value = NEW_WORKSPACE;
  sel.appendChild(create);
  wrap.hidden = false;
}

export function wireWorkspaceUI(){
  const sel = document.getElementById("workspaceSel");
  if (!sel) return;
  sel.addEventListener("change", () => {
    const chosen = sel.value;
    if (chosen === NEW_WORKSPACE){
      renderWorkspacePicker(); // put the selection back on the workspace still being shown
      openNewWorkspaceForm();
      return;
    }
    if (chosen === activeWorkspaceSlug()) return;
    location.hash = workspaceRouteHash(chosen, "/");
  });
}

/* ---- switching ------------------------------------------------------- */

// Called by renderRoute() on every hash change. Returns true when it started a
// switch. Synchronous up to and including `state.workspaceSlug`, so anything
// the route then renders already fetches from the right workspace.
export function applyRouteWorkspace(slug){
  if (slug === state.workspaceSlug) return false;
  // Switching rebuilds the board, so the open terminals have to be let go of
  // — but NOT refused. Holding sessions in more than one workspace at once is
  // the whole reason this is one server process rather than two, and the
  // agents survive their socket closing: the server forgets a process only
  // once it has exited. So detach, say they are still running, and reconnect
  // on the way back.
  const detached = detachAllTerminals();
  state.boardGeneration++;   // invalidates anything already in flight for the old workspace
  state.workspaceSlug = slug;
  renderWorkspacePicker();
  switchWorkspace(slug, detached);
  return true;
}

async function switchWorkspace(slug, detached = 0){
  if (state.dom.dbStateEl) state.dom.dbStateEl.textContent = "Loading " + workspaceName(activeWorkspaceSlug()) + "…";
  await loadWorkspaceBoard();
  const note = detached
    ? detached + " agent session" + (detached === 1 ? "" : "s") +
      " left running in the background — reopen the ticket there to reconnect."
    : "";
  syncIfStale(activeWorkspaceSlug(), note);
}

// Everything that is per-workspace but not per-ticket: categories, the tracker
// config, the tracker's status/priority/sprint option lists — then the board
// itself. Run once at startup and again on every switch, because every one of
// these belongs to the workspace, not to the install.
export async function loadWorkspaceBoard(afterCategories){
  try {
    const [catsRes, configRes] = await Promise.all([apiJson("/api/categories"), apiJson("/api/config")]);
    state.categories = Array.isArray(catsRes) ? catsRes : [];
    state.jiraBaseUrl = (configRes && configRes.jiraBaseUrl) || "";
  } catch (error) { /* leave categories/jiraBaseUrl empty — board renders with no lanes/no Jira links */ }
  buildCategoryUI();
  if (afterCategories) afterCategories();

  try {
    const res = await apiJson("/api/jira-statuses");
    state.jiraStatusOptions = res && res.ok ? res.statuses : [];
  } catch (error) { state.jiraStatusOptions = []; }
  try {
    const res = await apiJson("/api/notion/options");
    if (res && res.ok){
      state.notionStatusOptions = res.statuses || [];
      state.notionPriorityOptions = res.priorities || [];
      state.notionDoneStatuses = res.doneStatuses || [];
      state.sprints = res.sprints || [];
    }
  } catch (error) { /* same fallback for Notion-sourced tickets */ }

  await reloadBoard();
  await initCategoryManagement();
}

// Fire-and-forget: the server decides whether this workspace is stale enough to
// warrant a sync and returns immediately either way. The stored board is
// already on screen; a refresh lands when it lands.
export function syncIfStale(slug, note = ""){
  if (!slug) return;
  // `note` is whatever the switch already had to say (detached sessions). Both
  // messages are written through here so neither can overwrite the other
  // depending on which resolves first.
  const say = text => { if (state.dom.dbStateEl) state.dom.dbStateEl.textContent = [text, note].filter(Boolean).join("  ·  "); };
  if (note) say("");
  apiJson("/api/workspaces/" + encodeURIComponent(slug) + "/sync-if-stale", {method:"POST"})
    .then(res => {
      if (res && res.syncStarted) say("Syncing " + workspaceName(slug) + " in the background — the board updates when it finishes.");
    })
    .catch(() => { /* the board already renders from stored data; a failed nudge changes nothing */ });
}

/* ---- creating one ---------------------------------------------------- */

let focusNewWorkspace = false;

function workspaceRow(labelText, input){
  const row = el("div", "settingsrow");
  const label = document.createElement("label");
  label.textContent = labelText;
  row.appendChild(label);
  row.appendChild(input);
  return row;
}

function openNewWorkspaceForm(){
  focusNewWorkspace = true;
  location.hash = routeHash("#/settings");
  renderWorkspacesForm(); // the hash may already have been #/settings, which fires no hashchange
}

// The Settings section. Unlike the picker this renders even on a
// one-workspace install — it is the only way to ever get a second one.
export function renderWorkspacesForm(){
  const host = document.getElementById("settingsWorkspacesForm");
  if (!host) return;
  host.replaceChildren();

  host.appendChild(el("div", "settingshint",
    "This board is showing " + workspaceName(activeWorkspaceSlug()) +
    ". A workspace has its own tracker connection, tickets, categories, transcripts and memory folder — workspaces are switched, never merged. A new one starts empty, with nothing connected."));

  const form = el("form", "workspaceform");
  const slugInput = el("input");
  slugInput.type = "text";
  slugInput.id = "newWorkspaceSlug";
  slugInput.placeholder = "e.g. ticket-terminal";
  slugInput.maxLength = 40;
  const nameInput = el("input");
  nameInput.type = "text";
  nameInput.id = "newWorkspaceName";
  nameInput.placeholder = "e.g. Ticket Terminal";
  nameInput.maxLength = 60;
  form.appendChild(workspaceRow("Slug — lowercase letters, digits and hyphens", slugInput));
  form.appendChild(workspaceRow("Display name", nameInput));

  const submit = el("button", "refreshbtn", "Create workspace");
  submit.type = "submit";
  submit.id = "newWorkspaceBtn";
  const msg = el("span", "settingsmsg");
  msg.id = "newWorkspaceMsg";
  const actions = el("div", "settingsactions");
  actions.appendChild(submit);
  actions.appendChild(msg);
  form.appendChild(actions);
  host.appendChild(form);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const slug = slugInput.value.trim().toLowerCase();
    const name = nameInput.value.trim() || slug;
    if (!SLUG_RE.test(slug)){ msg.textContent = "Slug must be lowercase letters, digits and hyphens."; return; }
    if (slug === "default"){ msg.textContent = "\"default\" is reserved."; return; }
    submit.disabled = true;
    msg.textContent = "Creating…";
    try {
      const res = await apiJson("/api/workspaces", {method:"POST", body: JSON.stringify({slug, name})});
      if (!res || !res.ok){ msg.textContent = "Failed: " + ((res && res.error) || "unknown error"); return; }
      msg.textContent = "";
      await loadWorkspaces();
      // Lands on the new workspace's own Settings page, with nothing connected.
      location.hash = workspaceRouteHash(slug, "/settings");
    } catch (error) {
      msg.textContent = "Failed: " + error.message;
    } finally {
      submit.disabled = false;
    }
  });

  if (focusNewWorkspace){
    focusNewWorkspace = false;
    if (slugInput.focus) slugInput.focus();
  }
}
