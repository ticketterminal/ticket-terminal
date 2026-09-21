// The two pieces of a ticket row that reach furthest outside that row's own
// concerns: the "⚙ running" badge's kill button (mutates the shared
// runningProcesses set, triggers a full re-render) and the embedded terminal's
// lazy-start/close lifecycle (mutates the shared liveTerminalCount gate that
// pauses reloadBoard()/the process-badge poll while a terminal is open). Pulled
// out of ticket-row.js's renderTicketRow so that function is left with only
// read-only lookups (sessionCosts, memoryUsage, jiraStatusOptions, etc.).
import { state } from "./state.js";
import { apiJson, withWorkspace } from "./api.js";
import { reloadBoard, startLiveStatsPoll, stopLiveStatsPoll } from "./polling.js";
import { renderTickets } from "./lanes.js";
import { categoryLabel } from "./dom-utils.js";

// Returns the "⚙ running" badge button for this ticket, or null if no
// background process is running for it.
export function buildRunningProcessBadge(data){
  const processKey = state.runningProcesses.has(data.key) ? data.key : "codex:" + data.key;
  if (!state.runningProcesses.has(processKey)) return null;
  const bgBadge = document.createElement("button");
  bgBadge.type = "button";
  bgBadge.className = "badge ro";
  bgBadge.style.borderColor = "#F28E2B";
  bgBadge.style.color = "#F28E2B";
  bgBadge.style.cursor = "pointer";
  bgBadge.textContent = processKey.startsWith("codex:") ? "⚙ Codex running" : "⚙ Claude running";
  bgBadge.title = "Background process running — click to stop";
  bgBadge.addEventListener("click", async (e) => {
    e.stopPropagation();
    if (!confirm("Stop the background process for " + data.key + "?")) return;
    const res = await apiJson("/api/running-processes/" + encodeURIComponent(processKey) + "/kill", {method:"POST"});
    if (res.ok){
      state.runningProcesses.delete(processKey);
      renderTickets(state.lastTicketDocs, state.lastDbRef);
    } else {
      alert("Failed to kill process: " + (res.error || "unknown error"));
    }
  });
  return bgBadge;
}

// Wires a ticket row's expand button so the embedded Claude terminal starts
// automatically the first time the row is expanded — no separate button.
// liveTerminalCount pauses reloadBoard() (see polling.js) for as long as this
// connection is actually live, decremented only when the WebSocket really
// closes — not when the panel is just collapsed, since collapsing shouldn't
// kill an in-progress Claude session.
export function attachTerminal(termHost, expandBtn, expandPanel, doc, data){
  expandBtn.setAttribute("aria-controls", expandPanel.id);
  expandBtn.setAttribute("aria-expanded", "false");
  const controls = document.createElement("div");
  controls.className = "terminal-controls";
  termHost.before(controls);
  termHost.hidden = true;
  for (const provider of ["claude", "codex"]){
    const panel = document.createElement("div");
    panel.className = "termhost";
    panel.hidden = true;
    termHost.parentElement.appendChild(panel);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "refreshbtn";
    button.textContent = "Open " + (provider === "codex" ? "Codex" : "Claude");
    controls.appendChild(button);
    let started = false;

    // The actual spawn/attach, split out from the click handler so "hand the
    // session back" (bigger-tab close) can force it open without depending
    // on the button's current hidden/started state the way a plain click does.
    async function openEmbedded(){
      button.disabled = true;
      try {
        const response = await fetch(withWorkspace("/api/terminal-providers"));
        if (response.status === 404) throw new Error("Restart the Ticket Terminal server to load agent support.");
        if (!response.ok) throw new Error("Could not check installed agents (HTTP " + response.status + ").");
        const available = await response.json();
        if (!available.providers.includes(provider)) throw new Error(provider + " executable was not found. Set WMP_" + provider.toUpperCase() + "_BIN to its full path and restart the server.");
      } catch (error) {
        panel.hidden = true;
        alert("Cannot open session. " + error.message);
        return;
      } finally {
        button.disabled = false;
      }
      panel.hidden = false;
      started = true;
      state.openTerminals.add(panel);
      button.textContent = "Show / hide " + (provider === "codex" ? "Codex" : "Claude");
      state.liveTerminalCount++;
      startLiveStatsPoll();
      const cats = (data.categories || []).map(categoryLabel).join(", ") || "uncategorized";
      const promptText = "Work on " + data.key + " (" + cats + "): " + data.summary + "\n" + (data.url || "");
      window.openTicketTerminal(panel, doc.id, promptText, {
        provider,
        // Two workspaces can both hold a DATAFLINT-7652 and both sessions have
        // to stay alive at once, so the socket says which workspace it is for.
        workspace: state.workspaceSlug,
        onClose: () => {
          started = false;
          button.textContent = "Reopen " + (provider === "codex" ? "Codex" : "Claude");
          releaseTerminal(panel);
        }
      });
    }
    button.addEventListener("click", () => {
      panel.hidden = !panel.hidden;
      if (started) return;
      openEmbedded();
    });
    const stop = document.createElement("button");
    stop.type = "button";
    stop.className = "refreshbtn";
    stop.textContent = "Stop " + (provider === "codex" ? "Codex" : "Claude");
    stop.addEventListener("click", async () => {
      const key = provider === "codex" ? "codex:" + data.key : data.key;
      const result = await apiJson("/api/running-processes/" + encodeURIComponent(key) + "/kill", {method:"POST"});
      if (!result.ok) alert(result.error || "Could not stop session");
    });
    controls.appendChild(stop);

    // Pop the same session out into its own, full-size browser tab — the WS
    // endpoint already evicts cleanly on a second connection, so this needs no
    // server support. Release this panel's own hold first so the popup is the
    // sole owner from the start, then poll for the tab closing and reopen the
    // embedded panel automatically — the "hands back on close" behavior.
    const biggerTab = document.createElement("button");
    biggerTab.type = "button";
    biggerTab.className = "refreshbtn";
    biggerTab.textContent = "Open in bigger tab";
    biggerTab.addEventListener("click", () => {
      if (started){
        try { panel.disposeTicketTerminal?.(); } catch (e) { /* already gone */ }
        started = false;
        panel.hidden = true;
        button.textContent = "Open " + (provider === "codex" ? "Codex" : "Claude");
        releaseTerminal(panel);
      }
      const path = "/terminal/" + encodeURIComponent(data.key) + "/" + provider;
      const hash = state.workspaceSlug ? "#/w/" + encodeURIComponent(state.workspaceSlug) + path : "#" + path;
      const popup = window.open(location.origin + location.pathname + hash, "_blank");
      if (!popup){ alert("Couldn't open a new tab — check your browser's popup blocker."); return; }
      const poll = setInterval(() => {
        if (!popup.closed) return;
        clearInterval(poll);
        panel.hidden = false;
        if (!started) openEmbedded();
      }, 700);
    });
    controls.appendChild(biggerTab);

    // Hand off to the real app. Releases this ticket's tracked process (same
    // as Stop), then either opens the ChatGPT desktop app on this workspace —
    // a shared session, safe to come back from — or deep-links into the real
    // Claude app, which FORKS a one-time copy of the conversation with no way
    // back (verified live: the app's own imported copy isn't a valid
    // `--resume` id). Either way: full fidelity (images, diffs, everything
    // this embedded plain-text terminal can't do) that Ticket Terminal never
    // reimplements.
    const appHandoff = document.createElement("button");
    appHandoff.type = "button";
    appHandoff.className = "refreshbtn";
    appHandoff.textContent = provider === "codex" ? "Open in ChatGPT app" : "Open in Claude app (one-way)";
    appHandoff.addEventListener("click", async () => {
      if (provider === "claude" && !confirm("This opens a one-time copy of the conversation in the Claude app. New work there stays there — it won't come back to this ticket. Continue?")) return;
      appHandoff.disabled = true;
      try {
        const result = await apiJson("/api/tickets/" + encodeURIComponent(data.key) + "/handoff?provider=" + provider, {method:"POST"});
        if (!result.ok){ alert(result.error || "Could not hand off session"); return; }
        if (result.url) window.location.href = result.url;
      } catch (error) {
        alert("Could not hand off session: " + error.message);
      } finally {
        appHandoff.disabled = false;
      }
    });
    controls.appendChild(appHandoff);
  }
  expandBtn.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    const expanded = expandBtn.getAttribute("aria-expanded") !== "true";
    expandPanel.toggleAttribute("hidden", !expanded);
    expandBtn.textContent = expanded ? "▾" : "▸";
    expandBtn.setAttribute("aria-expanded", String(expanded));
    expandBtn.setAttribute("aria-label", expanded ? "Collapse ticket details" : "Expand ticket details");
  });
}


// Give up one terminal's claim on the shared live-terminal gate.
// `ws.close()` is asynchronous, so a panel's close can arrive long after a
// workspace switch already let that panel go — by which time the count may
// belong to a terminal opened in the NEW workspace. Membership of
// openTerminals is the ownership token: detachAllTerminals() clears the set,
// so a late close finds nothing and decrements nothing.
export function releaseTerminal(panel){
  if (!state.openTerminals.delete(panel)) return false;
  state.liveTerminalCount = Math.max(0, state.liveTerminalCount - 1);
  if (!state.liveTerminalCount) stopLiveStatsPoll();
  return true;
}

// Let go of every open terminal, for when the board is about to be rebuilt
// wholesale (switching workspace). This closes the WebSockets only: the server
// drops a process from its registry solely once that process has actually
// exited, so each agent keeps running in the background and reconnects on
// reopen — the same thing that already happens when a terminal is collapsed.
// Returns how many were detached, so the caller can say so.
export function detachAllTerminals(){
  const panels = Array.from(state.openTerminals);
  panels.forEach(panel => {
    try { panel.disposeTicketTerminal?.(); } catch (e) { /* already gone */ }
  });
  // The close events are asynchronous, so settle the shared gate here rather
  // than waiting for them; their handlers clamp at zero and are idempotent.
  state.openTerminals.clear();
  state.liveTerminalCount = 0;
  stopLiveStatsPoll();
  return panels.length;
}
