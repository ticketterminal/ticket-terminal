// LLM usage / cost / caching insights: a fixed dashboard over server/workflow_insights.py's
// computed data — no chat, no free-form question, no LLM call anywhere on this page. Every
// number here is either a real ledger total or one of codeburn's own findings.
import { el } from "./dom-utils.js";
import { apiJson } from "./api.js";

const RANGE_STORAGE_KEY = "wmp.insightsRange";
const DEFAULT_PRESET = "last30";

function fmtUsd(n){
  return "$" + (Number(n) || 0).toFixed(2);
}
function fmtPct(n){
  return n === null || n === undefined ? "—" : Math.round(n * 100) + "%";
}
function fmtNum(n){
  return Math.round(Number(n) || 0).toLocaleString();
}
function fmtDurationMs(ms){
  const totalMinutes = Math.round((Number(ms) || 0) / 60000);
  if (totalMinutes < 60) return totalMinutes + "m";
  return Math.round(totalMinutes / 60 * 10) / 10 + "h";
}

function tr(cells){
  const row = document.createElement("tr");
  cells.forEach(td => row.appendChild(td));
  return row;
}
function td(text, cls){
  const cell = document.createElement("td");
  if (cls) cell.className = cls;
  cell.textContent = text;
  return cell;
}

// Built with plain createElement/appendChild rather than insertRow()/insertCell() — those
// HTMLTableElement conveniences aren't implemented by every DOM (including this app's own
// linkedom-based UI test harness), and plain nodes work identically everywhere.
function table(headers, rows){
  const t = document.createElement("table");
  t.className = "insightstable";
  t.appendChild(tr(headers.map(h => td(h, "insightsth"))));
  rows.forEach(cells => t.appendChild(tr(cells.map(text => td(text)))));
  if (!rows.length){
    const empty = td("No data yet.", "empty-state");
    empty.colSpan = headers.length;
    t.appendChild(tr([empty]));
  }
  return t;
}

function section(title, help, contentEl){
  const wrap = el("div", "insightssection");
  const head = el("div", "panelsectionhead");
  head.appendChild(el("span", "memorypanellabel", title));
  wrap.appendChild(head);
  if (help) wrap.appendChild(el("div", "insightshelp", help));
  wrap.appendChild(contentEl);
  return wrap;
}

function renderProductivity(data){
  const grid = el("div", "productivitygrid");
  const card = (label, value, meta) => {
    const item = el("div", "productivitycard");
    item.appendChild(el("div", "productivitylabel", label));
    item.appendChild(el("div", "productivityvalue", value));
    item.appendChild(el("div", "productivitymeta", meta));
    grid.appendChild(item);
  };
  const outcomes = (Number(data.completed) || 0) + (Number(data.awaitingApproval) || 0);
  card("Tickets worked", fmtNum(data.ticketsWorked), fmtNum(data.sessions) + " agent sessions");
  card(
    "Current outcomes", fmtNum(outcomes),
    fmtNum(data.completed) + " done · " + fmtNum(data.awaitingApproval) + " awaiting approval"
  );
  card(
    "Linked delivery", fmtNum(data.changeRequests),
    fmtNum(data.deliveryTickets) + " tickets with PR / MR evidence"
  );
  card(
    "Agent spend", fmtUsd(data.totalCost),
    fmtUsd(data.costPerTicket) + " / ticket · " + fmtUsd(data.medianSessionCost) + " median session"
  );
  const wrap = document.createDocumentFragment();
  wrap.appendChild(grid);
  wrap.appendChild(el("div", "productivitynote", "Human time saved is intentionally not shown until hands-on attention is measured."));
  return section(
    "Measured productivity",
    "Directly observed Ticket Terminal records for this window. Current outcomes use each ticket's present status; no time-saved estimate is inferred.",
    wrap
  );
}

function renderVendorModel(data){
  const rows = data.byVendorModel.map(r => [
    r.provider, r.model, fmtNum(r.sessions), fmtUsd(r.totalCost), fmtUsd(r.avgCost),
    (Math.round(r.avgCalls * 10) / 10).toString(), fmtDurationMs(r.avgDurationMs),
  ]);
  const vendorTable = table(
    ["Provider", "Model", "Sessions", "Total cost", "Avg cost", "Avg calls", "Avg duration"], rows
  );

  const catRows = data.byCategory.slice(0, 15).map(r => [
    r.category, r.provider, r.model, fmtNum(r.sessions), fmtUsd(r.totalCost), fmtUsd(r.avgCost),
  ]);
  const categoryTable = table(
    ["Category", "Provider", "Model", "Sessions", "Total cost", "Avg cost"], catRows
  );

  const wrap = document.createDocumentFragment();
  wrap.appendChild(vendorTable);
  const catHead = el("div", "insightssubhead", "By category");
  wrap.appendChild(catHead);
  wrap.appendChild(categoryTable);
  return section(
    "Vendor & model cost", "Which vendor/model is actually cheapest for the work you do — real totals, not a guess.",
    wrap
  );
}

function renderCaching(data){
  const providerRows = data.byProvider.map(r => [r.provider, fmtPct(r.cacheEfficiency)]);
  const providerTable = table(["Provider", "Cache efficiency"], providerRows);

  const wasteRows = data.wasteCandidates.map(w => [
    w.ticketKey, w.provider, fmtPct(w.cacheRatio), fmtNum(w.totalTokens), fmtUsd(w.cost),
  ]);
  const wasteTable = table(["Ticket", "Provider", "Cache ratio", "Total tokens", "Cost"], wasteRows);

  const wrap = document.createDocumentFragment();
  wrap.appendChild(providerTable);
  wrap.appendChild(el("div", "insightssubhead", "Sessions with low cache reuse and high token volume"));
  wrap.appendChild(wasteTable);
  return section(
    "Caching", "Cache-read share of tokens — a low ratio on a high-volume session is real token waste, not a hunch.",
    wrap
  );
}

function renderMemory(rows){
  const memTable = table(
    ["Memory file", "Read by (tickets)", "Size (chars)"],
    rows.slice(0, 20).map(r => [r.id, fmtNum(r.readByTickets), fmtNum(r.chars)])
  );
  return section(
    "Memory structure · all time", "Memory reads do not carry timestamps yet, so this structural view remains lifetime even when usage is filtered.",
    memTable
  );
}

function renderOptimize(optimize, lifetimeOnly){
  const wrap = el("div");
  if (lifetimeOnly){
    wrap.appendChild(el("div", "empty-state", "codeburn's optimization findings are lifetime-only. Switch the usage window to All time to show them without mixing lifetime dollar estimates into this period."));
    return section("codeburn's own findings · all time", null, wrap);
  }
  if (!optimize){
    wrap.appendChild(el("div", "empty-state", "codeburn isn't installed, or `codeburn optimize` failed — this section needs it on PATH."));
    return section("codeburn's own findings", null, wrap);
  }
  const summary = optimize.summary || {};
  const stats = el("div", "insightsstatrow");
  stats.appendChild(el("span", "insightsstat", "Health: " + (summary.healthGrade || "—") + " (" + fmtNum(summary.healthScore) + "/100)"));
  stats.appendChild(el("span", "insightsstat", "Potential savings: " + fmtUsd(summary.potentialSavingsCostUSD) + " (" + fmtNum(summary.potentialSavingsTokens) + " tokens)"));
  wrap.appendChild(stats);

  const findings = optimize.findings || [];
  if (!findings.length){
    wrap.appendChild(el("div", "empty-state", "No findings."));
  } else {
    findings.forEach(f => {
      const card = el("div", "insightsfinding");
      const head = el("div", "insightsfindinghead");
      head.appendChild(el("span", "insightsfindingtitle", f.title));
      head.appendChild(el("span", "pill " + (f.severity === "high" ? "gap" : "partial"), (f.severity || "").toUpperCase()));
      card.appendChild(head);
      card.appendChild(el("div", "insightsfindingbody", f.explanation));
      card.appendChild(el("div", "insightsfindingmeta", "Est. savings: " + fmtUsd(f.estimatedSavingsUSD) + " (" + fmtNum(f.tokensSaved) + " tokens)"));
      wrap.appendChild(card);
    });
  }
  return section("codeburn's own findings", "Reused directly from `codeburn optimize` — not reimplemented here.", wrap);
}

function dateValue(date){
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return year + "-" + month + "-" + day;
}

function localMidnight(value){
  const [year, month, day] = value.split("-").map(Number);
  return new Date(year, month - 1, day);
}

function addDays(date, amount){
  const result = new Date(date);
  result.setDate(result.getDate() + amount);
  return result;
}

function readRangePreference(){
  try {
    return {...JSON.parse(localStorage.getItem(RANGE_STORAGE_KEY) || "{}")};
  } catch (_) {
    return {};
  }
}

function selectedRange(){
  const preset = document.getElementById("insightsRangePreset").value || DEFAULT_PRESET;
  const today = localMidnight(dateValue(new Date()));
  const end = addDays(today, 1);
  let start = null;
  if (preset === "last7") start = addDays(today, -6);
  if (preset === "week"){
    const thisWeekStart = addDays(today, -((today.getDay() + 6) % 7));
    start = addDays(thisWeekStart, -7);
    return {preset, start:start.toISOString(), end:thisWeekStart.toISOString()};
  }
  if (preset === "last30") start = addDays(today, -29);
  if (preset === "month") start = new Date(today.getFullYear(), today.getMonth(), 1);
  if (preset === "custom"){
    const startValue = document.getElementById("insightsStartDate").value;
    const endValue = document.getElementById("insightsEndDate").value;
    if (!startValue || !endValue) throw new Error("Choose both dates for the custom range.");
    start = localMidnight(startValue);
    const customEnd = addDays(localMidnight(endValue), 1); // “Through” is inclusive.
    if (start >= customEnd) throw new Error("The start date must be on or before the end date.");
    return {preset, start:start.toISOString(), end:customEnd.toISOString(), startValue, endValue};
  }
  if (preset === "all") return {preset, start:null, end:null};
  return {preset, start:start.toISOString(), end:end.toISOString()};
}

function insightsPath(range){
  const params = new URLSearchParams();
  if (range.start) params.set("start", range.start);
  if (range.end) params.set("end", range.end);
  return "/api/insights" + (params.size ? "?" + params.toString() : "");
}

function saveRange(range){
  localStorage.setItem(RANGE_STORAGE_KEY, JSON.stringify({
    preset: range.preset,
    startValue: range.startValue || document.getElementById("insightsStartDate").value,
    endValue: range.endValue || document.getElementById("insightsEndDate").value,
  }));
}

function rangeSummary(data, range){
  const count = Number(data.ledgerEntryCount) || 0;
  const total = Number(data.totalLedgerEntryCount) || 0;
  if (!range.start && !range.end) return count + " sessions · all recorded history";
  return count + " of " + total + " sessions in selected window";
}

async function load(){
  const body = document.getElementById("insightsBody");
  const summary = document.getElementById("insightsRangeSummary");
  body.innerHTML = "";
  body.appendChild(el("div", "empty-state", "Loading…"));
  summary.textContent = "";
  let range;
  try {
    range = selectedRange();
    saveRange(range);
  } catch (e) {
    body.innerHTML = "";
    body.appendChild(el("div", "empty-state", e.message));
    return;
  }
  let res;
  try {
    res = await apiJson(insightsPath(range));
  } catch (e) {
    body.innerHTML = "";
    body.appendChild(el("div", "empty-state", "Couldn't load insights: " + e.message));
    return;
  }
  if (!res.ok){
    body.innerHTML = "";
    body.appendChild(el("div", "empty-state", "Couldn't load insights: " + res.error));
    return;
  }
  const data = res.data;
  body.innerHTML = "";
  summary.textContent = rangeSummary(data, range);
  if (!data.ledgerEntryCount){
    body.appendChild(el("div", "empty-state", "No session-cost history yet — this fills in once a ticket's terminal session has actually done something (running or closed, either counts)."));
  }
  body.appendChild(renderProductivity(data.productivity));
  body.appendChild(renderVendorModel(data.vendorModel));
  body.appendChild(renderCaching(data.caching));
  body.appendChild(renderMemory(data.memory));
  body.appendChild(renderOptimize(data.codeburnOptimize, data.codeburnOptimizeLifetimeOnly));
}

async function applyRange(){
  const button = document.getElementById("insightsApplyRangeBtn");
  button.disabled = true;
  button.textContent = "Applying…";
  try {
    await load();
  } finally {
    button.disabled = false;
    button.textContent = "Apply";
  }
}

async function refreshCosts(){
  const button = document.getElementById("insightsRefreshBtn");
  const body = document.getElementById("insightsBody");
  button.disabled = true;
  button.textContent = "Refreshing costs…";
  try {
    const result = await apiJson("/api/insights/refresh", {method:"POST"});
    if (!result.ok) throw new Error(result.error || "refresh failed");
    await load();
  } catch (e) {
    body.innerHTML = "";
    body.appendChild(el("div", "empty-state", "Couldn't refresh insights: " + e.message));
  } finally {
    button.disabled = false;
    button.textContent = "⟳ Refresh";
  }
}

export async function renderInsightsPage(){
  // Assigned rather than addEventListener'd: this page's own route can be re-entered many
  // times in one session (hashchange back and forth), and renderInsightsPage runs fresh each
  // time against the same static button — assignment overwrites the handler instead of
  // stacking a duplicate one per visit.
  const preset = document.getElementById("insightsRangePreset");
  const custom = document.getElementById("insightsCustomRange");
  const startInput = document.getElementById("insightsStartDate");
  const endInput = document.getElementById("insightsEndDate");
  const saved = readRangePreference();
  const today = localMidnight(dateValue(new Date()));
  preset.value = ["last7", "week", "last30", "month", "all", "custom"].includes(saved.preset) ? saved.preset : DEFAULT_PRESET;
  startInput.value = saved.startValue || dateValue(addDays(today, -29));
  endInput.value = saved.endValue || dateValue(today);
  custom.classList.toggle("hidden", preset.value !== "custom");
  preset.onchange = () => {
    custom.classList.toggle("hidden", preset.value !== "custom");
    if (preset.value !== "custom") load();
  };
  document.getElementById("insightsApplyRangeBtn").onclick = applyRange;
  document.getElementById("insightsRefreshBtn").onclick = refreshCosts;
  await load();
}
