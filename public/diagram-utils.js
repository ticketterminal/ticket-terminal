// Shared Mermaid plumbing for both diagram surfaces: a single memory's own diagram (a
// ```mermaid fence in its body — see memory-graph.js, MEMORY_FORMAT.md) and a category's
// overarching diagram (its own generated field — see detail-view.js). Kept in one place so
// CDN init and render/error handling aren't copy-pasted across the two features.
import { el } from "./dom-utils.js";

let mermaidInitialized = false;
let mermaidRenderSeq = 0;

export function ensureMermaidInit(){
  if (mermaidInitialized || typeof mermaid === "undefined") return;
  mermaid.initialize({ startOnLoad: false, theme: window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "default" });
  mermaidInitialized = true;
}

export function extractMermaidFence(body){
  const m = /```mermaid\n([\s\S]*?)```/.exec(body || "");
  return m ? m[1].trim() : null;
}

export async function renderMermaidInto(container, source){
  ensureMermaidInit();
  if (typeof mermaid === "undefined"){
    container.innerHTML = "";
    container.appendChild(el("div","diagramerror","Mermaid failed to load — check your network connection."));
    return;
  }
  try {
    const { svg } = await mermaid.render("diagram-" + (mermaidRenderSeq++), source);
    container.innerHTML = svg;
  } catch (e) {
    container.innerHTML = "";
    container.appendChild(el("div","diagramerror","Diagram syntax error: " + e.message));
  }
}
