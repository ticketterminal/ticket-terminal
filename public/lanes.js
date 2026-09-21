// Category cards (grid), per-category lanes, lane ordering, and the two ticket
// lists that live inside them (grouped-by-lane, and the flat "all tickets" view).
import { state } from "./state.js";
import { el, applyScrollCap } from "./dom-utils.js";
import { renderTicketRow } from "./ticket-row.js";
import { passesFilters, isDone, renderFilterOptions, renderSprintOptions, normalizeSprintFilter, renderSearch } from "./filters.js";
import { renderPeople } from "./people.js";
import { routeHash } from "./workspaces.js";

export const STATUS_LABEL = {covered:"Covered", partial:"Partial", gap:"No runbook"};

// Priority is Jira's own field now, synced live by the server — there's no more
// internal P0-P3 (dropped 2026-09-06). Default order/colors match Jira's stock
// scheme; edit this to match your own project's priority values.
export const JIRA_PRIORITY_ORDER = ["Highest","High","Medium","Low","Lowest"];
export const JIRA_PRIORITY_COLOR = { Highest:"var(--gap)", High:"var(--partial)", Medium:"#4E79A7", Low:"var(--ink-muted)", Lowest:"var(--ink-muted)" };
const JIRA_STATUS_RANK = {
  "awaiting approval": 0,
  "waiting for approval": 0,
  "in progress": 1,
  "selected for development": 2,
  "backlog": 3,
  "open": 3,
  "to do": 3,
  "todo": 3,
  "done": 4,
  "cancelled": 5,
  "canceled": 5,
};

function priorityRank(priority){
  const rank = JIRA_PRIORITY_ORDER.indexOf(priority || "Medium");
  return rank < 0 ? JIRA_PRIORITY_ORDER.length : rank;
}

export function compareByPriority(a, b){
  const da = a.data() || {}, db2 = b.data() || {};
  return priorityRank(da.jiraPriority) - priorityRank(db2.jiraPriority) || compareByDate(a, b);
}
export function compareByDate(a, b){
  const da = a.data() || {}, db2 = b.data() || {};
  return (db2.createdAt || "").localeCompare(da.createdAt || ""); // newest first
}
export function compareByStatus(a, b){
  const da = a.data() || {}, db2 = b.data() || {};
  const aRank = JIRA_STATUS_RANK[(da.jiraStatus || "").trim().toLowerCase()] ?? 3;
  const bRank = JIRA_STATUS_RANK[(db2.jiraStatus || "").trim().toLowerCase()] ?? 3;
  return aRank - bRank || compareByPriority(a, b);
}

// How tickets order — set independently PER meta-category (a lane's own sort
// toggle, next to its move arrows), not one global setting. Each category's
// choice is a per-viewer display preference (localStorage). Search results
// span every category at once, so they always sort by priority — there's no
// single "category" to scope a toggle to there.
const LANE_SORT_KEY_PREFIX = "wmp.laneSort.";
const laneSortMode = {}; // populated once CATEGORIES resolves — see buildCategoryUI()
function compareDocsFor(catId){
  if (laneSortMode[catId] === "date") return compareByDate;
  return laneSortMode[catId] === "status" ? compareByStatus : compareByPriority;
}

export const laneTicketLists = {};
const laneCounts = {};

function buildCard(cat){
  const card = el("div","card");
  card.dataset.status = cat.status;

  const head = el("div","card-head");
  head.tabIndex = 0;
  head.setAttribute("role","button");
  head.setAttribute("aria-label","View files for " + cat.name);
  const navigate = () => { location.hash = routeHash("#/category/" + cat.id); };
  head.addEventListener("click", navigate);
  head.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " "){ e.preventDefault(); navigate(); } });

  const row1 = el("div","row1");
  row1.appendChild(el("h2",null,cat.name));
  row1.appendChild(el("span","pill "+cat.status, STATUS_LABEL[cat.status]));
  head.appendChild(row1);
  head.appendChild(el("div","note",cat.note));
  head.appendChild(el("div","viewdocs","View files →"));
  card.appendChild(head);

  if ((cat.memories && cat.memories.length) || (cat.skills && cat.skills.length) || (cat.repos && cat.repos.length)){
    const refs = el("div","refs");
    if (cat.memories && cat.memories.length){
      refs.appendChild(el("div","reflabel","Memory"));
      const row = el("div","chiprow");
      // Real nodes in the actual memory graph now, not disconnected labels — each jumps
      // straight to that node (view/edit); the trailing link opens the full graph.
      cat.memories.forEach(m => {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "chip memchip";
        chip.textContent = m;
        chip.addEventListener("click", (e) => { e.stopPropagation(); location.hash = routeHash("#/memory/" + encodeURIComponent(m)); });
        row.appendChild(chip);
      });
      const graphLink = document.createElement("button");
      graphLink.type = "button";
      graphLink.className = "chip memchip";
      graphLink.textContent = "◇ Full graph →";
      graphLink.addEventListener("click", (e) => { e.stopPropagation(); location.hash = routeHash("#/memory"); });
      row.appendChild(graphLink);
      refs.appendChild(row);
    }
    if (cat.skills && cat.skills.length){
      refs.appendChild(el("div","reflabel","Skill"));
      const row = el("div","chiprow");
      cat.skills.forEach(s => row.appendChild(el("span","chip skill",s)));
      refs.appendChild(row);
    }
    if (cat.repos && cat.repos.length){
      refs.appendChild(el("div","reflabel","Repo"));
      const row = el("div","chiprow");
      cat.repos.forEach(r => row.appendChild(el("span","chip",r)));
      refs.appendChild(row);
    }
    card.appendChild(refs);
  }

  return card;
}

function buildLane(cat){
  // Same <details>/<summary> mechanism as the People & teams and Skills &
  // knowledge sections above — clicking anywhere on the header toggles it
  // natively (incl. keyboard), open by default. "View files" is its own
  // button with stopPropagation so it navigates instead of toggling.
  const lane = document.createElement("details");
  lane.className = "lane";
  let collapsed = [];
  try { collapsed = JSON.parse(localStorage.getItem("wmp.collapsedCategories") || "[]"); } catch (e) {}
  lane.open = !collapsed.includes(cat.id);
  lane.dataset.categoryId = cat.id;
  lane.addEventListener("toggle", () => {
    try { localStorage.setItem("wmp.collapsedCategories", JSON.stringify(Object.entries(laneElements).filter(([, node]) => !node.open).map(([id]) => id))); } catch (e) {}
    updateCategoryToggle();
  });
  lane.dataset.status = cat.status;

  const head = document.createElement("summary");
  head.className = "lanehead";
  const dragHandle = document.createElement("button");
  dragHandle.type = "button";
  dragHandle.className = "lanedrag";
  dragHandle.textContent = "⠿";
  dragHandle.title = "Drag to move " + cat.name + "; use arrow buttons for keyboard ordering";
  dragHandle.setAttribute("aria-label", "Drag " + cat.name);
  dragHandle.draggable = true;
  dragHandle.addEventListener("click", event => { event.preventDefault(); event.stopPropagation(); });
  dragHandle.addEventListener("dragstart", event => {
    draggedCategory = cat.id;
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", cat.id);
    lane.classList.add("dragging");
  });
  dragHandle.addEventListener("dragend", () => {
    draggedCategory = null;
    document.querySelectorAll(".dragging,.drop-before,.drop-after").forEach(node => node.classList.remove("dragging", "drop-before", "drop-after"));
  });
  head.addEventListener("dragover", event => {
    if (!draggedCategory || draggedCategory === cat.id) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    const rect = head.getBoundingClientRect();
    const after = event.clientY >= rect.top + rect.height / 2;
    lane.classList.toggle("drop-after", after);
    lane.classList.toggle("drop-before", !after);
  });
  head.addEventListener("dragleave", () => lane.classList.remove("drop-before", "drop-after"));
  head.addEventListener("drop", event => {
    if (!draggedCategory || draggedCategory === cat.id) return;
    event.preventDefault();
    const rect = head.getBoundingClientRect();
    reorderCategory(draggedCategory, cat.id, event.clientY >= rect.top + rect.height / 2);
    lane.classList.remove("drop-before", "drop-after");
  });
  head.appendChild(dragHandle);

  const moveGroup = document.createElement("span");
  moveGroup.className = "lanemovegroup";
  const upBtn = document.createElement("button");
  upBtn.type = "button";
  upBtn.className = "lanemove";
  upBtn.textContent = "▲";
  upBtn.title = "Move this category up";
  upBtn.addEventListener("click", (e) => { e.stopPropagation(); moveLane(cat.id, -1); });
  const downBtn = document.createElement("button");
  downBtn.type = "button";
  downBtn.className = "lanemove";
  downBtn.textContent = "▼";
  downBtn.title = "Move this category down";
  downBtn.addEventListener("click", (e) => { e.stopPropagation(); moveLane(cat.id, 1); });
  moveGroup.appendChild(upBtn);
  moveGroup.appendChild(downBtn);
  head.appendChild(moveGroup);
  lane._upBtn = upBtn;
  lane._downBtn = downBtn;

  head.appendChild(el("h3",null,cat.name));
  head.appendChild(el("span","pill "+cat.status, STATUS_LABEL[cat.status]));
  const count = el("span","lanecount","0 tickets");
  laneCounts[cat.id] = count;
  head.appendChild(count);

  const sortSel = document.createElement("select");
  sortSel.className = "lanesort";
  sortSel.title = "Sort this category's tickets";
  [["status","Status"], ["priority","Priority"], ["date","Open date"]].forEach(([value, label]) => {
    const opt = document.createElement("option");
    opt.value = value; opt.textContent = label;
    sortSel.appendChild(opt);
  });
  sortSel.value = laneSortMode[cat.id];
  sortSel.addEventListener("click", (e) => e.stopPropagation());
  sortSel.addEventListener("change", () => {
    laneSortMode[cat.id] = sortSel.value;
    try { localStorage.setItem(LANE_SORT_KEY_PREFIX + cat.id, sortSel.value); } catch (e) {}
    renderTickets(state.lastTicketDocs, state.lastDbRef);
  });
  head.appendChild(sortSel);

  const viewBtn = document.createElement("button");
  viewBtn.type = "button";
  viewBtn.className = "laneview";
  viewBtn.textContent = "View files →";
  viewBtn.title = "View files for " + cat.name;
  viewBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    location.hash = routeHash("#/category/" + cat.id);
  });
  head.appendChild(viewBtn);
  lane.appendChild(head);

  const body = el("div","lanebody");
  laneTicketLists[cat.id] = body;
  lane.appendChild(body);

  if (cat.id === UNCATEGORIZED.id){
    lane.classList.add("uncategorized");
    dragHandle.hidden = true; moveGroup.hidden = true; viewBtn.hidden = true;
    head.querySelector(".pill").textContent = "needs a category";
    head.querySelector("h3").title = "Imported tickets whose category guess came back empty — pick one from each row's category controls";
  }
  return lane;
}

const grid = document.getElementById("grid");

// Lane order is a per-viewer display preference — remembered locally
// (localStorage), not shared server state. Reordering moves the existing
// <details> nodes (appendChild on an attached node relocates it), so open
// state and everything else about the lane survives a reorder untouched.
const LANE_ORDER_KEY = "wmp.laneOrder";
function loadLaneOrder(){
  let order;
  try { order = JSON.parse(localStorage.getItem(LANE_ORDER_KEY) || "null"); } catch (e) { order = null; }
  const allIds = state.categories.map(c => c.id);
  if (!Array.isArray(order)) return allIds.slice();
  const kept = order.filter(id => allIds.includes(id));
  allIds.forEach(id => { if (!kept.includes(id)) kept.push(id); });
  return kept;
}
function saveLaneOrder(){
  try { localStorage.setItem(LANE_ORDER_KEY, JSON.stringify(laneOrder)); } catch (e) {}
}
function applyLaneOrder(){
  laneOrder.forEach((id, idx) => {
    const lane = laneElements[id];
    if (!lane) return;
    lanesEl.appendChild(lane); // moves the existing node
    lane._upBtn.disabled = idx === 0;
    lane._downBtn.disabled = idx === laneOrder.length - 1;
  });
  if (uncategorizedLane && uncategorizedLane.parentNode === lanesEl) lanesEl.appendChild(uncategorizedLane); // always last
}
let draggedCategory = null;
export function reorderCategory(source, target, after = false){
  if (source === target || !laneOrder.includes(source) || !laneOrder.includes(target)) return;
  laneOrder = laneOrder.filter(id => id !== source);
  laneOrder.splice(laneOrder.indexOf(target) + (after ? 1 : 0), 0, source);
  saveLaneOrder();
  applyLaneOrder();
  document.getElementById("categoryOrderAnnouncement").textContent = "Category order saved.";
}

export function setCategoriesExpanded(open){
  Object.values(laneElements).forEach(lane => { lane.open = open; });
  updateCategoryToggle();
}

function updateCategoryToggle(){
  const button = document.getElementById("toggleCategoriesBtn");
  if (!button) return;
  const lanes = Object.values(laneElements);
  const hasCollapsedLane = lanes.some(lane => !lane.open);
  button.textContent = hasCollapsedLane ? "Expand all" : "Collapse all";
  button.disabled = lanes.length === 0;
  button.setAttribute("aria-label", hasCollapsedLane ? "Expand all categories" : "Collapse all categories");
}

export function wireCategoryControls(){
  document.getElementById("toggleCategoriesBtn").addEventListener("click", () => {
    const hasCollapsedLane = Object.values(laneElements).some(lane => !lane.open);
    setCategoriesExpanded(hasCollapsedLane);
  });
  document.getElementById("manageCategoriesBtn").addEventListener("click", () => { location.hash = routeHash("#/settings"); });
}

function moveLane(catId, dir){
  const idx = laneOrder.indexOf(catId);
  const newIdx = idx + dir;
  if (idx < 0 || newIdx < 0 || newIdx >= laneOrder.length) return;
  [laneOrder[idx], laneOrder[newIdx]] = [laneOrder[newIdx], laneOrder[idx]];
  saveLaneOrder();
  applyLaneOrder();
}

const laneElements = {};
export const lanesEl = document.getElementById("lanes");
let laneOrder = []; // populated once CATEGORIES resolves — see buildCategoryUI()

// A ticket with no category at all would otherwise be invisible in the
// grouped view — every real lane filters on `categories.includes(cat.id)`.
// That happens to every freshly imported ticket whose LLM category guess
// came back empty (or failed), so they land here instead, with their usual
// NEW badge and per-row category controls to file them. Built once like a
// real lane but kept out of laneElements/laneOrder: it can't be reordered,
// collapsed-all, or persisted, and it's only attached while non-empty.
export const UNCATEGORIZED = { id: "__uncategorized", name: "Uncategorized", status: "gap" };
let uncategorizedLane = null;

// Everything above this point that depends on the real CATEGORIES list (lane
// sort-mode defaults, the grid cards, the lanes themselves + their order) can't
// run until /api/categories resolves — called once from board.js's init(),
// right after that fetch, before the first renderRoute()/reloadBoard(). Also
// re-called after a Settings-page categories save, so it's written to be
// idempotent (clears + fully rebuilds) rather than assuming a single startup
// call — a second call without this would just append a duplicate set of
// lanes/cards alongside the old ones.
export function buildCategoryUI(){
  grid.innerHTML = "";
  lanesEl.innerHTML = "";
  Object.keys(laneElements).forEach(k => delete laneElements[k]);
  Object.keys(laneTicketLists).forEach(k => delete laneTicketLists[k]);
  Object.keys(laneCounts).forEach(k => delete laneCounts[k]);

  state.categories.forEach(cat => {
    let m;
    try { m = localStorage.getItem(LANE_SORT_KEY_PREFIX + cat.id); } catch (e) { m = null; }
    laneSortMode[cat.id] = ["status", "date", "priority"].includes(m) ? m : "priority";
  });
  state.categories.forEach(cat => grid.appendChild(buildCard(cat)));
  state.categories.forEach(cat => {
    const lane = buildLane(cat);
    laneElements[cat.id] = lane;
    lanesEl.appendChild(lane);
  });
  laneSortMode[UNCATEGORIZED.id] = "date";
  uncategorizedLane = buildLane(UNCATEGORIZED); // attached by renderTickets() only while it has tickets
  laneOrder = loadLaneOrder();
  applyLaneOrder();
  updateCategoryToggle();
}

/* Group a lane's tickets so a child whose parent is ALSO present in this same
   lane renders nested inside the parent's box instead of as a flat sibling —
   categorization itself is untouched, this is purely a presentation grouping
   within whatever lane a ticket already belongs to. "Parent" is detected
   dynamically (does any other ticket here have parentKey === this doc's id),
   not by issue type — a plain Task with sub-tasks (e.g. "EKS upgrade and
   management") needs the same box treatment as a real Epic. The EPIC badge
   itself (in ticket-row.js) is separate and only reflects the real Jira issue
   type. `cmp` is a plain (a,b)=>number comparator — decoupled from any one
   category so the same epic/parent-child grouping logic serves both the
   per-category lanes and the flat "all tickets" view (which isn't scoped to
   one category, so there's no cat.id to look a sort mode up by). */
export function buildLaneItems(forCat, cmp){
  const byId = {};
  forCat.forEach(d => { byId[d.id] = d; });
  const childrenOfParent = {};
  forCat.forEach(d => {
    const data = d.data() || {};
    if (data.parentKey && byId[data.parentKey]) {
      (childrenOfParent[data.parentKey] = childrenOfParent[data.parentKey] || []).push(d);
    }
  });
  const items = [];
  forCat.forEach(d => {
    const data = d.data() || {};
    if (data.parentKey && byId[data.parentKey]) return; // rendered nested under its parent instead
    const children = childrenOfParent[d.id];
    items.push(children ? {type:"parent", doc:d, children} : {type:"ticket", doc:d});
  });
  items.sort((a,b) => cmp(a.doc, b.doc));
  return items;
}

export function renderLaneItems(container, items, dbRef, cmp, emptyMessage){
  container.innerHTML = "";
  if (items.length === 0){
    container.appendChild(el("span","empty", emptyMessage || "No open tickets tagged with this category."));
    return;
  }
  items.forEach(item => {
    if (item.type === "parent"){
      const box = el("div","epicbox");
      box.appendChild(renderTicketRow(item.doc, dbRef));
      if (item.children.length){
        const kids = el("div","epicchildren");
        item.children
          .slice()
          .sort(cmp)
          .forEach(c => kids.appendChild(renderTicketRow(c, dbRef)));
        box.appendChild(kids);
      }
      container.appendChild(box);
    } else {
      container.appendChild(renderTicketRow(item.doc, dbRef));
    }
  });
}

export function renderTickets(allDocs, dbRef){
  state.lastTicketDocs = allDocs;
  state.lastDbRef = dbRef;
  normalizeSprintFilter(); // before any lane is filtered, so a stale remembered sprint can't empty the board for one render
  state.costBadgeEls = []; // every renderTicketRow() call below re-registers whatever it mounts
  state.memoryBadgeEls = [];
  state.categories.forEach(cat => {
    const forCat = allDocs.filter(d => {
      const data = d.data() || {};
      return Array.isArray(data.categories) && data.categories.includes(cat.id) && !isDone(d) && passesFilters(d);
    });
    const body = laneTicketLists[cat.id];
    renderLaneItems(body, buildLaneItems(forCat, compareDocsFor(cat.id)), dbRef, compareDocsFor(cat.id));
    applyScrollCap(body, 10);
    laneCounts[cat.id].textContent = forCat.length + (forCat.length === 1 ? " ticket" : " tickets");
  });
  if (uncategorizedLane){
    const loose = allDocs.filter(d => {
      const data = d.data() || {};
      return !(Array.isArray(data.categories) && data.categories.length) && !isDone(d) && passesFilters(d);
    });
    if (loose.length){
      if (uncategorizedLane.parentNode !== lanesEl) lanesEl.appendChild(uncategorizedLane);
      const body = laneTicketLists[UNCATEGORIZED.id];
      renderLaneItems(body, buildLaneItems(loose, compareDocsFor(UNCATEGORIZED.id)), dbRef, compareDocsFor(UNCATEGORIZED.id));
      applyScrollCap(body, 10);
      laneCounts[UNCATEGORIZED.id].textContent = loose.length + (loose.length === 1 ? " ticket" : " tickets");
    } else if (uncategorizedLane.parentNode === lanesEl){
      uncategorizedLane.remove();
    }
  }
  renderFilterOptions();
  renderSprintOptions();
  renderFlatList();
  renderSearch();
  renderPeople();
}

const allTicketsCountEl = document.getElementById("allTicketsCount");
export const allTicketsListEl = document.getElementById("allTicketsList");

// "All tickets" — the flat, non-grouped-by-category view. Each ticket's own
// category controls (already rendered by ticket-row.js, unchanged) show its
// meta-category here, since there's no lane to imply it.
export function renderFlatList(){
  const forAll = state.lastTicketDocs.filter(d => !isDone(d) && passesFilters(d));
  const cmp = state.flatSortMode === "status" ? compareByStatus : state.flatSortMode === "priority" ? compareByPriority : compareByDate;
  renderLaneItems(allTicketsListEl, buildLaneItems(forAll, cmp), state.lastDbRef, cmp, "No open tickets.");
  applyScrollCap(allTicketsListEl, 10);
  allTicketsCountEl.textContent = forAll.length + (forAll.length === 1 ? " ticket" : " tickets");
}
