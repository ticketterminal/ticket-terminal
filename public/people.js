// Team roster, reporter->team mapping, and the "People & teams" section.
import { state } from "./state.js";
import { el } from "./dom-utils.js";

// Client-side fallback shown only until /api/team-options resolves (real team
// data lives in data/db.json) — edit this if you'd rather see something more
// meaningful than "Team A"/"Team B" during that brief window.
export const DEFAULT_TEAM_OPTIONS = ["Team A", "Team B"];
export const TEAM_COLORS = { "Team A":"#4E79A7", "Team B":"#59A14F" };

export function teamColor(name){
  if (!name) return "var(--ink-muted)";
  if (TEAM_COLORS[name]) return TEAM_COLORS[name];
  let h = 0;
  for (let i=0;i<name.length;i++){ h = (h*31 + name.charCodeAt(i)) % 360; }
  return "hsl(" + h + ",45%,45%)";
}

export function normalizeName(name){
  return (name || "").toLowerCase().trim().replace(/[^a-z0-9]+/g,"-").replace(/^-+|-+$/g,"") || "unknown";
}

export function teamForReporter(reporter){
  const p = state.peopleMap[normalizeName(reporter)];
  return (p && p.team) || "";
}

const teamChipsEl = document.getElementById("teamChips");
const addTeamForm = document.getElementById("addTeamForm");
const newTeamInput = document.getElementById("newTeamInput");
const peopleListEl = document.getElementById("peopleList");
const peopleCountEl = document.getElementById("peopleCount");

export function renderTeamOptions(){
  teamChipsEl.innerHTML = "";
  state.teamOptions.forEach(name => {
    const chip = el("span","tagchip");
    chip.style.color = teamColor(name);
    chip.style.border = "1px solid " + teamColor(name);
    chip.appendChild(document.createTextNode(name));
    if (state.dbCapability){
      const x = document.createElement("button");
      x.type = "button";
      x.className = "tagx";
      x.textContent = "×";
      x.setAttribute("aria-label","Remove "+name+" from the team list");
      x.addEventListener("click", () => {
        state.dbCapability.doc("meta/teamOptions").set({options: state.teamOptions.filter(t => t !== name)});
      });
      chip.appendChild(x);
    }
    teamChipsEl.appendChild(chip);
  });
}

export function renderPeople(){
  const names = new Map();
  state.lastTicketDocs.forEach(d => {
    const r = (d.data() || {}).reporter;
    if (r) names.set(normalizeName(r), r);
  });
  Object.keys(state.peopleMap).forEach(id => {
    if (!names.has(id) && state.peopleMap[id] && state.peopleMap[id].name) names.set(id, state.peopleMap[id].name);
  });
  const rows = Array.from(names.entries()).sort((a,b) => a[1].localeCompare(b[1]));
  peopleListEl.innerHTML = "";
  if (rows.length === 0){
    peopleListEl.appendChild(el("span","empty","No reporters seen yet — load tickets first."));
  }
  rows.forEach(([id, name]) => {
    const row = el("div","personrow");
    row.appendChild(el("span","personname", name));
    const sel = document.createElement("select");
    sel.className = "teamsel";
    [""].concat(state.teamOptions).forEach(opt => {
      const o = document.createElement("option");
      o.value = opt;
      o.textContent = opt === "" ? "Unknown" : opt;
      sel.appendChild(o);
    });
    const current = (state.peopleMap[id] && state.peopleMap[id].team) || "";
    sel.value = current;
    sel.style.color = teamColor(current);
    sel.style.borderColor = teamColor(current);
    sel.disabled = !state.dbCapability;
    sel.addEventListener("change", () => {
      const val = sel.value;
      sel.style.color = teamColor(val);
      sel.style.borderColor = teamColor(val);
      if (state.dbCapability) state.dbCapability.doc("people/"+id).set({name, team: val});
    });
    row.appendChild(sel);
    peopleListEl.appendChild(row);
  });
  peopleCountEl.textContent = rows.length + (rows.length === 1 ? " person" : " people");
}

export function wirePeopleUI(){
  addTeamForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const val = newTeamInput.value.trim();
    newTeamInput.value = "";
    if (!val || !state.dbCapability || state.teamOptions.includes(val)) return;
    state.dbCapability.doc("meta/teamOptions").set({options: state.teamOptions.concat([val])});
  });
}
