// Shared, cross-module mutable board state. A single exported object, not bare
// `let` exports — ES module imports are read-only live *views*, so a module that
// only imports a `let` binding can't assign to it, only the declaring module can.
// Several of these are legitimately mutated from many different modules (e.g.
// runningProcesses from the 60s reload, the 15s poll, AND a ticket row's kill
// button), so mutating properties of one shared object is what actually works.
export const state = {
  // Which workspace the board is showing — see public/workspaces.js. This is
  // the slug as it appears in the route, so "" means a BARE route, i.e. the
  // default workspace: on a one-workspace install it is always "" and apiJson
  // sends no `?w=` at all. `workspaces`/`defaultWorkspace` come from
  // GET /api/workspaces once at init (and again after creating one); an empty
  // `workspaces` list renders no picker and no workspace chrome whatsoever.
  workspaceSlug: "",
  workspaces: [],
  defaultWorkspace: "",

  // Populated once at init() from GET /api/categories (server/content.py) — empty
  // (renders no lanes) until that resolves.
  categories: [],

  // Populated once at init() from GET /api/config. jiraHref() returns null (no
  // link) until this resolves, and forever if Jira isn't configured.
  jiraBaseUrl: "",

  // Fetched once at init() from GET /api/jira-statuses — empty if sync isn't
  // configured, or the fetch failed. A ticket row falls back to a read-only badge.
  jiraStatusOptions: [],

  // Same, for tickets whose `source` is "notion" — from GET /api/notion/options,
  // i.e. the mapped status/priority columns' option lists of the configured
  // database. Priorities is a plain array of names (Notion has no fixed scheme
  // like Jira's Highest…Lowest).
  notionStatusOptions: [],
  notionPriorityOptions: [],
  notionDoneStatuses: [],

  // Sprints known to the tracker, active first then newest first, from GET
  // /api/notion/options. Each is the tracker-independent contract shape
  // {id, name, state: "active"|"future"|"closed", start, end, url, rawStatus}
  // — `state` is what the board keys off; `rawStatus` is only ever displayed.
  // Empty on a board with no sprint column at all, which hides the selector
  // entirely rather than showing an empty control.
  sprints: [],

  // Which sprint the board is scoped to: "" = all, "current" = whichever
  // sprint(s) the tracker says are active now, "none" = tickets in no sprint,
  // or a literal sprint name. Per-viewer, so it lives in localStorage like the
  // other display preferences. Defaults to the active sprint the first time
  // a board has one, since mirroring your tracker's sprint view is the point;
  // renderSprintOptions falls back to "" when nothing is active.
  sprintFilter: localStorage.getItem("wmp.sprintFilter") ?? "current",

  // Per-ticket cost/memory-usage, keyed by claudeSessionId — refetched on every
  // reloadBoard() and by the lighter poll while a terminal is open (see polling.js).
  sessionCosts: {},
  memoryUsage: {},

  // Every rendered cost/memory badge registers itself here (cleared + rebuilt at
  // the top of every renderTickets() call) so the live poll can patch already-
  // mounted DOM in place instead of re-rendering rows.
  costBadgeEls: [],
  memoryBadgeEls: [],

  // Ticket keys with a background Claude process running — from GET /api/running-processes.
  runningProcesses: new Set(),

  // How many embedded terminals are currently live. reloadBoard() and the
  // running-process poll both skip their own re-render while this is > 0, since a
  // re-render would tear down any open terminal's DOM/WebSocket along with it.
  liveTerminalCount: 0,

  // Bumped on every workspace switch. Board data is fetched asynchronously, so
  // a slow response issued for the workspace you just left would otherwise
  // render over the one you just switched to — the counter is what lets a
  // reload notice it is stale and drop its result.
  boardGeneration: 0,

  // The terminal panels currently holding a live WebSocket. Needed because
  // switching workspace rebuilds the whole board and has to let go of them
  // deliberately — see detachAllTerminals(). The agent processes themselves
  // are NOT killed by this; the server only forgets a process once it has
  // actually exited, so they keep running and reconnect when you come back.
  openTerminals: new Set(),

  // "All tickets" flat view + per-lane sort mode are per-viewer display
  // preferences (localStorage), not shared server state.
  viewMode: localStorage.getItem("wmp.viewMode") === "flat" ? "flat" : "grouped",
  flatSortMode: ["status", "priority", "date"].includes(localStorage.getItem("wmp.flatSort")) ? localStorage.getItem("wmp.flatSort") : "date",

  // Multi-select team filter — see filters.js's syncSelectedTeams for why both of
  // these exist (null selectedTeams = not yet initialized).
  selectedTeams: null,
  knownTeamNames: new Set(),
  // Multi-select status filter — same pattern, see filters.js's syncSelectedStatuses.
  selectedStatuses: null,
  knownStatusNames: new Set(),
  filterPerson: "",
  filterInProgress: false,

  // Team roster + person->team map — real data from data/db.json.
  teamOptions: [],
  peopleMap: {},

  // The "current board snapshot" — set once per renderTickets() call, read by
  // nearly every other render/filter function.
  lastTicketDocs: [],
  lastDbRef: null,

  // The old Artifact's `db` capability equivalent — set once in init().
  dbCapability: null,

  // The real memory corpus as a graph. Shared here (rather than kept private to
  // whatever renders the graph) so a category detail page's "related memories"
  // table can read it without depending on the memory-graph page having already
  // rendered once first — that was a real bug in the pre-split code.
  lastMemoryNodes: [],
  lastMemoryEdges: [],

  // Bootstrap-owned DOM refs written to directly from several modules (a failed
  // status/priority push, reloadBoard's success/failure message, the refresh
  // button) — same direct-manipulation pattern the pre-split code already used,
  // just centralized here instead of being a bare top-level const only one
  // script's own top-level code could see.
  dom: { dbStateEl: null },
};
