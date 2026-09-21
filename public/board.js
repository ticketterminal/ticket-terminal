// Board entry point. Imports every module and wires/starts them in a
// deliberate order — the pre-split file scattered this DOM-lookup-plus-
// listener-wiring across top-level code interleaved through the whole file;
// making the order explicit here, instead of relying on import side-effects,
// is itself a readability win.
import { state } from "./state.js";
import { apiJson, localDb } from "./api.js";
import { reloadBoard } from "./polling.js";
import { renderTickets } from "./lanes.js";
import { wireFiltersUI } from "./filters.js";
import { wirePeopleUI } from "./people.js";
import { wireRouterUI, renderRoute } from "./router.js";
import { wireCategoryControls } from "./lanes.js";
import { wireSettingsUI } from "./settings.js";
import { initWorkspaceFromRoute, loadWorkspaces, loadWorkspaceBoard, wireWorkspaceUI, activeWorkspaceSlug, syncIfStale } from "./workspaces.js";

// Before anything fetches: a `#/w/<slug>/…` deep link has to be reflected in
// state.workspaceSlug (and so in every `?w=`) from the very first request on.
initWorkspaceFromRoute();

wireFiltersUI();
wirePeopleUI();
wireRouterUI();
wireSettingsUI();
wireCategoryControls();
wireWorkspaceUI();

const jiraScanHelp = document.querySelector("#ticketsSection .sectionhelp");
jiraScanHelp.addEventListener("click", (event) => {
  event.preventDefault();
  event.stopPropagation();
});

const refreshBtn = document.getElementById("refreshBtn");
refreshBtn.addEventListener("click", async () => {
  refreshBtn.disabled = true;
  const original = refreshBtn.textContent;
  refreshBtn.textContent = "Syncing…";
  try {
    const result = await apiJson("/api/sync", {method:"POST"});
    // A sync can roll the sprint over (yesterday's active sprint is today's
    // closed one), so take the fresh contract list with it rather than leaving
    // the selector on what /api/notion/options said at page load.
    if (Array.isArray(result.sprints)) state.sprints = result.sprints;
    await reloadBoard();
    if (!result.ok) state.dom.dbStateEl.textContent = "Tracker sync: " + result.error;
    else {
      const details = [];
      Object.entries(result.errors || {}).forEach(([tracker, err]) => details.push(tracker + " sync failed: " + err));
      if (result.added && result.added.length) details.push("Pulled in " + result.added.length + " new ticket" + (result.added.length === 1 ? "" : "s") + ": " + result.added.join(", "));
      if (result.categorized && result.categorized.length) details.push("Suggested categories for " + result.categorized.length + " previously uncategorized ticket" + (result.categorized.length === 1 ? "" : "s"));
      if (result.truncated) details.push("⚠ Stopped at the page limit — not every row was read");
      (result.mappingProblems || []).forEach(p => details.push("⚠ " + p));
      if (result.categoryError) details.push("Category suggestions could not run: " + result.categoryError);
      if (result.tagged && result.tagged.length) details.push("Content tags updated for " + result.tagged.length + " ticket" + (result.tagged.length === 1 ? "" : "s"));
      if (result.tagError) details.push("Content tags could not update: " + result.tagError);
      if (details.length) state.dom.dbStateEl.textContent = details.join(" · ");
    }
  } finally {
    refreshBtn.disabled = false;
    refreshBtn.textContent = original;
  }
});

// The server also syncs Jira/Notion status/priority on its own timer in the
// background (see server/jira_sync.py, server/notion_sync.py) — this just re-reads local state
// periodically so an already-open tab picks up those changes without making
// the viewer click refresh themselves. Cheap: hits the local server only,
// never Jira directly.
setInterval(() => { reloadBoard(); }, 60000);

async function init(){
  state.dbCapability = localDb;

  // The registry first: it decides whether any workspace chrome renders at all
  // (one workspace ⇒ none), and it resolves an unknown slug back to the default.
  await loadWorkspaces();

  // Categories, config, the tracker option lists and the board itself — all of
  // it belongs to one workspace, which is why switching re-runs exactly this.
  // renderRoute runs once the categories/jiraBaseUrl are in, so a
  // #/category/... deep link on first load still works.
  await loadWorkspaceBoard(renderRoute);

  // Non-default workspaces sync when you land on one and only if they're stale;
  // the default one is the background timer's job. Never awaited: the stored
  // board is already on screen.
  if (state.workspaceSlug) syncIfStale(activeWorkspaceSlug());

  // applyScrollCap measures real rendered row heights to cap long lists —
  // deliberately, since row height varies (tags/epic boxes/etc). But if that
  // first measurement happens before the custom webfonts finish loading, it
  // locks in a too-small height from fallback-font metrics, which then looks
  // "cut off" until something re-renders (e.g. the next 60s poll) and
  // measures again correctly. Force one corrective re-render right after
  // fonts actually finish, so it's not left to chance/timing.
  if (document.fonts && document.fonts.ready){
    document.fonts.ready.then(() => { renderTickets(state.lastTicketDocs, state.lastDbRef); });
  }
}

init();
