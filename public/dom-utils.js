// Pure(ish) DOM/formatting helpers with no board-specific behavior of their own.
import { state } from "./state.js";

export function el(tag, cls, text){
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

// Empty until init() resolves /api/config — a ticket key still renders as plain
// text (no link) until then, and forever if Jira isn't configured.
export function jiraHref(key){
  if (!key || !state.jiraBaseUrl) return null;
  const m = /^([A-Za-z]{2,10}-\d+)$/.exec(key.trim());
  if (!m) return null;
  return state.jiraBaseUrl + "/browse/" + m[1].toUpperCase();
}

export function categoryLabel(id){
  const c = state.categories.find(c => c.id === id);
  return c ? c.name : id;
}

// Jira's createdAt comes as an ISO-ish "YYYY-MM-DD..." string — reformat the
// date part only (no Date() parsing) to sidestep timezone shifting.
export function formatOpenDate(createdAt){
  const ymd = createdAt.slice(0, 10);
  const [y, m, d] = ymd.split("-");
  return d + "-" + m + "-" + y;
}

// codeburn's startedAt/endedAt are full ISO timestamps (not date-only like
// createdAt above), so converting through Date() here is the right call, not a
// timezone bug.
export function formatDateTime(iso){
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleString();
}

export function formatDuration(ms){
  if (!Number.isFinite(ms) || ms < 0) return "—";
  const totalSeconds = Math.round(ms / 1000);
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  if (h > 0) return h + "h " + m + "m";
  if (m > 0) return m + "m " + s + "s";
  return s + "s";
}

/* Caps a lane/search body to ~N ticket rows tall (default 10) with an internal
   scrollbar for the rest, rather than letting the section grow without bound —
   row height varies (tags/badges differ per ticket), so this measures the real
   rendered rows instead of guessing a pixel value. */
export function applyScrollCap(container, limit){
  limit = limit || 10;
  const rows = Array.from(container.children).filter(c => c.classList && (c.classList.contains("ticketrow") || c.classList.contains("epicbox")));
  if (rows.length > limit){
    container.classList.add("scrollcap");
    const cutoff = rows[limit - 1];
    container.style.maxHeight = (cutoff.offsetTop + cutoff.offsetHeight - container.children[0].offsetTop) + "px";
  } else {
    container.classList.remove("scrollcap");
    container.style.maxHeight = "";
  }
}

/* ---- tiny markdown-lite renderer for knowledge-base docs ---- */
export function escapeHtml(s){
  return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}
export function inlineMd(s){
  s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  // [[other-memory-id]] cross-references (see MEMORY_FORMAT.md) — flagged with a data
  // attribute rather than a real href so callers can wire navigation without this shared
  // helper knowing about the memory-graph route.
  s = s.replace(/\[\[([a-z0-9-]+)\]\]/g, '<span class="wikiref" data-memory-ref="$1">$1</span>');
  return s;
}
export function mdLite(raw){
  const esc = escapeHtml(raw);
  const lines = esc.split("\n");
  let html = "";
  let inCode = false;
  let listOpen = false;
  function closeList(){ if (listOpen){ html += "</ul>"; listOpen = false; } }
  for (const line of lines){
    if (/^```/.test(line.trim())){
      if (!inCode){ closeList(); html += "<pre><code>"; inCode = true; }
      else { html += "</code></pre>"; inCode = false; }
      continue;
    }
    if (inCode){ html += line + "\n"; continue; }
    if (line.trim() === ""){ closeList(); continue; }
    let m;
    if ((m = /^(#{1,4})\s+(.*)$/.exec(line))){
      closeList();
      const level = Math.min(m[1].length + 2, 6);
      html += "<h" + level + ">" + inlineMd(m[2]) + "</h" + level + ">";
      continue;
    }
    if ((m = /^[-*]\s+\[( |x|X)\]\s+(.*)$/.exec(line))){
      if (!listOpen){ html += "<ul>"; listOpen = true; }
      const checked = /x/i.test(m[1]);
      html += '<li class="taskline">' + (checked ? "☑" : "☐") + " " + inlineMd(m[2]) + "</li>";
      continue;
    }
    if ((m = /^[-*]\s+(.*)$/.exec(line))){
      if (!listOpen){ html += "<ul>"; listOpen = true; }
      html += "<li>" + inlineMd(m[1]) + "</li>";
      continue;
    }
    closeList();
    html += "<p>" + inlineMd(line) + "</p>";
  }
  closeList();
  if (inCode) html += "</code></pre>";
  return html;
}
