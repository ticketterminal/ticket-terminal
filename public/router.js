// Hash-based routing between the grid, one category's detail page, the
// memory graph, and Settings — each optionally prefixed with `#/w/<slug>`
// naming the workspace being shown. A BARE route means the default workspace,
// so every link that predates workspaces still resolves; the prefix is
// stripped here and each view's own pattern is matched against what's left,
// unchanged.
import { state } from "./state.js";
import { renderDetail } from "./detail-view.js";
import { renderMemoryGraph } from "./memory-graph.js";
import { renderSettingsPage } from "./settings.js";
import { renderInsightsPage } from "./insights.js";
import { renderTerminalPage, disposeTerminalPage } from "./terminal-page.js";
import { parseRoute, routeHash, applyRouteWorkspace } from "./workspaces.js";

const gridview = document.getElementById("gridview");
const detailview = document.getElementById("detailview");
const memoryview = document.getElementById("memoryview");
const settingsview = document.getElementById("settingsview");
const insightsview = document.getElementById("insightsview");
const terminalpageview = document.getElementById("terminalpageview");

function hideAll(){
  gridview.classList.add("hidden");
  detailview.classList.add("hidden");
  memoryview.classList.add("hidden");
  settingsview.classList.add("hidden");
  insightsview.classList.add("hidden");
  terminalpageview.classList.add("hidden");
}

export function renderRoute(){
  const route = parseRoute(location.hash);
  // Kicks off a reload of every per-workspace thing when the slug changed;
  // state.workspaceSlug is updated synchronously, so whatever this route then
  // renders already fetches from the workspace the URL names.
  applyRouteWorkspace(route.slug);
  const hash = "#" + route.path;

  // Leaving the full-page terminal releases its WebSocket before anything
  // else renders — same idea as detachAllTerminals() on a workspace switch,
  // just for this one page. Harmless no-op if nothing was open, and if the
  // route below re-enters the same terminal page it just reconnects fresh.
  disposeTerminalPage();

  const termMatch = /^#\/terminal\/([^/]+)\/(claude|codex)$/.exec(hash);
  if (termMatch){
    hideAll();
    terminalpageview.classList.remove("hidden");
    window.scrollTo(0,0);
    renderTerminalPage(decodeURIComponent(termMatch[1]), termMatch[2]);
    return;
  }

  const catMatch = /^#\/category\/([a-z0-9-]+)$/.exec(hash);
  if (catMatch){
    const cat = state.categories.find(c => c.id === catMatch[1]);
    if (cat){
      renderDetail(cat);
      hideAll();
      detailview.classList.remove("hidden");
      window.scrollTo(0,0);
      return;
    }
  }
  const memMatch = /^#\/memory(?:\/([a-z0-9-]+))?$/.exec(hash);
  if (memMatch){
    hideAll();
    memoryview.classList.remove("hidden");
    window.scrollTo(0,0);
    renderMemoryGraph(memMatch[1] || null);
    return;
  }
  if (hash === "#/settings"){
    hideAll();
    settingsview.classList.remove("hidden");
    window.scrollTo(0,0);
    renderSettingsPage();
    return;
  }
  if (hash === "#/insights"){
    hideAll();
    insightsview.classList.remove("hidden");
    window.scrollTo(0,0);
    renderInsightsPage();
    return;
  }
  hideAll();
  gridview.classList.remove("hidden");
}

export function wireRouterUI(){
  window.addEventListener("hashchange", renderRoute);
  document.getElementById("memoryBackBtn").addEventListener("click", () => { location.hash = routeHash(""); });
  document.getElementById("memoryGraphBtn").addEventListener("click", () => { location.hash = routeHash("#/memory"); });
  document.getElementById("settingsBtn").addEventListener("click", () => { location.hash = routeHash("#/settings"); });
  document.getElementById("settingsBackBtn").addEventListener("click", () => { location.hash = routeHash(""); });
  document.getElementById("insightsBtn").addEventListener("click", () => { location.hash = routeHash("#/insights"); });
  document.getElementById("insightsBackBtn").addEventListener("click", () => { location.hash = routeHash(""); });
  document.getElementById("terminalPageBackBtn").addEventListener("click", () => { location.hash = routeHash(""); });
}
