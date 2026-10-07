# Ticket Terminal — handoff document

Written for: an LLM coding agent (Codex, a new Claude Code session, etc.) picking up
development on this repo with no prior context. Everything below was verified
against the actual code as of 2026-10-07 (including the status board and agent
activity/trail work after PR #48) — not derived from memory
or from the README alone. Where the real code disagrees with the README or with
in-code comments, that's called out explicitly so you don't propagate the stale
version.

## 1. What this is

**Ticket Terminal** syncs tickets from Jira and/or Notion into a single Kanban-style
board, and can open a real `claude` or `codex` CLI terminal session per ticket —
a genuine PTY process on this machine, not a sandbox or a transcript replay.
Categories double as a searchable knowledge-base index (SKILL.md/CLAUDE.md/memory
docs per category). There's also a shared "memory graph" (markdown notes under
`~/.claude/projects/<cwd>/memory/`, the same convention Claude Code itself uses)
and a cost/usage insights dashboard.

Single local user, `127.0.0.1`-only by default, no auth layer — the network
boundary *is* the security boundary. Keep that framing in mind before adding
anything that assumes multi-user or remote access.

## 2. Stack and repo layout

- **Backend:** FastAPI + plain `requests` calls to Jira/Notion. No ORM, no real
  database — `server/db.py` is a lock-guarded JSON file with atomic tmp-then-replace
  writes. Python deps: `requirements.in` (5 direct deps) compiled to a hash-pinned
  `requirements.txt` via `uv pip compile`. **There is no `pyproject.toml`** — don't
  go looking for one or assume `uv.lock`/PEP 621 project structure.
- **Frontend:** vanilla JS ES modules under `public/`, zero npm dependencies, zero
  build step. Three runtime libraries (xterm, vis-network, mermaid) load from
  jsDelivr CDN `<script>` tags in `index.html`. The only `package.json` in the repo
  is `tests/ui/package.json` (one dev dependency: `linkedom`, for DOM-less JS tests).
- **Data:** `data/workspaces/<slug>/*.json` per workspace (a workspace = one board,
  one tracker connection). `data/workspaces.json` at the root is the install-wide
  registry of which workspaces exist.
- Run locally: `uv venv && uv pip install --require-hashes -r requirements.txt && source .venv/bin/activate && python server/main.py`,
  serves on `127.0.0.1:4173`. Docker is the other supported path (`docker compose up`) —
  see §8.

```
server/        FastAPI app + all Python modules (24 files, see §4)
public/        ES-module frontend (25 .js files + index.html + styles.css, see §5)
tests/         Python unittest suite (19 files, 241 tests)
tests/ui/      DOM-less JS tests (7 .mjs files via linkedom, ~300 assertions)
data/          Per-workspace JSON state (gitignored except *.example.json)
docs/          Static marketing page, deployed to Cloudflare Pages (unrelated to the app itself)
```

## 3. Request lifecycle, in one pass

1. Browser loads `/` → `public/index.html` → classic scripts (xterm, xterm-addon-fit,
   vis-network, mermaid CDN globals, then `terminal.js`) → `<script type="module" src="/static/board.js">`.
2. `board.js` is the only bootstrap entrypoint. Exact order matters:
   `initWorkspaceFromRoute()` (must run before any fetch adds `?w=`) → wire up
   filters/people/router/settings/categories/workspaces/help UIs → wire the
   Refresh button and the 60s poll → `init()`: set `state.dbCapability` →
   `loadWorkspaces()` → `loadWorkspaceBoard(renderRoute)` → fire-and-forget
   `syncIfStale()` if on a non-default workspace.
3. `WorkspaceMiddleware` (raw ASGI middleware in `main.py`) pins the `?w=` query
   param as the active workspace for the whole request/WebSocket via a
   `contextvars.ContextVar` (see `server/workspaces.py`). Every path-resolving
   function (`db.db_path()`, `content.data_dir()`, `settings_store.settings_path()`,
   etc.) is a **function**, resolved per-call through this ContextVar — never a
   module-level constant. If you add a new per-workspace file, follow that pattern
   or it will silently read/write the wrong workspace.
4. Board data comes from `GET /api/tickets` + `GET /api/people` + `GET /api/team-options`
   etc., merged client-side into `state` (the one shared mutable object in
   `public/state.js`) and rendered by `lanes.js`/`ticket-row.js`.
5. A background asyncio loop syncs Jira/Notion into `db.json` every 10 minutes for
   the **default workspace only** (other workspaces sync on switch, if stale — see
   §6). Opening a terminal spawns a real PTY process and bridges it to the browser
   over a WebSocket (`/ws/terminal/{key}`) — see §7.

## 4. `server/*.py` — one line each

| File | Purpose |
|---|---|
| `main.py` (1450 lines) | FastAPI app, the whole REST API, the terminal WebSocket. Binds `127.0.0.1` (override `WMP_HOST`) on `4173`. |
| `db.py` | Lock-guarded `db.json`: tickets, people, team roster, hidden-assignee allowlist. |
| `workspaces.py` | Named-workspace registry, path resolution, legacy-layout migration. |
| `settings_store.py` | Per-workspace `settings.json` (Jira/Notion creds, memory dir), write-only-secret semantics. |
| `content.py` | Categories + knowledge-base docs, with a committed `*.example.json` fallback. |
| `jira_sync.py` | Live Jira read/write adapter (see §6). |
| `notion_sync.py` (65 KB, largest backend file) | Notion as a second ticket source — OAuth + internal-token auth, schema-role mapping, sprint/time-box discovery. |
| `category_management.py` | Role presets, LLM-driven taxonomy review scans, write-ahead-logged category revisions. |
| `memory_analysis.py` | Reads the memory markdown folder into a graph (see `MEMORY_FORMAT.md`); per-session memory-read counts for both Claude and Codex. |
| `agent_activity.py` | Parses durable Claude/Codex JSONL transcripts into normalized command, file, memory and skill events for the terminal activity trail. |
| `cost_analysis.py` | Thin wrapper around the external `codeburn` CLI for per-session cost. |
| `spend_ledger.py` | Durable per-workspace history of what each *closed* terminal session cost. |
| `workflow_insights.py` | Pure-Python cost/caching/memory rollups over the spend ledger — no LLM call. |
| `claude_cli.py` | The one place a tool-less, non-interactive `claude -p` classification call is built. |
| `auto_categorize.py` | Guesses a new ticket's categories via `claude`; only called from `jira_sync.discover_new_tickets`. |
| `content_tags.py` | Generates 1–3 content tags per ticket via `claude`, hash-gated so unchanged tickets aren't resent. |
| `diagram_gen.py` | Drafts Mermaid diagrams for a memory or a category. **Bypasses `claude_cli.py`** and still passes the removed `--restricted` flag — both diagram endpoints are likely silently dead on current Claude Code (see §9). |
| `codex_sessions.py` | Finds a Codex session id for a ticket from its unique opening-prompt marker (sqlite, then a transcript scan). |
| `terminal_draft.py` | Inserts an editable (never auto-submitted) Codex composer draft once the composer footer appears. |
| `pty_io.py` | Cancellable async PTY reads. |
| `agent_launch.py` | Pure-stdlib PTY/launch primitives shared by `main.py` AND the standalone `host_bridge.py`. |
| `host_bridge_protocol.py` | Stdlib wire format shared by both bridge sides: 4-byte length prefix + JSON over TCP. |
| `host_bridge.py` (executable) | Standalone host-side helper (`python3 server/host_bridge.py`) that spawns real PTYs on the host for a Dockerized server. |
| `host_bridge_client.py` | Container-side client; every function fails soft so "unconfigured" and "unreachable" look identical. |

**Fully implemented and wired in, not just planned:** the host bridge (`host_bridge.py`
+ `host_bridge_client.py` + `host_bridge_protocol.py`) is live on the real spawn path.
See §7.

## 5. `public/*.js` — module map

23 ES modules reachable from `board.js`, plus `terminal.js` (a **classic**,
non-module script loaded before `board.js` — see the callout below).

| File | Purpose / exports |
|---|---|
| `board.js` | Bootstrap entrypoint, exports nothing. See §3 for exact wiring order. |
| `state.js` | The single shared mutable state object. No imports. Exports `state`. |
| `api.js` | REST shim (`apiJson`, `localDb`, `touch`, `withWorkspace`) — the one place `?w=` is appended to every request. |
| `router.js` | Hash routing: grid / `#/category/<id>` / `#/memory[/<id>]` / `#/settings` / `#/insights` / `#/terminal/<key>/<provider>`, each optionally `#/w/<slug>`-prefixed. |
| `lanes.js` | Category cards, per-category lanes, lane ordering, both ticket lists. |
| `filters.js` | Team/person/status/assignee/sprint filters, grouped-vs-flat toggle, search. **Circular import with `lanes.js`** — see §9. |
| `ticket-row.js` | Shared row renderer for one ticket (Jira or Notion). |
| `polling.js` | `reloadBoard()` (full fetch + re-render, every 60s and after every mutation), `pollLiveTicketStats()` (15s badge-only patch). |
| `people.js` | Team roster, reporter→team mapping, "People & teams" settings section. |
| `category-management.js` | Settings-page UI for role profile, scans, pending reviews, category history. |
| `dom-utils.js` | `el`, formatting helpers. No board-specific behavior. |
| `badges.js` | Cost/memory badge text + detail boxes. Pure functions. |
| `terminal-controller.js` | Embedded terminal lazy-start/close lifecycle plus the activity-trail toggle and refresh loop. |
| `agent-trail.js` | Renders normalized agent actions beside the terminal; memory/skill resources deep-link into the memory graph. |
| `terminal.js` | ⚠ **Classic script**, not a module (see callout below). Assigns `window.openTicketTerminal`. |
| `terminal-page.js` | Full-page terminal view; calls the `window.openTicketTerminal` global. |
| `workspaces.js` | Workspace routing, picker, switching, the Settings-page workspaces form. |
| `detail-view.js` | One category's detail page (docs, Mermaid diagram, related memories). |
| `memory-graph.js` | The memory corpus as a vis-network graph + editable panel. |
| `insights.js` | Cost/caching/memory dashboard over `GET /api/insights`. |
| `diagram-utils.js` | Shared Mermaid plumbing for `detail-view.js` and `memory-graph.js`. |
| `settings.js` (41 KB, largest frontend file) | The whole Settings page: categories, Jira/Notion connections, hidden assignees, memory dir, workspaces. |
| `mascot.js` | Casey the stationmaster speech-bubble helper (`mascotSay`). |
| `help.js` | Standalone Help popup, fixed `TIPS` array, uses `mascotSay`. |
| `demo-data.js` | Fixed illustrative tickets shown only when no tracker is configured and no real tickets exist (`isDemo: true`). |

**Why `terminal.js` is a classic script, and why that comment in `index.html`
matters:** classic scripts run synchronously in document order; a module script is
deferred-by-default. `terminal.js` must attach `window.openTicketTerminal` as a true
global before `board.js`'s module graph (which calls it) runs — converting it to a
module, or adding `async` to any of the classic `<script>` tags before it, breaks
that guarantee. Separately, `main.py` explicitly calls
`mimetypes.add_type("text/javascript", ".js")` before mounting `/static` — browsers
strictly enforce the MIME type for `type="module"` scripts (unlike classic ones),
and the platform `mimetypes` DB doesn't reliably map `.js` on every OS/Python build.
Without that line, `board.js` silently fails to load on some machines while
`terminal.js` keeps working, which is a confusing failure mode if you ever touch it.

## 6. Tracker sync (Jira + Notion)

- `TRACKERS = {"jira": jira_sync, "notion": notion_sync}` (`main.py`). Both modules
  satisfy the same contract: `configured()` + `sync_all_tickets(db)`. A ticket's
  `source` field (absent ⇒ `"jira"`) decides which module a status/priority/assignee
  edit pushes back to (`ticket_source(ticket)`).
- `jira_sync.py` config precedence: `settings.json` (Settings page) over
  `JIRA_BASE_URL`/`JIRA_EMAIL`/`JIRA_API_TOKEN`/`JIRA_PROJECT_KEY` env vars, **re-read
  on every call** — a Settings-page save takes effect immediately, no restart.
  Auth is HTTP Basic (email + API token) against Jira Cloud's REST v3. Known gotcha
  we hit directly: the email must be the **full address**, not the local part — a
  bad email causes a misleading failure pattern (search returns `200` with zero
  issues instead of a clean `401`, because Jira treats it as effectively anonymous
  rather than rejecting the request outright; only `/rest/api/3/myself` reports it
  honestly).
- `get_assignable_users()` narrows Jira's own `/rest/api/3/user/assignable/search`
  (which can return effectively the whole company on a permissive permission
  scheme — service accounts and bots included) down to names this board has
  actually seen as a reporter or assignee (`_known_team_names()`), then further
  respects a local-only `hiddenAssignees` allowlist set from the Settings page
  (`GET/PUT /api/hidden-assignees`) — hiding someone there never touches Jira.
- Background sync: `_start_background_tracker_sync()` sleeps
  `TRACKER_SYNC_INTERVAL_SECONDS = 600` **first**, then syncs — the first sync after
  a server (re)start is 10 minutes out, not immediate. It only ever syncs the
  **default workspace**; every other workspace syncs on switch via
  `POST /api/workspaces/{slug}/sync-if-stale`, fired from the frontend, which
  returns immediately and never awaits the sync. A manual "⟳ Refresh" always
  catches you up immediately if you don't want to wait.
- One `threading.Lock` per workspace (`_sync_locks`) so a slow sync on one board
  never blocks another.

## 7. Terminal / agent-spawning architecture

Two spawn paths, one branch point: `_resolve_agent(provider)` returns `(path, bridged)`.
`bridged = True` only when `host_bridge_client.available()` — i.e.
`WMP_HOST_BRIDGE_PORT` is set **and** a TCP connection to
`host.docker.internal:<port>` (default `4174`) succeeds.

- **Local path** (native install, or Docker with no bridge configured):
  `pty.openpty()` + `subprocess.Popen(cmd, ..., preexec_fn=agent_launch.pty_child_preexec)`
  — a real PTY in this process.
- **Bridged path** (Docker wanting the agent CLI to run as a genuine host process):
  `host_bridge_client.spawn()` opens a TCP connection to a standalone
  `python3 server/host_bridge.py` process running natively on the host, which does
  the real `pty.openpty()`/`Popen` *there* and relays bytes over the socket. The
  container side gets back a detached `socket.socketpair()` end as `master_fd` and
  treats it exactly like a real PTY fd (`os.read`/`os.write`). No silent fallback —
  if the bridge drops between resolve and spawn, it raises.

**⚠ `WMP_HOST_BRIDGE_SOCKET` does not exist as an env var.** The real, and only,
env var is `WMP_HOST_BRIDGE_PORT`, and the transport is TCP, not a Unix socket
(`server/host_bridge_protocol.py` explains why: a bind-mounted `AF_UNIX` socket
fails with `ENOTSUP` across a VM-backed Docker boundary on macOS/Windows). Three
comments in `main.py` (lines 899, 908, 948) and one line in `README.md` (290) still
say "socket" — stale, left over from an earlier design. Don't propagate it.

A tracked process (`running_processes[key]["proc"]`) is either a real `Popen` or a
`host_bridge_client.HostProcessHandle`. Every call site in `main.py` uses exactly
four methods — `.poll()`, `.terminate()`, `.wait(timeout=)`, `.kill()` — so anything
implementing just those four is a drop-in. `HostProcessHandle` adds `.resize(rows,cols)`
(used instead of an ioctl on the bridged path) and `.close()` (for ledgering a
bridged session's control connection; a plain `Popen` has no `.close()` and is
unaffected via `getattr(..., "close", None)`).

Other things worth knowing before touching this code:
- The reconnect-vs-new decision, capturing a stale previous owner, and claiming
  the new one all happen inside **one lock acquisition with no `await` inside it**
  — this is deliberate, guarding against two near-simultaneous connections (a
  rapid double reload) both believing they're first.
- `--no-daemon` for codex is added only when `(not bridged) and _codex_supports_no_daemon(executable)`
  — an `lru_cache`d probe of the *resolved* binary's own `--help` output, not an
  assumption based on topology. Older codex releases need the flag (their daemon
  health-check shells out to `ps`, missing in minimal containers); newer releases
  removed it and hard-error if it's passed.
- Processes **deliberately outlive the WebSocket** — the server only forgets one
  once it has actually exited. Closing a browser tab doesn't kill your agent.
- `GET /api/running-processes` reports both long-lived `running` sessions and the
  narrower `working` set. `working` means the PTY produced output within the last
  three seconds; the blinking dot is therefore activity-based, not session-based.
- `GET /api/agent-activity/{key}?provider=...` reads the provider's durable JSONL
  transcript and returns normalized action/resource events. The 60/40 terminal
  activity trail uses this endpoint in both embedded and full-page terminal views.
- A new Codex session gets an editable draft inserted once the composer footer
  appears in the PTY output (`terminal_draft.py`) — bracketed-paste bytes with no
  trailing newline, so **only the user can submit it**, never auto-submitted.
- `codex --no-daemon` and bridged-vs-local are genuinely different axes (don't
  conflate "running inside Docker" with "bridged" — both the container's own local
  codex and a real native non-Docker install take the identical local-spawn code
  path; only `WMP_HOST_BRIDGE_PORT` configured-and-reachable means bridged).

## 8. Data model (structure only — see `data/workspaces/<slug>/*.json`)

- **`db.json`**: `jiraTickets` (keyed by ticket key — summary, description, status,
  priority, reporter, `assigneeName`/`assigneeAccountId`, categories, content tags,
  session ids, notes, `source` for Notion rows), `people`, `teamOptions`,
  `hiddenAssignees` (Jira account ids).
- **`categories.json`**: a top-level **array**, not an object — `{id, name, status,
  color, note, memories, skills, docs, repos?, diagram?}`.
- **`docs.json`**: `{docId: {title, path, kind, content}}`.
- **`category-management.json`**: role/onboarding state, scan status, pending
  reviews (LLM-suggested add/rename/merge/assign actions awaiting accept/reject),
  and a write-ahead `pendingCommit` used to recover from an interrupted write.
- **`spend-ledger.json`**: `{entries: [...]}`, one row per *closed* terminal session
  (cost, tokens, cache stats, duration, close reason).
- **`settings.json`**: Jira creds, Notion connection (OAuth or internal token +
  schema role mapping), `memoryDir` override.
- **`sessions/`**: raw PTY transcripts, `<KEY>.log` (Claude) / `<KEY>.codex.log`
  (Codex) — can be multi-MB, gitignored, don't read wholesale.
- **`data/workspaces.json`** (root level, install-wide): the workspace registry —
  which slugs exist, which is default, each one's last-sync timestamp.

Categories/docs fall back to a committed `*.example.json` at the data root when the
real per-workspace file is absent (`content.py`'s `_read_json_with_fallback`).

## 9. Known sharp edges — read before changing nearby code

1. **`GET /api/memory-graph/stats` is shadowed.** It's registered *after*
   `GET /api/memory-graph/{memory_id}` in `main.py`, and FastAPI matches routes in
   registration order — `/api/memory-graph/stats` actually gets captured by the
   `{memory_id}` route (`"stats"` matches its id pattern), so it returns
   `{"ok": false, "error": "not found"}` instead of real stats. If you need this
   endpoint working, move its registration above the `{memory_id}` route.
2. **`diagram_gen.py` likely silently fails on current Claude Code.** It builds its
   own `claude -p --restricted ...` command instead of going through
   `claude_cli.command()` (the one sanctioned place for this), and `--restricted`
   is the exact flag `claude_cli.py`'s own docstring says current Claude Code
   rejects as an unknown option. Both diagram endpoints swallow the failure into a
   generic "diagram generation failed" message, so you won't see a loud error —
   check this first if a diagram-generation feature looks broken.
3. **`lanes.js` ↔ `filters.js` have a circular import**, and it only works because
   every binding crossing that cycle is a hoisted function declaration or a
   module-level `const` read lazily at call time. Adding a top-level `const` in
   either file that reads a cross-imported binding *at module-evaluation time*
   will break board load. Don't "clean up" this cycle without understanding why
   it currently works.
4. **Never pin a `workspaces`-resolved path at import time.** `db.db_path()`,
   `content.data_dir()`, `settings_store.settings_path()`,
   `category_management.state_path()`, `main.sessions_dir()` are all **functions**,
   called fresh every time, because which workspace is active is a per-request
   `contextvars.ContextVar`, not a constant. A new per-workspace file must follow
   this pattern.
5. **A plain `threading.Thread` does not inherit contextvars**; `asyncio.to_thread`
   does. `category_management.start_scan()` carries the active workspace slug into
   its worker thread manually for exactly this reason — any new background work
   needs the same care.
6. **The `reporter` field means different things per tracker.** For Jira tickets
   it's the literal Jira reporter. For Notion tickets, `notion_sync.py` maps its
   "assignee" role into this same local `reporter` field (there's no separate
   Notion assignee concept in this app) — so `reporter` is NOT a reliable
   cross-tracker "who opened this" signal. The real `assigneeName`/`assigneeAccountId`
   fields (added for the assignee feature) are Jira-only; Notion tickets never get
   them and always render as "Unassigned" in that filter/column.
7. **The real host-bridge env var is `WMP_HOST_BRIDGE_PORT`, the transport is TCP**
   — see §7. Several comments and one README line still say otherwise; trust the
   code (`host_bridge_client.py`, `host_bridge_protocol.py`), not those comments.
8. **The background tracker-sync loop sleeps before its first run.** Don't assume
   a fresh server restart has already synced — it hasn't, for up to 10 minutes.
   Hit the manual `POST /api/sync` (the "⟳ Refresh" button) if you need current
   data sooner, e.g. right after deploying a change to what gets synced.
9. There is **no `.env` file committed or persisted by default** (only
   `.env.example`). If you run the server manually via a backgrounded shell
   command with inline env vars (`WMP_DEFAULT_WORKDIR=... nohup ... &`), those
   vars are NOT remembered across a future restart unless you set them again
   explicitly — this has caused real regressions this session (the memory graph
   went empty after a restart dropped `WMP_DEFAULT_WORKDIR`). Prefer writing a
   real `.env` file (the app already depends on `python-dotenv`) over ad-hoc
   inline env vars if you're going to be restarting the server repeatedly.

## 10. Testing

```bash
.venv/bin/python -m unittest discover -s tests -q   # NOT system python3 — it lacks the deps
npm --prefix tests/ui ci && npm --prefix tests/ui test
```

- Python: 19 files, 241 tests. No `pytest`, no `tests/__init__.py` — every file
  does its own `sys.path.insert(0, <repo>/server)`. `tests/workspace_fixture.py`'s
  `TempWorkspaces` is the shared fixture: it patches `workspaces.DATA_ROOT` to a
  temp dir laid out like a real install and enters `workspaces.use(slug)`, so a
  test never touches the real `data/` tree.
- JS: 8 `.mjs` files in `tests/ui/`, run as plain `node` scripts (no test runner)
  against a `linkedom`-provided DOM, chained with `&&` so the first failure stops
  the run. ~300 raw `assert` calls total.
- CI (`.github/workflows/ci.yml` + `dco.yml`/`codeql.yml`/`scorecard.yml`): backend
  tests, UI tests, a full-history secret scan (gitleaks), and a DCO sign-off check
  — all required before merge.

## 11. Contribution mechanics

- **DCO sign-off is required on every commit**: `git commit -s` (adds
  `Signed-off-by: Name <email>` matching the commit author). `scripts/install-hooks.sh`
  installs a `prepare-commit-msg` hook that does this automatically. CI's `dco.yml`
  job fails a PR missing one.
- Apache 2.0, no CLA — contributors keep their own copyright.
- This session's working convention (not a repo rule, but worth continuing): one
  feature branch per coherent unit of work, PR against `main`, merge once CI is
  green (`gh pr merge --merge --auto` when branch protection requires checks to
  finish first). Never commit directly to `main`.
- Git commit messages and PR descriptions in this session end with the attribution
  lines the harness's system reminder specifies at the time — check current
  instructions rather than copying an old trailer verbatim.

## 12. Deployment options

- **Option 1 — native Python**: `uv venv && uv pip install --require-hashes -r requirements.txt`,
  run `python server/main.py` directly. Host-native agents "just work" since
  there's no container boundary.
- **Option 2 — Docker**: `docker compose up -d --build`, one service
  (`ticket-terminal`), `$HOME` bind-mounted 1:1 (so ticket workdirs plus
  `~/.claude`, `~/.codex`, `~/.ssh`, `~/.aws`, `~/.kube` are all visible inside the
  container at their real paths — the README is explicit that this makes the
  Docker image "a packaging convenience, not a sandbox"). Port published as
  `127.0.0.1:4173:4173` — the compose file's own comment says never drop that
  `127.0.0.1:` prefix.  Within Docker there's a second, optional axis: agents
  running inside the container (default) vs. a host-native agent via the bridge
  (`WMP_HOST_BRIDGE_PORT`, see §7) when you want `claude`/`codex` to run as genuine
  host processes with the host's own installed CLI versions and credentials.

## 13. Recent history (for context, not exhaustive)

In rough order: migrated Python packaging from pip/venv to `uv`; added Casey the
stationmaster mascot + a speech-bubble UI for onboarding and a new Help popup;
fixed a `codex --no-daemon` hard-error on native installs (the binary-introspection
fix described in §7); the host-bridge architecture (§7) shipped as a full feature,
not just the plan that originally proposed it; most recently, the ticket-assignee
feature (PR #47) — assign a ticket to a real Jira person, show the current
assignee, filter by assignee, and curate which assignable users actually show up
in the app versus what Jira's own permission scheme would otherwise expose — plus
a fix for a bug where every Settings-page "Saved ✓" confirmation across four
different forms was invisibly wiped by the full-form re-render that immediately
followed it. PR #48 added the Jira-style status board and full-width layouts.
The latest work replaces the unreliable running badge with a true PTY-activity
dot, removes the redundant token bar, fixes the initial empty-board refresh race,
and adds the optional 60/40 graphical activity trail beside embedded and expanded
terminals.
