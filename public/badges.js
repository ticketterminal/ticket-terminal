// Cost/memory badge text + detail-box rendering — pure functions, take their
// data (info/usage) as parameters, touch no shared state.
import { el, formatDateTime, formatDuration } from "./dom-utils.js";

// codeburn's own table view drops "<synthetic>" from the visible model list
// (internal/non-billed calls) — match that here rather than leaking it into
// badges/tooltips/detail.
export function realCostModels(info){
  return (info.models || []).filter(m => m !== "<synthetic>");
}

export function costBadgeText(info){
  return (info.provider === "codex" ? "Codex " : "Claude ") + "$" + info.cost.toFixed(2);
}

export function costBadgeTitle(info){
  const realModels = realCostModels(info);
  return info.calls + " API call" + (info.calls === 1 ? "" : "s") +
    (realModels.length ? " — " + realModels.join(", ") : "") +
    " (via codeburn) — click for the full breakdown";
}

// Builds/refreshes the "click the cost badge" detail box content — shared by
// the initial render and every live-poll tick (see polling.js) so both paths
// render identically. Shared shape with the memory-usage badge's box below —
// both are a "small label/value breakdown + a source note", just fed different rows.
export function renderDetailRows(box, rows, note){
  box.innerHTML = "";
  rows.forEach(([label, value]) => {
    const line = el("div","detailboxrow");
    line.appendChild(el("span","detailboxlabel", label));
    line.appendChild(el("span","detailboxvalue", value));
    box.appendChild(line);
  });
  if (note) box.appendChild(el("div","detailboxnote", note));
}

export function renderCostDetail(box, info){
  const rows = [
    ["Cost", "$" + info.cost.toFixed(4)],
    ["Cache savings", "$" + (info.savingsUSD || 0).toFixed(4)],
    ["API calls", String(info.calls) + " (" + info.turns + " turn" + (info.turns === 1 ? "" : "s") + ")"],
    ["Input tokens", info.inputTokens.toLocaleString()],
    ["Output tokens", info.outputTokens.toLocaleString()],
    ["Cache read", info.cacheReadTokens.toLocaleString()],
    ["Cache write", info.cacheWriteTokens.toLocaleString()],
    ["Duration", formatDuration(info.durationMs)],
    ["Started", formatDateTime(info.startedAt)],
    ["Ended", formatDateTime(info.endedAt)],
  ];
  const realModels = realCostModels(info);
  if (realModels.length) rows.push(["Model" + (realModels.length === 1 ? "" : "s"), realModels.join(", ")]);
  renderDetailRows(box, rows, "Source: codeburn local transcript analysis. Token-based cost estimate; subscription billing may differ.");
}

// usage: {memoryId: timesRead} for one ticket+provider, from GET /api/ticket-memory-usage.
export function renderMemoryDetail(box, usage){
  const rows = Object.keys(usage)
    .sort((a, b) => usage[b] - usage[a])
    .map(id => [id, usage[id] + "×"]);
  renderDetailRows(box, rows, "Counts a memory file only when this ticket's session directly referenced it (a Claude Read tool call, or a Codex command mentioning the file) — not every Grep/Glob sweep over the memory folder, which can't be pinned to one file.");
}
