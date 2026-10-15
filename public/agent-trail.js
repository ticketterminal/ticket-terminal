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

function resourceChip(resource){
  const clickable = resource.type === "memory";
  const chip = document.createElement(clickable ? "button" : "span");
  if (clickable) chip.type = "button";
  chip.className = "agenttrail-resource " + (resource.type || "file");
  const prefix = resource.type === "memory" ? "Memory · " : resource.type === "skill" ? "Skill · " : "File · ";
  chip.textContent = prefix + resource.label;
  chip.title = resource.path || resource.label;
  if (clickable) chip.addEventListener("click", () => {
    location.hash = routeHash("#/memory/" + encodeURIComponent(resource.id));
  });
  return chip;
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
    if (event.resource) body.appendChild(resourceChip(event.resource));
    item.appendChild(body);
    list.appendChild(item);
  });
  host.appendChild(list);
  host.scrollTop = host.scrollHeight;
}

function flowStage(event){
  const kind = event.kind || "tool";
  const detail = (event.detail || "").toLowerCase();
  if (["read","search","web"].includes(kind)) return ["investigate","Investigate"];
  if (["memory","skill"].includes(kind)) return ["knowledge","Use knowledge"];
  if (kind === "write") return ["change","Make changes"];
  if (kind === "integration") return ["coordinate","Coordinate"];
  if (kind === "command"){
    if (/\b(test|pytest|unittest|npm test|cargo test|go test|lint|typecheck|compile|build)\b/.test(detail)) return ["verify","Verify"];
    if (/\b(git (commit|push)|gh pr|glab mr)\b/.test(detail)) return ["deliver","Deliver"];
    if (/login|auth/.test(detail)) return ["access","Get access"];
    if (/\bgit (status|diff|log|show)\b/.test(detail)) return ["investigate","Inspect changes"];
  }
  return ["operate","Run tooling"];
}

export function summarizeManager(events, ticket={}){
  const counts = {};
  const flow = [];
  const objects = new Map();
  const knowledge = new Map();
  events.forEach(event => {
    counts[event.kind] = (counts[event.kind] || 0) + 1;
    const [id,label] = flowStage(event);
    const detail = event.title || event.detail || "Agent action";
    const previous = flow[flow.length - 1];
    if (previous && previous.id === id){ previous.count++; previous.detail = detail; }
    else flow.push({id,label,detail,count:1});
    const resources = event.resources || (event.resource ? [event.resource] : []);
    resources.forEach(resource => {
      const identity = resource.path || resource.id || resource.label;
      if (!identity) return;
      if (event.kind === "write") objects.set(identity, {
        type:resource.type || "file",label:resource.label || identity,path:resource.path || "",action:resource.action || "change",
      });
      if (["memory","skill"].includes(resource.type)) knowledge.set(identity, resource);
    });
  });
  const subject = ticket.summary || ticket.key || "this ticket";
  const why = (ticket.description || subject).split("\n\n",1)[0].trim();
  const facts = [];
  if (objects.size) facts.push("Changed " + objects.size + " named object" + (objects.size === 1 ? "" : "s"));
  else if (counts.write) facts.push("Made " + counts.write + " change action" + (counts.write === 1 ? "" : "s") + "; paths were not exposed");
  if (counts.command) facts.push("Ran " + counts.command + " command" + (counts.command === 1 ? "" : "s"));
  const refs = (counts.memory || 0) + (counts.skill || 0);
  if (refs) facts.push("Used " + refs + " memory/skill reference" + (refs === 1 ? "" : "s"));
  const flowLabels = flow.map(step => step.label.toLowerCase());
  const approach = flowLabels.length
    ? "The agent " + flowLabels.map((label,index) => (index === 0 ? "began by " : index === flowLabels.length - 1 ? "then finished by " : "then ") + label).join(", ") + "."
    : "No implementation narrative has been recorded yet.";
  return {
    headline:events.length ? "Work recorded toward “" + subject + "”." : "No recorded work yet.",
    why, facts, actionCount:events.length, flow:flow.slice(-10), objects:[...objects.values()], knowledge:[...knowledge.values()],
    story:{request:why,rationale:why,approach,outcome:facts.length ? facts.join(". ") + "." : "No outcome has been recorded yet."},
  };
}

export function renderManagerSummary(host, summary){
  host.replaceChildren();
  summary = summary || {};
  const wrap = el("div", "managersummary");
  const story = summary.story || {
    request:summary.why || "The ticket does not include a request.",
    rationale:summary.why || "No rationale has been recorded yet.",
    approach:"The recorded flow below shows how the work was carried out.",
    outcome:summary.headline || "No outcome has been recorded yet.",
  };
  const narrative = el("article", "managerstory");
  [
    ["The request",story.request],
    ["Why this approach",story.rationale],
    ["How it was carried out",story.approach],
    ["Outcome",story.outcome],
  ].forEach(([label,copy]) => {
    const section = el("section", "managerstory-section");
    section.appendChild(el("span", "managersummary-label", label));
    section.appendChild(el("p", null, copy));
    narrative.appendChild(section);
  });
  wrap.appendChild(narrative);

  const facts = Array.isArray(summary.facts) ? summary.facts : [];
  if (facts.length){
    const factRow = el("div", "managersummary-facts");
    facts.forEach(fact => factRow.appendChild(el("span", null, fact)));
    wrap.appendChild(factRow);
  }

  const flow = Array.isArray(summary.flow) ? summary.flow : [];
  const flowSection = el("section", "managersummary-section");
  flowSection.appendChild(el("span", "managersummary-label", "Flow"));
  if (!flow.length) flowSection.appendChild(el("div", "managersummary-empty", "The action flow will appear once the agent starts using tools."));
  else {
    const flowGraph = el("div", "managerflow");
    flow.forEach((phase, index) => {
      const node = el("div", "managerflow-node managerflow-" + phase.id);
      node.appendChild(el("span", "managerflow-index", String(index + 1)));
      const copy = el("span", "managerflow-copy");
      copy.appendChild(el("strong", null, phase.label));
      copy.appendChild(el("small", null, phase.detail + (phase.count > 1 ? " · " + phase.count + " actions" : "")));
      node.appendChild(copy);
      flowGraph.appendChild(node);
    });
    flowSection.appendChild(flowGraph);
  }
  wrap.appendChild(flowSection);

  const objects = Array.isArray(summary.objects) ? summary.objects : [];
  const objectsSection = el("section", "managersummary-section");
  objectsSection.appendChild(el("span", "managersummary-label", "Objects changed"));
  if (!objects.length) objectsSection.appendChild(el("div", "managersummary-empty", "No named changed objects are present in the recorded actions."));
  else {
    const grid = el("div", "managerobjects");
    objects.forEach(object => {
      const item = el("div", "managerobject");
      item.appendChild(el("span", "managerobject-action " + object.action, object.action || "change"));
      const copy = el("span", "managerobject-copy");
      copy.appendChild(el("strong", null, object.label));
      if (object.path && object.path !== object.label) copy.appendChild(el("code", null, object.path));
      item.appendChild(copy);
      grid.appendChild(item);
    });
    objectsSection.appendChild(grid);
  }
  wrap.appendChild(objectsSection);

  const knowledge = Array.isArray(summary.knowledge) ? summary.knowledge : [];
  if (knowledge.length){
    const knowledgeSection = el("section", "managersummary-section");
    knowledgeSection.appendChild(el("span", "managersummary-label", "Knowledge used"));
    const chips = el("div", "managerknowledge");
    knowledge.forEach(resource => chips.appendChild(resourceChip(resource)));
    knowledgeSection.appendChild(chips);
    wrap.appendChild(knowledgeSection);
  }

  host.appendChild(wrap);
}

export function createAgentTrailView(key, provider, ticket={}){
  const shell = el("div", "agentterminal");
  const terminal = el("div", "termhost agentterminal-pane");
  const trail = el("aside", "agenttrail");
  trail.id = "agent-trail-" + provider + "-" + String(key).replace(/[^a-zA-Z0-9_-]/g, "-");
  trail.hidden = true;
  const heading = el("div", "agenttrail-head");
  const headingTitle = el("strong", null, "Agent trail");
  heading.appendChild(headingTitle);
  heading.appendChild(el("span", null, provider === "codex" ? "Codex" : "Claude"));
  const feed = el("div", "agenttrail-feed");
  const summaryFeed = el("div", "agenttrail-feed managersummary-feed");
  summaryFeed.hidden = true;
  trail.appendChild(heading);
  trail.appendChild(feed);
  trail.appendChild(summaryFeed);
  shell.appendChild(terminal);
  shell.appendChild(trail);

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "refreshbtn agenttrail-toggle";
  toggle.textContent = "◫ Agent trail";
  toggle.setAttribute("aria-pressed", "false");
  toggle.setAttribute("aria-controls", trail.id);

  const summaryToggle = document.createElement("button");
  summaryToggle.type = "button";
  summaryToggle.className = "refreshbtn agenttrail-toggle managersummary-toggle";
  summaryToggle.textContent = "▤ Manager summary";
  summaryToggle.setAttribute("aria-pressed", "false");
  summaryToggle.setAttribute("aria-controls", trail.id);

  let timer = null;
  let disposed = false;
  let requestNumber = 0;
  let lastSignature = null;
  let mode = "trail";
  async function refresh(){
    const ownRequest = ++requestNumber;
    try {
      const response = await apiJson("/api/agent-activity/" + encodeURIComponent(key) + "?provider=" + encodeURIComponent(provider));
      const events = response.events || [];
      const summary = response.summary || summarizeManager(events, ticket);
      const signature = JSON.stringify([events.map(event => [event.id, event.kind, event.title, event.detail]), summary]);
      if (!disposed && ownRequest === requestNumber && signature !== lastSignature){
        lastSignature = signature;
        renderAgentTrail(feed, events);
        renderManagerSummary(summaryFeed, summary);
      }
    } catch (error) {
      if (!disposed && ownRequest === requestNumber) feed.replaceChildren(el("div", "agenttrail-empty", "Couldn't load the activity history."));
    }
  }
  function paintMode(){
    const summaryMode = mode === "summary";
    feed.hidden = summaryMode;
    summaryFeed.hidden = !summaryMode;
    headingTitle.textContent = summaryMode ? "Manager summary" : "Agent trail";
    toggle.setAttribute("aria-pressed", String(!trail.hidden && !summaryMode));
    summaryToggle.setAttribute("aria-pressed", String(!trail.hidden && summaryMode));
    toggle.textContent = !trail.hidden && !summaryMode ? "▣ Hide agent trail" : "◫ Agent trail";
    summaryToggle.textContent = !trail.hidden && summaryMode ? "▥ Hide manager summary" : "▤ Manager summary";
  }
  function setOpen(open, nextMode="trail"){
    mode = nextMode;
    trail.hidden = !open;
    shell.classList.toggle("agenttrail-open", open);
    paintMode();
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
  function selectMode(nextMode){
    const isAlreadyOpen = !trail.hidden && mode === nextMode;
    setOpen(!isAlreadyOpen, nextMode);
  }
  function activate(){
    disposed = false;
    if (!trail.hidden){
      refresh();
      clearInterval(timer);
      timer = setInterval(refresh, 1500);
    }
  }
  toggle.addEventListener("click", () => selectMode("trail"));
  summaryToggle.addEventListener("click", () => selectMode("summary"));
  shell.disposeAgentTrail = () => {
    disposed = true;
    clearInterval(timer);
    timer = null;
  };
  shell.disposeTicketTerminal = () => {
    shell.disposeAgentTrail();
    terminal.disposeTicketTerminal?.();
  };
  return { shell, terminal, trail, feed, summaryFeed, toggle, summaryToggle, refresh, setOpen, activate };
}
