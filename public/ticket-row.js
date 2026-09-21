// Shared row renderer for a ticket doc (Jira or Notion — see `source`), used
// inside each category lane's ticket list, the flat "all tickets" view, and
// search results. `jiraStatus`/`jiraPriority` are read-only mirrors of the
// tracker's own fields (named for Jira, the original source; Notion tickets
// fill the same two so every sort/filter works unchanged) — change those in
// the tracker itself and re-scan, or edit here, which pushes straight back to
// whichever tracker the ticket came from. `priority`/`team`/`categories` are
// internal-only, editable here, last-writer-wins.
import { state } from "./state.js";
import { el, jiraHref, categoryLabel, formatOpenDate } from "./dom-utils.js";
import { apiJson, touch } from "./api.js";
import { reloadBoard } from "./polling.js";
import { JIRA_PRIORITY_ORDER, JIRA_PRIORITY_COLOR } from "./lanes.js";
import { teamColor, teamForReporter } from "./people.js";
import { costBadgeText, costBadgeTitle, renderCostDetail, renderMemoryDetail } from "./badges.js";
import { buildRunningProcessBadge, attachTerminal } from "./terminal-controller.js";
import { routeHash } from "./workspaces.js";

const STATUS_SELECT_ORDER = [
  "cancelled", "canceled", "backlog", "open", "to do", "todo",
  "selected for development", "in progress",
  "waiting approval", "waiting for approval", "awaiting approval", "done",
];

function statusSelectRank(status){
  const rank = STATUS_SELECT_ORDER.indexOf((status || "").trim().toLowerCase());
  return rank < 0 ? STATUS_SELECT_ORDER.length : rank;
}

// Which tracker a ticket mirrors — drives the select option lists and the
// wording of the push-back tooltips/errors. Absent `source` = Jira, the original.
function trackerOf(data){ return data.source === "notion" ? "Notion" : "Jira"; }
function statusOptionsFor(data){ return data.source === "notion" ? state.notionStatusOptions : state.jiraStatusOptions; }
function priorityOrderFor(data){
  if (data.source !== "notion") return JIRA_PRIORITY_ORDER;
  const names = state.notionPriorityOptions.slice();
  if (data.jiraPriority && !names.includes(data.jiraPriority)) names.unshift(data.jiraPriority);
  return names;
}

function buildTopRow(data){
  const top = el("div","tickettop");
  const titleGroup = el("div","tickettitle");
  const expandBtn = document.createElement("button");
  expandBtn.type = "button";
  expandBtn.className = "rowtri";
  expandBtn.setAttribute("aria-label", "Expand ticket details");
  expandBtn.textContent = "▸";
  titleGroup.appendChild(expandBtn);

  const titleText = document.createElement("button");
  titleText.type = "button";
  titleText.className = "tickettitletext";
  titleText.textContent = (data.key || "?") + " — " + (data.summary || "");
  titleText.addEventListener("click", () => expandBtn.click());
  titleGroup.appendChild(titleText);

  const link = document.createElement("a");
  link.className = "ticketlinkicon";
  link.href = data.url || jiraHref(data.key) || "#";
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  const trackerName = trackerOf(data);
  link.title = "Open in " + trackerName;
  link.setAttribute("aria-label", "Open in " + trackerName);
  link.textContent = "↗";
  link.addEventListener("click", (e) => e.stopPropagation());
  titleGroup.appendChild(link);

  top.appendChild(titleGroup);

  const tools = el("div","tickettools");
  if (data.createdAt){
    tools.appendChild(el("span","opendate", "opened " + formatOpenDate(data.createdAt)));
  }
  top.appendChild(tools);
  return { top, expandBtn };
}

// Badges: issue-type/new flags, the running-process badge, editable
// status/priority selects (pushing straight to Jira), the cost/memory badges
// (+ their click-to-expand detail boxes), the team/reporter tags, and the
// spend indicator. All bundled in one function since several of these share
// the same `costInfo` lookup and append in a fixed sequence to the same row.
function animateTicketDeparture(row){
  if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches){
    row.hidden = true;
    return Promise.resolve();
  }
  row.classList.add("ticket-departing");
  return new Promise(resolve => {
    let settled = false;
    let fallbackTimer;
    const finish = () => {
      if (settled) return;
      settled = true;
      clearTimeout(fallbackTimer);
      row.removeEventListener("animationend", finish);
      row.hidden = true;
      resolve();
    };
    row.addEventListener("animationend", finish, {once:true});
    // Animation events can be suppressed when a tab is backgrounded.
    fallbackTimer = setTimeout(finish, 1200);
  });
}

function animateTicketDepartures(ticketKey, changedRow){
  const copies = Array.from(document.querySelectorAll(".ticketrow"))
    .filter(row => row.dataset.ticketKey === ticketKey);
  if (!copies.includes(changedRow)) copies.push(changedRow);
  return Promise.all(copies.map(animateTicketDeparture));
}

export function categoriesForAction(categories, selection){
  const [action, categoryId] = selection.split(":", 2);
  if (!categoryId) return null;
  if (action === "add") return Array.from(new Set(categories.concat(categoryId)));
  if (action === "remove") return categories.filter(cid => cid !== categoryId);
  if (action === "move") return [categoryId];
  return null;
}

export function trainFrameForStatus(status){
  const normalized = (status || "").trim().toLowerCase();
  if (normalized === "backlog" || normalized === "open" || normalized === "to do" || normalized === "todo") return 0;
  if (normalized === "selected for development") return 1;
  if (normalized === "in progress") return 2;
  if (normalized === "awaiting approval" || normalized === "waiting for approval") return 3;
  if (normalized === "done") return 4;
  return 0;
}

function setTrainStatus(icon, status){
  const frame = trainFrameForStatus(status);
  icon.dataset.frame = frame;
  if (icon.parentElement && icon.parentElement.classList.contains("statusprogress")){
    icon.parentElement.dataset.frame = frame;
  }
  icon.classList.toggle("cancelled", ["cancelled", "canceled"].includes((status || "").trim().toLowerCase()));
  icon.title = status ? "Train progress: " + status : "Train progress";
}

function buildTrainStatus(status){
  const icon = el("span", "trainstatus");
  icon.setAttribute("aria-hidden", "true");
  setTrainStatus(icon, status);
  return icon;
}

function buildStatusProgress(statusControl, trainStatus){
  const progress = el("span", "statusprogress");
  progress.dataset.frame = trainStatus.dataset.frame;
  const labelSegment = el("span", "statuslabelsegment");
  if (statusControl.tagName === "SELECT"){
    const sizer = el("span", "statuslabelsizer", statusControl.value);
    const syncWidth = () => {
      const currentWidth = labelSegment.getBoundingClientRect().width;
      sizer.textContent = statusControl.value;
      const targetWidth = sizer.getBoundingClientRect().width;
      if (!currentWidth || !targetWidth) return;
      labelSegment.style.width = currentWidth + "px";
      const nextFrame = window.requestAnimationFrame || (callback => callback());
      nextFrame(() => { labelSegment.style.width = targetWidth + "px"; });
    };
    statusControl.addEventListener("change", syncWidth);
    statusControl._syncStatusWidth = syncWidth;
    labelSegment.appendChild(sizer);
  }
  labelSegment.appendChild(statusControl);
  progress.appendChild(labelSegment);
  progress.appendChild(trainStatus);
  return progress;
}

function buildBadgeRow(data, doc, dbRef, row){
  const badges = el("div","badgerow");
  if (data.issueType && data.issueType !== "Task") badges.appendChild(el("span","badge epicbadge",data.issueType.toUpperCase()));
  if (!data.reviewed) badges.appendChild(el("span","badge new","new"));

  const bgBadge = buildRunningProcessBadge(data);
  if (bgBadge) badges.appendChild(bgBadge);

  // Sprint the ticket belongs to. Shown even when the board is already scoped
  // to one sprint, because carry-over tickets can belong to several and the
  // extra ones are exactly what you want to notice.
  if (data.sprint){
    const names = Array.isArray(data.sprintNames) ? data.sprintNames : [];
    const isActive = data.sprintState === "active";
    const chip = el("span", "badge sprintbadge" + (isActive ? " sprintactive" : ""), data.sprint);
    chip.title = (isActive ? "Active sprint" : "Sprint") +
      (names.length > 1 ? " — also in " + names.filter(n => n !== data.sprint).join(", ") : "");
    badges.appendChild(chip);
  }

  // Immediate select, same as priority below — no separate "load options"
  // click. jiraStatusOptions is fetched once at startup, not per row, since
  // every ticket in this project shares the same workflow (verified live
  // 2026-09-06). Falls back to a plain read-only badge if that fetch came
  // back empty (sync not configured, or it failed).
  const tracker = trackerOf(data);
  const statusOptions = statusOptionsFor(data);
  const trainStatus = buildTrainStatus(data.jiraStatus);
  if (statusOptions.length){
    const statusSel = document.createElement("select");
    statusSel.className = "statussel";
    const names = statusOptions.map(s => s.name);
    if (data.jiraStatus && !names.includes(data.jiraStatus)) names.unshift(data.jiraStatus);
    names.sort((a, b) => statusSelectRank(a) - statusSelectRank(b) || a.localeCompare(b));
    names.forEach(name => {
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name;
      if (data.jiraStatus === name) opt.selected = true;
      statusSel.appendChild(opt);
    });
    statusSel.title = "Status — changes push straight to " + tracker;
    statusSel.addEventListener("change", async () => {
      const newVal = statusSel.value;
      const prevVal = data.jiraStatus;
      const match = statusOptions.find(s => s.name === newVal);
      if (!match){ statusSel.value = prevVal; statusSel._syncStatusWidth?.(); return; } // shouldn't happen — only the unshifted current value lacks one
      setTrainStatus(trainStatus, newVal);
      statusSel.disabled = true;
      try {
        const res = await apiJson("/api/tickets/" + encodeURIComponent(doc.id) + "/jira-transition", {method:"POST", body: JSON.stringify({transitionId: match.id, statusName: newVal})});
        if (!res.ok) throw new Error(res.error || "failed");
        if (prevVal.toLowerCase() !== "done" && newVal.toLowerCase() === "done"){
          await animateTicketDepartures(doc.id, row);
        }
        await reloadBoard();
      } catch (e) {
        state.dom.dbStateEl.textContent = "Couldn't move " + doc.id + " to " + newVal + " in " + tracker + ": " + e.message;
        statusSel.value = prevVal;
        statusSel._syncStatusWidth?.();
        setTrainStatus(trainStatus, prevVal);
        statusSel.disabled = false;
      }
    });
    badges.prepend(buildStatusProgress(statusSel, trainStatus));
  } else {
    const statusLabel = el("span", "statuslabel", data.jiraStatus || "unknown");
    badges.prepend(buildStatusProgress(statusLabel, trainStatus));
  }

  if (data.jiraPriority){
    // Editable — Jira's priority is now the only priority (no more internal
    // P0-P3), so changing it here pushes straight to the real Jira issue via
    // PATCH /api/tickets/{key}/jira-priority (verified live 2026-09-06).
    const prioSel = document.createElement("select");
    prioSel.className = "badge priobadge prioritysel";
    priorityOrderFor(data).forEach(p => {
      const opt = document.createElement("option");
      opt.value = p;
      opt.textContent = (p === "BLOCKING" ? "⚡ " : "") + p;
      if (data.jiraPriority === p) opt.selected = true;
      prioSel.appendChild(opt);
    });
    const paintPrio = () => {
      prioSel.style.background = JIRA_PRIORITY_COLOR[prioSel.value] || "var(--ink-muted)";
      prioSel.style.color = (prioSel.value === "Medium" || prioSel.value === "Low") ? "#fff" : "#1a1a1a";
    };
    paintPrio();
    prioSel.title = "Priority — changes push straight to " + tracker;
    if (data.source === "notion" && !state.notionPriorityOptions.length) prioSel.disabled = true; // no mapped priority column to push to
    prioSel.addEventListener("change", async () => {
      const newVal = prioSel.value;
      const prevVal = data.jiraPriority;
      prioSel.disabled = true;
      try {
        const res = await apiJson("/api/tickets/" + encodeURIComponent(doc.id) + "/jira-priority", {method:"PATCH", body: JSON.stringify({priority: newVal})});
        if (!res.ok) throw new Error(res.error || "failed");
        paintPrio();
        await reloadBoard();
      } catch (e) {
        state.dom.dbStateEl.textContent = "Couldn't update " + doc.id + "'s priority in " + tracker + ": " + e.message;
        prioSel.value = prevVal;
        paintPrio();
        prioSel.disabled = false;
      }
    });
    badges.appendChild(prioSel);
  }

  // Read-only — codeburn attributes cost per session id, not per ticket, so
  // there's nothing to push a change back to. Absent whenever this ticket
  // never opened a real Claude session yet, or codeburn has no data for it
  // (as opposed to a genuine $0.00).
  const costDetailBox = el("div", "cost-details");
  for (const provider of ["claude", "codex"]){
    const costKey = provider + ":" + data.key;
    const costBadge = document.createElement("button");
    costBadge.type = "button";
    costBadge.className = "badge ro costbadge";
    const box = el("div", "detailbox");
    box.hidden = true;
    costDetailBox.appendChild(box);
    badges.appendChild(costBadge);
    const update = info => {
      costBadge.hidden = !info;
      if (!info) return;
      costBadge.textContent = costBadgeText(info);
      costBadge.title = costBadgeTitle(info);
      if (!box.hidden) renderCostDetail(box, info);
    };
    update(state.sessionCosts[costKey]);
    costBadge.addEventListener("click", () => {
      box.hidden = !box.hidden;
      update(state.sessionCosts[costKey]);
    });
    state.costBadgeEls.push({sessionId: costKey, badgeEl: costBadge, renderDetail: update});
  }

  // Same pattern as the cost badges just above, fed from GET /api/ticket-memory-usage — one
  // small badge per provider, keyed "<provider>:<ticketKey>" (hidden/absent when that provider
  // never ran on this ticket), so a ticket that's run under both Claude and Codex over its
  // lifetime shows both counts rather than one silently overwriting the other.
  const memoryDetailBox = el("div", "memory-details");
  for (const provider of ["claude", "codex"]){
    const memKey = provider + ":" + data.key;
    const memInfo = state.memoryUsage[memKey];
    if (!memInfo || !Object.keys(memInfo).length) continue;

    const memBadge = document.createElement("button");
    memBadge.type = "button";
    memBadge.className = "badge ro memorybadge";
    const memCount = Object.keys(memInfo).length;
    memBadge.textContent = "🧠 " + (provider === "codex" ? "Codex " : "Claude ") + memCount;
    memBadge.title = memCount + " memory file" + (memCount === 1 ? "" : "s") + " read during this " + provider + " session — click for the breakdown";
    badges.appendChild(memBadge);

    const box = el("div","detailbox");
    box.hidden = true;
    memoryDetailBox.appendChild(box);
    renderMemoryDetail(box, memInfo);
    memBadge.addEventListener("click", () => {
      box.hidden = !box.hidden;
      if (!box.hidden) renderMemoryDetail(box, state.memoryUsage[memKey] || memInfo);
    });

    state.memoryBadgeEls.push({
      sessionId: memKey,
      badgeEl: memBadge,
      renderDetail: (usage) => { if (!box.hidden) renderMemoryDetail(box, usage); }
    });
  }

  const team = teamForReporter(data.reporter);
  const teamBadge = el("span","badge ro", team || "Unknown");
  teamBadge.style.color = teamColor(team);
  teamBadge.style.borderColor = teamColor(team);
  teamBadge.title = "Set team in People & teams above";
  badges.appendChild(teamBadge);
  if (data.reporter){
    const reporterTag = el("span","reportertag", data.reporter);
    badges.appendChild(reporterTag);
  }

  // Spend indicator — green bar to the right, longer the more tokens consumed.
  const ticketCosts = [state.sessionCosts["claude:" + data.key], state.sessionCosts["codex:" + data.key]].filter(Boolean);
  if (ticketCosts.length){
    const totalTokens = ticketCosts.reduce((sum, info) => sum + (info.inputTokens || 0) + (info.outputTokens || 0), 0);
    const indicator = document.createElement("div");
    indicator.className = "spendindicator";
    indicator.title = totalTokens.toLocaleString() + " tokens";
    const minWidth = 20;
    const maxWidth = 150;
    const width = Math.min(maxWidth, Math.max(minWidth, Math.log(totalTokens + 1) * 10));
    indicator.style.width = width + "px";
    badges.appendChild(indicator);
  }

  return { badges, costDetailBox, memoryDetailBox };
}

function buildTagRow(data, doc, dbRef, cats){
  const tagrow = el("div","tagrow");
  (data.contentTags || []).slice(0, 3).forEach(tag => {
    const chip = el("span","tagchip contenttag", tag);
    chip.title = "Generated from the ticket's title and description during refresh";
    tagrow.appendChild(chip);
  });
  if (!(data.contentTags || []).length){
    tagrow.appendChild(el("span", "tagpending", "Content tags added on the next refresh"));
  }

  const membership = cats.length ? cats.map(categoryLabel).join(", ") : "Uncategorized";
  const categorySummary = el("span", "categorymembership", "Category: " + membership);
  categorySummary.title = "Categories control board lanes; content tags describe the ticket";
  tagrow.appendChild(categorySummary);

  if (dbRef){
    const editor = el("span", "categoryedit");
    const select = document.createElement("select");
    select.setAttribute("aria-label", "Edit categories for " + doc.id);
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = "Edit categories…";
    select.appendChild(placeholder);

    const addGroup = document.createElement("optgroup");
    addGroup.label = "Add another category";
    state.categories.filter(c => !cats.includes(c.id)).forEach(c => {
      const option = document.createElement("option");
      option.value = "add:" + c.id;
      option.textContent = "+ " + c.name;
      addGroup.appendChild(option);
    });
    if (addGroup.children.length) select.appendChild(addGroup);

    if (cats.length) {
      const removeGroup = document.createElement("optgroup");
      removeGroup.label = "Remove category";
      cats.forEach(cid => {
        const option = document.createElement("option");
        option.value = "remove:" + cid;
        option.textContent = "− " + categoryLabel(cid);
        removeGroup.appendChild(option);
      });
      select.appendChild(removeGroup);
    }

    if (state.categories.length > 1 || cats.length !== 1) {
      const moveGroup = document.createElement("optgroup");
      moveGroup.label = "Replace with one category";
      state.categories.forEach(c => {
        if (cats.length === 1 && cats[0] === c.id) return;
        const option = document.createElement("option");
        option.value = "move:" + c.id;
        option.textContent = "Only " + c.name;
        moveGroup.appendChild(option);
      });
      if (moveGroup.children.length) select.appendChild(moveGroup);
    }

    select.addEventListener("change", () => {
      const categories = categoriesForAction(cats, select.value);
      if (categories) touch(dbRef, doc.id, {categories});
      select.value = "";
    });
    editor.appendChild(select);
    tagrow.appendChild(editor);
  }
  return tagrow;
}

// Expand panel — the embedded Claude terminal (auto-starts via
// terminal-controller.js), MR link, memory-usage breakdown, then the
// activity-log/notes at the bottom. Local-app-only features a sandboxed
// Artifact page could never provide (no local process execution, no
// persistent per-ticket session history). Returns {expandPanel, termHost} —
// the caller wires termHost/expandBtn/expandPanel together via attachTerminal
// once both this and the top row exist.
function buildExpandPanel(data, doc, dbRef){
  const expandPanel = el("div","expandpanel");
  expandPanel.id = "ticket-details-" + String(doc.id).replace(/[^a-zA-Z0-9_-]/g, "-");
  expandPanel.hidden = true;

  const descriptionWrap = document.createElement("details");
  descriptionWrap.className = "descriptionwrap";
  descriptionWrap.appendChild(el("summary","reflabel","Description"));
  descriptionWrap.appendChild(el(
    "div",
    "ticketdescription",
    (data.description || "").trim() || "No description provided."
  ));
  expandPanel.appendChild(descriptionWrap);

  // Files and links found on the Notion page (image/file/PDF blocks, bookmarks,
  // and any files property). Signed Notion URLs expire, so these are links out
  // to the page's own copy rather than anything downloaded here.
  const attachments = Array.isArray(data.attachments) ? data.attachments : [];
  if (attachments.length){
    const filesWrap = document.createElement("details");
    filesWrap.className = "descriptionwrap";
    filesWrap.appendChild(el("summary","reflabel","Attachments (" + attachments.length + ")"));
    const row = el("div","ticketfiles");
    attachments.forEach(att => {
      const a = document.createElement("a");
      a.className = "ticketfile";
      a.href = att.url || "#";
      a.target = "_blank"; a.rel = "noopener noreferrer";
      a.textContent = (att.kind === "image" ? "🖼 " : att.kind === "pdf" ? "📄 " : "🔗 ") + (att.name || att.kind || "file");
      row.appendChild(a);
    });
    filesWrap.appendChild(row);
    expandPanel.appendChild(filesWrap);
  }

  // Every property the source database carried, mapped or not. This is what
  // keeps the board from being tailored to one team's column layout: whatever
  // a database tracks (sprint, story points, service, environment…) is here
  // even though the board itself has no concept of it.
  const props = data.notionProperties && typeof data.notionProperties === "object" ? data.notionProperties : null;
  if (props && Object.keys(props).length){
    const propsWrap = document.createElement("details");
    propsWrap.className = "descriptionwrap";
    propsWrap.appendChild(el("summary","reflabel","Notion fields (" + Object.keys(props).length + ")"));
    const grid = el("div","ticketprops");
    Object.keys(props).sort().forEach(name => {
      const item = el("span","ticketprop");
      item.appendChild(el("b", null, name + ": "));
      item.appendChild(document.createTextNode(String(props[name]).slice(0, 200)));
      grid.appendChild(item);
    });
    propsWrap.appendChild(grid);
    expandPanel.appendChild(propsWrap);
  }

  const termWrap = el("div","termwrap");
  const termHost = el("div","termhost");
  termWrap.appendChild(termHost);
  expandPanel.appendChild(termWrap);

  const mrWrap = el("div","mrlinkrow");
  mrWrap.appendChild(el("span","reflabel","MR link"));
  const mrInput = document.createElement("input");
  mrInput.type = "url";
  mrInput.className = "mrlinkinput";
  mrInput.placeholder = "https://gitlab.com/.../merge_requests/...";
  mrInput.value = data.mrLink || "";
  let mrPrev = mrInput.value;
  mrInput.addEventListener("blur", () => {
    if (mrInput.value !== mrPrev){ mrPrev = mrInput.value; touch(dbRef, doc.id, {mrLink: mrInput.value.trim()}); }
  });
  mrWrap.appendChild(mrInput);
  if (data.mrLink){
    const mrOpen = document.createElement("a");
    mrOpen.href = data.mrLink; mrOpen.target = "_blank"; mrOpen.rel = "noopener noreferrer";
    mrOpen.className = "copybtn"; mrOpen.textContent = "Open MR";
    mrWrap.appendChild(mrOpen);
  }
  expandPanel.appendChild(mrWrap);

  for (const provider of ["claude", "codex"]){
    const usage = state.memoryUsage[provider + ":" + data.key];
    if (!usage || !Object.keys(usage).length) continue;
    const memUsageWrap = el("div","memoryusagewrap");
    memUsageWrap.appendChild(el("span","reflabel","Memory accessed (" + (provider === "codex" ? "Codex" : "Claude") + ")"));
    const memList = el("div","memoryusagelist");
    const sortedMems = Object.keys(usage).sort((a, b) => usage[b] - usage[a]);
    sortedMems.forEach(memId => {
      const line = el("div","memoryusageline");
      const name = el("span","memoryusagename",memId);
      name.style.cursor = "pointer";
      name.addEventListener("click", () => { location.hash = routeHash("#/memory/" + encodeURIComponent(memId)); });
      const count = el("span","memoryusagecount", usage[memId] + "×");
      line.appendChild(name);
      line.appendChild(count);
      memList.appendChild(line);
    });
    memUsageWrap.appendChild(memList);
    expandPanel.appendChild(memUsageWrap);
  }

  const notesWrap = el("div","noteswrap");
  notesWrap.appendChild(el("span","reflabel","Activity log"));
  const notesList = el("div","noteslist");
  (data.notes || []).forEach(n => {
    const line = el("div","noteline");
    line.appendChild(el("span","notetime", n.at));
    line.appendChild(el("span","notetext", n.text));
    notesList.appendChild(line);
  });
  if (!(data.notes || []).length) notesList.appendChild(el("span","empty","No activity yet."));
  notesWrap.appendChild(notesList);
  const noteForm = document.createElement("form");
  noteForm.className = "noteform";
  const noteInput = document.createElement("input");
  noteInput.type = "text"; noteInput.placeholder = "Add a note…"; noteInput.maxLength = 500;
  const noteBtn = document.createElement("button");
  noteBtn.type = "submit"; noteBtn.textContent = "Add";
  noteForm.appendChild(noteInput); noteForm.appendChild(noteBtn);
  noteForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = noteInput.value.trim();
    if (!text) return;
    noteInput.value = "";
    await apiJson("/api/tickets/" + encodeURIComponent(doc.id) + "/notes", {method:"POST", body: JSON.stringify({text})});
    await reloadBoard();
  });
  notesWrap.appendChild(noteForm);
  expandPanel.appendChild(notesWrap);

  return { expandPanel, termHost };
}

export function renderTicketRow(doc, dbRef){
  const data = doc.data() || {};
  const cats = Array.isArray(data.categories) ? data.categories : [];
  const row = el("div","ticketrow");
  row.dataset.ticketKey = doc.id;
  const subjectCategory = cats[0] && state.categories.find(c => c.id === cats[0]);
  if (subjectCategory && subjectCategory.color) row.style.setProperty("--subject", subjectCategory.color);

  const { top, expandBtn } = buildTopRow(data);
  row.appendChild(top);

  const { badges, costDetailBox, memoryDetailBox } = buildBadgeRow(data, doc, dbRef, row);
  row.appendChild(badges);
  if (costDetailBox) row.appendChild(costDetailBox);
  if (memoryDetailBox) row.appendChild(memoryDetailBox);

  row.appendChild(buildTagRow(data, doc, dbRef, cats));

  const { expandPanel, termHost } = buildExpandPanel(data, doc, dbRef);
  attachTerminal(termHost, expandBtn, expandPanel, doc, data);
  row.appendChild(expandPanel);

  return row;
}
