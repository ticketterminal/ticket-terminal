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

// Whichever ticket/provider this page currently holds, so leaving the route
// (router.js calls this before rendering anything else) releases the
// WebSocket cleanly rather than leaving it to the eviction race.
let current = null;

export function disposeTerminalPage(){
  if (!current) return;
  try { hostEl.disposeTicketTerminal?.(); } catch (e) { /* already gone */ }
  current = null;
}

export async function renderTerminalPage(key, provider){
  current = { key, provider };
  titleEl.textContent = key + " — " + (provider === "codex" ? "Codex" : "Claude");
  hostEl.innerHTML = "";
  let data;
  try {
    const tickets = await apiJson("/api/tickets");
    data = tickets[key];
  } catch (e) {
    hostEl.textContent = "Couldn't load this ticket: " + e.message;
    return;
  }
  if (!data){
    hostEl.textContent = "No such ticket: " + key;
    return;
  }
  const cats = (data.categories || []).map(categoryLabel).join(", ") || "uncategorized";
  const promptText = "Work on " + key + " (" + cats + "): " + data.summary + "\n" + (data.url || "");
  window.openTicketTerminal(hostEl, key, promptText, {
    provider,
    workspace: state.workspaceSlug,
  });
}
