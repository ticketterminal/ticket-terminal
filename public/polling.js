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
  if (document.hidden) return;
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
    docs = docs.map(doc => {
      const pending = state.pendingTicketStatuses.get(doc.id);
      if (!pending) return doc;
      return makeSnapshot(doc.id, {...(doc.data() || {}), jiraStatus: pending.status});
    });
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
let agentActivityPollTimer = null;
let activityRevisions = new Map();
let statsRefreshTimer = null;
let statsRefreshInFlight = false;
let statsRefreshPending = false;
const ACTIVITY_STATS_SETTLE_MS = 5000;

function patchAgentActivityDots(){
  state.agentActivityEls.forEach(({ticketKey, dot}) => {
    dot.hidden = !state.workingProcesses.has(ticketKey) && !state.workingProcesses.has("codex:" + ticketKey);
  });
}

// The process endpoint is an in-memory lookup, unlike the heavier cost poll
// above. Poll it quickly enough for the dot to follow actual PTY activity and
// patch the already-mounted rows without disturbing an open xterm instance.
export async function pollAgentActivity(){
  if (document.hidden) return;
  const generation = state.boardGeneration;
  try {
    const response = await apiJson("/api/running-processes");
    if (generation !== state.boardGeneration || !response || !response.ok) return;
    state.runningProcesses = new Set(response.running || []);
    state.workingProcesses = new Set(response.working || []);
    const nextRevisions = new Map(Object.entries(response.activity || {}).map(([key, value]) => [key, Number(value) || 0]));
    const hasNewActivity = [...nextRevisions].some(([key, revision]) =>
      revision > (activityRevisions.has(key) ? activityRevisions.get(key) : 0)
    );
    activityRevisions = nextRevisions;
    if (hasNewActivity) scheduleActivityStatsRefresh();
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

export async function pollLiveTicketStats({refreshCosts=false}={}){
  if (document.hidden) return;
  if (statsRefreshInFlight){
    if (refreshCosts) statsRefreshPending = true;
    return;
  }
  const generation = state.boardGeneration;
  statsRefreshInFlight = true;
  try {
    const [costsRes, memUsageRes] = await Promise.all([
      apiJson("/api/ticket-costs" + (refreshCosts ? "?refresh=true" : "")),
      apiJson("/api/ticket-memory-usage")
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
  } catch (e) { /* the next activity edge retries */ }
  finally {
    statsRefreshInFlight = false;
    if (statsRefreshPending){
      statsRefreshPending = false;
      scheduleActivityStatsRefresh();
    }
  }
}

export function startLiveStatsPoll(){
  // Kept as the terminal lifecycle hook. Expensive stats are now queued by actual
  // PTY output revisions in pollAgentActivity(), not by an unconditional timer.
}

export function stopLiveStatsPoll(){
  // Do not cancel a refresh already earned by agent output: it writes the durable
  // spend snapshot even if the user collapses the terminal immediately afterward.
}
state.stopLiveStatsPoll = stopLiveStatsPoll;

function scheduleActivityStatsRefresh(){
  if (document.hidden) return;
  // Debounce until output settles. A throttle would still run codeburn repeatedly during
  // a long streaming turn—the exact moment CPU belongs to the agent, not accounting.
  clearTimeout(statsRefreshTimer);
  statsRefreshTimer = setTimeout(async () => {
    statsRefreshTimer = null;
    await pollLiveTicketStats({refreshCosts:true});
  }, ACTIVITY_STATS_SETTLE_MS);
}

document.addEventListener("visibilitychange", () => {
  if (document.hidden) return;
  pollAgentActivity();
});
