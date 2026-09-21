// LLM usage / cost / caching insights: a fixed dashboard over server/workflow_insights.py's
// computed data — no chat, no free-form question, no LLM call anywhere on this page. Every
// number here is either a real ledger total or one of codeburn's own findings.
import { el } from "./dom-utils.js";
import { apiJson } from "./api.js";

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
    "Memory structure", "Files that are both heavily read and large cost real input tokens on every session that touches them.",
    memTable
  );
}

function renderOptimize(optimize){
  const wrap = el("div");
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

async function load(){
  const body = document.getElementById("insightsBody");
  body.innerHTML = "";
  body.appendChild(el("div", "empty-state", "Loading…"));
  let res;
  try {
    res = await apiJson("/api/insights");
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
  if (!data.ledgerEntryCount){
    body.appendChild(el("div", "empty-state", "No session-cost history yet — this fills in as tickets' terminal sessions are stopped (or finish on their own)."));
  }
  body.appendChild(renderVendorModel(data.vendorModel));
  body.appendChild(renderCaching(data.caching));
  body.appendChild(renderMemory(data.memory));
  body.appendChild(renderOptimize(data.codeburnOptimize));
}

export async function renderInsightsPage(){
  // Assigned rather than addEventListener'd: this page's own route can be re-entered many
  // times in one session (hashchange back and forth), and renderInsightsPage runs fresh each
  // time against the same static button — assignment overwrites the handler instead of
  // stacking a duplicate one per visit.
  document.getElementById("insightsRefreshBtn").onclick = load;
  await load();
}
