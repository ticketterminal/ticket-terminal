import { apiJson } from "./api.js";
import { el } from "./dom-utils.js";
import { routeHash } from "./workspaces.js";

const ICONS = {
  command: "›_", memory: "◇", skill: "✦", read: "↗", write: "✎",
  search: "⌕", web: "◎", integration: "⌁", tool: "·",
};

function timeLabel(value){
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleTimeString([], {hour:"2-digit", minute:"2-digit", second:"2-digit"});
}

export function renderAgentTrail(host, events){
  host.replaceChildren();
  if (!events.length){
    host.appendChild(el("div", "agenttrail-empty", "Actions will appear here when the agent uses a tool, command, memory, or skill."));
    return;
  }
  const list = el("div", "agenttrail-list");
  events.forEach(event => {
    const item = el("article", "agenttrail-item agenttrail-" + (event.kind || "tool"));
    item.appendChild(el("span", "agenttrail-icon", ICONS[event.kind] || ICONS.tool));
    const body = el("div", "agenttrail-event");
    const head = el("div", "agenttrail-eventhead");
    head.appendChild(el("strong", null, event.title || "Agent action"));
    const when = timeLabel(event.timestamp);
    if (when) head.appendChild(el("time", null, when));
    body.appendChild(head);
    if (event.detail) body.appendChild(el("code", "agenttrail-detail", event.detail));
    if (event.resource){
      const chip = document.createElement(event.resource.type === "memory" ? "button" : "span");
      if (chip.tagName === "BUTTON") chip.type = "button";
      chip.className = "agenttrail-resource " + event.resource.type;
      chip.textContent = (event.resource.type === "memory" ? "Memory · " : event.resource.type === "skill" ? "Skill · " : "File · ") + event.resource.label;
      chip.title = event.resource.path || event.resource.label;
      if (event.resource.type === "memory") chip.addEventListener("click", () => {
        location.hash = routeHash("#/memory/" + encodeURIComponent(event.resource.id));
      });
      body.appendChild(chip);
    }
    item.appendChild(body);
    list.appendChild(item);
  });
  host.appendChild(list);
  host.scrollTop = host.scrollHeight;
}

export function createAgentTrailView(key, provider){
  const shell = el("div", "agentterminal");
  const terminal = el("div", "termhost agentterminal-pane");
  const trail = el("aside", "agenttrail");
  trail.id = "agent-trail-" + provider + "-" + String(key).replace(/[^a-zA-Z0-9_-]/g, "-");
  trail.hidden = true;
  const heading = el("div", "agenttrail-head");
  heading.appendChild(el("strong", null, "Agent trail"));
  heading.appendChild(el("span", null, provider === "codex" ? "Codex" : "Claude"));
  const feed = el("div", "agenttrail-feed");
  trail.appendChild(heading);
  trail.appendChild(feed);
  shell.appendChild(terminal);
  shell.appendChild(trail);

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "refreshbtn agenttrail-toggle";
  toggle.textContent = "◫ Agent trail";
  toggle.setAttribute("aria-pressed", "false");
  toggle.setAttribute("aria-controls", trail.id);

  let timer = null;
  let disposed = false;
  let requestNumber = 0;
  let lastSignature = null;
  async function refresh(){
    const ownRequest = ++requestNumber;
    try {
      const response = await apiJson("/api/agent-activity/" + encodeURIComponent(key) + "?provider=" + encodeURIComponent(provider));
      const events = response.events || [];
      const signature = JSON.stringify(events.map(event => [event.id, event.kind, event.title, event.detail]));
      if (!disposed && ownRequest === requestNumber && signature !== lastSignature){
        lastSignature = signature;
        renderAgentTrail(feed, events);
      }
    } catch (error) {
      if (!disposed && ownRequest === requestNumber) feed.replaceChildren(el("div", "agenttrail-empty", "Couldn't load the activity history."));
    }
  }
  function setOpen(open){
    trail.hidden = !open;
    shell.classList.toggle("agenttrail-open", open);
    toggle.setAttribute("aria-pressed", String(open));
    toggle.textContent = open ? "▣ Hide agent trail" : "◫ Agent trail";
    clearInterval(timer);
    timer = null;
    if (open){
      refresh();
      timer = setInterval(refresh, 1500);
    }
    const notifyResize = () => window.dispatchEvent(new Event("resize"));
    if (window.requestAnimationFrame) window.requestAnimationFrame(notifyResize);
    else notifyResize();
  }
  function activate(){
    disposed = false;
    if (!trail.hidden){
      refresh();
      clearInterval(timer);
      timer = setInterval(refresh, 1500);
    }
  }
  toggle.addEventListener("click", () => setOpen(trail.hidden));
  shell.disposeAgentTrail = () => {
    disposed = true;
    clearInterval(timer);
    timer = null;
  };
  shell.disposeTicketTerminal = () => {
    shell.disposeAgentTrail();
    terminal.disposeTicketTerminal?.();
  };
  return { shell, terminal, trail, feed, toggle, refresh, setOpen, activate };
}
