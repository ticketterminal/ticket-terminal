// Settings page: editable categories, Jira + Notion connections, and the memory-source
// directory — all editable from the running app instead of hand-edited JSON/
// .env files. See server/settings_store.py for the precedence rule (a
// Settings-page save wins over the corresponding env var, applied immediately,
// no restart needed).
import { categoryRevision, renderCategoryManagement, refreshCategoryManagement } from "./category-management.js";
import { state } from "./state.js";
import { el } from "./dom-utils.js";
import { apiJson } from "./api.js";
import { reloadBoard } from "./polling.js";
import { buildCategoryUI, renderTickets } from "./lanes.js";
import { renderWorkspacesForm } from "./workspaces.js";

const catListEl = document.getElementById("settingsCategoriesList");
const catCountEl = document.getElementById("settingsCatCount");
const catMsgEl = document.getElementById("settingsCategoriesMsg");
const addCategoryBtn = document.getElementById("settingsAddCategoryBtn");
const saveCategoriesBtn = document.getElementById("settingsSaveCategoriesBtn");
const jiraFormEl = document.getElementById("settingsJiraForm");
const notionFormEl = document.getElementById("settingsNotionForm");
const memoryFormEl = document.getElementById("settingsMemoryForm");

const STATUS_OPTIONS = ["covered", "partial", "gap"];

// Local working copy — edits only apply to the live board (state.categories)
// once "Save categories" is clicked, so adding/editing several rows doesn't
// touch the real board mid-edit.
let draftCategories = [];
let editorRevision = "";

function showMsg(el, text, kind){
  el.textContent = text;
  el.className = "settingsmsg" + (kind ? " " + kind : "");
}

function toCsv(arr){ return (arr || []).join(", "); }
function fromCsv(text){ return text.split(",").map(s => s.trim()).filter(Boolean); }

function buildCategoryRow(cat, index){
  const row = el("div","categoryeditrow");

  const fields = el("div","categoryeditfields");
  const moveGroup = document.createElement("span");
  moveGroup.className = "lanemovegroup";
  const upBtn = document.createElement("button");
  upBtn.type = "button"; upBtn.className = "lanemove"; upBtn.textContent = "▲";
  upBtn.disabled = index === 0;
  upBtn.addEventListener("click", () => {
    [draftCategories[index-1], draftCategories[index]] = [draftCategories[index], draftCategories[index-1]];
    renderCategoriesEditor();
  });
  const downBtn = document.createElement("button");
  downBtn.type = "button"; downBtn.className = "lanemove"; downBtn.textContent = "▼";
  downBtn.disabled = index === draftCategories.length - 1;
  downBtn.addEventListener("click", () => {
    [draftCategories[index+1], draftCategories[index]] = [draftCategories[index], draftCategories[index+1]];
    renderCategoriesEditor();
  });
  moveGroup.appendChild(upBtn); moveGroup.appendChild(downBtn);
  fields.appendChild(moveGroup);

  const idInput = document.createElement("input");
  idInput.dataset.field = "id"; idInput.placeholder = "id (e.g. access-provisioning)"; idInput.value = cat.id || "";
  idInput.readOnly = state.categories.some(c => c.id === cat.id);
  idInput.title = idInput.readOnly ? "Stable ID — edit the display name to rename this category" : "Lowercase words separated by hyphens";
  idInput.addEventListener("input", () => { cat.id = idInput.value; });
  fields.appendChild(idInput);

  const nameInput = document.createElement("input");
  nameInput.dataset.field = "name"; nameInput.placeholder = "Display name"; nameInput.value = cat.name || "";
  nameInput.addEventListener("input", () => { cat.name = nameInput.value; });
  fields.appendChild(nameInput);

  const statusSel = document.createElement("select");
  STATUS_OPTIONS.forEach(s => {
    const opt = document.createElement("option");
    opt.value = s; opt.textContent = s;
    if ((cat.status || "gap") === s) opt.selected = true;
    statusSel.appendChild(opt);
  });
  statusSel.addEventListener("change", () => { cat.status = statusSel.value; });
  fields.appendChild(statusSel);

  const colorInput = document.createElement("input");
  colorInput.type = "color"; colorInput.value = cat.color || "#4E79A7";
  colorInput.title = "Lane accent color";
  colorInput.addEventListener("input", () => { cat.color = colorInput.value; });
  fields.appendChild(colorInput);

  const noteInput = document.createElement("input");
  noteInput.dataset.field = "note"; noteInput.placeholder = "Short note shown on the tile"; noteInput.value = cat.note || "";
  noteInput.addEventListener("input", () => { cat.note = noteInput.value; });
  fields.appendChild(noteInput);

  const deleteBtn = document.createElement("button");
  deleteBtn.type = "button"; deleteBtn.className = "copybtn categoryeditdelete"; deleteBtn.textContent = "Delete";
  deleteBtn.addEventListener("click", () => {
    if (!confirm("Remove category '" + (cat.name || cat.id) + "'? Its tickets become uncategorized when saved. History can restore their assignments.")) return;
    draftCategories.splice(index, 1);
    renderCategoriesEditor();
  });
  fields.appendChild(deleteBtn);
  row.appendChild(fields);

  const listFields = el("div","categoryeditlistfields");
  [["memories","Memory ids"], ["skills","Skill ids"], ["docs","Doc ids"]].forEach(([key, label]) => {
    const wrap = document.createElement("label");
    wrap.appendChild(document.createTextNode(label));
    const input = document.createElement("input");
    input.value = toCsv(cat[key]);
    input.placeholder = "comma-separated";
    input.addEventListener("input", () => { cat[key] = fromCsv(input.value); });
    wrap.appendChild(input);
    listFields.appendChild(wrap);
  });
  row.appendChild(listFields);

  return row;
}

function renderCategoriesEditor(){
  catListEl.innerHTML = "";
  if (draftCategories.length === 0){
    catListEl.appendChild(el("span","empty","No categories yet — add one below."));
  }
  draftCategories.forEach((cat, i) => catListEl.appendChild(buildCategoryRow(cat, i)));
  catCountEl.textContent = draftCategories.length + (draftCategories.length === 1 ? " category" : " categories");
  showMsg(catMsgEl, "", "");
}

async function saveCategories(){
  if (state.liveTerminalCount > 0){ showMsg(catMsgEl, "Reload the page to detach terminals before changing categories. Background sessions remain available.", "err"); return; }
  saveCategoriesBtn.disabled = true;
  showMsg(catMsgEl, "Saving…", "");
  try {
    const res = await apiJson("/api/categories?revision=" + encodeURIComponent(editorRevision), {method:"PUT", body: JSON.stringify(draftCategories)});
    if (!res.ok) throw new Error(res.error || "save failed");
    state.categories = res.categories;
    draftCategories = res.categories.map(c => ({...c}));
    buildCategoryUI(); // idempotent — clears + rebuilds the live board's lanes/cards
    await reloadBoard();
    renderCategoriesEditor();
    showMsg(catMsgEl, "Saved ✓ — board updated. Previous version saved in category history.", "ok");
    const manager = await refreshCategoryManagement();
    editorRevision = manager.revision;
    renderCategoryManagement();
  } catch (e) {
    showMsg(catMsgEl, "Couldn't save: " + e.message, "err");
  } finally {
    saveCategoriesBtn.disabled = false;
  }
}

function buildSettingsRow(labelText, inputEl){
  const row = el("div","settingsrow");
  const label = document.createElement("label");
  label.textContent = labelText;
  row.appendChild(label);
  row.appendChild(inputEl);
  return row;
}

async function renderJiraForm(){
  jiraFormEl.innerHTML = "Loading…";
  const settings = await apiJson("/api/settings").catch(() => null);
  jiraFormEl.innerHTML = "";
  if (!settings){
    jiraFormEl.appendChild(el("div","empty-state","Couldn't load current settings — is the server running?"));
    return;
  }

  const baseUrlInput = document.createElement("input");
  baseUrlInput.type = "url"; baseUrlInput.placeholder = "https://your-domain.atlassian.net";
  baseUrlInput.value = settings.jira.baseUrl || "";
  jiraFormEl.appendChild(buildSettingsRow("Base URL", baseUrlInput));

  const emailInput = document.createElement("input");
  emailInput.type = "email"; emailInput.placeholder = "you@example.com";
  emailInput.value = settings.jira.email || "";
  jiraFormEl.appendChild(buildSettingsRow("Email", emailInput));

  const tokenInput = document.createElement("input");
  tokenInput.type = "password";
  tokenInput.placeholder = settings.jira.apiTokenSet ? ("Currently set (" + settings.jira.apiTokenPreview + ") — leave blank to keep") : "Paste a token from id.atlassian.com";
  jiraFormEl.appendChild(buildSettingsRow("API Token", tokenInput));

  const projectInput = document.createElement("input");
  projectInput.placeholder = "PROJ";
  projectInput.value = settings.jira.projectKey || "";
  jiraFormEl.appendChild(buildSettingsRow("Project key", projectInput));

  const hint = el("div","settingshint","Generate a token at id.atlassian.com/manage-profile/security/api-tokens. Values here override .env immediately — no restart.");
  jiraFormEl.appendChild(hint);

  const actions = el("div","settingsactions");
  const saveBtn = document.createElement("button");
  saveBtn.type = "button"; saveBtn.className = "refreshbtn"; saveBtn.textContent = "Save Jira settings";
  const testBtn = document.createElement("button");
  testBtn.type = "button"; testBtn.className = "copybtn"; testBtn.textContent = "Test connection";
  const msg = el("span","settingsmsg","");
  actions.appendChild(saveBtn); actions.appendChild(testBtn); actions.appendChild(msg);
  jiraFormEl.appendChild(actions);

  saveBtn.addEventListener("click", async () => {
    saveBtn.disabled = true;
    showMsg(msg, "Saving…", "");
    try {
      await apiJson("/api/settings", {method:"PUT", body: JSON.stringify({
        jira: { baseUrl: baseUrlInput.value.trim(), email: emailInput.value.trim(), apiToken: tokenInput.value, projectKey: projectInput.value.trim() }
      })});
      showMsg(msg, "Saved ✓", "ok");
      await renderJiraForm(); // re-fetch so the token preview reflects what's actually stored
    } catch (e) {
      showMsg(msg, "Couldn't save: " + e.message, "err");
    } finally {
      saveBtn.disabled = false;
    }
  });

  testBtn.addEventListener("click", async () => {
    testBtn.disabled = true;
    showMsg(msg, "Testing…", "");
    try {
      const res = await apiJson("/api/sync-jira", {method:"POST"});
      if (res.ok) showMsg(msg, "Connected ✓ — checked " + (res.checked || 0) + " ticket" + (res.checked === 1 ? "" : "s") + ".", "ok");
      else showMsg(msg, "Failed: " + res.error, "err");
    } catch (e) {
      showMsg(msg, "Failed: " + e.message, "err");
    } finally {
      testBtn.disabled = false;
    }
  });
}

async function renderMemoryForm(){
  memoryFormEl.innerHTML = "Loading…";
  const settings = await apiJson("/api/settings").catch(() => null);
  memoryFormEl.innerHTML = "";
  if (!settings){
    memoryFormEl.appendChild(el("div","empty-state","Couldn't load current settings — is the server running?"));
    return;
  }

  const sourceLabel = { settings: "set on this page", env: "from WMP_MEMORY_DIR", default: "derived default (no override set)" }[settings.memoryDirSource] || settings.memoryDirSource;
  const dirInput = document.createElement("input");
  dirInput.placeholder = "/path/to/your/memory/folder";
  dirInput.value = settings.memoryDirSource === "settings" ? settings.memoryDir : "";
  memoryFormEl.appendChild(buildSettingsRow("Memory folder path", dirInput));
  memoryFormEl.appendChild(el("div","settingshint","Currently reading from: " + settings.memoryDir + " (" + sourceLabel + "). Leave blank here to keep using that."));

  const explain = el("div","settingsexplain");
  explain.innerHTML =
    "<strong>What memory is:</strong> a folder of <code>.md</code> files — this app's own " +
    "knowledge base, not something tied to Claude. It defaults to reusing Claude Code's own " +
    "per-project memory location for convenience, but any folder works, and any LLM vendor's " +
    "agent (Claude, Codex, a future local model) can read or write it. The graph and the " +
    "category detail pages read every file in it. Each file may start with YAML frontmatter " +
    "(optional, but gives it a friendly name/description/type):<br><br>" +
    "<code>---<br>name: my-memory-id<br>description: one-line summary shown in the graph<br>" +
    "metadata:<br>&nbsp;&nbsp;type: user | feedback | project | reference<br>---</code><br><br>" +
    "The body can link to other memory files with <code>[[other-file-id]]</code> — those become " +
    "edges in the graph — and may include a <code>```mermaid</code> fenced block, rendered and " +
    "editable as a diagram in the memory graph panel. Files named <code>MEMORY.md</code> or " +
    "<code>README.md</code> are treated as index pages and skipped, not shown as nodes. Full " +
    "spec: <code>MEMORY_FORMAT.md</code> at the repo root.";
  memoryFormEl.appendChild(explain);

  const actions = el("div","settingsactions");
  const saveBtn = document.createElement("button");
  saveBtn.type = "button"; saveBtn.className = "refreshbtn"; saveBtn.textContent = "Save memory source";
  const msg = el("span","settingsmsg","");
  actions.appendChild(saveBtn); actions.appendChild(msg);
  memoryFormEl.appendChild(actions);

  saveBtn.addEventListener("click", async () => {
    saveBtn.disabled = true;
    showMsg(msg, "Saving…", "");
    try {
      await apiJson("/api/settings", {method:"PUT", body: JSON.stringify({ memoryDir: dirInput.value.trim() })});
      showMsg(msg, "Saved ✓", "ok");
      await renderMemoryForm();
    } catch (e) {
      showMsg(msg, "Couldn't save: " + e.message, "err");
    } finally {
      saveBtn.disabled = false;
    }
  });
}

// Notion: a personal (internal-integration) token pasted directly is the
// primary path — nothing to register publicly. OAuth against a public
// integration the user registers themselves is the advanced fold (client
// id/secret saved here, then "Connect with Notion" bounces through
// GET /api/notion/oauth/start → Notion consent → /api/notion/oauth/callback →
// back to #/settings). Then a database picker + which columns play
// status/priority. See server/notion_sync.py.
export async function renderNotionForm(){
  notionFormEl.innerHTML = "Loading…";
  const settings = await apiJson("/api/settings").catch(() => null);
  notionFormEl.innerHTML = "";
  if (!settings || !settings.notion){
    notionFormEl.appendChild(el("div","empty-state","Couldn't load current settings — is the server running?"));
    return;
  }
  const n = settings.notion;

  // --- connection status -------------------------------------------------
  const status = el("div","settingshint");
  if (n.connected){
    status.textContent = "Connected" + (n.workspaceName ? " to workspace “" + n.workspaceName + "”" : "") +
      (n.authMode === "oauth" ? " via OAuth" : n.authMode === "token" ? " via personal integration token" : "") +
      (n.accessTokenPreview ? " (" + n.accessTokenPreview + ")" : "") + ".";
    status.className = "settingsmsg ok";
  } else {
    status.textContent = "Not connected.";
  }
  notionFormEl.appendChild(status);
  if (n.lastOauthError){
    notionFormEl.appendChild(el("div","settingsmsg err","Last connection attempt failed: " + n.lastOauthError));
  }

  // --- personal token (the recommended path) ------------------------------
  // An *internal* integration: created in the user's own workspace, visible
  // only there, no OAuth app registration. Share the tickets database with it
  // from Notion's ··· → Connections menu and paste its secret here.
  notionFormEl.appendChild(el("div","reflabel","Personal integration token (recommended)"));
  const tokenInput = document.createElement("input");
  tokenInput.type = "password"; tokenInput.placeholder = n.connected && n.authMode === "token" ? ("Currently set (" + n.accessTokenPreview + ") — paste a new one to replace") : "ntn_… (Internal integration → Configuration → Internal Integration Secret)";
  notionFormEl.appendChild(buildSettingsRow("Integration secret", tokenInput));
  notionFormEl.appendChild(el("div","settingshint",
    "At notion.so/my-integrations create an integration for your workspace (leave it Internal — nobody outside the workspace can see or use it), copy its Internal Integration Secret here, " +
    "then in Notion open your tickets database → ··· → Connections → add that integration so it can read the pages."));
  const tokenActions = el("div","settingsactions");
  const tokenBtn = document.createElement("button");
  tokenBtn.type = "button"; tokenBtn.className = "refreshbtn"; tokenBtn.textContent = "Connect with token";
  const disconnectBtn = document.createElement("button");
  disconnectBtn.type = "button"; disconnectBtn.className = "copybtn"; disconnectBtn.textContent = "Disconnect";
  disconnectBtn.hidden = !n.connected;
  const tokenMsg = el("span","settingsmsg","");
  tokenActions.appendChild(tokenBtn); tokenActions.appendChild(disconnectBtn); tokenActions.appendChild(tokenMsg);
  notionFormEl.appendChild(tokenActions);
  tokenBtn.addEventListener("click", async () => {
    tokenBtn.disabled = true;
    showMsg(tokenMsg, "Checking the token against Notion…", "");
    try {
      const res = await apiJson("/api/notion/token", {method:"POST", body: JSON.stringify({ token: tokenInput.value })});
      if (!res.ok) throw new Error(res.error || "rejected");
      await renderNotionForm();
    } catch (e) {
      showMsg(tokenMsg, "Failed: " + e.message, "err");
      tokenBtn.disabled = false;
    }
  });
  disconnectBtn.addEventListener("click", async () => {
    if (!confirm("Disconnect Notion? Already-imported tickets stay on the board; syncing and status/priority pushes stop until you reconnect.")) return;
    await apiJson("/api/notion/disconnect", {method:"POST"});
    await renderNotionForm();
  });

  // --- advanced: OAuth against a public integration --------------------------
  // Only worth it if this board is being handed to people in other workspaces;
  // folded shut unless it's already in use so the token path stays the obvious one.
  const oauthFold = document.createElement("details");
  oauthFold.className = "settingsfold";
  oauthFold.open = Boolean(n.clientId) || n.authMode === "oauth";
  const oauthSummary = document.createElement("summary");
  oauthSummary.textContent = "Advanced: OAuth with a public integration";
  oauthFold.appendChild(oauthSummary);
  notionFormEl.appendChild(oauthFold);

  oauthFold.appendChild(el("div","settingshint",
    "Requires registering the integration as Public in Notion (company name, website, privacy policy) so it can be authorized into other workspaces via a Notion login screen. " +
    "It isn't listed anywhere, but anyone holding the client ID can authorize it into their own workspace. For a board only you use, the token above is simpler."));

  const clientIdInput = document.createElement("input");
  clientIdInput.placeholder = "OAuth client ID"; clientIdInput.value = n.clientId || "";
  oauthFold.appendChild(buildSettingsRow("Client ID", clientIdInput));

  const clientSecretInput = document.createElement("input");
  clientSecretInput.type = "password";
  clientSecretInput.placeholder = n.clientSecretSet ? ("Currently set (" + n.clientSecretPreview + ") — leave blank to keep") : "OAuth client secret";
  oauthFold.appendChild(buildSettingsRow("Client secret", clientSecretInput));

  const redirectInput = document.createElement("input");
  redirectInput.type = "url"; redirectInput.value = n.redirectUri || "";
  redirectInput.placeholder = "http://localhost:4173/api/notion/oauth/callback";
  oauthFold.appendChild(buildSettingsRow("Redirect URI (add this exact value to the integration's allowed redirect URIs)", redirectInput));

  const oauthActions = el("div","settingsactions");
  const saveAppBtn = document.createElement("button");
  saveAppBtn.type = "button"; saveAppBtn.className = "copybtn"; saveAppBtn.textContent = "Save OAuth app settings";
  const connectBtn = document.createElement("a");
  connectBtn.className = "refreshbtn"; connectBtn.textContent = n.connected && n.authMode === "oauth" ? "Reconnect with Notion" : "Connect with Notion";
  connectBtn.href = "/api/notion/oauth/start";
  const appMsg = el("span","settingsmsg","");
  oauthActions.appendChild(saveAppBtn); oauthActions.appendChild(connectBtn); oauthActions.appendChild(appMsg);
  oauthFold.appendChild(oauthActions);

  saveAppBtn.addEventListener("click", async () => {
    saveAppBtn.disabled = true;
    showMsg(appMsg, "Saving…", "");
    try {
      await apiJson("/api/settings", {method:"PUT", body: JSON.stringify({
        notion: { clientId: clientIdInput.value.trim(), clientSecret: clientSecretInput.value, redirectUri: redirectInput.value.trim() }
      })});
      showMsg(appMsg, "Saved ✓ — now click Connect with Notion", "ok");
      await renderNotionForm();
    } catch (e) {
      showMsg(appMsg, "Couldn't save: " + e.message, "err");
    } finally {
      saveAppBtn.disabled = false;
    }
  });
  connectBtn.addEventListener("click", (event) => {
    // Unsaved id/secret edits would be lost across the redirect — save first, then go.
    if (clientIdInput.value.trim() !== (n.clientId || "") || clientSecretInput.value || redirectInput.value.trim() !== (n.redirectUri || "")){
      event.preventDefault();
      saveAppBtn.click();
      showMsg(appMsg, "Saved — click Connect again", "ok");
    }
  });

  if (!n.connected) return;

  // --- database + field mapping (only meaningful once connected) ----------
  // The board needs a few ROLES (title, status, description…) but must not
  // assume a database names or shapes them any particular way — so every role
  // is bound here explicitly, from the real property list of the chosen
  // database. Auto-detection only pre-fills; it never decides silently.
  notionFormEl.appendChild(el("div","reflabel","Ticket source"));
  const dbSel = document.createElement("select");
  const dbManual = document.createElement("input");
  dbManual.placeholder = "…or paste a database ID / URL"; dbManual.value = n.databaseId || "";
  const dbRow = buildSettingsRow("Database", dbSel);
  dbRow.appendChild(dbManual);
  notionFormEl.appendChild(dbRow);

  const mapHint = el("div","settingshint","Only databases shared with the integration appear here.");
  notionFormEl.appendChild(mapHint);
  const roleWrap = el("div","rolemap");
  notionFormEl.appendChild(roleWrap);

  const mapActions = el("div","settingsactions");
  const saveMapBtn = document.createElement("button");
  saveMapBtn.type = "button"; saveMapBtn.className = "refreshbtn"; saveMapBtn.textContent = "Save mapping";
  const testBtn = document.createElement("button");
  testBtn.type = "button"; testBtn.className = "copybtn"; testBtn.textContent = "Sync now";
  const mapMsg = el("span","settingsmsg","");
  mapActions.appendChild(saveMapBtn); mapActions.appendChild(testBtn); mapActions.appendChild(mapMsg);
  notionFormEl.appendChild(mapActions);

  const ROLE_LABEL = {
    title: "Title", key: "Ticket ID", status: "Status", priority: "Priority",
    assignee: "Assignee", description: "Description", due: "Due date",
    sprint: "Sprint", epic: "Epic / parent", labels: "Labels",
  };
  const ROLE_NOTE = {
    description: "Combined with the page body, which is always read.",
    status: "Drives the board's status column and which tickets count as done.",
    key: "Used as the ticket key; falls back to the page id when unset.",
  };
  // Which role selections are currently on screen — read on save.
  let roleSelects = {};

  dbSel.addEventListener("change", () => {
    if (!dbSel.value) return;
    dbManual.value = dbSel.value;
    // The column list belongs to the SAVED database, so a different pick makes
    // the on-screen mapping stale. Blank it and say so rather than letting
    // "Save mapping" write one database's field names against another's id.
    roleWrap.innerHTML = "";
    roleSelects = {};
    roleWrap.appendChild(el("div","settingshint","Save this database first, then its fields can be mapped below."));
  });

  function renderRoleMap(res){
    roleWrap.innerHTML = "";
    roleSelects = {};
    const props = res.properties || [];
    const roles = res.roles || {};
    (res.roleOrder || []).forEach(role => {
      const info = roles[role] || {};
      const allowed = (res.roleTypes || {})[role] || [];
      const fitting = props.filter(p => allowed.includes(p.type));
      const sel = document.createElement("select");
      const auto = document.createElement("option");
      auto.value = ""; auto.textContent = fitting.length ? "Auto-detect" : "No matching property in this database";
      sel.appendChild(auto);
      const off = document.createElement("option");
      off.value = "-"; off.textContent = "Don't use";
      sel.appendChild(off);
      fitting.forEach(p => {
        const o = document.createElement("option");
        o.value = p.name; o.textContent = p.name + "  (" + p.type + ")";
        sel.appendChild(o);
      });
      if (info.source === "configured" && info.name) sel.value = info.name;
      else if (info.source === "disabled") sel.value = "-";
      else sel.value = "";
      roleSelects[role] = sel;

      const row = buildSettingsRow(ROLE_LABEL[role] || role, sel);
      const status = el("span", "rolestate");
      if (info.problem){ status.textContent = "⚠ " + info.problem; status.classList.add("err"); }
      else if (info.source === "configured") status.textContent = "you chose “" + info.name + "”";
      else if (info.source === "suggested") status.textContent = "auto-detected “" + info.name + "” (" + info.type + ")";
      // "discovered" is the sprint role's shape-based detection — it looked at
      // the database's relations and what they point at, not just at names, so
      // it carries its own reasons (shown below the row).
      else if (info.source === "discovered") status.textContent = "discovered “" + info.name + "” (" + info.type + ")";
      else if (info.source === "disabled") status.textContent = "off";
      else status.textContent = fitting.length ? "not mapped — nothing matched by name" : "not available";
      row.appendChild(status);
      if (ROLE_NOTE[role]) row.appendChild(el("span","settingshint", ROLE_NOTE[role]));
      roleWrap.appendChild(row);
      // Sprints are the one role the board can't read straight off the
      // property: a relation to a companion database only says WHICH sprints a
      // ticket is in, never which of them is running. Everything that answers
      // that question hangs off this row. Only for a relation — the
      // select/date-range sprint shapes aren't supported yet.
      if (role === "sprint" && info.type === "relation") roleWrap.appendChild(buildSprintPanel(res, info));
    });
    roleWrap.appendChild(el("div","settingshint",
      "Every other property on the database is imported with the ticket regardless of mapping, and shown on the ticket — mapping only decides what the board sorts, filters and writes back."));
  }

  // The sprint row's extras: why this relation was picked, which status value
  // means "running", and what the server currently makes of the sprint list.
  function buildSprintPanel(res, info){
    const panel = el("div","sprintmarker");

    if (info.source === "discovered"){
      const why = (info.why || []).filter(Boolean);
      const target = info.target ? " → “" + info.target + "”" : "";
      panel.appendChild(el("div","settingshint",
        "Found by looking at the database's relations" + target + (why.length ? ": " + why.join("; ") : ".")));
    }

    const marker = res.sprintMarker || {};
    const options = Array.isArray(marker.options) ? marker.options : [];
    let note;
    if (marker.source === "confirmed") note = "Confirmed";
    else if (marker.source === "inferred" && marker.inferredFrom) note = "Detected from “" + marker.inferredFrom + "”, whose dates cover today";
    else if (!marker.hasStatusProperty) note = "Dates only — no status column";
    else note = "Not set — sprint dates alone decide which sprint is active";

    // Ask nothing when there's nothing to ask about: no status column on the
    // sprints database means there is no value to pick, and the dates already
    // answer the question on their own.
    if (marker.hasStatusProperty || options.length || marker.value){
      const row = el("div","sprintmarkerrow");
      row.appendChild(el("label", null, "Active sprint marker"));
      const sel = document.createElement("select");
      const blank = document.createElement("option");
      blank.value = ""; blank.textContent = "(use dates only)";
      if (!marker.value) blank.selected = true;
      sel.appendChild(blank);
      const names = options.slice();
      // A stored marker whose option has since been renamed away must still be
      // visible and re-selectable, not silently swapped for "(use dates only)".
      if (marker.value && !names.includes(marker.value)) names.push(marker.value);
      names.forEach(name => {
        const o = document.createElement("option");
        o.value = name; o.textContent = name;
        if (name === marker.value) o.selected = true;
        sel.appendChild(o);
      });
      row.appendChild(sel);

      const confirmBtn = document.createElement("button");
      confirmBtn.type = "button"; confirmBtn.className = "copybtn"; confirmBtn.textContent = "Confirm marker";
      confirmBtn.addEventListener("click", async () => {
        confirmBtn.disabled = true;
        showMsg(mapMsg, "Saving…", "");
        try {
          await apiJson("/api/settings", {method:"PUT", body: JSON.stringify({ notion: { sprintActiveMarker: sel.value } })});
          const fresh = await apiJson("/api/notion/options");
          if (fresh && fresh.ok){
            state.sprints = fresh.sprints || [];
            showMsg(mapMsg, "Active sprint marker saved ✓", "ok");
            // Re-render (every sprint's state may have just changed) but keep the
            // user's unsaved choices in the OTHER role selects — confirming a
            // marker must not silently revert edits made a moment earlier.
            const keep = {};
            Object.keys(roleSelects).forEach(role => { if (role !== "sprint") keep[role] = roleSelects[role].value; });
            renderRoleMap(fresh);
            Object.keys(keep).forEach(role => {
              const sel = roleSelects[role];
              if (sel) Array.from(sel.options).forEach(o => { o.selected = o.value === keep[role]; });
            });
          } else {
            showMsg(mapMsg, "Saved, but the sprint list couldn't be re-read: " + ((fresh && fresh.error) || "unknown error"), "err");
            confirmBtn.disabled = false;
          }
        } catch (e) {
          showMsg(mapMsg, "Couldn't save the marker: " + e.message, "err");
          confirmBtn.disabled = false;
        }
      });
      row.appendChild(confirmBtn);
      row.appendChild(el("span","rolestate", note));
      panel.appendChild(row);
    } else {
      panel.appendChild(el("div","rolestate", note));
    }

    const sprints = Array.isArray(res.sprints) ? res.sprints : [];
    const count = s => sprints.filter(x => x.state === s).length;
    panel.appendChild(el("div","settingshint",
      sprints.length + " sprint" + (sprints.length === 1 ? "" : "s") +
      " · " + count("active") + " active · " + count("future") + " future · " + count("closed") + " closed"));
    return panel;
  }

  const dbOpt0 = document.createElement("option"); dbOpt0.value = ""; dbOpt0.textContent = "Loading databases…"; dbSel.appendChild(dbOpt0);
  apiJson("/api/notion/databases").then(res => {
    dbSel.innerHTML = "";
    const none = document.createElement("option"); none.value = ""; none.textContent = res.ok ? "— pick a database —" : ("Couldn't list databases: " + res.error);
    dbSel.appendChild(none);
    (res.databases || []).forEach(d => {
      const o = document.createElement("option"); o.value = d.id; o.textContent = d.title;
      if ((n.databaseId || "").replace(/-/g,"") === d.id.replace(/-/g,"")) o.selected = true;
      dbSel.appendChild(o);
    });
  }).catch(() => {});

  if (n.databaseId){
    roleWrap.appendChild(el("div","settingshint","Reading this database's fields…"));
    apiJson("/api/notion/options").then(res => {
      if (!res.ok){ roleWrap.innerHTML = ""; showMsg(mapMsg, "Couldn't read the database: " + res.error, "err"); return; }
      mapHint.textContent = "“" + (res.databaseTitle || "database") + "” — " + (res.properties || []).length + " properties.";
      renderRoleMap(res);
    }).catch(error => {
      // Never silently blank the mapping table — an empty panel with no
      // explanation is indistinguishable from "this database has no fields".
      roleWrap.innerHTML = "";
      roleWrap.appendChild(el("div","settingsmsg err","Couldn't show the field mapping: " + (error && error.message ? error.message : error)));
    });
  }

  saveMapBtn.addEventListener("click", async () => {
    saveMapBtn.disabled = true;
    showMsg(mapMsg, "Saving…", "");
    const roles = {};
    Object.keys(roleSelects).forEach(role => { if (roleSelects[role].value) roles[role] = roleSelects[role].value; });
    try {
      await apiJson("/api/settings", {method:"PUT", body: JSON.stringify({
        notion: { databaseId: dbManual.value.trim(), roles }
      })});
      showMsg(mapMsg, "Saved ✓", "ok");
      await renderNotionForm();
    } catch (e) {
      showMsg(mapMsg, "Couldn't save: " + e.message, "err");
      saveMapBtn.disabled = false;
    }
  });
  testBtn.addEventListener("click", async () => {
    testBtn.disabled = true;
    showMsg(mapMsg, "Syncing… a first import of a large database takes a while.", "");
    try {
      const res = await apiJson("/api/sync-notion", {method:"POST"});
      if (!res.ok){ showMsg(mapMsg, "Failed: " + res.error, "err"); return; }
      if (Array.isArray(res.sprints)) state.sprints = res.sprints;   // the board's selector, refreshed by the same sync
      const bits = ["checked " + (res.checked || 0) + " page" + (res.checked === 1 ? "" : "s"),
                    (res.added || []).length + " new"];
      if ((res.categorized || []).length) bits.push((res.categorized).length + " categorized");
      if (res.truncated) bits.push("⚠ stopped at the page limit — not all rows were read");
      if (res.categoryError) bits.push("categories failed: " + res.categoryError);
      if (res.tagError) bits.push("tags failed: " + res.tagError);
      showMsg(mapMsg, bits.join(" · "), res.truncated || res.categoryError || res.tagError ? "err" : "ok");
      await reloadBoard();
    } catch (e) {
      showMsg(mapMsg, "Failed: " + e.message, "err");
    } finally {
      testBtn.disabled = false;
    }
  });
}


export async function renderSettingsPage(){
  renderCategoryManagement();
  try {
    const manager = await refreshCategoryManagement();
    draftCategories = structuredClone(manager.categories);
    editorRevision = manager.revision;
  } catch (error) {
    draftCategories = structuredClone(state.categories);
    editorRevision = "";
  }
  renderCategoriesEditor();
  renderWorkspacesForm();
  renderJiraForm();
  renderNotionForm();
  renderMemoryForm();
}

export function wireSettingsUI(){
  window.addEventListener("categories-updated", () => { draftCategories = state.categories.map(c => structuredClone(c)); editorRevision = categoryRevision(); renderCategoriesEditor(); });
  addCategoryBtn.addEventListener("click", () => {
    draftCategories.push({ id: "", name: "", status: "gap", color: "#4E79A7", note: "", memories: [], skills: [], docs: [] });
    renderCategoriesEditor();
  });
  saveCategoriesBtn.addEventListener("click", saveCategories);
}
