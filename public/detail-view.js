// One category's detail page: its linked knowledge-base docs (fetched lazily,
// only when opened) and a "related memories" table.
import { state } from "./state.js";
import { el, mdLite } from "./dom-utils.js";
import { apiJson } from "./api.js";
import { STATUS_LABEL } from "./lanes.js";
import { renderMermaidInto } from "./diagram-utils.js";
import { routeHash } from "./workspaces.js";

const detailview = document.getElementById("detailview");

// A category's overarching diagram is generated once, over all its linked memories at once
// (see server/diagram_gen.generate_category_diagram), and persisted on the category itself
// (cat.diagram — see content.set_category_diagram), not derived from any per-memory diagrams.
// Node ids are the memory ids they represent by construction, so a click routes straight to
// "#/memory/<id>" — the same route the "Related memories" table row click already uses.
function renderCategoryDiagram(cat){
  const wrap = el("div");

  const header = el("div","panelsectionhead");
  header.appendChild(el("span","memorypanellabel","Diagram"));
  const genBtn = document.createElement("button");
  genBtn.type = "button";
  genBtn.className = "panelminorbtn";
  genBtn.textContent = cat.diagram && cat.diagram.mermaid ? "Regenerate diagram" : "Generate diagram";
  header.appendChild(genBtn);
  wrap.appendChild(header);

  const diagramEl = el("div","categorydiagram");
  wrap.appendChild(diagramEl);
  const genMsg = el("div","memorygenmsg","");
  wrap.appendChild(genMsg);

  const memoryIds = new Set(cat.memories || []);
  diagramEl.addEventListener("click", (event) => {
    const node = event.target.closest(".node");
    if (!node || !node.id) return;
    // Mermaid's own DOM convention for a flowchart node's element id.
    const match = /^flowchart-(.+)-\d+$/.exec(node.id);
    if (match && memoryIds.has(match[1])) location.hash = routeHash("#/memory/" + encodeURIComponent(match[1]));
  });

  function showDiagram(){
    if (cat.diagram && cat.diagram.mermaid){
      renderMermaidInto(diagramEl, cat.diagram.mermaid);
    } else {
      diagramEl.innerHTML = "";
      diagramEl.appendChild(el("div","empty-state","No diagram yet — click Generate to draft one from this category's linked memories."));
    }
  }
  showDiagram();

  genBtn.addEventListener("click", async () => {
    genBtn.disabled = true;
    genMsg.textContent = "Generating…";
    try {
      const res = await apiJson("/api/categories/" + encodeURIComponent(cat.id) + "/diagram", { method: "POST" });
      if (!res.ok) throw new Error(res.error || "failed");
      cat.diagram = res.diagram;
      showDiagram();
      genBtn.textContent = "Regenerate diagram";
      genMsg.textContent = "Generated ✓ (saved)";
    } catch (e) {
      genMsg.textContent = "Couldn't generate: " + e.message;
    } finally {
      genBtn.disabled = false;
    }
  });

  return wrap;
}

export async function renderDetail(cat){
  detailview.innerHTML = "";
  const back = el("button","backlink","‹ Back to chart");
  back.type = "button";
  back.addEventListener("click", () => { location.hash = routeHash(""); });
  detailview.appendChild(back);

  const head = el("div","detailhead");
  head.appendChild(el("h1",null,cat.name));
  head.appendChild(el("span","pill "+cat.status, STATUS_LABEL[cat.status]));
  detailview.appendChild(head);
  detailview.appendChild(el("div","detailnote",cat.note));

  if (cat.memories && cat.memories.length) detailview.appendChild(renderCategoryDiagram(cat));

  if (!cat.docs || cat.docs.length === 0){
    const empty = el("div","empty-state");
    empty.textContent = "No SKILL.md or CLAUDE.md exists for this yet — it's an open gap. Once the real steps are documented, this page will show the resulting runbook.";
    detailview.appendChild(empty);
  } else {
    // Fetched lazily, only when this category's detail view is actually opened —
    // see server/content.py / GET /api/docs/{id} — rather than shipping every doc
    // in this project's knowledge base on every page load regardless of whether
    // it's ever viewed.
    const docs = await Promise.all(cat.docs.map(key => apiJson("/api/docs/" + encodeURIComponent(key))));
    docs.forEach(doc => {
      if (!doc || !doc.ok) return;
      const doccard = el("div","doccard");
      const dochead = el("div","dochead");
      const left = el("div",null);
      left.appendChild(el("div","doctitle",doc.title));
      left.appendChild(el("div","docpath",doc.path));
      dochead.appendChild(left);
      dochead.appendChild(el("span","kindbadge "+doc.kind, doc.kind.toUpperCase()));
      doccard.appendChild(dochead);
      const body = el("div","docbody");
      body.innerHTML = mdLite(doc.content);
      doccard.appendChild(body);
      detailview.appendChild(doccard);
    });
  }

  // Show related memories in a table. state.lastMemoryNodes is normally
  // populated by the memory-graph page (see memory-graph.js) — but a viewer
  // can land here via a category card without ever visiting #/memory first,
  // so fetch it here too if it's still empty, rather than silently rendering
  // a table with headers and no rows.
  if (cat.memories && cat.memories.length && state.lastMemoryNodes.length === 0){
    const res = await apiJson("/api/memory-graph").catch(() => null);
    if (res && res.ok){
      state.lastMemoryNodes = res.nodes;
      state.lastMemoryEdges = res.edges;
    }
  }
  if (cat.memories && cat.memories.length){
    const memSection = el("div");
    memSection.style.marginTop = "26px";
    const title = el("h3",null,"Related memories");
    title.style.fontSize = "18px";
    title.style.fontFamily = '"Big Shoulders", sans-serif';
    title.style.fontWeight = "700";
    title.style.margin = "0 0 12px";
    memSection.appendChild(title);

    const table = document.createElement("table");
    table.style.width = "100%";
    table.style.borderCollapse = "collapse";
    table.style.fontSize = "13.5px";

    const headerRow = table.insertRow();
    headerRow.style.borderBottom = "1px solid var(--line)";
    ["Memory", "Type", "Description"].forEach(label => {
      const cell = headerRow.insertCell();
      cell.textContent = label;
      cell.style.padding = "8px";
      cell.style.textAlign = "left";
      cell.style.fontWeight = "600";
      cell.style.color = "var(--ink-muted)";
      cell.style.fontSize = "11px";
      cell.style.textTransform = "uppercase";
      cell.style.letterSpacing = ".04em";
    });

    cat.memories.forEach(memId => {
      const memNode = state.lastMemoryNodes.find(n => n.id === memId);
      if (!memNode) return;
      const row = table.insertRow();
      row.style.borderBottom = "1px solid var(--line)";
      row.style.cursor = "pointer";
      row.addEventListener("click", () => {
        location.hash = routeHash("#/memory/" + encodeURIComponent(memId));
      });
      row.addEventListener("mouseover", () => { row.style.background = "var(--surface-2)"; });
      row.addEventListener("mouseout", () => { row.style.background = ""; });

      const cells = [
        { text: memId, style: "font-family: 'IBM Plex Mono', monospace; font-size: 12px;" },
        { text: memNode.type || "—", style: "color: var(--ink-muted);" },
        { text: memNode.description || "—", style: "color: var(--ink-muted); max-width: 200px; overflow: hidden; text-overflow: ellipsis;" }
      ];
      cells.forEach(({ text, style }) => {
        const cell = row.insertCell();
        cell.textContent = text;
        cell.style.padding = "8px";
        cell.setAttribute("style", (cell.getAttribute("style") || "") + "; " + style);
      });
    });

    memSection.appendChild(table);
    detailview.appendChild(memSection);
  }
}
