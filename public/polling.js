// Data loading + the two live-refresh loops:
//  - reloadBoard(): the full tickets/people/team-options/costs/memory/running-
//    processes fetch + re-render, on a 60s timer and after every mutation.
//  - pollLiveTicketStats(): a much lighter poll (just cost/memory/running-process
//    badges, patched into already-mounted DOM) that runs instead, every 15s,
//    for as long as at least one embedded terminal is open — see state.liveTerminalCount.
//
// reloadBoard used to be a `let reloadBoard = async () => {}` stub, reassigned
// once init() ran, purely because plain bindings don't hoist and a few callers
// elsewhere needed to reference it before init() defined it. A real exported
// function declaration (hoisted, like every other function here) needs no such
// workaround — importers see the same function from the moment their own module
// evaluates, regardless of file/import order.
import { state } from "./state.js";
import { apiJson, makeSnapshot, localDb } from "./api.js";
import { costBadgeText, costBadgeTitle } from "./badges.js";
import { DEFAULT_TEAM_OPTIONS, renderTeamOptions } from "./people.js";
import { renderTickets } from "./lanes.js";
import { buildDemoDocs } from "./demo-data.js";

const dbStateEl = document.getElementById("dbstate");
const refreshTimeEl = document.getElementById("refreshTime");
state.dom.dbStateEl = dbStateEl;

function markRefreshed(){
  refreshTimeEl.textContent = "Last refreshed " + new Date().toLocaleString();
}

export async function reloadBoard(){
  if (state.liveTerminalCount > 0){
    dbStateEl.textContent = "Board refresh paused — " + state.liveTerminalCount + " agent session" + (state.liveTerminalCount === 1 ? "" : "s") + " open";
    return;
  }
  // Which workspace this reload is for. If the board moves on while these
  // requests are in flight, their answers describe a board nobody is looking
  // at any more and must be dropped rather than rendered.
  const generation = state.boardGeneration;
  try {
    const [ticketsObj, peopleObj, teamOpts, costsRes, memUsageRes, processRes] = await Promise.all([
      apiJson("/api/tickets"), apiJson("/api/people"), apiJson("/api/team-options"),
      apiJson("/api/ticket-costs"), apiJson("/api/ticket-memory-usage"), apiJson("/api/running-processes")
    ]);
    if (costsRes && costsRes.ok) state.sessionCosts = costsRes.costs || {};
    if (memUsageRes && memUsageRes.ok) state.memoryUsage = memUsageRes.usage || {};
    if (processRes && processRes.ok){
      state.runningProcesses = new Set(processRes.running || []);
      state.workingProcesses = new Set(processRes.working || []);
      if (state.runningProcesses.size) startAgentActivityPoll();
      else if (!state.liveTerminalCount) stopAgentActivityPoll();
    }
    if (generation !== state.boardGeneration) return; // switched workspace while these were in flight
    state.teamOptions = Array.isArray(teamOpts) && teamOpts.length ? teamOpts : DEFAULT_TEAM_OPTIONS.slice();
    state.peopleMap = peopleObj || {};
    let docs = Object.keys(ticketsObj || {})
      .map(k => makeSnapshot(k, ticketsObj[k]))
      .sort((a,b) => (b.data().createdAt || "").localeCompare(a.data().createdAt || ""));
    // Demo mode: nothing real to show yet (no tracker connected, no tickets of
    // any other origin either) — see demo-data.js for why these are safe to
    // show and never persisted anywhere.
    state.showingDemoDocs = docs.length === 0 && !state.jiraConfigured && !state.notionConfigured;
    if (state.showingDemoDocs) docs = buildDemoDocs();
    renderTeamOptions();
    renderTickets(docs, localDb);
    dbStateEl.textContent = "Local server — data/db.json";
    markRefreshed();
  } catch (e) {
    if (generation === state.boardGeneration){
      dbStateEl.textContent = "Couldn't reach the local server — is it still running?";
    }
  }
}

// Keeps the cost + memory-usage badges/detail boxes current while reloadBoard()
// is paused (see above) — a single shared timer regardless of how many
// terminals are open at once, so N open tickets cost one codeburn invocation
// (+ one memory-usage parse) per tick, not N. Patches already-mounted DOM via
// state.costBadgeEls/memoryBadgeEls; never touches anything reloadBoard()
// would (no re-render, so terminals are untouched).
let liveStatsPollTimer = null;
let agentActivityPollTimer = null;

function patchAgentActivityDots(){
  state.agentActivityEls.forEach(({ticketKey, dot}) => {
    dot.hidden = !state.workingProcesses.has(ticketKey) && !state.workingProcesses.has("codex:" + ticketKey);
  });
}

// The process endpoint is an in-memory lookup, unlike the heavier cost poll
// above. Poll it quickly enough for the dot to follow actual PTY activity and
// patch the already-mounted rows without disturbing an open xterm instance.
export async function pollAgentActivity(){
  const generation = state.boardGeneration;
  try {
    const response = await apiJson("/api/running-processes");
    if (generation !== state.boardGeneration || !response || !response.ok) return;
    state.runningProcesses = new Set(response.running || []);
    state.workingProcesses = new Set(response.working || []);
    patchAgentActivityDots();
    if (!state.runningProcesses.size && !state.liveTerminalCount) stopAgentActivityPoll();
  } catch (e) { /* next tick retries */ }
}

export function startAgentActivityPoll(){
  if (agentActivityPollTimer) return;
  pollAgentActivity();
  agentActivityPollTimer = setInterval(pollAgentActivity, 1000);
}

export function stopAgentActivityPoll(){
  if (!agentActivityPollTimer) return;
  clearInterval(agentActivityPollTimer);
  agentActivityPollTimer = null;
  state.workingProcesses = new Set();
  patchAgentActivityDots();
}

export async function pollLiveTicketStats(){
  const generation = state.boardGeneration;
  try {
    const [costsRes, memUsageRes, processRes] = await Promise.all([
      apiJson("/api/ticket-costs"), apiJson("/api/ticket-memory-usage"), apiJson("/api/running-processes")
    ]);
    if (generation !== state.boardGeneration) return; // badges would be the previous workspace's
    if (costsRes && costsRes.ok){
      state.sessionCosts = costsRes.costs || {};
      state.costBadgeEls.forEach(entry => {
        const info = state.sessionCosts[entry.sessionId];
        if (!info) return; // transient miss (e.g. codeburn briefly unavailable) — keep the last-known value
        entry.badgeEl.hidden = false;
        entry.badgeEl.textContent = costBadgeText(info);
        entry.badgeEl.title = costBadgeTitle(info);
        entry.renderDetail(info);
      });
    }
    if (memUsageRes && memUsageRes.ok){
      state.memoryUsage = memUsageRes.usage || {};
      state.memoryBadgeEls.forEach(entry => {
        const usage = state.memoryUsage[entry.sessionId];
        if (!usage) return;
        const count = Object.keys(usage).length;
        entry.badgeEl.textContent = "🧠 " + count;
        entry.badgeEl.title = count + " memory file" + (count === 1 ? "" : "s") + " read during this session — click for the breakdown";
        entry.renderDetail(usage);
      });
    }
    if (processRes && processRes.ok){
      const newRunning = new Set(processRes.running || []);
      if (newRunning.size !== state.runningProcesses.size || [...newRunning].some(k => !state.runningProcesses.has(k))){
        state.runningProcesses = newRunning;
        // Same rule reloadBoard() follows: a re-render rebuilds every row from
        // scratch, which would kill any open terminal's live WebSocket/PTY along
        // with it. Skip the rebuild while one is open — the badge just catches up
        // on the next tick after it closes.
        if (state.liveTerminalCount === 0) renderTickets(state.lastTicketDocs, state.lastDbRef);
      }
    }
  } catch (e) { /* next tick retries */ }
}

export function startLiveStatsPoll(){
  if (liveStatsPollTimer) return;
  liveStatsPollTimer = setInterval(pollLiveTicketStats, 15000);
}

export function stopLiveStatsPoll(){
  if (!liveStatsPollTimer) return;
  clearInterval(liveStatsPollTimer);
  liveStatsPollTimer = null;
}
