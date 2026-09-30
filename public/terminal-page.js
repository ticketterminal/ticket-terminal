// Full-page terminal — the same WebSocket bridge as a ticket row's inline
// panel (terminal.js), just given the whole page instead of the cramped
// embedded box. Opened via terminal-controller.js's "Open in bigger tab",
// which pops this into its own browser tab and hands the session back to the
// embedded panel automatically once that tab closes.
import { state } from "./state.js";
import { apiJson } from "./api.js";
import { categoryLabel } from "./dom-utils.js";

const hostEl = document.getElementById("terminalPageHost");
const titleEl = document.getElementById("terminalPageTitle");
// Captured once at load, so this stays whatever index.html's <title> actually
// says instead of hardcoding a second copy of it here.
const DEFAULT_TITLE = document.title;

// Whichever ticket/provider this page currently holds, so leaving the route
// (router.js calls this before rendering anything else) releases the
// WebSocket cleanly rather than leaving it to the eviction race.
let current = null;

function setHeadline(text){
  titleEl.textContent = text;
  document.title = text;
}

export function disposeTerminalPage(){
  if (!current) return;
  try { hostEl.disposeTicketTerminal?.(); } catch (e) { /* already gone */ }
  current = null;
  document.title = DEFAULT_TITLE;
}

export async function renderTerminalPage(key, provider){
  const session = current = { key, provider };
  const providerLabel = provider === "codex" ? "Codex" : "Claude";
  // A ticket's own key + full title, so a browser tab-strip full of these is
  // actually distinguishable at a glance — the provider suffix stays because
  // the same ticket can have both a Claude and a Codex tab open at once.
  setHeadline(key + " — " + providerLabel);
  hostEl.innerHTML = "";
  let data;
  try {
    const tickets = await apiJson("/api/tickets");
    data = tickets[key];
  } catch (e) {
    hostEl.textContent = "Couldn't load this ticket: " + e.message;
    return;
  }
  if (current !== session) return; // navigated away while that fetch was in flight
  if (!data){
    hostEl.textContent = "No such ticket: " + key;
    return;
  }
  setHeadline(key + " — " + data.summary + " (" + providerLabel + ")");
  const cats = (data.categories || []).map(categoryLabel).join(", ") || "uncategorized";
  const promptText = "Work on " + key + " (" + cats + "): " + data.summary + "\n" + (data.url || "");
  window.openTicketTerminal(hostEl, key, promptText, {
    provider,
    workspace: state.workspaceSlug,
  });
}
