// The real memory corpus (~/.claude/projects/.../memory/) as a graph — see
// server/memory_analysis.py. Fetched fresh on every visit (cheap: reading ~30
// small local files) rather than cached, so an edit saved from the panel below
// is reflected immediately. Uses the vis-network CDN global.
import { state } from "./state.js";
import { el, mdLite } from "./dom-utils.js";
import { apiJson } from "./api.js";
import { renderMermaidInto, extractMermaidFence } from "./diagram-utils.js";
import { routeHash } from "./workspaces.js";

const memoryCanvasEl = document.getElementById("memoryCanvas");
const memoryPanelEl = document.getElementById("memoryPanel");
const memoryGraphSubEl = document.getElementById("memoryGraphSub");

const MEMORY_TYPE_COLOR = { user: "#4E79A7", feedback: "#F28E2B", project: "#59A14F", reference: "#B07AA1" };
const SELECTED_BORDER = "#ffd76a";
let visNetworkInstance = null;
let memoryGraphState = { focusNode: null, visibleTypes: { user: true, feedback: true, project: true, reference: true }, springLength: 180 };

// Shared by the initial render and every filter/spacing re-apply, so a selected node's
// highlight border and a type's fill color are never defined in two places that could drift.
function nodeSpec(n){
  const bg = MEMORY_TYPE_COLOR[n.type] || "#8A8F98";
  return {
    id: n.id,
    label: n.id,
    title: n.description || "",
    color: { background: bg, border: "rgba(255,255,255,.18)", highlight: { background: bg, border: SELECTED_BORDER } },
  };
}

function networkOptions(springLength){
  return {
    autoResize: true,
    physics: {
      enabled: true,
      stabilization: { iterations: 200 },
      barnesHut: { springLength, springConstant: 0.03, avoidOverlap: 0.4, gravitationalConstant: -2200, damping: 0.15 },
    },
    nodes: { shape: "ellipse", borderWidth: 2, borderWidthSelected: 4, margin: 10, font: { face: "IBM Plex Mono, monospace", size: 11, color: "#ffffff" } },
    edges: { arrows: "to", color: { color: "rgba(140,140,140,.55)" }, smooth: { type: "continuous" } },
    interaction: { hover: true },
  };
}

// At ~45 nodes/150 edges, the old physics tuning (weak springs + strong repulsion) never
// converged — the simulation ran forever instead of settling, which read as the graph
// "constantly spinning" with no way to stop it. Freezing physics the moment vis-network's own
// stabilized event fires locks the layout in place; re-enabling it (see the spacing slider) is
// what makes a later re-layout possible, and each re-enable needs its own one-shot freeze to
// lock again once THAT round settles. A fixed timeout freeze runs alongside "stabilized" as a
// hard backstop — some parameter combinations may never actually fire that event, and the
// whole point of this function is that the layout is GUARANTEED to stop, not just usually.
function freezeOnceStable(network){
  let frozen = false;
  const freeze = () => { if (!frozen){ frozen = true; network.setOptions({ physics: false }); } };
  network.once("stabilized", freeze);
  setTimeout(freeze, 4000);
}

// A memory's diagram is a plain ```mermaid fenced block inside its own markdown body (see
// MEMORY_FORMAT.md) — not a separate field, so it stays one portable file. vis-network (above)
// stays scoped to the node-to-node overview graph; Mermaid (see diagram-utils.js) renders a
// single memory's own diagram, since its declarative flowchart/graph syntax is the better fit
// for hand-edited or LLM-drafted content than driving vis-network's DataSet API per node.

function debounce(fn, ms){
  let timer = null;
  return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), ms); };
}

export function applyMemoryGraphFilters(){
  if (!visNetworkInstance) return;
  const { focusNode, visibleTypes } = memoryGraphState;
  const types = ["user", "feedback", "project", "reference"];
  const shownTypes = types.filter(t => visibleTypes[t]);

  let nodesToShow = state.lastMemoryNodes.filter(n => shownTypes.includes(n.type || "reference"));
  let edgesToShow = state.lastMemoryEdges;

  if (focusNode){
    const focusSet = new Set([focusNode]);
    state.lastMemoryEdges.forEach(e => {
      if (e.from === focusNode) focusSet.add(e.to);
      if (e.to === focusNode) focusSet.add(e.from);
    });
    nodesToShow = nodesToShow.filter(n => focusSet.has(n.id));
    edgesToShow = edgesToShow.filter(e => focusSet.has(e.from) && focusSet.has(e.to));
  }

  const nodes = new vis.DataSet(nodesToShow.map(nodeSpec));
  const edges = new vis.DataSet(edgesToShow.map(e => ({ from: e.from, to: e.to })));
  visNetworkInstance.setData({ nodes, edges });
}

export async function renderMemoryGraph(focusId){
  memoryPanelEl.innerHTML = "";
  memoryPanelEl.appendChild(el("div","empty-state","Click a node to view or edit it."));
  memoryGraphSubEl.textContent = "loading…";
  const res = await apiJson("/api/memory-graph").catch(() => null);
  if (!res || !res.ok){
    memoryCanvasEl.innerHTML = "";
    memoryCanvasEl.appendChild(el("div","empty-state","Couldn't load the memory graph: " + ((res && res.error) || "server unreachable")));
    memoryGraphSubEl.textContent = "";
    return;
  }
  state.lastMemoryNodes = res.nodes;
  state.lastMemoryEdges = res.edges;
  memoryGraphSubEl.textContent = res.nodes.length + " memories, " + res.edges.length + " links";

  // Render type filter controls
  const controlsEl = document.getElementById("memoryControls");
  controlsEl.innerHTML = "";
  const group = el("div","controlgroup");
  group.appendChild(el("span","controllabel","Type:"));
  ["user", "feedback", "project", "reference"].forEach(type => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "typefilter active";
    btn.textContent = type[0].toUpperCase() + type.slice(1);
    btn.style.borderColor = MEMORY_TYPE_COLOR[type];
    btn.style.color = MEMORY_TYPE_COLOR[type];
    btn.addEventListener("click", () => {
      memoryGraphState.visibleTypes[type] = !memoryGraphState.visibleTypes[type];
      btn.classList.toggle("active");
      applyMemoryGraphFilters();
    });
    group.appendChild(btn);
  });
  const expandBtn = document.createElement("button");
  expandBtn.type = "button";
  expandBtn.textContent = memoryGraphState.focusNode ? "Show all" : "Focus mode";
  expandBtn.style.marginLeft = "auto";
  expandBtn.addEventListener("click", () => {
    if (memoryGraphState.focusNode){
      memoryGraphState.focusNode = null;
      expandBtn.textContent = "Focus mode";
    } else if (visNetworkInstance){
      const selected = visNetworkInstance.getSelectedNodes();
      if (selected.length){
        memoryGraphState.focusNode = selected[0];
        expandBtn.textContent = "Show all";
      }
    }
    applyMemoryGraphFilters();
  });
  group.appendChild(expandBtn);
  controlsEl.appendChild(group);

  const spacingGroup = el("div","controlgroup");
  spacingGroup.appendChild(el("span","controllabel","Spacing:"));
  const spacingSlider = document.createElement("input");
  spacingSlider.type = "range";
  spacingSlider.min = "100"; spacingSlider.max = "420"; spacingSlider.step = "10";
  spacingSlider.value = String(memoryGraphState.springLength);
  spacingSlider.className = "spacingslider";
  spacingSlider.addEventListener("input", () => {
    memoryGraphState.springLength = Number(spacingSlider.value);
    if (visNetworkInstance){
      visNetworkInstance.setOptions(networkOptions(memoryGraphState.springLength));
      freezeOnceStable(visNetworkInstance);
    }
  });
  spacingGroup.appendChild(spacingSlider);
  controlsEl.appendChild(spacingGroup);

  const nodes = new vis.DataSet(res.nodes.map(nodeSpec));
  const edges = new vis.DataSet(res.edges.map(e => ({ from: e.from, to: e.to })));
  if (visNetworkInstance) visNetworkInstance.destroy();
  visNetworkInstance = new vis.Network(memoryCanvasEl, { nodes, edges }, networkOptions(memoryGraphState.springLength));
  freezeOnceStable(visNetworkInstance);
  visNetworkInstance.on("click", (params) => {
    if (params.nodes.length) openMemoryPanel(params.nodes[0]);
  });
  if (focusId && res.nodes.some(n => n.id === focusId)){
    visNetworkInstance.once("afterDrawing", () => {
      visNetworkInstance.selectNodes([focusId]);
      visNetworkInstance.focus(focusId, { scale: 1.1, animation: true });
    });
    openMemoryPanel(focusId);
  }
}

async function openMemoryPanel(memoryId){
  memoryPanelEl.innerHTML = "";
  const meta = state.lastMemoryNodes.find(n => n.id === memoryId) || {};
  memoryPanelEl.appendChild(el("h3",null,memoryId));
  if (meta.type) memoryPanelEl.appendChild(el("div","memorypaneltype",meta.type));
  if (meta.description) memoryPanelEl.appendChild(el("div","memorypaneldesc",meta.description));

  // Show categories that reference this memory
  const usingCats = state.categories.filter(c => c.memories && c.memories.includes(memoryId));
  if (usingCats.length){
    memoryPanelEl.appendChild(el("div","memorypanellabel","Used by"));
    const catChips = el("div","chiprow");
    usingCats.forEach(c => {
      const chip = el("span","chip", c.name);
      chip.style.cursor = "pointer";
      chip.addEventListener("click", () => { location.hash = routeHash("#/category/" + c.id); });
      catChips.appendChild(chip);
    });
    memoryPanelEl.appendChild(catChips);
  }

  // Connected memories are shown via the graph's own edges (vis-network
  // highlights them on select) rather than parsed here — that would require
  // re-parsing this doc's body for [[wikilinks]], which the graph already did
  // server-side to build the edge list in the first place.

  const res = await apiJson("/api/memory-graph/" + encodeURIComponent(memoryId)).catch(() => null);
  if (!res || !res.ok){
    memoryPanelEl.appendChild(el("div","empty-state","Couldn't load this memory's content."));
    return;
  }

  const diagramHeader = el("div","panelsectionhead");
  diagramHeader.appendChild(el("span","memorypanellabel","Diagram"));
  const expandBtn = document.createElement("button");
  expandBtn.type = "button";
  expandBtn.className = "panelminorbtn";
  const wrapEl = memoryPanelEl.closest(".memorywrap");
  expandBtn.textContent = wrapEl.classList.contains("expanded") ? "Collapse ⤡" : "Expand ⤢";
  expandBtn.addEventListener("click", () => {
    const expanded = wrapEl.classList.toggle("expanded");
    expandBtn.textContent = expanded ? "Collapse ⤡" : "Expand ⤢";
  });
  diagramHeader.appendChild(expandBtn);
  memoryPanelEl.appendChild(diagramHeader);

  const diagramEl = el("div","memorydiagram");
  memoryPanelEl.appendChild(diagramEl);

  const genBar = el("div","memorygenbar");
  const genBtn = document.createElement("button");
  genBtn.type = "button";
  const genMsg = el("span","memorygenmsg","");
  genBar.appendChild(genBtn);
  genBar.appendChild(genMsg);
  memoryPanelEl.appendChild(genBar);

  function showDiagramFrom(body){
    const source = extractMermaidFence(body);
    genBtn.textContent = source ? "Regenerate diagram" : "Generate diagram";
    if (source){
      renderMermaidInto(diagramEl, source);
    } else {
      diagramEl.innerHTML = "";
      diagramEl.appendChild(el("div","empty-state","No diagram yet — click Generate, or write a ```mermaid fence below."));
    }
  }

  const contentHeader = el("div","panelsectionhead");
  contentHeader.appendChild(el("span","memorypanellabel","Content"));
  const viewToggleBtn = document.createElement("button");
  viewToggleBtn.type = "button";
  viewToggleBtn.className = "panelminorbtn";
  contentHeader.appendChild(viewToggleBtn);
  memoryPanelEl.appendChild(contentHeader);

  // Rendered view (headers/bullets/code/wikilinks via the same mdLite this app already uses
  // for doc content — reused here rather than syntax-highlighting inside the raw textarea,
  // which a plain <textarea> can't do) is the default; the textarea is the actual edit/save
  // surface, toggled into view on demand.
  const readView = el("div","docbody memoryreadview");
  memoryPanelEl.appendChild(readView);

  const textarea = document.createElement("textarea");
  textarea.className = "memoryedit";
  textarea.value = res.content;
  textarea.hidden = true;
  memoryPanelEl.appendChild(textarea);

  function stripFrontmatter(text){
    if (!text.startsWith("---")) return text;
    const end = text.indexOf("\n---", 3);
    return end === -1 ? text : text.slice(end + 4).replace(/^\s+/, "");
  }
  function renderReadView(){
    readView.innerHTML = mdLite(stripFrontmatter(textarea.value)) || "<p><em>(empty)</em></p>";
    readView.querySelectorAll("[data-memory-ref]").forEach(refEl => {
      refEl.addEventListener("click", () => { location.hash = routeHash("#/memory/" + encodeURIComponent(refEl.dataset.memoryRef)); });
    });
  }
  function setEditing(editing){
    textarea.hidden = !editing;
    readView.hidden = editing;
    viewToggleBtn.textContent = editing ? "View" : "Edit source";
    if (!editing) renderReadView();
  }
  setEditing(false);
  viewToggleBtn.addEventListener("click", () => setEditing(textarea.hidden));

  showDiagramFrom(textarea.value);
  // Live preview: edit the fence, watch the diagram redraw — this is what makes the diagram
  // "editable/annotatable" without a separate node-drag editor (see MEMORY_FORMAT.md).
  textarea.addEventListener("input", debounce(() => showDiagramFrom(textarea.value), 400));

  async function triggerGenerate(){
    genBtn.disabled = true;
    genMsg.textContent = "Generating…";
    try {
      const genRes = await apiJson("/api/memory-graph/" + encodeURIComponent(memoryId) + "/diagram", { method: "POST" });
      if (!genRes.ok) throw new Error(genRes.error || "failed");
      textarea.value = genRes.content;
      showDiagramFrom(textarea.value);
      if (textarea.hidden) renderReadView();
      genMsg.textContent = "Generated ✓ (saved)";
    } catch (e) {
      genMsg.textContent = "Couldn't generate: " + e.message;
    } finally {
      genBtn.disabled = false;
    }
  }
  genBtn.addEventListener("click", triggerGenerate);

  // A memory with no diagram yet drafts one automatically on first open, rather than making
  // every memory require a manual click before it shows anything — this is a one-time cost per
  // memory: once drafted, the fence is persisted in the file, so reopening the same memory
  // later finds it immediately and never re-triggers this.
  if (!extractMermaidFence(textarea.value)) triggerGenerate();

  const saveBar = el("div","memorysavebar");
  const saveBtn = document.createElement("button");
  saveBtn.type = "button";
  saveBtn.textContent = "Save";
  const saveMsg = el("span","memorysavemsg","");
  saveBar.appendChild(saveBtn);
  saveBar.appendChild(saveMsg);
  memoryPanelEl.appendChild(saveBar);

  saveBtn.addEventListener("click", async () => {
    saveBtn.disabled = true;
    saveMsg.textContent = "Saving…";
    try {
      const putRes = await apiJson("/api/memory-graph/" + encodeURIComponent(memoryId), {
        method: "PUT", body: JSON.stringify({ content: textarea.value })
      });
      if (!putRes.ok) throw new Error(putRes.error || "failed");
      saveMsg.textContent = "Saved ✓";
      // Frontmatter/links may have changed — re-render the graph, keeping this node focused.
      await renderMemoryGraph(memoryId);
    } catch (e) {
      saveMsg.textContent = "Couldn't save: " + e.message;
    } finally {
      saveBtn.disabled = false;
    }
  });
}
