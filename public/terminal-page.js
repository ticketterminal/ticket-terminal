// Full-page terminal — the same WebSocket bridge as a ticket row's inline
// panel (terminal.js), just given the whole page instead of the cramped
// embedded box. Opened via terminal-controller.js's "Open in bigger tab",
// which pops this into its own browser tab and hands the session back to the
// embedded panel automatically once that tab closes.
import { state } from "./state.js";
import { apiJson } from "./api.js";
import { categoryLabel } from "./dom-utils.js";
import { createAgentTrailView } from "./agent-trail.js";
import { createChangeRequestView } from "./change-requests.js";

const hostEl = document.getElementById("terminalPageHost");
const titleEl = document.getElementById("terminalPageTitle");
const providerEl = document.getElementById("terminalPageProvider");
const controlsEl = document.getElementById("terminalPageControls");
const defaultDocumentTitle = document.title || "Ticket Terminal";

// Whichever ticket/provider this page currently holds, so leaving the route
// (router.js calls this before rendering anything else) releases the
// WebSocket cleanly rather than leaving it to the eviction race.
let current = null;

export function disposeTerminalPage(){
  document.title = defaultDocumentTitle;
  providerEl.textContent = "";
  if (!current) return;
  current.changeRequestView?.dispose();
  try { hostEl.disposeTicketTerminal?.(); } catch (e) { /* already gone */ }
  controlsEl.replaceChildren();
  current = null;
}

export async function renderTerminalPage(key, provider){
  current = { key, provider };
  const providerLabel = provider === "codex" ? "Codex" : "Claude";
  titleEl.textContent = key;
  providerEl.textContent = providerLabel + " terminal";
  document.title = key + " · " + providerLabel + " · " + defaultDocumentTitle;
  hostEl.innerHTML = "";
  let data;
  try {
    const tickets = await apiJson("/api/tickets");
    if (!current || current.key !== key || current.provider !== provider) return;
    data = tickets[key];
  } catch (e) {
    if (!current || current.key !== key || current.provider !== provider) return;
    hostEl.textContent = "Couldn't load this ticket: " + e.message;
    return;
  }
  if (!data){
    hostEl.textContent = "No such ticket: " + key;
    return;
  }
  const summary = (data.summary || "Untitled ticket").trim();
  titleEl.textContent = key + " — " + summary;
  document.title = key + " — " + summary + " · " + defaultDocumentTitle;
  const cats = (data.categories || []).map(categoryLabel).join(", ") || "uncategorized";
  const promptText = "Work on " + key + " (" + cats + "): " + data.summary + "\n" + (data.url || "");
  const view = createAgentTrailView(key, provider, data);
  const changeRequestView = createChangeRequestView(key, data, {compact:true});
  current.changeRequestView = changeRequestView;
  hostEl.replaceChildren(view.shell);
  controlsEl.replaceChildren(changeRequestView.shell, view.toggle, view.summaryToggle);
  changeRequestView.start();
  hostEl.disposeTicketTerminal = () => view.shell.disposeTicketTerminal?.();
  window.openTicketTerminal(view.terminal, key, promptText, {
    provider,
    workspace: state.workspaceSlug,
  });
}
