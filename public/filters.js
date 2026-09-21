// Team/person/in-progress filters, the grouped-vs-flat view toggle, and search.
import { state } from "./state.js";
import { el, applyScrollCap } from "./dom-utils.js";
import { teamColor, teamForReporter } from "./people.js";
import { compareByPriority, renderFlatList, laneTicketLists, lanesEl, renderTickets } from "./lanes.js";
import { renderTicketRow } from "./ticket-row.js";

const allTicketsEl = document.getElementById("allTicketsView");
const allTicketsListEl = document.getElementById("allTicketsList");
const flatSortSelEl = document.getElementById("flatSortSel");
const viewGroupedBtn = document.getElementById("viewGroupedBtn");
const viewFlatBtn = document.getElementById("viewFlatBtn");
const inProgressBtn = document.getElementById("inProgressBtn");
const searchResultsEl = document.getElementById("searchResults");
const searchListEl = document.getElementById("searchList");
const searchCountEl = document.getElementById("searchCount");
const searchInputEl = document.getElementById("ticketSearch");
const searchHintEl = document.getElementById("searchHint");
const filterPersonSel = document.getElementById("filterPersonSel");
const teamFilterRowEl = document.getElementById("teamFilterRow");
const teamFilterResetBtn = document.getElementById("teamFilterReset");
const teamFilterClearBtn = document.getElementById("teamFilterClear");
const statusFilterRowEl = document.getElementById("statusFilterRow");
const statusFilterResetBtn = document.getElementById("statusFilterReset");
const statusFilterClearBtn = document.getElementById("statusFilterClear");

// Jira's fixed pair, or — for a Notion-sourced ticket — whatever its status
// column's "Complete" group holds (Done, Archived, Duplicate…), fetched with
// the option lists at startup. Falls back to the Jira pair if that fetch
// failed, so a Notion "Done" is still done.
const DONE_STATUSES = ["Done", "Cancelled"];
export function isDone(doc){
  const data = doc.data() || {};
  if (data.source === "notion" && state.notionDoneStatuses.length) return state.notionDoneStatuses.includes(data.jiraStatus);
  return DONE_STATUSES.includes(data.jiraStatus);
}

// Multi-select team filter: starts with every team (incl. "" = Unknown)
// selected/shown; clicking a chip toggles it out. null = not yet initialized
// (before the first teamOptions snapshot arrives). `knownTeamNames` is what
// makes re-syncing safe: every render calls syncSelectedTeams() again, and it
// must only default-include a team the FIRST time it's ever seen — otherwise a
// deliberate deselect gets silently re-added on the very next render (the bug
// this fixes).
function syncSelectedTeams(){
  const all = [""].concat(state.teamOptions);
  if (state.selectedTeams === null){
    state.selectedTeams = new Set(all);
    state.knownTeamNames = new Set(all);
    return;
  }
  all.forEach(t => {
    if (!state.knownTeamNames.has(t)){
      state.selectedTeams.add(t);
      state.knownTeamNames.add(t);
    }
  });
}

function renderTeamFilterChips(){
  teamFilterRowEl.innerHTML = "";
  [""].concat(state.teamOptions).forEach(name => {
    const active = state.selectedTeams.has(name);
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "filterchip" + (active ? " active" : "");
    chip.textContent = name === "" ? "Unknown" : name;
    const c = teamColor(name);
    if (active){ chip.style.background = c; chip.style.color = "#fff"; chip.style.borderColor = c; }
    else { chip.style.background = "transparent"; chip.style.color = c; chip.style.borderColor = c; }
    chip.addEventListener("click", () => {
      if (state.selectedTeams.has(name)) state.selectedTeams.delete(name); else state.selectedTeams.add(name);
      renderTeamFilterChips();
      renderTickets(state.lastTicketDocs, state.lastDbRef);
    });
    teamFilterRowEl.appendChild(chip);
  });
}

// Every status a ticket can carry: the tracker's own option list(s) — a
// mixed-source board can have both Jira and Notion tickets, hence both lists —
// plus (mirroring statusOptionsFor's per-row fallback) any status actually
// found on a ticket that isn't in either list, so a stray/custom value never
// gets silently hidden from the filter. "" ("Unknown") is always included,
// same as the team filter, so a status-less ticket is never dropped before
// the user gets a chance to control it.
function allStatusNames(){
  // jiraStatusOptions/notionStatusOptions are both [{id, name}, ...] — see
  // statusOptionsFor in ticket-row.js, which reads the same two lists the
  // same way.
  const names = new Set([""].concat(state.jiraStatusOptions.map(s => s.name)).concat(state.notionStatusOptions.map(s => s.name)));
  state.lastTicketDocs.forEach(d => { const s = (d.data()||{}).jiraStatus; if (s) names.add(s); });
  return Array.from(names);
}

// Same null-until-initialized / grow-only-on-new-names pattern as
// syncSelectedTeams, and for the same reason: re-syncing on every render must
// only default-include a status the FIRST time it's ever seen, or a
// deliberate deselect gets silently re-added on the next render.
function syncSelectedStatuses(){
  const all = allStatusNames();
  if (state.selectedStatuses === null){
    state.selectedStatuses = new Set(all);
    state.knownStatusNames = new Set(all);
    return;
  }
  all.forEach(s => {
    if (!state.knownStatusNames.has(s)){
      state.selectedStatuses.add(s);
      state.knownStatusNames.add(s);
    }
  });
}

// Deterministic per-status color, same hash-to-hue approach as teamColor but
// with no fixed roster to special-case — statuses vary by tracker.
function statusColor(name){
  if (!name) return "var(--ink-muted)";
  let h = 0;
  for (let i=0;i<name.length;i++){ h = (h*31 + name.charCodeAt(i)) % 360; }
  return "hsl(" + h + ",45%,45%)";
}

function renderStatusFilterChips(){
  statusFilterRowEl.innerHTML = "";
  allStatusNames().forEach(name => {
    const active = state.selectedStatuses.has(name);
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "filterchip" + (active ? " active" : "");
    chip.textContent = name === "" ? "Unknown" : name;
    const c = statusColor(name);
    if (active){ chip.style.background = c; chip.style.color = "#fff"; chip.style.borderColor = c; }
    else { chip.style.background = "transparent"; chip.style.color = c; chip.style.borderColor = c; }
    chip.addEventListener("click", () => {
      if (state.selectedStatuses.has(name)) state.selectedStatuses.delete(name); else state.selectedStatuses.add(name);
      renderStatusFilterChips();
      renderTickets(state.lastTicketDocs, state.lastDbRef);
    });
    statusFilterRowEl.appendChild(chip);
  });
}

// Every sprint the tracker currently considers running. `state` is the
// tracker-independent contract ("active"/"future"/"closed"); for Notion the
// server derives it from the sprint rows' dates and active marker.
export function activeSprints(){
  return state.sprints.filter(s => s.state === "active");
}

// Sprint membership as the ticket carries it. A ticket with NO sprint fields
// at all — from a tracker with no sprint concept, or synced before sprint
// support existed — is not subject to the sprint filter: otherwise a mixed
// Jira+Notion board would silently lose every Jira ticket the moment Notion
// exposed a sprint. Tickets that only carry the older `sprint` string are
// normalised to a one-element list until a sync rewrites them.
export function sprintMembership(data){
  if (Array.isArray(data.sprintNames)) return { subject: true, names: data.sprintNames };
  if (typeof data.sprint === "string" && data.sprint) return { subject: true, names: [data.sprint] };
  if (data.sprintState !== undefined) return { subject: true, names: [] };
  return { subject: false, names: [] };
}

// Make state.sprintFilter something the current sprint list can satisfy, and
// remember the correction. Called BEFORE lanes are filtered (see renderTickets)
// — doing it only while drawing the selector left one render with every lane
// empty and the selector already saying "All sprints".
export function normalizeSprintFilter(){
  if (!state.sprints.length) return;
  const active = activeSprints();
  const valid = ["", "none"].concat(active.length ? ["current"] : []).concat(state.sprints.map(s => s.name));
  if (valid.includes(state.sprintFilter)) return;
  state.sprintFilter = active.length ? "current" : "";
  try { localStorage.setItem("wmp.sprintFilter", state.sprintFilter); } catch (e) {}
}

// A ticket can sit in several sprints at once (carry-over), so membership is
// tested against the full list, not just the one the board displays.
export function passesSprintFilter(data){
  const mode = state.sprintFilter;
  if (!mode || !state.sprints.length) return true;          // "all", or a board with no sprints
  const { subject, names } = sprintMembership(data);
  if (!subject) return true;
  if (mode === "none") return names.length === 0;
  if (mode === "current"){
    // The tracker's own list of active sprints is authoritative when we have
    // it: a ticket's stored sprintState was captured at sync time and goes
    // stale on rollover in BOTH directions (still "active" for last sprint's
    // tickets, not yet "active" for this sprint's). Only without that list
    // does the stored flag decide.
    const active = activeSprints();
    if (active.length) return active.some(s => names.includes(s.name));
    return data.sprintState === "active";
  }
  return names.includes(mode);
}

export function passesFilters(doc){
  const data = doc.data() || {};
  if (state.filterInProgress && !data.claudeSessionId) return false;
  if (!passesSprintFilter(data)) return false;
  if (state.filterPerson) return data.reporter === state.filterPerson;
  if (state.selectedTeams && !state.selectedTeams.has(teamForReporter(data.reporter))) return false;
  if (state.selectedStatuses && !state.selectedStatuses.has(data.jiraStatus || "")) return false;
  return true;
}

// The sprint selector: hidden unless the tracker actually has sprints.
const sprintSelEl = document.getElementById("sprintSel");
const sprintNoteEl = document.getElementById("sprintNote");

// "Sprint 36  (2026-09-07) · active" — dates and state are the two things that
// tell apart two identically-named-looking sprints in a long list.
function sprintOptionLabel(s){
  return s.name + (s.start ? "  (" + s.start + ")" : "") + (s.state ? " · " + s.state : "");
}

export function renderSprintOptions(){
  const wrap = document.getElementById("sprintWrap");
  if (!wrap) return;
  wrap.hidden = state.sprints.length === 0;
  if (wrap.hidden) return;

  const active = activeSprints();
  sprintSelEl.innerHTML = "";
  const add = (value, label) => {
    const o = document.createElement("option");
    o.value = value; o.textContent = label;
    sprintSelEl.appendChild(o);
  };
  // Only offer "the sprint that's running" when one actually is — between
  // sprints (or on a board whose sprints are all dated in the future) there is
  // nothing for it to mean.
  if (active.length === 1) add("current", "Active sprint — " + active[0].name);
  else if (active.length > 1) add("current", "Active sprints (" + active.length + ")");
  add("", "All sprints");
  add("none", "No sprint");
  // The server already sorts sprints active-first then newest-first, so the
  // list order is the tracker's, not one re-derived here.
  state.sprints.forEach(s => add(s.name, sprintOptionLabel(s)));
  normalizeSprintFilter(); // idempotent — renderTickets already ran it before filtering
  sprintSelEl.value = state.sprintFilter;

  if (sprintNoteEl){
    if (state.sprintFilter === "current" && active.length > 1){
      sprintNoteEl.textContent = active.map(s => s.name).join("  ·  "); // several running: name them, don't show one's dates as if they were all
    } else {
      const shown = state.sprintFilter === "current" ? active[0]
                  : state.sprints.find(s => s.name === state.sprintFilter);
      sprintNoteEl.textContent = shown && shown.start
        ? shown.start + " → " + (shown.end || shown.start) + (shown.rawStatus ? "  ·  " + shown.rawStatus : "")
        : "";
    }
  }
}

export function renderFilterOptions(){
  syncSelectedTeams();
  renderTeamFilterChips();
  syncSelectedStatuses();
  renderStatusFilterChips();

  const prevPerson = filterPersonSel.value;
  const names = new Set();
  state.lastTicketDocs.forEach(d => { const r = (d.data()||{}).reporter; if (r) names.add(r); });
  filterPersonSel.innerHTML = '<option value="">All people</option>';
  Array.from(names).sort().forEach(n => {
    const o = document.createElement("option");
    o.value = n; o.textContent = n;
    filterPersonSel.appendChild(o);
  });
  filterPersonSel.value = names.has(prevPerson) ? prevPerson : "";
}

function matchesQuery(doc, q){
  const data = doc.data() || {};
  const team = teamForReporter(data.reporter);
  const hay = [data.key, data.summary, data.reporter, team].filter(Boolean).join(" ").toLowerCase();
  return hay.includes(q);
}

export function renderSearch(){
  const q = (searchInputEl.value || "").trim().toLowerCase();
  updateViewVisibility();
  if (!q){
    searchHintEl.textContent = "";
    return;
  }
  // Each ticket doc is unique (doc id = ticket key), so filtering the doc list
  // directly — rather than flattening the per-lane groupings — can never
  // produce a duplicate row even though one ticket may carry several category
  // category assignments and so appear in several lanes.
  const matches = state.lastTicketDocs.filter(d => matchesQuery(d, q) && passesFilters(d));
  matches.sort(compareByPriority);
  searchListEl.innerHTML = "";
  if (matches.length === 0){
    searchListEl.appendChild(el("span","empty","No tickets match “"+q+"”."));
  } else {
    matches.forEach(d => searchListEl.appendChild(renderTicketRow(d, state.lastDbRef)));
  }
  applyScrollCap(searchListEl, 10);
  searchCountEl.textContent = matches.length + (matches.length === 1 ? " ticket" : " tickets");
  searchHintEl.textContent = "matches key, summary, person, or team — includes Done tickets";
}

// Which of lanes / all-tickets / search-results is visible right now — a
// search query always wins; otherwise it's whichever viewMode is set.
export function updateViewVisibility(){
  const searching = !!(searchInputEl.value || "").trim();
  searchResultsEl.hidden = !searching;
  lanesEl.hidden = searching || state.viewMode !== "grouped";
  document.getElementById("categoryToolbar").hidden = lanesEl.hidden;
  allTicketsEl.hidden = searching || state.viewMode !== "flat";
  viewGroupedBtn.classList.toggle("active", state.viewMode === "grouped");
  viewFlatBtn.classList.toggle("active", state.viewMode === "flat");
  // applyScrollCap measures real offsetTop/offsetHeight, which read as 0 on a
  // display:none container — so a lane/list measured while its view was
  // hidden (e.g. the periodic background refresh runs renderTickets() for
  // BOTH views even though only one is ever visible) freezes at max-height:0,
  // cutting it off until something re-renders. Re-measure whichever container
  // just became visible now that layout reflects that — content is already
  // rendered, this only fixes the cap, so it's safe even with a terminal open
  // elsewhere.
  if (!lanesEl.hidden){
    state.categories.forEach(cat => applyScrollCap(laneTicketLists[cat.id], 10));
  }
  if (!allTicketsEl.hidden){
    applyScrollCap(allTicketsListEl, 10);
  }
  if (!searchResultsEl.hidden){
    applyScrollCap(searchListEl, 10);
  }
}

function setViewMode(mode){
  state.viewMode = mode;
  try { localStorage.setItem("wmp.viewMode", mode); } catch (e) {}
  updateViewVisibility();
}

export function wireFiltersUI(){
  teamFilterResetBtn.addEventListener("click", () => {
    state.selectedTeams = new Set([""].concat(state.teamOptions));
    renderTeamFilterChips();
    renderTickets(state.lastTicketDocs, state.lastDbRef);
  });
  teamFilterClearBtn.addEventListener("click", () => {
    state.selectedTeams = new Set();
    renderTeamFilterChips();
    renderTickets(state.lastTicketDocs, state.lastDbRef);
  });
  statusFilterResetBtn.addEventListener("click", () => {
    state.selectedStatuses = new Set(allStatusNames());
    renderStatusFilterChips();
    renderTickets(state.lastTicketDocs, state.lastDbRef);
  });
  statusFilterClearBtn.addEventListener("click", () => {
    state.selectedStatuses = new Set();
    renderStatusFilterChips();
    renderTickets(state.lastTicketDocs, state.lastDbRef);
  });
  filterPersonSel.addEventListener("change", () => { state.filterPerson = filterPersonSel.value; renderTickets(state.lastTicketDocs, state.lastDbRef); });
  if (sprintSelEl){
    sprintSelEl.addEventListener("change", () => {
      state.sprintFilter = sprintSelEl.value;
      try { localStorage.setItem("wmp.sprintFilter", state.sprintFilter); } catch (e) {}
      renderSprintOptions();
      renderTickets(state.lastTicketDocs, state.lastDbRef);
    });
  }

  viewGroupedBtn.addEventListener("click", () => setViewMode("grouped"));
  viewFlatBtn.addEventListener("click", () => setViewMode("flat"));
  inProgressBtn.addEventListener("click", () => {
    state.filterInProgress = !state.filterInProgress;
    inProgressBtn.classList.toggle("active");
    renderTickets(state.lastTicketDocs, state.lastDbRef);
  });

  flatSortSelEl.value = state.flatSortMode;
  flatSortSelEl.addEventListener("change", () => {
    state.flatSortMode = flatSortSelEl.value;
    try { localStorage.setItem("wmp.flatSort", state.flatSortMode); } catch (e) {}
    renderFlatList();
  });

  searchInputEl.addEventListener("input", renderSearch);

  // Same failure mode updateViewVisibility() already guards against above
  // (applyScrollCap freezing a lane at a too-small max-height because it
  // measured real layout at a bad moment), two more triggers for it: the
  // webfonts swapping in after the initial measurement (rows are shorter
  // pre-swap), and the tab sitting backgrounded/asleep for a while. Both look
  // exactly like "the board is stuck showing a sliver of the first ticket
  // until the next 60s auto-refresh" — re-measure as soon as each resolves
  // instead of waiting for that.
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(updateViewVisibility);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) updateViewVisibility(); });
}
