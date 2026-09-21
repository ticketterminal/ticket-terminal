"""Local work-management-platform server.

Serves the board UI and a REST API backed by one workspace's db.json (see db.py
and workspaces.py — which workspace depends on the request's ?w=), plus a
WebSocket endpoint that opens a real PTY running `claude`, bridged to an
xterm.js terminal in the browser — this is the part a sandboxed Artifact page
could never do.

SECURITY: bind to 127.0.0.1 only (see the __main__ block). This process can
spawn a real shell with the user's own permissions; it must never be reachable
from the network. No auth is added on top of that for v1 — localhost-only IS
the security boundary, by design, not an oversight.
"""
import asyncio
import datetime
import fcntl
import json
import mimetypes
import os
import pty
import struct
import subprocess
import termios
import threading
import uuid
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import Body, FastAPI, WebSocket
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.websockets import WebSocketDisconnect

import content
import category_management
import cost_analysis
import codex_sessions
import diagram_gen
import pty_io
import spend_ledger
import terminal_draft
import shutil
import db
import jira_sync
import memory_analysis
import notion_sync
import settings_store
import workflow_insights
import workspaces

BASE_DIR = Path(__file__).resolve().parent.parent
PUBLIC_DIR = BASE_DIR / "public"
DEFAULT_WORKDIR = memory_analysis.DEFAULT_WORKDIR  # one WMP_DEFAULT_WORKDIR, read once
TRACKER_SYNC_INTERVAL_SECONDS = 600  # 10 minutes, for every configured tracker (Jira, Notion) — see .env.example

app = FastAPI()


def sessions_dir() -> Path:
    """Terminal transcripts belong to one board — see workspaces.py."""
    return workspaces.root() / "sessions"


# ---------- workspaces: which board is this request talking about ----------

class WorkspaceMiddleware:
    """Pin every request (and every WebSocket, for its whole life) to the
    workspace named by `?w=<slug>`; no `w` means the default workspace.

    Deliberately a raw ASGI middleware rather than `@app.middleware("http")`:
    BaseHTTPMiddleware runs the endpoint in a separate task, and it does not
    cover WebSockets at all — but a terminal WebSocket is exactly the
    long-lived, concurrently-open-with-another-workspace case this whole
    mechanism exists for. A raw middleware wraps the endpoint in the same
    context, so the ContextVar is set for the endpoint, for anything it
    `create_task`s, and for anything it hands to `asyncio.to_thread`.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        asked = parse_qs(scope.get("query_string", b"").decode()).get("w", [""])[0]
        try:
            slug = workspaces.resolve(asked)
        except workspaces.UnknownWorkspace:
            if scope["type"] == "websocket":
                return await send({"type": "websocket.close", "code": 1008})
            response = JSONResponse({"ok": False, "error": "no such workspace"}, status_code=404)
            return await response(scope, receive, send)
        with workspaces.use(slug):
            await self.app(scope, receive, send)


app.add_middleware(WorkspaceMiddleware)


@app.on_event("startup")
async def _migrate_workspaces():
    """Idempotent, and a no-op on an install that has already been moved (or
    has nothing to move) — see workspaces.migrate_if_needed."""
    await asyncio.to_thread(workspaces.migrate_if_needed)


def _workspace_summary(entry: dict) -> dict:
    slug = entry["slug"]
    with workspaces.use(slug):
        try:
            ticket_count = len(db.read()["jiraTickets"])
        except Exception:
            ticket_count = 0
        connected = jira_sync.configured() or notion_sync.configured()
    return {
        "slug": slug,
        "name": entry.get("name") or slug,
        "createdAt": entry.get("createdAt") or "",
        "connected": connected,
        "ticketCount": ticket_count,
        "lastSyncAt": entry.get("lastSyncAt") or "",
        "syncing": sync_lock_for(slug).locked(),
    }


@app.get("/api/workspaces")
def get_workspaces():
    """The picker's whole data source. There is deliberately no merged view
    anywhere: workspaces are switched between, never combined."""
    registry = workspaces.read_registry()
    return {
        "ok": True,
        "defaultWorkspace": registry["defaultWorkspace"],
        "active": workspaces.current(),
        "workspaces": [_workspace_summary(w) for w in registry["workspaces"]],
    }


@app.post("/api/workspaces")
def post_workspace(body: dict = Body(...)):
    try:
        entry = workspaces.create(body.get("slug", ""), body.get("name", ""))
    except ValueError as error:
        return {"ok": False, "error": str(error)}
    return {"ok": True, "workspace": _workspace_summary(entry)}


def _is_stale(last_sync_at: str) -> bool:
    if not last_sync_at:
        return True
    try:
        when = datetime.datetime.fromisoformat(last_sync_at)
    except ValueError:
        return True
    if when.tzinfo is None:
        when = when.replace(tzinfo=datetime.timezone.utc)
    age = (datetime.datetime.now(datetime.timezone.utc) - when).total_seconds()
    return age >= TRACKER_SYNC_INTERVAL_SECONDS


@app.post("/api/workspaces/{slug}/sync-if-stale")
async def workspace_sync_if_stale(slug: str):
    """Called when the board switches to a workspace. Starts a sync only if
    that workspace has not synced within TRACKER_SYNC_INTERVAL_SECONDS —
    otherwise flipping back and forth would restart an hour-long sync every
    time. Returns immediately either way and NEVER awaits the sync: the stored
    board renders now and the refresh lands when it lands."""
    try:
        target = workspaces.resolve(slug)
    except workspaces.UnknownWorkspace:
        return JSONResponse({"ok": False, "error": "no such workspace"}, status_code=404)
    last_sync_at = workspaces.get_last_sync_at(target)
    if sync_lock_for(target).locked() or not _is_stale(last_sync_at):
        return {"ok": True, "syncStarted": False, "lastSyncAt": last_sync_at}

    async def run_sync():
        with workspaces.use(target):
            try:
                result = await asyncio.to_thread(sync_trackers)
                for name, error in (result.get("errors") or {}).items():
                    print(f"[{name}-sync] {target}: {error}")
            except Exception as error:
                print(f"[tracker-sync] {target}: {error}")

    asyncio.create_task(run_sync())
    return {"ok": True, "syncStarted": True, "lastSyncAt": last_sync_at}


# Registry of background processes, keyed "<slug>|<provider>|<ticketKey>": two
# workspaces can both hold a ticket called DATAFLINT-7652, and a session open in
# each of them must stay alive at once — that is the whole point of running one
# server rather than two copies of it.
# {process_key: {'proc': Popen, 'master_fd': int, 'lock': Lock}}
# Processes stay alive even after WebSocket closes, so users can reconnect to them.
running_processes = {}
processes_lock = threading.Lock()


def process_key_for(key: str, provider: str, slug: str | None = None) -> str:
    return f"{slug or workspaces.current()}|{provider}|{key}"


# The ticket trackers this board can mirror. Each module exposes the same
# configured()/sync_all_tickets(db) pair; a ticket's `source` field (absent =
# "jira", the original) says which one a status/priority edit pushes back to.
TRACKERS = {"jira": jira_sync, "notion": notion_sync}


def ticket_source(ticket: dict) -> str:
    return ticket.get("source") or "jira"


# One lock per workspace, so a sync that takes an hour on a big board never
# blocks a two-second one next door.
_sync_locks: dict[str, threading.Lock] = {}
_sync_locks_guard = threading.Lock()


def sync_lock_for(slug: str | None = None) -> threading.Lock:
    slug = slug or workspaces.current()
    with _sync_locks_guard:
        return _sync_locks.setdefault(slug, threading.Lock())


def sync_trackers() -> dict:
    """Run every configured tracker's sync and merge the per-tracker results
    into one summary for the Refresh button. A failure in one tracker never
    blocks the other — it's reported under `errors` instead. Only one sync
    runs at a time: a first import can take minutes (a model call per new
    ticket), and the Refresh button landing on top of the 10-minute timer
    would otherwise double every one of those calls."""
    slug = workspaces.current()
    lock = sync_lock_for(slug)
    if not lock.acquire(blocking=False):
        return {"synced": [], "errors": {"sync": "a sync is already running — try again in a minute"}, "busy": True}
    try:
        return _sync_trackers_locked()
    finally:
        # Recorded success or failure alike: a failed sync still counts as
        # "recently attempted", so a broken tracker cannot re-trigger a full
        # sync on every switch back to its workspace.
        workspaces.set_last_sync_at(slug)
        lock.release()


def _sync_trackers_locked() -> dict:
    merged = {"synced": [], "errors": {}, "checked": 0, "updated": 0, "changed": [], "added": [],
              "categorized": [], "tagged": [], "tagError": None, "categoryError": None,
              "truncated": False, "mappingProblems": [], "sprints": []}
    for name, module in TRACKERS.items():
        if not module.configured():
            continue
        try:
            result = module.sync_all_tickets(db)
        except Exception as e:
            merged["errors"][name] = str(e)
            continue
        merged["synced"].append(name)
        merged["checked"] += result.get("checked", 0)
        merged["updated"] += result.get("updated", 0)
        for field in ("changed", "added", "categorized", "tagged"):
            merged[field].extend(result.get(field) or [])
        for field in ("tagError", "categoryError"):
            if result.get(field):
                merged[field] = ((merged[field] + " · ") if merged[field] else "") + f"{name}: {result[field]}"
        if result.get("truncated"):
            merged["truncated"] = True
        merged["mappingProblems"].extend(result.get("mappingProblems") or [])
        if result.get("sprints"):
            merged["sprints"] = result["sprints"]  # so the board's Refresh can roll its sprint selector over
    return merged


@app.on_event("startup")
async def _start_background_tracker_sync():
    async def loop_forever():
        while True:
            await asyncio.sleep(TRACKER_SYNC_INTERVAL_SECONDS)
            # The timer syncs the DEFAULT workspace and nothing else. Every
            # other workspace syncs when you switch to it, if it is stale —
            # see POST /api/workspaces/{slug}/sync-if-stale. The server never
            # needs to know which workspace a browser happens to be showing.
            try:
                with workspaces.use(workspaces.default_slug()):
                    result = await asyncio.to_thread(sync_trackers)
                for name, error in result["errors"].items():
                    print(f"[{name}-sync] background sync failed: {error}")
            except Exception as e:
                print(f"[tracker-sync] background sync failed: {e}")
    asyncio.create_task(loop_forever())


# ---------- REST: tickets / people / team options ----------

@app.get("/api/tickets")
def get_tickets():
    return db.read()["jiraTickets"]


@app.patch("/api/tickets/{key}")
def patch_ticket(key: str, patch: dict = Body(...)):
    return db.update_ticket(key, patch)


@app.post("/api/tickets/{key}/notes")
def post_note(key: str, body: dict = Body(...)):
    return db.add_note(key, body.get("text", ""))


@app.get("/api/people")
def get_people():
    return db.read()["people"]


@app.put("/api/people/{person_id}")
def put_person(person_id: str, body: dict = Body(...)):
    return db.upsert_person(person_id, body)


@app.get("/api/team-options")
def get_team_options():
    return db.read()["teamOptions"]


@app.put("/api/team-options")
def put_team_options(body: dict = Body(...)):
    return db.set_team_options(body.get("options", []))


@app.get("/api/categories")
def get_categories():
    """Board lanes + their knowledge-base doc lists — see content.py for the
    real-data/gitignored-with-example-fallback pattern (same as db.py)."""
    return content.read_categories()


@app.put("/api/categories")
def put_categories(categories: list = Body(...), revision: str | None = None):
    """Written from the Settings page. The frontend sends the whole current
    array back (same pattern PUT /api/team-options already uses) — content.py
    rejects an empty/duplicate id or empty name before writing."""
    try:
        return {"ok": True, "categories": category_management.update_categories(categories, revision)}
    except ValueError as e:
        return {"ok": False, "error": str(e)}


def category_action(fn, *args):
    try:
        return {"ok": True, "data": fn(*args)}
    except (ValueError, TypeError) as error:
        return {"ok": False, "error": str(error)}


@app.post("/api/categories/{category_id}/diagram")
def generate_category_diagram(category_id: str):
    """Drafts (or redrafts) one overarching Mermaid diagram for a category's whole subject
    from all of its linked memories at once — see diagram_gen.generate_category_diagram. Not
    part of category_management's revision-tracked edits; see content.set_category_diagram."""
    try:
        categories = content.read_categories()
        cat = next((c for c in categories if c.get("id") == category_id), None)
        if cat is None:
            return {"ok": False, "error": "no such category"}
        graph_nodes = {n["id"]: n for n in memory_analysis.read_graph()["nodes"]}
        memories = []
        for memory_id in cat.get("memories") or []:
            body = memory_analysis.read_doc(memory_id)
            if body is None:
                continue
            memories.append({"id": memory_id, "description": graph_nodes.get(memory_id, {}).get("description", ""), "body": body})
        if not memories:
            return {"ok": False, "error": "this category has no linked memories to diagram"}
        mermaid = diagram_gen.generate_category_diagram(cat.get("name", category_id), memories)
        if mermaid is None:
            return {"ok": False, "error": "diagram generation failed (claude not authenticated, timed out, or returned nothing usable)"}
        diagram = {"mermaid": mermaid, "generatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat()}
        content.set_category_diagram(category_id, diagram)
        return {"ok": True, "diagram": diagram}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/category-management")
def category_status():
    return category_action(category_management.status)


@app.put("/api/category-management/profile")
def category_profile(body: dict = Body(...)):
    return category_action(category_management.profile, body)


@app.post("/api/category-management/scan")
def category_scan():
    return category_action(category_management.start_scan)


@app.post("/api/category-management/reviews/{review_id}")
def category_decision(review_id: str, body: dict = Body(...)):
    return category_action(category_management.decide, review_id, body)


@app.post("/api/category-management/restore/{version}")
def category_restore(version: str):
    return category_action(category_management.restore, version)


@app.on_event("startup")
async def start_category_scanner():
    """Scheduled category scans run for the DEFAULT workspace only, matching
    the tracker-sync timer: a scan spends model tokens, and the server has no
    way to know which board anyone is looking at. Another workspace's scans
    are on-demand from its own Settings page, where they run in that
    workspace's context (see category_management.start_scan)."""
    def in_default(fn):
        with workspaces.use(workspaces.default_slug()):
            return fn()

    await asyncio.to_thread(in_default, category_management.status)

    async def category_loop():
        while True:
            await asyncio.sleep(60)
            try:
                await asyncio.to_thread(in_default, category_management.maybe_scan)
            except Exception as error:
                print(f"[category-scan] {error}")
    app.state.category_scan_task = asyncio.create_task(category_loop())


@app.on_event("shutdown")
async def stop_category_scanner():
    task = getattr(app.state, "category_scan_task", None)
    if task:
        task.cancel()


@app.get("/api/docs/{doc_id}")
def get_doc(doc_id: str):
    doc = content.read_doc(doc_id)
    if doc is None:
        return {"ok": False, "error": "not found"}
    return {"ok": True, **doc}


@app.get("/api/config")
def get_config():
    """The few org-specific values the frontend needs but shouldn't hardcode."""
    return {
        "jiraBaseUrl": jira_sync.get_config()["base_url"],
        "jiraConfigured": jira_sync.configured(),
        "notionConfigured": notion_sync.configured(),
    }


@app.get("/api/settings")
def get_settings():
    """Effective config the Settings page displays — merges this workspace's settings.json
    over the .env fallback (see jira_sync.get_config / memory_analysis.
    memory_dir_info for the precedence rule). The Jira API token is never
    round-tripped back to the browser once saved — only whether one is set and
    a last-4-chars preview, matching the usual write-only-secret pattern."""
    jira = jira_sync.get_config()
    token = jira["api_token"]
    notion = notion_sync.get_config()
    mem_info = memory_analysis.memory_dir_info()
    return {
        "jira": {
            "baseUrl": jira["base_url"],
            "email": jira["email"],
            "projectKey": jira["project"],
            "apiTokenSet": bool(token),
            "apiTokenPreview": _secret_preview(token),
        },
        "notion": {
            "clientId": notion["client_id"],
            "clientSecretSet": bool(notion["client_secret"]),
            "clientSecretPreview": _secret_preview(notion["client_secret"]),
            "redirectUri": notion["redirect_uri"],
            "connected": bool(notion["access_token"]),
            "authMode": notion["auth_mode"],
            "workspaceName": notion["workspace_name"],
            "accessTokenPreview": _secret_preview(notion["access_token"]),
            "databaseId": notion["database_id"],
            "statusProperty": notion["status_property"],
            "priorityProperty": notion["priority_property"],
            "lastOauthError": notion_sync.last_oauth_error,
        },
        "memoryDir": str(mem_info["path"]),
        "memoryDirSource": mem_info["source"],
    }


def _secret_preview(secret: str) -> str:
    return ("••••" + secret[-4:]) if len(secret) >= 4 else ("set" if secret else "")


@app.put("/api/settings")
def put_settings(body: dict = Body(...)):
    """Partial update — an omitted/blank jira.apiToken leaves the stored token
    unchanged (see settings_store.update). Clears the cached Jira workflow-
    status list since a new instance/project can have a different workflow.

    Sending notion.sprintActiveMarker is the user answering "which status
    means the sprint is running?" themselves, so it is recorded as confirmed
    and inference stops overwriting it; sending it blank clears both fields
    and hands the question back to inference."""
    notion_patch = (body or {}).get("notion") or {}
    notion_patch.pop("sprintActiveMarkerSource", None)  # server-owned flag: only the marker branch below may set it
    settings_store.update(body)
    if "sprintActiveMarker" in notion_patch:
        marker = (notion_patch.get("sprintActiveMarker") or "").strip()
        settings_store.set_section_fields("notion", {
            "sprintActiveMarker": marker,
            "sprintActiveMarkerSource": "confirmed" if marker else "",
        })
    jira_sync.invalidate_cache()
    notion_sync.invalidate_cache()
    return {"ok": True}


# ---------- Notion: OAuth handshake + database picker ----------

@app.get("/api/notion/oauth/start")
def notion_oauth_start():
    """Browser navigates here (a plain link, not fetch) and gets bounced to
    Notion's consent screen; Notion sends it back to /oauth/callback below."""
    try:
        return RedirectResponse(notion_sync.build_authorize_url(), status_code=302)
    except Exception as e:
        notion_sync.last_oauth_error = str(e)
        return RedirectResponse("/#/settings", status_code=302)


@app.get("/api/notion/oauth/callback")
def notion_oauth_callback(code: str = "", state: str = "", error: str = "", error_description: str = ""):
    """Notion's redirect target. Validates the CSRF state we issued, swaps the
    one-time code for a workspace token, and lands the user back on Settings —
    which re-reads /api/settings and shows the connected workspace (or the
    error stashed in notion_sync.last_oauth_error)."""
    origin = notion_sync.consume_oauth_state(state) if not error else None
    if error:
        notion_sync.last_oauth_error = error_description or error
    elif origin is None:
        notion_sync.last_oauth_error = "OAuth state didn't match (expired or replayed) — click Connect with Notion again"
    elif not workspaces.exists(origin):
        notion_sync.last_oauth_error = "the workspace this connection was started from no longer exists"
    else:
        # Notion's callback carries no ?w=, so the middleware resolved this
        # request to the default workspace. Store into the one the flow
        # actually began in, or connecting from a second workspace would
        # overwrite the default's token.
        try:
            with workspaces.use(origin):
                notion_sync.exchange_code(code)
            notion_sync.last_oauth_error = None
        except Exception as e:
            notion_sync.last_oauth_error = str(e)
    return RedirectResponse(_settings_hash(origin), status_code=302)


def _settings_hash(slug: str | None) -> str:
    """Back to the Settings page OF THE WORKSPACE the flow began in."""
    if not slug or slug == workspaces.default_slug():
        return "/#/settings"
    return "/#/w/" + slug + "/settings"


@app.post("/api/notion/token")
def notion_set_token(body: dict = Body(...)):
    """The primary, no-OAuth path: a personal internal-integration secret.
    Validated before being stored, so a bad paste leaves any existing
    connection untouched."""
    token = (body.get("token") or "").strip()
    if not token:
        return {"ok": False, "error": "paste an integration token"}
    try:
        notion_sync.set_internal_token(token)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/notion/disconnect")
def notion_disconnect():
    notion_sync.disconnect()
    notion_sync.last_oauth_error = None
    return {"ok": True}


@app.get("/api/notion/databases")
def notion_databases():
    if not notion_sync.connected():
        return {"ok": False, "error": "not connected"}
    try:
        return {"ok": True, "databases": notion_sync.list_databases()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/notion/options")
def notion_options():
    """Status/priority choices for Notion tickets' selects + the column list
    for the Settings page's mapping pickers."""
    if not notion_sync.configured():
        return {"ok": False, "error": "not configured"}
    try:
        return {"ok": True, **notion_sync.get_options()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/sync-notion")
def sync_notion():
    if not notion_sync.configured():
        return {"ok": False, "error": "not configured — connect Notion and pick a database on the Settings page"}
    lock = sync_lock_for()
    if not lock.acquire(blocking=False):
        return {"ok": False, "error": "a sync is already running — try again in a minute"}
    try:
        return {"ok": True, **notion_sync.sync_all_tickets(db)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        lock.release()


@app.post("/api/sync")
def sync_all():
    """What the board's Refresh button calls: every configured tracker at once."""
    result = sync_trackers()
    if result.get("busy"):
        return {"ok": False, "error": result["errors"]["sync"]}
    if not result["synced"] and not result["errors"]:
        return {"ok": False, "error": "no tracker configured — set up Jira or Notion on the Settings page"}
    if not result["synced"]:
        return {"ok": False, "error": " · ".join(f"{k}: {v}" for k, v in result["errors"].items())}
    return {"ok": True, **result}


@app.post("/api/sync-jira")
def sync_jira():
    if not jira_sync.configured():
        return {"ok": False, "error": "not configured — copy .env.example to .env and fill it in"}
    lock = sync_lock_for()
    if not lock.acquire(blocking=False):
        return {"ok": False, "error": "a sync is already running — try again in a minute"}
    try:
        result = jira_sync.sync_all_tickets(db)
        return {"ok": True, **result}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        lock.release()


@app.patch("/api/tickets/{key}/jira-priority")
def patch_jira_priority(key: str, body: dict = Body(...)):
    priority = body.get("priority", "")
    ticket = db.read()["jiraTickets"].get(key, {})
    if ticket_source(ticket) == "notion":
        try:
            notion_sync.set_priority(ticket, priority)
            db.update_ticket(key, {"jiraPriority": priority})
            return {"ok": True, "jiraPriority": priority}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    if not jira_sync.configured():
        return {"ok": False, "error": "not configured — copy .env.example to .env and fill it in"}
    try:
        jira_sync.set_priority(key, priority)
        db.update_ticket(key, {"jiraPriority": priority})
        return {"ok": True, "jiraPriority": priority}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/jira-statuses")
def get_jira_statuses():
    """The one shared status list every ticket's status <select> renders from
    — see jira_sync.get_workflow_statuses for why this is safe to cache
    instead of a per-ticket GET."""
    if not jira_sync.configured():
        return {"ok": False, "error": "not configured — copy .env.example to .env and fill it in"}
    try:
        keys = [k for k, t in db.read()["jiraTickets"].items() if ticket_source(t) == "jira"]
        if not keys:
            return {"ok": True, "statuses": []}
        return {"ok": True, "statuses": jira_sync.get_workflow_statuses(keys[0])}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/ticket-costs")
def get_ticket_costs():
    """Per-session cost from the real codeburn CLI, keyed by claudeSessionId — see
    cost_analysis.get_session_costs for why this shells out instead of reimplementing
    codeburn's pricing logic."""
    try:
        costs = cost_analysis.get_session_costs()
        for key, ticket in db.read()["jiraTickets"].items():
            for provider in ("claude", "codex"):
                sid = ticket.get(provider + "SessionId")
                if provider == "codex" and not sid and ticket.get("codexSessionMarker"):
                    sid = codex_sessions.find_session(ticket["codexSessionMarker"], (ticket.get("workDir") if os.path.isdir(ticket.get("workDir") or "") else DEFAULT_WORKDIR))
                    if sid:
                        db.update_ticket(key, {"codexSessionId": sid})
                if sid and sid in costs:
                    costs[provider + ":" + key] = {**costs[sid], "provider": provider}
        return {"ok": True, "costs": costs}
    except FileNotFoundError:
        return {"ok": False, "error": "codeburn is not installed (npm install -g codeburn)"}
    except subprocess.CalledProcessError as e:
        return {"ok": False, "error": "codeburn exited with an error: " + (e.stderr or str(e))}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/memory-graph")
def get_memory_graph():
    """The real memory corpus as a graph — see memory_analysis.read_graph."""
    try:
        return {"ok": True, **memory_analysis.read_graph()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/memory-graph/{memory_id}")
def get_memory_doc(memory_id: str):
    content = memory_analysis.read_doc(memory_id)
    if content is None:
        return {"ok": False, "error": "not found"}
    return {"ok": True, "content": content}


@app.put("/api/memory-graph/{memory_id}")
def put_memory_doc(memory_id: str, body: dict = Body(...)):
    try:
        memory_analysis.write_doc(memory_id, body.get("content", ""))
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/memory-graph/{memory_id}/diagram")
def generate_memory_diagram(memory_id: str):
    """Drafts (or redrafts) a ```mermaid diagram for this memory's body via `claude -p` — see
    diagram_gen.generate. Splices the result into the doc and writes it back, same as a normal
    PUT, so the frontend can treat the response identically to /api/memory-graph/{id}'s GET."""
    try:
        body = memory_analysis.read_doc(memory_id)
        if body is None:
            return {"ok": False, "error": "not found"}
        mem_type = next((n["type"] for n in memory_analysis.read_graph()["nodes"] if n["id"] == memory_id), "")
        diagram = diagram_gen.generate(body, mem_type)
        if diagram is None:
            return {"ok": False, "error": "diagram generation failed (claude not authenticated, timed out, or returned nothing usable)"}
        new_body = memory_analysis.splice_diagram(body, diagram)
        memory_analysis.write_doc(memory_id, new_body)
        return {"ok": True, "content": new_body}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/ticket-memory-usage")
def get_ticket_memory_usage():
    """Per-ticket memory access, keyed by both the raw sessionId and "<provider>:<ticketKey>"
    for claude/codex tickets alike — see memory_analysis.all_ticket_memory_usage for why this
    only counts a direct file reference (a Grep/Glob sweep isn't attributed to one file, so is
    deliberately left out rather than approximated)."""
    try:
        tickets = db.read()["jiraTickets"]
        return {"ok": True, "usage": memory_analysis.all_ticket_memory_usage(tickets, DEFAULT_WORKDIR)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/insights")
def get_insights():
    """Cost/performance/caching dashboard data — see workflow_insights.compute_insights. Pure
    computation over the spend ledger + codeburn + existing memory-usage stats; never calls an
    LLM."""
    try:
        tickets = db.read()["jiraTickets"]
        return {"ok": True, "data": workflow_insights.compute_insights(tickets, DEFAULT_WORKDIR)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/memory-graph/stats")
def get_memory_graph_stats():
    """Per-memory metadata: which categories reference it, how many tickets read it."""
    try:
        tickets = db.read()["jiraTickets"]
        graph = memory_analysis.read_graph()
        usage = memory_analysis.all_ticket_memory_usage(tickets, DEFAULT_WORKDIR)

        stats = {}
        for node in graph["nodes"]:
            mid = node["id"]
            stats[mid] = {"referencedBy": [], "readByTickets": 0}

        # Find categories that reference each memory
        # This would need CATEGORIES from the frontend — for now, just count ticket reads
        for session_usage in usage.values():
            for mid in session_usage:
                if mid in stats:
                    stats[mid]["readByTickets"] += 1

        return {"ok": True, "stats": stats}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/tickets/{key}/jira-transition")
def post_jira_transition(key: str, body: dict = Body(...)):
    transition_id = body.get("transitionId", "")
    status_name = body.get("statusName", "")
    ticket = db.read()["jiraTickets"].get(key, {})
    if ticket_source(ticket) == "notion":
        # Notion has no workflow edges — any status option is reachable directly.
        try:
            notion_sync.set_status(ticket, status_name)
            db.update_ticket(key, {"jiraStatus": status_name})
            return {"ok": True, "jiraStatus": status_name}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    if not jira_sync.configured():
        return {"ok": False, "error": "not configured — copy .env.example to .env and fill it in"}
    try:
        jira_sync.transition_issue(key, transition_id)
        db.update_ticket(key, {"jiraStatus": status_name})
        return {"ok": True, "jiraStatus": status_name}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---------- Terminal: real PTY running `claude`, bridged over a WebSocket ----------

def _set_winsize(fd, rows, cols):
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except OSError:
        pass


def _pty_child_preexec():
    """Set up the child as a proper terminal session before exec.

    `os.setsid()` alone is NOT enough, and this was a real bug for a long time:
    it makes the child a session leader with *no controlling terminal*, because
    the PTY slave was opened here in the parent — the child only inherits the
    fd, it never `open()`s the terminal itself, which is what would implicitly
    claim it. With no controlling terminal there is no foreground process group
    for that terminal, so the kernel has nowhere to deliver SIGWINCH when we
    resize the master. The TUI therefore never learns the window changed and
    never repaints, which is what made a reconnected terminal sit blank
    forever (see the reconnect nudge in terminal_ws).

    TIOCSCTTY on fd 0 claims the slave as this session's controlling terminal.
    fd 0 is the slave: preexec_fn runs after Popen has dup2'd it onto stdin.
    As a bonus this also makes job control work properly — SIGINT/SIGWINCH now
    reach the process group the way they would in a real terminal.
    """
    os.setsid()
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


def _claude_session_exists(cwd: str, session_id: str) -> bool:
    """Whether Claude Code actually wrote a resumable transcript for this
    session id. A stored claudeSessionId can point to nothing real — e.g. the
    env-var bug (fixed 2026-09-06) that silently disabled transcript
    persistence for a while — so this is checked before ever trying --resume,
    rather than letting `claude` fail with "No conversation found" and
    leaving the ticket permanently stuck on a dead id."""
    project_dir = memory_analysis.claude_project_dir(cwd)
    return (project_dir / f"{session_id}.jsonl").exists()


def agent_executable(provider):
    """Resolve once for both availability and launch, including desktop installs."""
    override = os.environ.get("WMP_" + provider.upper() + "_BIN")
    if override:
        return shutil.which(os.path.expanduser(override))
    found = shutil.which(provider)
    if found:
        return found
    if provider == "codex":
        candidates = [
            Path("/Applications/ChatGPT.app/Contents/Resources/codex"),
            Path("/Applications/Codex.app/Contents/Resources/codex"),
            Path.home() / "Applications/ChatGPT.app/Contents/Resources/codex",
            Path.home() / "Applications/Codex.app/Contents/Resources/codex",
            Path("/opt/homebrew/bin/codex"),
            Path("/usr/local/bin/codex"),
            Path.home() / ".local/bin/codex",
        ]
        for candidate in candidates:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
    return None


@app.get("/api/terminal-providers")
def get_terminal_providers():
    return {"providers": [p for p in ("claude", "codex") if agent_executable(p)]}


def _wire_process_key(process_key: str) -> str:
    """The browser never sees a slug in a process key — its request is already
    scoped to one workspace (`?w=`), so it keeps talking the workspace-relative
    "<key>" / "codex:<key>" shape it always has."""
    _, provider, key = process_key.split("|", 2)
    return key if provider == "claude" else provider + ":" + key


def _process_key_from_wire(wire_key: str) -> str | None:
    """Decode the browser's `TICKET` / `codex:TICKET` form into a registry key
    scoped to THIS request's workspace.

    The workspace is always taken from `?w=`, never from the key. An earlier
    version passed a key already containing "|" straight through as "already
    fully qualified", which let a request scoped to one workspace name — and
    so kill — a process belonging to another. No ticket key contains "|", so
    one that does is not a key this endpoint should act on."""
    if "|" in wire_key:
        return None
    provider, _, key = wire_key.partition(":")
    if not key:
        provider, key = "claude", wire_key
    if provider not in ("claude", "codex") or not key:
        return None
    return process_key_for(key, provider)


@app.get("/api/running-processes")
def get_running_processes():
    """Ticket keys with background processes running IN THIS WORKSPACE. A
    session in another workspace stays alive but is deliberately invisible
    here — workspaces are never merged into one view."""
    prefix = workspaces.current() + "|"
    with processes_lock:
        keys = [k for k in running_processes if k.startswith(prefix)]
    return {"ok": True, "running": [_wire_process_key(k) for k in keys]}


def _terminate_process(registry_key: str, proc_info: dict, close_reason: str) -> None:
    """Stop a tracked background process and record its final cost — shared by
    an explicit Stop click and a handoff to the real app (see handoff_session).
    `close_reason` is what distinguishes the two in the spend ledger."""
    try:
        proc_info["proc"].terminate()
        proc_info["proc"].wait(timeout=2)
    except Exception:
        try:
            proc_info["proc"].kill()
        except Exception:
            pass
    try:
        os.close(proc_info["master_fd"])
    except OSError:
        pass
    # This is a genuine, explicit "this session is over" moment (unlike a websocket
    # disconnect, which can just be a collapsed tab reconnecting later) — record its final
    # cost now, before the session id might get rotated out from under this ticket later.
    _, provider, ticket_key = registry_key.split("|", 2)
    ticket = db.read()["jiraTickets"].get(ticket_key)
    if ticket:
        spend_ledger.append_entry(ticket_key, provider, ticket.get(provider + "SessionId"), ticket, close_reason)


@app.post("/api/running-processes/{key}/kill")
def kill_background_process(key: str):
    """Terminate a background process for a ticket."""
    with processes_lock:
        registry_key = _process_key_from_wire(key)
        proc_info = running_processes.pop(registry_key, None) if registry_key else None
    if not proc_info:
        return {"ok": False, "error": "no process running for this ticket"}
    _terminate_process(registry_key, proc_info, "stopped")
    return {"ok": True}


@app.post("/api/tickets/{key}/handoff")
async def handoff_session(key: str, provider: str = "claude"):
    """Hand a ticket's session off to the real Claude/Codex app for deep work
    at full fidelity (images, diffs, everything the embedded plain-text
    terminal can't do) — Ticket Terminal reimplements none of that, it just
    releases its own hold and gets the user there. Never raises: worst case
    is nothing to hand off.

    The two providers are NOT symmetric here, verified live (2026-09-18):
    - codex's `app` command opens the real ChatGPT desktop app, which shares
      the same on-disk/daemon session store the CLI uses (`codex agents`
      calls it "the shared local app-server daemon") — safe to come back
      from, hence the codexHandedOffAt note in terminal_ws for the one real
      gap (no scriptable way to release it first).
    - claude has no such shared store for its desktop app: `claude://resume`
      FORKS a one-time copy into the app's own storage under a `local_<id>`
      name that isn't a valid `--resume` id (confirmed: the CLI rejects it
      outright, "not a UUID and does not match any session title"). So this
      is one-way by construction — the original session is simply never
      touched, which is why there's nothing to track or release on return.
    """
    try:
        if provider not in ("claude", "codex"):
            return {"ok": False, "error": "unknown provider"}
        jira_tickets = db.read()["jiraTickets"]
        if key not in jira_tickets:
            return {"ok": False, "error": "no such ticket"}
        ticket = jira_tickets[key]
        cwd = ticket.get("workDir") or DEFAULT_WORKDIR
        if not os.path.isdir(cwd):
            cwd = DEFAULT_WORKDIR
        executable = agent_executable(provider)
        if not executable:
            return {"ok": False, "error": provider + " is not installed or is not on the server PATH."}

        registry_key = process_key_for(key, provider)
        with processes_lock:
            proc_info = running_processes.pop(registry_key, None)
        if proc_info:
            _terminate_process(registry_key, proc_info, "handed-off")

        if provider == "claude":
            session_id = ticket.get("claudeSessionId")
            if not session_id:
                return {"ok": False, "error": "no Claude session on this ticket yet — open it here first"}
            return {"ok": True, "url": "claude://resume?session=" + session_id}

        # codex: open the real Desktop app and let its own (cwd-scoped) resume
        # picker find the session. Fire-and-forget: it's a GUI launch, nothing
        # to await.
        subprocess.Popen([executable, "app", cwd], cwd=cwd)
        db.update_ticket(key, {"codexHandedOffAt": datetime.datetime.now(datetime.timezone.utc).isoformat()})
        return {"ok": True, "opened": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _load_transcript(key: str) -> bytes:
    """Load the entire session transcript for a ticket, or empty bytes if none exists."""
    log_path = sessions_dir() / f"{key}.log"
    if log_path.exists():
        return log_path.read_bytes()
    return b""


def _save_transcript(key: str, raw: bytes) -> tuple[str, bool]:
    """Append this session's raw output to one running log per ticket (not a new
    file per open — real conversational memory now lives in Claude's own resumable
    session; this is just a raw byte trail for forensics). Returns (path, is_first)
    so the caller can note it in the Activity Log only the first time it's created."""
    directory = sessions_dir()
    directory.mkdir(parents=True, exist_ok=True)
    log_path = directory / f"{key}.log"
    is_first = not log_path.exists()
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(log_path, "ab") as f:
        f.write(f"\n\n===== session opened {stamp} =====\n\n".encode())
        f.write(raw)
    return str(log_path), is_first


@app.websocket("/ws/terminal/{key}")
async def terminal_ws(websocket: WebSocket, key: str, provider: str = "claude"):
    await websocket.accept()

    if provider not in ("claude", "codex") or key not in db.read()["jiraTickets"]:
        await websocket.close(code=1008)
        return
    executable = agent_executable(provider)
    if not executable:
        await websocket.send_text(provider + " is not installed or is not on the server PATH. Install it and sign in, then retry.")
        await websocket.close()
        return
    process_key = process_key_for(key, provider)
    log_key = key if provider == "claude" else key + ".codex"
    ticket = db.read()["jiraTickets"][key]
    cwd = ticket.get("workDir") or DEFAULT_WORKDIR
    if not os.path.isdir(cwd):
        cwd = DEFAULT_WORKDIR

    session_id = ticket.get(provider + "SessionId")
    marker = ticket.get("codexSessionMarker")
    if provider == "codex" and not session_id and marker:
        session_id = await asyncio.to_thread(codex_sessions.find_session, marker, cwd)
        if session_id:
            db.update_ticket(key, {"codexSessionId": session_id})

    # A claude /handoff never needs a check here: it forks a one-time copy
    # into the Claude app's own storage (see handoff_session's docstring) and
    # never touches this ticket's real session — reconnecting is always as
    # safe as any other reconnect. Codex is different: its /handoff opens the
    # Desktop app, which Ticket Terminal has no handle on. Can't safely
    # release it, so just say so once, as the first line the user sees here.
    if provider == "codex" and ticket.get("codexHandedOffAt"):
        await websocket.send_text("\x1b[33mNote: this may still be open in the ChatGPT app — close it there first to avoid two sessions touching the same conversation.\x1b[0m\r\n")
        db.update_ticket(key, {"codexHandedOffAt": None})

    pending_draft = None
    is_new_session = False
    is_reconnect = False
    master_fd = None
    proc = None

    stale_ws = None
    stale_reader_task = None

    transcript = bytearray()
    loop = asyncio.get_event_loop()

    async def read_pty():
        while True:
            try:
                data = await pty_io.read_chunk(master_fd)
            except OSError:
                break
            if not data:
                break
            transcript.extend(data)
            info = running_processes.get(process_key, {})
            draft_bytes = terminal_draft.draft_when_ready(info, data)
            if draft_bytes:
                try:
                    os.write(master_fd, draft_bytes)
                except OSError:
                    pass
            try:
                await websocket.send_bytes(data)
            except Exception:
                break

        try:
            await websocket.close()
        except Exception:
            pass

    # Everything below — deciding reconnect-vs-new, capturing whoever owned this
    # process's PTY before us, and claiming that ownership for this connection
    # (registering our own reader_task/ws) — happens in one lock acquisition
    # with no `await` inside it. That matters: two connections for the same
    # ticket can arrive almost simultaneously (e.g. a rapid double page-reload
    # sends two reconnects within milliseconds), and if "check who owned it"
    # and "claim it for myself" were two separate critical sections with any
    # async work between them, both connections could look up nobody owning it
    # yet and both start reading — exactly the split-output race this is meant
    # to prevent. One uninterrupted critical section means whichever of the two
    # runs second always sees the first's claim and evicts it correctly.
    with processes_lock:
        proc_info = running_processes.get(process_key)
        if proc_info and proc_info["proc"].poll() is None:
            # Process still alive — reconnect to its existing PTY for live streaming.
            # Deliberately NOT replaying the historical byte transcript here: raw PTY
            # captures accumulate hundreds of KB to MB of old escape sequences/redraws,
            # and dumping that in one blob corrupts xterm.js rendering. Full
            # conversational context survives regardless, in Claude's own .jsonl file.
            is_reconnect = True
            proc = proc_info["proc"]
            master_fd = proc_info["master_fd"]
            stale_ws = proc_info.get("ws")
            stale_reader_task = proc_info.get("reader_task")
        else:
            if proc_info:
                # Process info exists but process is dead — clean it up
                running_processes.pop(process_key, None)
            # New process needed
            if provider == "claude":
                if session_id is None or not _claude_session_exists(cwd, session_id):
                    is_new_session = True
                    session_id = str(uuid.uuid4())
                    db.update_ticket(key, {"claudeSessionId": session_id})
                agent_cmd = ["claude", "--session-id", session_id] if is_new_session else ["claude", "--resume", session_id]
            elif session_id:
                agent_cmd = ["codex", "resume", session_id]
            else:
                marker = marker or "[Ticket Terminal " + str(uuid.uuid4()) + "]"
                db.update_ticket(key, {"codexSessionMarker": marker})
                prompt = marker + " Work on " + key + ": " + ticket.get("summary", "") + "\n" + ticket.get("url", "")
                pending_draft = prompt
                agent_cmd = ["codex"]

            agent_cmd[0] = executable
            master_fd, slave_fd = pty.openpty()
            _set_winsize(master_fd, 30, 100)
            child_env = os.environ.copy()
            for k in list(child_env):
                if k.startswith("CLAUDE") or k in {"AI_AGENT", "CODEX_THREAD_ID", "CODEX_SESSION_ID", "CODEX_INTERNAL_ORIGINATOR_OVERRIDE", "CODEX_APP_TOOLS_PIPE_PATH"}:
                    del child_env[k]
            child_env.setdefault("TERM", "xterm-256color")
            try:
                proc = subprocess.Popen(
                    agent_cmd,
                    stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
                    cwd=cwd, preexec_fn=_pty_child_preexec, env=child_env,
                )
            except Exception:
                os.close(master_fd)
                raise
            finally:
                os.close(slave_fd)

            # Register this process as running in the background
            running_processes[process_key] = {"proc": proc, "master_fd": master_fd, "draft": pending_draft}

        # Claim ownership right here, atomically with the check above.
        reader_task = asyncio.create_task(read_pty())
        running_processes[process_key]["reader_task"] = reader_task
        running_processes[process_key]["ws"] = websocket

    if stale_reader_task is not None or stale_ws is not None:
        # A previous connection for this same ticket was still holding the PTY —
        # e.g. a stale browser tab, or one that dropped without a clean close
        # (laptop sleep, wifi blip), or simply lost the race above. Two readers
        # on the same master_fd would split PTY output between them
        # nondeterministically: this is exactly the "reconnected... but no
        # further output" bug, where the new viewer's bytes silently go to the
        # old, invisible connection instead. Evict it now that this connection
        # has already secured ownership, so only one reader ever owns the fd.
        if stale_reader_task is not None:
            stale_reader_task.cancel()
        if stale_ws is not None:
            try:
                await stale_ws.close()
            except Exception:
                pass

    if is_reconnect:
        try:
            await websocket.send_bytes(b"[Reconnected to background session]\n")
        except Exception:
            pass
        # The previous connection's reader already consumed whatever Claude last
        # wrote to the PTY — those bytes are gone from the kernel buffer, so there's
        # nothing left to read until Claude produces something new. The TUI won't
        # repaint on its own; it only redraws on SIGWINCH. The browser always sends
        # its real terminal size right after connecting (see terminal.js), but if
        # that size happens to match what's already set, the kernel skips the
        # signal. Nudge the size to something different first so that follow-up
        # resize is guaranteed to differ and trigger a real repaint of the current
        # screen — not a replay of history, just what's on screen right now.
        try:
            _set_winsize(master_fd, 1, 1)
        except Exception:
            pass

    try:
        while True:
            msg = await websocket.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            text = msg.get("text")
            if text is None:
                continue
            payload = json.loads(text)
            kind = payload.get("type")
            if kind == "start":
                prompt = payload.get("prompt", "")
                if is_new_session:
                    async def feed():
                        await asyncio.sleep(1.5)
                        try:
                            os.write(master_fd, (prompt + "\n").encode())
                        except OSError:
                            pass
                    asyncio.create_task(feed())
            elif kind == "input":
                try:
                    os.write(master_fd, payload.get("data", "").encode())
                except OSError:
                    pass
            elif kind == "resize":
                _set_winsize(master_fd, payload.get("rows", 30), payload.get("cols", 100))
    except WebSocketDisconnect:
        pass
    finally:
        reader_task.cancel()
        # Save transcript if this was a new session or reconnect (not just a reconnect to existing)
        if transcript:
            log_path, is_first = _save_transcript(log_key, bytes(transcript))
            if is_first:
                db.add_note(key, f"{provider.title()} session log: {log_path}")
        with processes_lock:
            proc_info = running_processes.get(process_key)
            if proc_info:
                # Only clear the reader/ws slot if a newer connection hasn't
                # already claimed it out from under this one (the eviction
                # above, from that newer connection's perspective).
                if proc_info.get("reader_task") is reader_task:
                    proc_info["reader_task"] = None
                    proc_info["ws"] = None
                # Clean up dead processes
                if proc_info["proc"].poll() is not None:
                    running_processes.pop(process_key, None)
                    # The agent CLI exited on its own (finished, or crashed) rather than
                    # via an explicit Stop click — still a genuine "session is over" moment,
                    # so record its final cost the same way kill_background_process does.
                    if session_id:
                        current_ticket = db.read()["jiraTickets"].get(key)
                        if current_ticket:
                            spend_ledger.append_entry(key, provider, session_id, current_ticket, "process-exited")


# ---------- Static frontend ----------

# board.js loads as `<script type="module">`, and browsers strictly enforce MIME
# type for module scripts (unlike classic scripts). Starlette's StaticFiles defers
# to the platform's mimetypes database for Content-Type, which isn't guaranteed to
# map .js correctly on every OS/Python build a contributor might run this on.
mimetypes.add_type("text/javascript", ".js")

app.mount("/static", StaticFiles(directory=str(PUBLIC_DIR)), name="static")


@app.get("/")
def index():
    return FileResponse(str(PUBLIC_DIR / "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=4173)
