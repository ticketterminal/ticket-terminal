import { apiJson } from "./api.js";
import { el } from "./dom-utils.js";

function normalize(value, fallbackSource="manual"){
  const raw = typeof value === "string" ? {url:value,source:fallbackSource} : (value || {});
  let parsed;
  try { parsed = new URL(raw.url); } catch (error) { return null; }
  const path = parsed.pathname.replace(/\/$/, "");
  let match = path.match(/^\/(.+?)\/pull\/(\d+)(?:\/.*)?$/);
  let provider = "github";
  if (!match){
    match = path.match(/^\/(.+?)\/(?:-\/)?merge_requests\/(\d+)(?:\/.*)?$/);
    provider = "gitlab";
  }
  if (!match) return null;
  return {
    url: parsed.origin + path,
    provider,
    repository: raw.repository || match[1].replace(/\.git$/, ""),
    number: Number(match[2]),
    source: raw.source || fallbackSource,
    discoveredAt: raw.discoveredAt || raw.timestamp || "",
  };
}

export function mergeChangeRequests(...groups){
  const byUrl = new Map();
  groups.flat().forEach(value => {
    const item = normalize(value, "transcript");
    if (item) byUrl.set(item.url, item);
  });
  return [...byUrl.values()].sort((a,b) => (a.discoveredAt || "").localeCompare(b.discoveredAt || "") || a.url.localeCompare(b.url));
}

function labelFor(item){
  const repo = (item.repository || "repository").split("/").pop();
  return repo + (item.provider === "gitlab" ? " !" : " #") + item.number;
}

export function createChangeRequestView(key, data, {compact=false}={}){
  const shell = el("section", "changerequests" + (compact ? " changerequests-compact" : ""));
  if (!compact) shell.appendChild(el("span", "reflabel", "Pull / merge requests"));
  const list = el("div", "changerequest-list");
  shell.appendChild(list);

  let items = mergeChangeRequests(
    Array.isArray(data.changeRequests) ? data.changeRequests : [],
    data.mrLink ? [{url:data.mrLink, source:"legacy-manual"}] : []
  );
  let timer = null;
  let disposed = false;

  function render(){
    list.replaceChildren();
    if (!items.length) list.appendChild(el("span", "empty changerequest-empty", "No PR or MR discovered yet."));
    items.forEach(item => {
      const chip = el("span", "changerequest-chip " + item.provider);
      const link = document.createElement("a");
      link.href = item.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = labelFor(item) + " ↗";
      link.title = item.url + (item.source === "manual" || item.source === "legacy-manual" ? " — added manually" : " — discovered from agent history");
      chip.appendChild(link);
      if (item.source === "manual" || item.source === "legacy-manual"){
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "changerequest-remove";
        remove.setAttribute("aria-label", "Remove " + labelFor(item));
        remove.textContent = "×";
        remove.addEventListener("click", async () => {
          const next = items.filter(candidate => candidate.url !== item.url);
          await apiJson("/api/tickets/" + encodeURIComponent(key), {
            method:"PATCH",
            body:JSON.stringify({changeRequests:next, mrLink:data.mrLink === item.url ? "" : (data.mrLink || "")}),
          });
          data.changeRequests = next;
          if (data.mrLink === item.url) data.mrLink = "";
          items = next;
          render();
        });
        chip.appendChild(remove);
      }
      list.appendChild(chip);
    });
  }

  if (!data.isDemo){
    const form = document.createElement("form");
    form.className = "changerequest-form";
    const input = document.createElement("input");
    input.type = "url";
    input.placeholder = "Paste GitHub PR or GitLab MR URL…";
    input.setAttribute("aria-label", "Pull or merge request URL");
    const add = document.createElement("button");
    add.type = "submit";
    add.textContent = "Add link";
    form.appendChild(input);
    form.appendChild(add);
    form.addEventListener("submit", async event => {
      event.preventDefault();
      const item = normalize({url:input.value.trim(), source:"manual", discoveredAt:new Date().toISOString()});
      if (!item){
        input.setCustomValidity?.("Enter a GitHub pull-request or GitLab merge-request URL.");
        input.reportValidity?.();
        return;
      }
      input.setCustomValidity?.("");
      const next = mergeChangeRequests(items, [item]);
      add.disabled = true;
      try {
        await apiJson("/api/tickets/" + encodeURIComponent(key), {method:"PATCH", body:JSON.stringify({changeRequests:next})});
        data.changeRequests = next;
        items = next;
        input.value = "";
        render();
      } finally { add.disabled = false; }
    });
    input.addEventListener("input", () => input.setCustomValidity?.(""));
    shell.appendChild(form);
  }

  async function refresh(){
    if (data.isDemo) return;
    try {
      const response = await apiJson("/api/tickets/" + encodeURIComponent(key) + "/change-requests/refresh", {method:"POST"});
      if (!disposed && response.ok){
        items = mergeChangeRequests(response.changeRequests || []);
        data.changeRequests = items;
        render();
      }
    } catch (error) { /* a later poll retries; keep the last-known links visible */ }
  }
  function start(){
    if (data.isDemo) return;
    disposed = false;
    refresh();
    clearInterval(timer);
    timer = setInterval(() => {
      if (!shell.isConnected){ clearInterval(timer); timer = null; return; }
      refresh();
    }, 4000);
  }
  function stop(){ clearInterval(timer); timer = null; }
  function dispose(){ disposed = true; stop(); }

  render();
  return {shell, refresh, start, stop, dispose, get items(){ return items; }};
}
