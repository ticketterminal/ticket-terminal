// Per-viewer board UI state. This belongs in localStorage, not db.json: two
// people can look at the same tracker workspace with different filters and
// open panels without changing one another's board.
import { state } from "./state.js";

const VERSION = 1;

function workspaceKey(){
  return "wmp.boardState.v" + VERSION + "." + (state.workspaceSlug || state.defaultWorkspace || "default");
}

function array(value){ return Array.isArray(value) ? value.filter(item => typeof item === "string") : null; }

export function loadBoardState(){
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(workspaceKey()) || "null"); } catch (e) { saved = null; }
  const filters = saved && saved.filters || {};
  state.selectedTeams = array(filters.teams) ? new Set(filters.teams) : null;
  state.knownTeamNames = new Set(array(filters.knownTeams) || array(filters.teams) || []);
  state.selectedStatuses = array(filters.statuses) ? new Set(filters.statuses) : null;
  state.knownStatusNames = new Set(array(filters.knownStatuses) || array(filters.statuses) || []);
  state.selectedAssignees = array(filters.assignees) ? new Set(filters.assignees) : null;
  state.knownAssigneeNames = new Set(array(filters.knownAssignees) || array(filters.assignees) || []);
  state.filterPerson = typeof filters.person === "string" ? filters.person : "";
  state.filterInProgress = filters.inProgress === true;
  state.searchQuery = typeof filters.search === "string" ? filters.search : "";
  state.sprintFilter = typeof filters.sprint === "string" ? filters.sprint : (localStorage.getItem("wmp.sprintFilter") ?? "current");
  const legacyView = localStorage.getItem("wmp.viewMode");
  const legacySort = localStorage.getItem("wmp.flatSort");
  state.viewMode = ["grouped", "flat", "workflow", "status"].includes(saved && saved.viewMode) ? saved.viewMode
    : ["grouped", "flat", "workflow", "status"].includes(legacyView) ? legacyView : "grouped";
  state.flatSortMode = ["status", "priority", "date"].includes(saved && saved.flatSortMode) ? saved.flatSortMode
    : ["status", "priority", "date"].includes(legacySort) ? legacySort : "date";
  state.showNested = saved ? saved.showNested !== false : localStorage.getItem("wmp.showNested") !== "off";
  state.expandedTickets = new Set(array(saved && saved.expandedTickets) || []);
  state.terminalPanels = saved && saved.terminalPanels && typeof saved.terminalPanels === "object" ? saved.terminalPanels : {};
  state.agentPanelModes = saved && saved.agentPanelModes && typeof saved.agentPanelModes === "object" ? saved.agentPanelModes : {};
  const search = document.getElementById("ticketSearch");
  if (search) search.value = state.searchQuery;
}

export function saveBoardState(){
  const payload = {
    viewMode: state.viewMode,
    flatSortMode: state.flatSortMode,
    showNested: state.showNested,
    expandedTickets: [...state.expandedTickets],
    terminalPanels: state.terminalPanels,
    agentPanelModes: state.agentPanelModes,
    filters: {
      teams: state.selectedTeams ? [...state.selectedTeams] : null,
      knownTeams: [...state.knownTeamNames],
      statuses: state.selectedStatuses ? [...state.selectedStatuses] : null,
      knownStatuses: [...state.knownStatusNames],
      assignees: state.selectedAssignees ? [...state.selectedAssignees] : null,
      knownAssignees: [...state.knownAssigneeNames],
      person: state.filterPerson,
      inProgress: state.filterInProgress,
      sprint: state.sprintFilter,
      search: state.searchQuery,
    },
  };
  try { localStorage.setItem(workspaceKey(), JSON.stringify(payload)); } catch (e) { /* storage unavailable */ }
}

export function setTicketExpanded(key, expanded){
  if (expanded) state.expandedTickets.add(key); else state.expandedTickets.delete(key);
  saveBoardState();
}

function terminalId(key, provider){ return key + ":" + provider; }

export function setTerminalPanel(key, provider, panel){
  const id = terminalId(key, provider);
  if (panel) state.terminalPanels[id] = {visible: panel.visible !== false};
  else delete state.terminalPanels[id];
  saveBoardState();
}

export function getTerminalPanel(key, provider){ return state.terminalPanels[terminalId(key, provider)] || null; }

export function setAgentPanelMode(key, provider, mode){
  const id = terminalId(key, provider);
  if (mode) state.agentPanelModes[id] = mode; else delete state.agentPanelModes[id];
  saveBoardState();
}

export function getAgentPanelMode(key, provider){ return state.agentPanelModes[terminalId(key, provider)] || null; }

function visibleTicketRoot(){
  const search = document.getElementById("searchResults");
  if (search && !search.hidden) return search;
  if (state.viewMode === "flat") return document.getElementById("allTicketsView");
  if (state.viewMode === "workflow") return document.getElementById("workflowView");
  if (state.viewMode === "status") return document.getElementById("statusBoardView");
  return document.getElementById("lanes");
}

export function restoreBoardState(){
  const root = visibleTicketRoot();
  if (!root) return;
  const rows = [...root.querySelectorAll(".ticketrow")];
  state.expandedTickets.forEach(key => {
    const row = rows.find(candidate => candidate.dataset.ticketKey === key);
    if (!row) return;
    const expand = row.querySelector(".rowtri");
    if (expand && expand.getAttribute("aria-expanded") !== "true") expand.click();
  });
}
