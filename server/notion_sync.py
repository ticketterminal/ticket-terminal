"""Notion as a second ticket source, alongside Jira (see jira_sync.py, whose
shape this deliberately mirrors): one Notion database is the "project", each
page in it is a ticket, and a status/select column maps onto the board's
status/priority fields.

Auth is OAuth 2.0 against a Notion *public integration* you register yourself
(client id + secret from notion.so/my-integrations) — the server hosts the
authorize redirect and the callback, stores the resulting workspace token in
the workspace's settings.json, and refreshes it when Notion hands out a refresh
token.
The primary path, though, is a personal *internal integration* token pasted
straight in — matching how the Jira section takes a plain API token, and
needing no publicly registered OAuth app at all.

Config precedence is the same as Jira's: Settings page (settings.json)
wins over NOTION_* env vars (.env), re-read on every call so a Settings-page
save takes effect immediately. Without either, Notion sync is simply
unavailable and nothing else in the app depends on it.

Ticket fields deliberately reuse the Jira-named mirrors (`jiraStatus`,
`jiraPriority`) so every existing sort/filter/badge on the board works
unchanged; `source: "notion"` on the ticket is what tells the server which
tracker a status/priority edit pushes back to.
"""
import base64
import datetime
import os
import re
import secrets
import textwrap
import threading
import time
from pathlib import Path
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv

import auto_categorize
import content
import content_tags
import settings_store
import workspaces

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")

NOTION_API = "https://api.notion.com/v1"
NOTION_AUTHORIZE_URL = "https://api.notion.com/v1/oauth/authorize"
NOTION_TOKEN_URL = "https://api.notion.com/v1/oauth/token"
# Pinned to the last version where a database is queried directly at
# /databases/{id}/query. Newer versions (2025-09-03+) split databases into
# "data sources" with a different query endpoint; Notion keeps every version
# live per-request, so pinning here keeps this adapter working regardless of
# what the workspace itself is on.
NOTION_VERSION = "2022-06-28"
DEFAULT_REDIRECT_URI = "http://localhost:4173/api/notion/oauth/callback"
OAUTH_STATE_TTL_SECONDS = 600
# 100 rows per request. High enough that a real board is fetched whole (the
# previous value of 20 silently stopped at 2000 rows), low enough to bound a
# runaway. Hitting it is reported, never silent - see _query_all_pages.
MAX_QUERY_PAGES = 500
MAX_DESCRIPTION_BLOCKS = 100
MAX_BLOCK_DEPTH = 3
MAX_CHILD_REQUESTS_PER_PAGE = 25
REQUEST_TIMEOUT = 20

# Single-use CSRF states for in-flight OAuth handshakes: {state: expires_at}.
# In-memory on purpose — a restart mid-handshake just means clicking Connect
# again, and nothing here needs to survive that.
# {state: (expires_at, workspace slug the flow began in)}
_oauth_states: dict[str, tuple[float, str]] = {}
_oauth_lock = threading.Lock()
last_oauth_error: str | None = None

# Keyed by (workspace slug, database id): a different workspace is a different
# token, and may be a different Notion account entirely, so one workspace's
# schema must never answer another's question.
_schema_cache: dict[tuple[str, str], dict] = {}


def _cache_key(database_id: str) -> tuple[str, str]:
    return (workspaces.current(), database_id)


def _clear_workspace_cache(cache: dict) -> None:
    """Drop only the entries belonging to the workspace in hand — another
    workspace's cache is untouched by a config change over here."""
    slug = workspaces.current()
    for key in [k for k in cache if k[0] == slug]:
        del cache[key]


class NotionError(RuntimeError):
    status: int | None = None


# ---------- config ----------

def get_config():
    n = settings_store.read()["notion"]
    return {
        "client_id": n.get("clientId") or os.environ.get("NOTION_CLIENT_ID", ""),
        "client_secret": n.get("clientSecret") or os.environ.get("NOTION_CLIENT_SECRET", ""),
        "redirect_uri": n.get("redirectUri") or os.environ.get("NOTION_REDIRECT_URI", "") or DEFAULT_REDIRECT_URI,
        "access_token": n.get("accessToken") or os.environ.get("NOTION_TOKEN", ""),
        "refresh_token": n.get("refreshToken") or "",
        "auth_mode": n.get("authMode") or ("token" if not n.get("accessToken") and os.environ.get("NOTION_TOKEN") else ""),
        "workspace_name": n.get("workspaceName") or "",
        "workspace_id": n.get("workspaceId") or "",
        "database_id": _normalize_id(n.get("databaseId") or os.environ.get("NOTION_DATABASE_ID", "")),
        "status_property": n.get("statusProperty") or "",
        "priority_property": n.get("priorityProperty") or "",
        # {role: property name}; "-" means the user switched that role off.
        # Seeded from the older statusProperty/priorityProperty pair so an
        # existing setup keeps its mapping without being re-chosen.
        "roles": {**({"status": n["statusProperty"]} if n.get("statusProperty") else {}),
                  **({"priority": n["priorityProperty"]} if n.get("priorityProperty") else {}),
                  **(n.get("roles") or {})},
    }


def oauth_available() -> bool:
    c = get_config()
    return bool(c["client_id"] and c["client_secret"])


def connected() -> bool:
    return bool(get_config()["access_token"])


def configured() -> bool:
    c = get_config()
    return bool(c["access_token"] and c["database_id"])


def invalidate_cache():
    """Call after a Settings-page save — a different database has a different
    schema, so neither the cached column list nor the discovered sprint shape
    can be trusted across a config change."""
    _clear_workspace_cache(_schema_cache)
    _clear_workspace_cache(_timebox_cache)


def _normalize_id(value: str) -> str:
    """Accept a raw 32-hex id, a dashed UUID, or a pasted Notion URL
    (…/Workspace-Name-<32hex>?v=…) and return the dashed UUID Notion's API
    expects. Anything unrecognizable passes through so the error surfaces
    from Notion itself rather than being silently swallowed here."""
    value = (value or "").strip()
    compact = value.replace("-", "") if re.fullmatch(r"[0-9a-fA-F-]{32,36}", value) else value
    m = re.search(r"([0-9a-fA-F]{32})(?![0-9a-fA-F])", compact)
    if not m:
        return value
    h = m.group(1).lower()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def _not_configured_error() -> RuntimeError:
    if not connected():
        return RuntimeError("Notion isn't connected — open Settings → Notion connection and click Connect with Notion (or paste an integration token)")
    return RuntimeError("Notion sync needs a database — pick one under Settings → Notion connection")


# ---------- OAuth ----------

def build_authorize_url() -> str:
    """Where the browser goes when the user clicks Connect. The `state` is
    remembered server-side and must come back unchanged on the callback.

    It also remembers WHICH WORKSPACE the flow started from. Notion calls the
    redirect URI itself, so that request carries no `?w=` and would otherwise
    resolve to the default workspace — connecting from a second workspace's
    Settings would silently overwrite the default workspace's Notion token."""
    c = get_config()
    if not (c["client_id"] and c["client_secret"]):
        raise RuntimeError("Save a Notion client ID and client secret first — from notion.so/my-integrations, Public integration → OAuth")
    state = secrets.token_urlsafe(32)
    now = time.time()
    with _oauth_lock:
        for s, (exp, _) in list(_oauth_states.items()):
            if exp < now:
                _oauth_states.pop(s, None)
        _oauth_states[state] = (now + OAUTH_STATE_TTL_SECONDS, workspaces.current())
    return NOTION_AUTHORIZE_URL + "?" + urlencode({
        "client_id": c["client_id"],
        "redirect_uri": c["redirect_uri"],
        "response_type": "code",
        "owner": "user",
        "state": state,
    })


def consume_oauth_state(state: str) -> str | None:
    """The workspace this flow started from, exactly once per state we issued
    and that hasn't expired. None means the state was forged, replayed or
    stale — the caller must not store anything."""
    with _oauth_lock:
        entry = _oauth_states.pop(state or "", None)
    if entry is None:
        return None
    expires_at, slug = entry
    return slug if expires_at >= time.time() else None


def _token_request(body: dict) -> dict:
    c = get_config()
    basic = base64.b64encode(f"{c['client_id']}:{c['client_secret']}".encode()).decode()
    resp = requests.post(
        NOTION_TOKEN_URL, json=body, timeout=REQUEST_TIMEOUT,
        headers={"Authorization": "Basic " + basic, "Content-Type": "application/json", "Notion-Version": NOTION_VERSION},
    )
    if resp.status_code >= 400:
        try:
            detail = resp.json()
            message = detail.get("error_description") or detail.get("message") or detail.get("error") or resp.text
        except ValueError:
            message = resp.text
        raise NotionError(f"Notion token endpoint returned {resp.status_code}: {message}")
    return resp.json()


def _store_token_response(payload: dict, auth_mode: str):
    owner = payload.get("owner") or {}
    settings_store.set_section_fields("notion", {
        "authMode": auth_mode,
        "accessToken": payload.get("access_token", ""),
        # A missing/null refresh_token means this token doesn't expire — keep
        # whatever we already had rather than blanking a still-valid one.
        **({"refreshToken": payload["refresh_token"]} if payload.get("refresh_token") else {}),
        "workspaceName": payload.get("workspace_name") or (owner.get("user") or {}).get("name") or "",
        "workspaceId": payload.get("workspace_id") or "",
        "botId": payload.get("bot_id") or "",
    })


def exchange_code(code: str):
    """Second leg of the handshake: the callback's one-time code becomes the
    workspace's access token, stored to this workspace's settings.json."""
    c = get_config()
    payload = _token_request({"grant_type": "authorization_code", "code": code, "redirect_uri": c["redirect_uri"]})
    _store_token_response(payload, "oauth")
    invalidate_cache()
    return payload


def refresh_access_token():
    c = get_config()
    if not c["refresh_token"]:
        raise NotionError("Notion access token was rejected and there's no refresh token — reconnect from Settings")
    payload = _token_request({"grant_type": "refresh_token", "refresh_token": c["refresh_token"]})
    _store_token_response(payload, "oauth")


def disconnect():
    settings_store.set_section_fields("notion", {
        "authMode": "", "accessToken": "", "refreshToken": "",
        "workspaceName": "", "workspaceId": "", "botId": "",
    })
    invalidate_cache()


def set_internal_token(token: str):
    """The primary, no-OAuth path: an internal integration's secret pasted
    straight in. Validated against Notion *before* anything is stored, so a
    typo never replaces a working connection."""
    token = token.strip()
    resp = requests.get(NOTION_API + "/users/me", headers=_headers(token), timeout=REQUEST_TIMEOUT)
    if resp.status_code >= 400:
        try:
            message = resp.json().get("message") or resp.text
        except ValueError:
            message = resp.text
        raise NotionError(f"Notion rejected that token ({resp.status_code}): {message}")
    me = resp.json()
    workspace = ((me.get("bot") or {}).get("workspace_name")) or me.get("name") or ""
    settings_store.set_section_fields("notion", {
        "authMode": "token", "accessToken": token, "refreshToken": "",
        "workspaceName": workspace, "workspaceId": "", "botId": me.get("id") or "",
    })
    invalidate_cache()


# ---------- HTTP ----------

def _headers(token: str) -> dict:
    return {"Authorization": "Bearer " + token, "Notion-Version": NOTION_VERSION, "Content-Type": "application/json"}


def _request(method: str, path: str, *, retry_auth: bool = True, **kwargs) -> dict:
    c = get_config()
    if not c["access_token"]:
        raise _not_configured_error()
    resp = requests.request(method, NOTION_API + path, headers=_headers(c["access_token"]), timeout=REQUEST_TIMEOUT, **kwargs)
    if resp.status_code == 401 and retry_auth and c["refresh_token"] and c["client_id"] and c["client_secret"]:
        refresh_access_token()
        return _request(method, path, retry_auth=False, **kwargs)
    if resp.status_code >= 400:
        try:
            message = resp.json().get("message") or resp.text
        except ValueError:
            message = resp.text
        error = NotionError(f"Notion API {method} {path} returned {resp.status_code}: {message}")
        error.status = resp.status_code
        raise error
    return resp.json()


# ---------- schema / databases ----------

def list_databases() -> list[dict]:
    """Every database the integration has been granted access to (the user
    picks pages during the OAuth consent, or shares them with an internal
    integration) — for the Settings page's database picker."""
    results, cursor = [], None
    for _ in range(MAX_QUERY_PAGES):
        body = {"filter": {"value": "database", "property": "object"}, "page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        page = _request("POST", "/search", json=body)
        for item in page.get("results", []):
            results.append({"id": item["id"], "title": _rich_text_to_plain(item.get("title") or []) or "(untitled)", "url": item.get("url", "")})
        if not page.get("has_more"):
            break
        cursor = page.get("next_cursor")
    return results


def get_schema(database_id: str | None = None) -> dict:
    """The database's column definitions, cached per database (cleared on a
    Settings-page save — see invalidate_cache)."""
    database_id = _normalize_id(database_id or get_config()["database_id"])
    if not database_id:
        raise _not_configured_error()
    key = _cache_key(database_id)
    if key not in _schema_cache:
        _schema_cache[key] = _request("GET", f"/databases/{database_id}")
    return _schema_cache[key]


# ---------- role mapping: discover, never hardcode ----------
#
# The board needs a handful of ROLES (what is the title? the status? the
# description?). A Notion database can name and shape those columns any way it
# likes — this adapter must work against someone else's board, not just the one
# it was written against. So: every property is captured verbatim on the ticket
# (see capture_properties), and roles are bound EXPLICITLY, from the Settings
# page. Type-and-name suggestions exist only to pre-fill that choice; they are
# surfaced as suggestions, never silently treated as the user's decision, and a
# configured property that disappears from the schema is reported as a problem
# rather than quietly re-guessed.
#
# `types` is the hard filter (a title role can only be a title property).
# `hints` only ranks candidates of a fitting type; `solo` means "if exactly one
# property of a fitting type exists, it is unambiguous, suggest it even with no
# name match" — true for title/unique_id, false for anything a database
# plausibly has several of.
ROLES = {
    "title":       {"types": ("title",), "hints": (), "solo": True},
    "key":         {"types": ("unique_id",), "hints": ("id", "key", "ticket", "task id"), "solo": True},
    "status":      {"types": ("status", "select"), "hints": ("status", "state", "stage"), "solo": True},
    "priority":    {"types": ("select", "status"), "hints": ("priority", "prio", "severity", "urgency", "importance"), "solo": False},
    "assignee":    {"types": ("people", "created_by"), "hints": ("assignee", "owner", "reporter", "assigned", "requester", "responsible"), "solo": True},
    "description": {"types": ("rich_text", "formula"), "hints": ("summary", "description", "details", "detail", "notes", "context", "body"), "solo": False},
    "due":         {"types": ("date",), "hints": ("due", "deadline", "target", "due date"), "solo": False},
    # Relation only this iteration (select / date-on-ticket shapes are a follow-up) and NO name
    # hints: a name-based suggestion here pre-empted shape discovery entirely, so a select called
    # "Milestone" beat a relation called "Ciclo" that pointed at real dated cycles. Discovery
    # (resolve_roles_with_discovery) is the only path that binds this role when unconfigured.
    "sprint":      {"types": ("relation",), "hints": (), "solo": False},
    "epic":        {"types": ("relation",), "hints": ("epic", "parent", "initiative", "feature"), "solo": False},
    "labels":      {"types": ("multi_select",), "hints": ("label", "labels", "tag", "tags", "component", "area"), "solo": False},
}

# Roles the board can push an edit back to Notion for, and the payload shape
# Notion expects for that property type.
WRITABLE_ROLES = ("status", "priority")


def _suggest(schema: dict, role: str) -> tuple[str | None, str | None]:
    """Best guess for one role, or (None, None) when nothing fits well enough.
    Deliberately conservative: a wrong silent guess is worse than no guess,
    because an unmapped role is visible in Settings and a wrong one is not."""
    spec = ROLES[role]
    props = schema.get("properties") or {}
    candidates = [(n, p.get("type")) for n, p in props.items() if p.get("type") in spec["types"]]
    if not candidates:
        return None, None
    for name, kind in candidates:
        if name.strip().lower() in spec["hints"]:
            return name, kind
    for name, kind in candidates:
        lowered = name.strip().lower()
        if any(hint in lowered for hint in spec["hints"]):
            return name, kind
    if spec["solo"] and len(candidates) == 1:
        return candidates[0]
    return None, None


def resolve_roles(schema: dict) -> dict:
    """Bind every role for this schema. Each entry carries where the binding
    came from, so the Settings page can show "you chose this" versus "we
    guessed this" versus "nothing fits", and so a configured property that has
    since been renamed or deleted in Notion surfaces as a problem instead of
    silently falling back to a guess."""
    props = schema.get("properties") or {}
    configured = get_config()["roles"]
    out = {}
    for role in ROLES:
        chosen = (configured.get(role) or "").strip()
        if chosen == "-":  # explicit "none" — the user turned this role off
            out[role] = {"name": None, "type": None, "source": "disabled", "problem": None}
            continue
        if chosen:
            if chosen in props:
                out[role] = {"name": chosen, "type": props[chosen].get("type"), "source": "configured", "problem": None}
            else:
                out[role] = {"name": None, "type": None, "source": "configured",
                             "problem": f"the property “{chosen}” you mapped to {role} no longer exists in this database"}
            continue
        name, kind = _suggest(schema, role)
        out[role] = {"name": name, "type": kind, "source": "suggested" if name else "unmapped", "problem": None}
    return out


def role_name(roles: dict, role: str) -> str | None:
    return (roles.get(role) or {}).get("name")


def _option_names(schema: dict, name: str | None) -> list[str]:
    if not name:
        return []
    prop = (schema.get("properties") or {}).get(name) or {}
    kind = prop.get("type")
    options = (prop.get(kind) or {}).get("options") or []
    return [o.get("name", "") for o in options if o.get("name")]


def done_statuses(schema: dict, status_name: str | None) -> list[str]:
    """Which status values mean "finished" for this database. A Notion
    *status* property groups its options into To-do / In progress / Complete
    (the option names are user-chosen, the group names are not), so the
    Complete group is the authoritative answer and needs no word list. A plain
    *select* column has no groups, so fall back to matching common finished
    words — a guess, but only where Notion offers nothing better."""
    if not status_name:
        return []
    prop = (schema.get("properties") or {}).get(status_name) or {}
    kind = prop.get("type")
    body = prop.get(kind) or {}
    if kind == "status":
        by_id = {o.get("id"): o.get("name") for o in body.get("options") or []}
        for group in body.get("groups") or []:
            if (group.get("name") or "").strip().lower() == "complete":
                return [by_id[i] for i in group.get("option_ids") or [] if by_id.get(i)]
    finished = {"done", "cancelled", "canceled", "archived", "closed", "duplicate",
                "won't do", "wont do", "deferred", "shipped", "released", "complete", "completed"}
    return [o.get("name") for o in body.get("options") or [] if (o.get("name") or "").strip().lower() in finished]


def _sample_ticket_pages(database_id: str | None = None, size: int | None = None) -> list:
    """One page of the newest ticket rows, used only to see which columns are
    actually filled in (see discover_sprint_candidates). One request, and a
    failure is not worth failing the whole options read over."""
    try:
        body = {"page_size": size or SPRINT_SAMPLE_PAGES,
                "sorts": [{"timestamp": "created_time", "direction": "descending"}]}
        database_id = _normalize_id(database_id or get_config()["database_id"])
        return _request("POST", f"/databases/{database_id}/query", json=body).get("results", []) or []
    except (NotionError, requests.RequestException):
        return []


def get_options() -> dict:
    """Everything the Settings page needs to show and edit the mapping, plus
    the option lists the board's status/priority selects render from."""
    schema = get_schema()
    _clear_workspace_cache(_timebox_cache)  # see sync_all_tickets — the sprint list must be current when shown
    sample = _sample_ticket_pages()
    roles = resolve_roles_with_discovery(schema, sample_pages=sample)
    status_name = role_name(roles, "status")
    context = read_sprint_context(schema, roles)
    return {
        "databaseTitle": _rich_text_to_plain(schema.get("title") or []),
        "roles": roles,
        "roleOrder": list(ROLES),
        "roleTypes": {role: list(spec["types"]) for role, spec in ROLES.items()},
        "properties": sorted(
            ({"name": n, "type": p.get("type")} for n, p in (schema.get("properties") or {}).items()),
            key=lambda p: p["name"].lower()),
        "statuses": [{"id": n, "name": n} for n in _option_names(schema, status_name)],
        "doneStatuses": done_statuses(schema, status_name),
        "priorities": _option_names(schema, role_name(roles, "priority")),
        "sprints": sprint_summary(context["sprints"]),
        "sprintCandidates": discover_sprint_candidates(schema, sample_pages=sample),
        "sprintMarker": {**context["marker"], "options": context["options"],
                         "hasStatusProperty": context["hasStatusProperty"]},
        "problems": [r["problem"] for r in roles.values() if r.get("problem")],
    }


# ---------- sprints, found by shape rather than by name ----------
#
# Nearly every team runs sprints/iterations, and nearly every team models them
# differently: a relation to a "Sprints" database, a relation to one called
# "Cycles" or "Iterations" or something in another language entirely, or just a
# select column on the ticket. Matching on column names only ever fits the
# board it was written against, so the sprint field is DISCOVERED from the
# shape of the data instead:
#
#   a sprint is a small set of named, dated time boxes that many tickets link to
#
# so a relation is sprint-like when the database it points at has a date
# property whose values are ranges, few enough rows to be time boxes rather
# than records, and ideally a status. Each candidate is scored, the reasons are
# shown in Settings in plain words, and the user can always override — a guess
# is offered, never imposed.
#
# What every sprint is reduced to is Jira's model, adopted as the internal
# contract for every tracker: {id, name, state, start, end, url, rawStatus}
# with state in {"active", "future", "closed"}. Jira states that outright;
# Notion has no such notion, so state is DERIVED here (see derive_state) and
# everything board-side keys off it.

# Only ever a small tie-breaking bonus, never a requirement, so an
# English-named column wins a close call but a differently-named one is still
# found on shape alone.
SPRINT_NAME_HINTS = ("sprint", "iteration", "cycle", "milestone", "increment")
SPRINT_SCORE_THRESHOLD = 4
# The one word list left, and only for UNDATED sprint rows, where there is no
# other evidence at all: a row saying "Past"/"Done" is behind us, anything else
# is assumed to be ahead. Dated rows never reach it.
CLOSED_SPRINT_WORDS = {"past", "last", "done", "closed", "complete", "completed", "finished", "archived"}
MAX_TIMEBOX_ROWS = 500  # more rows than this and it is a record table, not time boxes
SPRINT_SAMPLE_PAGES = 100  # ticket rows sampled to see which relation is actually filled in

_timebox_cache: dict[tuple[str, str], dict] = {}  # keyed like _schema_cache


def _date_props(db_schema: dict) -> list[str]:
    return [n for n, p in (db_schema.get("properties") or {}).items() if p.get("type") == "date"]


def _pick_timebox_properties(db_schema: dict, rows: list) -> dict:
    """Which property is the name, the date range and the state — chosen from
    how the values actually look, not from what the columns are called."""
    props = db_schema.get("properties") or {}
    title = next((n for n, p in props.items() if p.get("type") == "title"), None)

    # The date column of a time box is the one whose values carry an END, i.e.
    # a range. A "created on"/"review by" column holds single dates.
    best_date, best_ranges = None, 0
    for name in _date_props(db_schema):
        ranges = 0
        for row in rows:
            value = ((row.get("properties") or {}).get(name) or {}).get("date") or {}
            if value.get("start") and value.get("end"):
                ranges += 1
        if ranges > best_ranges:
            best_date, best_ranges = name, ranges
    if best_date is None:
        best_date = next(iter(_date_props(db_schema)), None)

    # The status/select column supplies rawStatus — the tracker's own word for
    # the state, shown as-is and matched against the active marker. Its
    # groups are deliberately NOT read: workspaces rename and repurpose them.
    status = next((n for n, p in props.items() if p.get("type") == "status"), None)
    if status is None:
        status = next((n for n, p in props.items() if p.get("type") == "select"), None)
    return {"title": title, "date": best_date, "status": status, "datedRows": best_ranges,
            "tiling": _tiling(rows, best_date)}


def _tiling(rows: list, date_name: str | None) -> dict | None:
    """How the rows' date ranges sit on the calendar. Iterations are short and
    tile time with little overlap; epics, projects and releases run for months
    and overlap freely. This is the shape signal that separates a sprints
    database from an epics database when both are dated, both have a status
    and both are linked from tickets. None when there is too little to judge."""
    if not date_name:
        return None
    ranges = []
    for row in rows:
        start, end = _date_range((row.get("properties") or {}).get(date_name) or {})
        try:
            s, e = datetime.date.fromisoformat(start[:10]), datetime.date.fromisoformat(end[:10])
        except ValueError:
            continue
        if e >= s:
            ranges.append((s, e))
    if len(ranges) < 3:
        return None
    ranges.sort()
    durations = sorted((e - s).days + 1 for s, e in ranges)
    overlaps = sum(1 for (s1, e1), (s2, _) in zip(ranges, ranges[1:]) if s2 < e1)
    return {"medianDays": durations[len(durations) // 2], "overlapRatio": overlaps / (len(ranges) - 1)}


def _score_timebox(db_schema: dict, rows: list, picks: dict, property_name: str) -> tuple[int, list]:
    score, reasons = 0, []
    if picks["datedRows"]:
        score += 3
        reasons.append("its rows have start/end date ranges")
    elif picks["date"]:
        score += 1
        reasons.append("it has a date column")
    status_prop = (db_schema.get("properties") or {}).get(picks["status"] or "") or {}
    if status_prop.get("type") == "status":
        score += 2
        reasons.append("it has a status column with progress groups")
    elif status_prop:
        score += 1
        reasons.append("it has a state column")
    if rows and len(rows) <= MAX_TIMEBOX_ROWS:
        score += 2
        reasons.append(f"it holds {len(rows)} rows, few enough to be time boxes")
    elif len(rows) > MAX_TIMEBOX_ROWS:
        score -= 2
        reasons.append("it holds too many rows to be time boxes")
    if any(p.get("type") == "relation" for p in (db_schema.get("properties") or {}).values()):
        score += 1
        reasons.append("its rows link back to tickets")
    tiling = picks.get("tiling")
    if tiling:
        if tiling["medianDays"] <= 45 and tiling["overlapRatio"] <= 0.25:
            score += 3
            reasons.append(f"its date ranges are short (about {tiling['medianDays']} days) and rarely overlap, like iterations")
        elif tiling["medianDays"] > 120:
            score -= 2
            reasons.append(f"its date ranges run for months (about {tiling['medianDays']} days), more like epics or projects")
    if any(h in property_name.strip().lower() for h in SPRINT_NAME_HINTS):
        score += 1
        reasons.append(f"the column is called “{property_name}”")
    return score, reasons


def _fill_rate(property_name: str, sample_pages: list | None) -> float | None:
    """How much of a sample of real tickets actually has this relation filled
    in. None when there is nothing to measure."""
    if not sample_pages:
        return None
    filled = sum(1 for p in sample_pages if _relation_ids((p.get("properties") or {}).get(property_name) or {}))
    return filled / len(sample_pages)


def _database_shape(database_id: str) -> dict | None:
    """Schema, a sample of rows, and the structural picks/score for one
    database. Cached per database for the life of the config, because
    discovery costs a couple of requests per candidate and the answer only
    changes when the workspace does."""
    key = _cache_key(database_id)
    if key in _timebox_cache:
        return _timebox_cache[key]
    try:
        db_schema = _request("GET", f"/databases/{database_id}")
        rows, cursor = [], None
        while len(rows) <= MAX_TIMEBOX_ROWS:
            body = {"page_size": 100}
            if cursor:
                body["start_cursor"] = cursor
            page = _request("POST", f"/databases/{database_id}/query", json=body)
            rows.extend(page.get("results", []))
            if not page.get("has_more"):
                break
            cursor = page.get("next_cursor")
    except NotionError as error:
        # 403/404 mean the integration genuinely cannot see this database — remember that.
        # Anything else (429 rate limit, 5xx) is transient: caching it would freeze the board
        # with no sprints until a restart, so leave it uncached and try again next time.
        if error.status in (403, 404):
            _timebox_cache[key] = None
        return None
    except requests.RequestException:
        return None  # one unreachable candidate must not fail the whole options read
    shape = {"schema": db_schema, "rows": rows, "picks": _pick_timebox_properties(db_schema, rows),
             "title": _rich_text_to_plain(db_schema.get("title") or [])}
    _timebox_cache[key] = shape
    return shape


def discover_sprint_candidates(schema: dict, sample_pages: list | None = None, exclude: tuple | set = ()) -> list[dict]:
    """Every relation that could carry a sprint, best first, each with the
    reasons it scored — so Settings can explain the guess instead of asserting
    it. Relations are judged by the shape of the database they point at plus
    how many real tickets actually fill them in. Properties already bound to
    another role (`exclude`, e.g. the epic relation) are not candidates: one
    column must not silently serve two roles.

    Select/multi_select sprint columns are a follow-up and are deliberately not
    scored at all — a half-bound role that yields no sprints is worse than an
    unmapped one."""
    candidates = []
    for name, prop in (schema.get("properties") or {}).items():
        if prop.get("type") != "relation" or name in exclude:
            continue
        database_id = (prop.get("relation") or {}).get("database_id")
        if not database_id:
            continue
        shape = _database_shape(database_id)
        if not shape:
            continue
        score, reasons = _score_timebox(shape["schema"], shape["rows"], shape["picks"], name)
        rate = _fill_rate(name, sample_pages)
        if rate is not None:
            if rate == 0:
                score -= 3
                reasons.append("no recent ticket has one set")
            else:
                bonus = 1 + (rate > 0.30) + (rate > 0.60)   # graded, so 100% beats 60%
                score += bonus
                reasons.append(f"{round(rate * 100)}% of recent tickets have one set")
        candidates.append({"property": name, "type": "relation", "score": score, "reasons": reasons,
                           "target": shape["title"] or "linked database",
                           "fillRate": round(rate, 4) if rate is not None else 0.0})
    # Name is the LAST key and only orders the display; it never decides a binding (see below).
    return sorted(candidates, key=lambda c: (-c["score"], -c["fillRate"], c["property"]))


def resolve_roles_with_discovery(schema: dict, sample_pages: list | None = None) -> dict:
    """resolve_roles, plus shape discovery for the sprint role whenever the
    user has not mapped or disabled one. Kept separate from resolve_roles
    because discovery makes network calls, and the cheap version is what the
    hot paths (a status push, a per-ticket read) want.

    A genuine tie between the top two candidates is reported as a problem to
    pick from in Settings, not broken by name order: guessing wrong here would
    scope the whole board by the wrong thing, silently."""
    roles = resolve_roles(schema)
    entry = roles.get("sprint") or {}
    if entry.get("source") in ("configured", "disabled"):
        return roles
    taken = {r["name"] for role, r in roles.items() if role != "sprint" and r.get("name")}
    candidates = discover_sprint_candidates(schema, sample_pages, exclude=taken)
    best = candidates[0] if candidates else None
    if not best or best["score"] < SPRINT_SCORE_THRESHOLD:
        return roles
    if len(candidates) > 1 and candidates[1]["score"] == best["score"] and candidates[1]["fillRate"] == best["fillRate"]:
        names = " and ".join(f"“{c['property']}”" for c in candidates[:2])
        roles["sprint"] = {"name": None, "type": None, "source": "ambiguous",
                           "problem": f"{names} look equally like sprints — choose one under Settings, Notion connection",
                           "candidates": [c["property"] for c in candidates[:2]]}
        return roles
    roles["sprint"] = {"name": best["property"], "type": best["type"], "source": "discovered",
                       "problem": None, "why": best["reasons"], "target": best["target"]}
    return roles


def _date_range(prop: dict) -> tuple[str, str]:
    if not isinstance(prop, dict) or prop.get("type") != "date":
        return "", ""
    value = prop.get("date") or {}
    return value.get("start") or "", value.get("end") or value.get("start") or ""


def _today() -> str:
    return datetime.date.today().isoformat()


def derive_state(raw_status: str, start: str, end: str, marker: str = "", today: str | None = None) -> str:
    """Notion has no sprint state, so one is derived: "active", "future" or
    "closed". Three signals, most reliable first.

    1. The active marker — the status value this workspace uses for the sprint
       that is running (see infer_active_marker). It is the only signal that
       survives a gap day, when yesterday's sprint has ended and tomorrow's
       has not begun.
    2. The dates. A range covering today is running, whatever it is called, in
       any language; ended is closed, not yet begun is future.
    3. Only for an undated row, the status word itself.

    Notion's status GROUPS are deliberately not consulted: a workspace can
    rename and repurpose them ("Current"/"Future"/"Complete" in the reference
    workspace), so they are not a structural signal at all."""
    if start and not end:
        end = start  # a lone start date is a one-day box, never "active forever"
    today = today or _today()
    status = (raw_status or "").strip()
    if marker and status and status.lower() == marker.strip().lower():
        return "active"
    start, end = (start or "")[:10], (end or "")[:10]
    if start or end:
        if end and end < today:
            return "closed"
        if start and start > today:
            return "future"
        return "active"  # the range covers today — dates are evidence too
    return "closed" if status.lower() in CLOSED_SPRINT_WORDS else "future"


def infer_active_marker(sprints_raw, today: str | None = None) -> str:
    """Which status value means "running" in this workspace, read off the data
    rather than guessed from a word list: among the sprints whose dates cover
    today, if every one that has a status agrees on it, that is the marker.
    Disagreement (or nothing covering today) means no marker — better none
    than a wrong one, since a wrong one would mark the wrong sprint active."""
    today = today or _today()
    values = []
    for row in sprints_raw:
        start, end = (row.get("start") or "")[:10], (row.get("end") or "")[:10]
        if not (start and end and start <= today <= end):
            continue
        status = (row.get("rawStatus") or "").strip()
        if status:
            values.append(status)
    return values[0] if values and len(set(values)) == 1 else ""


def _covering_sprint_name(sprints_raw, marker: str, today: str | None = None) -> str:
    """The sprint whose dates cover today and whose status is the marker — the
    evidence Settings shows for an inferred marker ("detected from …")."""
    today = today or _today()
    for row in sprints_raw:
        start, end = (row.get("start") or "")[:10], (row.get("end") or "")[:10]
        if start and end and start <= today <= end and (row.get("rawStatus") or "").strip().lower() == marker.strip().lower():
            return row.get("name") or ""
    return ""


def active_marker(sprints_raw) -> dict:
    """The stored marker, refreshed from inference. A marker the user has
    CONFIRMED is never overwritten — it is the answer to the question
    inference is trying to guess — and an inference that comes back empty
    (every sprint between date ranges, which is most days in some workspaces)
    leaves the stored one alone rather than throwing it away."""
    stored = settings_store.read().get("notion") or {}
    value = (stored.get("sprintActiveMarker") or "").strip()
    source = stored.get("sprintActiveMarkerSource") or ""
    inferred = infer_active_marker(sprints_raw)
    if source != "confirmed" and inferred and inferred != value:
        settings_store.set_section_fields("notion", {"sprintActiveMarker": inferred,
                                                     "sprintActiveMarkerSource": "inferred"})
        value, source = inferred, "inferred"
    if value and not source:
        source = "inferred"
    return {"value": value, "source": source,
            "inferredFrom": _covering_sprint_name(sprints_raw, value) if value else ""}


def read_sprint_context(schema: dict, roles: dict) -> dict:
    """Everything known about this database's sprints in one read: the sprints
    themselves (contract shape, keyed by page id), the active marker, and the
    sprints database's own status options so Settings can offer them. Empty
    when the sprint role is unmapped or is not a relation — a select-valued
    sprint column names its sprint inline and has no database to read."""
    empty = {"sprints": {}, "marker": {"value": "", "source": "", "inferredFrom": ""},
             "options": [], "hasStatusProperty": False}
    entry = roles.get("sprint") or {}
    if entry.get("type") != "relation" or not entry.get("name"):
        return empty
    database_id = (((schema.get("properties") or {}).get(entry["name"]) or {}).get("relation") or {}).get("database_id")
    if not database_id:
        return empty
    shape = _database_shape(database_id)
    if not shape:
        return empty

    picks = shape["picks"]
    raw = []
    for row in shape["rows"]:
        props = row.get("properties") or {}
        name = _prop_text(props.get(picks["title"])) if picks["title"] else ""
        status = _prop_text(props.get(picks["status"])) if picks["status"] else ""
        start, end = _date_range(props.get(picks["date"])) if picks["date"] else ("", "")
        raw.append({"id": row["id"], "name": name or "(untitled)", "rawStatus": status,
                    "start": start[:10], "end": end[:10], "url": row.get("url", "")})

    marker = active_marker(raw)
    sprints = {}
    for row in raw:
        sprints[row["id"]] = {**row, "state": derive_state(row["rawStatus"], row["start"], row["end"], marker["value"])}
    return {"sprints": sprints, "marker": marker,
            "options": _option_names(shape["schema"], picks["status"]),
            "hasStatusProperty": bool(picks["status"])}


def read_sprints(schema: dict, roles: dict) -> dict:
    """Every sprint the mapped/discovered sprint relation can refer to, keyed
    by page id, in the contract shape {id, name, state, start, end, url,
    rawStatus}."""
    return read_sprint_context(schema, roles)["sprints"]


def sprint_summary(sprints: dict) -> list[dict]:
    """For the board's selector: whatever is running at the top, then the rest
    newest first, undated ones last."""
    rows = sorted(sprints.values(), key=lambda s: s["name"].lower())
    rows.sort(key=lambda s: s["start"] or "", reverse=True)  # newest first; undated ("") fall to the end
    rows.sort(key=lambda s: 0 if s["state"] == "active" else 1)  # stable, so the above survives
    return rows


def ticket_sprint(page: dict, roles: dict, sprints: dict) -> dict:
    """The sprint fields for one ticket. A ticket can sit in several sprints
    (carry-over): all of them are kept, and the running one is the one shown.
    Only the relation shape is read — a select- or date-valued sprint column
    is a separate shape this does not yet model, and a half-filled answer
    would be worse than none."""
    empty = {"sprint": "", "sprintIds": [], "sprintNames": [], "sprintState": ""}
    entry = roles.get("sprint") or {}
    name = entry.get("name")
    if not name:
        return empty
    prop = (page.get("properties") or {}).get(name) or {}
    if prop.get("type") != "relation":
        return empty

    ids = sorted(_relation_ids(prop))  # stable order: a reorder of the same links is not a change
    linked = [sprints[i] for i in ids if i in sprints]
    names = [s["name"] for s in linked]
    chosen = next((s for s in linked if s["state"] == "active"), None)
    if chosen is None and linked:
        dated = [s for s in linked if s["start"]]
        chosen = max(dated, key=lambda s: s["start"]) if dated else linked[0]
    return {
        "sprint": chosen["name"] if chosen else "",
        "sprintIds": ids, "sprintNames": names,
        "sprintState": chosen["state"] if chosen else "",
    }


# ---------- page → ticket ----------

def _rich_text_to_plain(rich: list) -> str:
    return "".join((r.get("plain_text") or "") for r in rich or [])


def _prop_text(prop: dict) -> str:
    """One readable string for ANY Notion property type. Every type Notion
    defines is handled (or explicitly rendered as a count), because this feeds
    the generic property capture — an unrecognized type returning "" would
    silently drop a column this adapter was never told about, which is exactly
    the tailoring this module must avoid."""
    if not isinstance(prop, dict):
        return ""
    kind = prop.get("type")
    value = prop.get(kind)
    if kind in ("title", "rich_text"):
        return _rich_text_to_plain(value or [])
    if kind in ("select", "status"):
        return (value or {}).get("name", "") if value else ""
    if kind == "multi_select":
        return ", ".join(o.get("name", "") for o in value or [])
    if kind == "unique_id":
        if not value or value.get("number") is None:
            return ""
        return f"{value['prefix']}-{value['number']}" if value.get("prefix") else str(value["number"])
    if kind in ("people", "created_by", "last_edited_by"):
        people = value if isinstance(value, list) else [value]
        return ", ".join(p.get("name", "") for p in people if isinstance(p, dict) and p.get("name"))
    if kind == "number":
        return "" if value is None else str(value)
    if kind == "checkbox":
        return "yes" if value else "no"
    if kind in ("url", "email", "phone_number", "created_time", "last_edited_time"):
        return value or ""
    if kind == "date":
        if not value:
            return ""
        start, end = value.get("start", ""), value.get("end")
        return f"{start} → {end}" if end else start
    if kind == "files":
        return ", ".join(f.get("name", "") for f in value or [] if f.get("name"))
    if kind == "formula":
        inner = value or {}
        return _prop_text({"type": inner.get("type"), inner.get("type"): inner.get(inner.get("type"))}) if inner.get("type") else ""
    if kind == "rollup":
        inner = value or {}
        if inner.get("type") == "array":
            return ", ".join(filter(None, (_prop_text(item) for item in inner.get("array") or [])))
        return _prop_text({"type": inner.get("type"), inner.get("type"): inner.get(inner.get("type"))}) if inner.get("type") else ""
    if kind == "relation":
        # Resolving each related page's title would cost one request per link;
        # the count keeps the column visible without that, and the role-mapped
        # relations (epic/sprint) store their ids separately for later use.
        count = len(value or [])
        return f"{count} linked page{'' if count == 1 else 's'}" if count else ""
    if kind in ("verification", "button"):
        return ""
    return ""


def _relation_ids(prop: dict) -> list[str]:
    if not isinstance(prop, dict) or prop.get("type") != "relation":
        return []
    return [r["id"] for r in prop.get("relation") or [] if isinstance(r, dict) and r.get("id")]


def capture_properties(page: dict) -> dict:
    """Every non-empty property on this page, by name. This is the anti-
    tailoring guarantee: whatever columns a database has — sprints, story
    points, services, environments, anything — survive onto the ticket even
    when no role maps to them, so nothing is lost just because this adapter
    did not anticipate it."""
    captured = {}
    for name, prop in (page.get("properties") or {}).items():
        text = _prop_text(prop)
        if text:
            captured[name] = text
    return captured


def _file_url(node: dict) -> str:
    """Notion returns either an S3 link it signs (expiring) or an external URL."""
    if not isinstance(node, dict):
        return ""
    return (node.get("external") or {}).get("url") or (node.get("file") or {}).get("url") or ""


def property_attachments(page: dict) -> list[dict]:
    out = []
    for name, prop in (page.get("properties") or {}).items():
        if (prop or {}).get("type") != "files":
            continue
        for entry in prop.get("files") or []:
            url = _file_url(entry)
            if url:
                out.append({"name": entry.get("name") or name, "url": url, "kind": "file", "from": name})
    return out


def _block_line(block: dict, attachments: list) -> str | None:
    """One block rendered as text. Media blocks become markdown links and also
    register in `attachments` — previously they produced nothing at all, so a
    ticket whose content was a screenshot or an attached PDF imported with an
    empty description and no trace that a file existed."""
    kind = block.get("type", "")
    body = block.get(kind) or {}
    text = _rich_text_to_plain(body.get("rich_text") or body.get("text") or [])

    if kind in ("image", "file", "pdf", "video", "audio"):
        url = _file_url(body)
        if not url:
            return None
        caption = _rich_text_to_plain(body.get("caption") or [])
        name = caption or body.get("name") or kind
        attachments.append({"name": name, "url": url, "kind": kind, "from": "body"})
        return f"[{kind}: {name}]({url})"
    if kind in ("bookmark", "embed", "link_preview"):
        url = body.get("url") or ""
        if not url:
            return None
        attachments.append({"name": _rich_text_to_plain(body.get("caption") or []) or url, "url": url, "kind": kind, "from": "body"})
        return f"[{url}]({url})"
    if kind == "child_page":
        return "[sub-page: " + (body.get("title") or "") + "]"
    if kind == "child_database":
        return "[sub-database: " + (body.get("title") or "") + "]"
    if kind == "table_row":
        cells = body.get("cells") or []
        return "| " + " | ".join(_rich_text_to_plain(c) for c in cells) + " |"
    if kind == "bulleted_list_item":
        return "- " + text
    if kind == "to_do":
        return ("[x] " if body.get("checked") else "[ ] ") + text
    if kind.startswith("heading_"):
        return "\n" + text + "\n"
    if kind == "code":
        return "```" + (body.get("language") or "") + "\n" + text + "\n```"
    if kind == "quote":
        return "> " + text
    if kind == "equation":
        return body.get("expression") or ""
    if kind == "divider":
        return "---"
    if kind in ("paragraph", "callout", "toggle", "synced_block", "column_list", "column", "table", "template", "breadcrumb", "table_of_contents"):
        return text  # container blocks carry their content in children
    return text


def _blocks_to_text(blocks: list, attachments: list | None = None, fetch_children=None, depth: int = 0) -> str:
    """Render a page body. Notion nests heavily (toggles, columns, synced
    blocks, table rows), and a flat top-level read silently loses whatever
    lives inside them — so children are descended into when `fetch_children`
    is supplied, bounded by MAX_BLOCK_DEPTH and the caller's request budget."""
    attachments = attachments if attachments is not None else []
    lines = []
    number = 0
    for block in blocks:
        kind = block.get("type", "")
        if kind == "numbered_list_item":
            number += 1
            line = f"{number}. " + _rich_text_to_plain((block.get(kind) or {}).get("rich_text") or [])
        else:
            number = 0
            line = _block_line(block, attachments)
        if line is not None and line != "":
            lines.append(line)
        if block.get("has_children") and fetch_children and depth < MAX_BLOCK_DEPTH:
            child_text = _blocks_to_text(fetch_children(block["id"]), attachments, fetch_children, depth + 1)
            if child_text:
                lines.append(textwrap.indent(child_text, "  ") if depth else child_text)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def fetch_page_content(page_id: str) -> tuple[str, list[dict]]:
    """The page body as text, plus every file/link it references. Child-block
    reads are capped per page so one pathologically nested page cannot spend
    an unbounded number of requests during a full-database sync."""
    budget = [MAX_CHILD_REQUESTS_PER_PAGE]

    def fetch_children(block_id: str) -> list:
        if budget[0] <= 0:
            return []
        budget[0] -= 1
        try:
            return _request("GET", f"/blocks/{block_id}/children", params={"page_size": MAX_DESCRIPTION_BLOCKS}).get("results", [])
        except NotionError:
            return []  # a single unreadable child block must not fail the whole import

    attachments: list[dict] = []
    top = _request("GET", f"/blocks/{page_id}/children", params={"page_size": MAX_DESCRIPTION_BLOCKS}).get("results", [])
    return _blocks_to_text(top, attachments, fetch_children), attachments


def _fallback_key(page_id: str) -> str:
    return "NOTION-" + page_id.replace("-", "")[:8].upper()


def page_to_fields(page: dict, roles: dict) -> dict:
    """The board-facing fields of one ticket, from one database row.

    `jiraStatus`/`jiraPriority` keep their Jira-era names so every existing
    board sort, filter and badge works unchanged for both sources; `source`
    on the ticket is what says which tracker an edit pushes back to."""
    props = page.get("properties") or {}

    def text_for(role):
        name = role_name(roles, role)
        return _prop_text(props.get(name)) if name else ""

    key = text_for("key")
    if key and "-" not in key:
        key = "NOTION-" + key  # a prefix-less unique_id is just a number
    return {
        "key": key or _fallback_key(page["id"]),
        "summary": text_for("title"),
        "url": page.get("url", ""),
        "issueType": "Task",
        "jiraStatus": text_for("status"),
        "jiraPriority": text_for("priority"),
        "reporter": text_for("assignee"),
        "dueDate": text_for("due"),
        "createdAt": page.get("created_time", ""),
        "updatedAt": page.get("last_edited_time", ""),
        "notionLastEdited": page.get("last_edited_time", ""),
        "notionProperties": capture_properties(page),
    }


def _query_all_pages(database_id: str) -> tuple[list[dict], bool]:
    """Every row of the database, NEWEST FIRST, with a hard request ceiling.

    Newest-first is deliberate and load-bearing: a full sync of a large
    database is long, and an interrupted one must leave the tickets people
    actually work on imported rather than the oldest archive. (Ascending order
    plus a page cap is what previously imported four thousand rows' worth of
    2023 and never reached this year.) Returns whether the ceiling was hit, so
    the caller can report truncation instead of silently losing rows."""
    results, cursor = [], None
    for _ in range(MAX_QUERY_PAGES):
        body = {"page_size": 100, "sorts": [{"timestamp": "created_time", "direction": "descending"}]}
        if cursor:
            body["start_cursor"] = cursor
        page = _request("POST", f"/databases/{database_id}/query", json=body)
        results.extend(page.get("results", []))
        if not page.get("has_more"):
            return results, False
        cursor = page.get("next_cursor")
    return results, True


def _assemble_description(page: dict, roles: dict, body_text: str) -> str:
    """A ticket's description can live in a property (many boards keep a
    Summary/Description column), in the page body, or in both — so take both,
    property first. Reading only the body is what left most tickets blank."""
    parts = []
    name = role_name(roles, "description")
    if name:
        text = _prop_text((page.get("properties") or {}).get(name))
        if text:
            parts.append(text)
    if body_text:
        parts.append(body_text)
    return "\n\n".join(parts)


def _unique_key(preferred: str, page_id: str, taken) -> str:
    """A ticket key that is free. The preferred key can already belong to a
    Jira issue or to another Notion page whose ID column collides; the
    page-id fallback can itself be taken in a (rare) 8-hex-char collision, so
    it is checked too rather than assumed free — writing to a taken key would
    shallow-merge one ticket's data over another's."""
    if preferred and preferred not in taken:
        return preferred
    fallback = _fallback_key(page_id)
    if fallback not in taken:
        return fallback
    compact = page_id.replace("-", "").upper()
    for size in range(12, len(compact) + 1, 4):
        candidate = "NOTION-" + compact[:size]
        if candidate not in taken:
            return candidate
    return "NOTION-" + compact


def sync_all_tickets(db) -> dict:
    """Import every row of the configured database and refresh tracked ones.

    Unlike Jira's discovery (which deliberately never reaches back before the
    original import), the whole database is in scope: choosing a database IS
    the scoping decision. Rows come back newest-first so an interrupted run
    leaves current work imported.

    Human-owned fields (category, team, notes, sessions, MR links) are never
    touched. Page bodies and category classification are spent only on tickets
    that are not already finished — on a database with thousands of archived
    rows, fetching and classifying all of them costs a great deal and buys
    nothing, and a later reopen changes last_edited_time, which pulls the body
    in then."""
    if not configured():
        raise _not_configured_error()
    c = get_config()
    schema = get_schema(c["database_id"])
    _clear_workspace_cache(_timebox_cache)  # sprint rows change weekly; a cached read from last sync would hide a new sprint
    pages, truncated = _query_all_pages(c["database_id"])
    # The rows are already in hand, so sprint discovery gets its sample for
    # free: which relation is actually filled in is what tells a live sprint
    # column from an archival one.
    roles = resolve_roles_with_discovery(schema, sample_pages=pages[:200])
    problems = [r["problem"] for r in roles.values() if r.get("problem")]
    finished = set(done_statuses(schema, role_name(roles, "status")))
    sprints = read_sprints(schema, roles)  # one or two requests, not one per ticket

    data = db.read()
    tracked = data["jiraTickets"]
    by_page_id = {t["notionPageId"]: k for k, t in tracked.items() if t.get("notionPageId")}
    category_terms = []
    for category in content.read_categories():
        category_terms.extend([category.get("id", ""), category.get("name", "")])

    added, changed, classify_candidates, tag_candidates = [], [], [], []

    for page in pages:
        fields = {**page_to_fields(page, roles), **ticket_sprint(page, roles, sprints)}
        existing_key = by_page_id.get(page["id"])
        is_done = bool(finished) and fields["jiraStatus"] in finished
        ticket = tracked.get(existing_key or "", {})

        if existing_key is None:
            key = _unique_key(fields["key"], page["id"], tracked)
            body, attachments = ("", [])
            if not is_done:
                body, attachments = fetch_page_content(page["id"])
            attachments = attachments + property_attachments(page)
            description = _assemble_description(page, roles, body)
            record = {
                **fields, "key": key, "source": "notion", "notionPageId": page["id"],
                "description": description, "attachments": attachments,
                # False for a finished ticket, whose body we deliberately skip
                # — so if it is ever reopened the body is pulled in then,
                # rather than every sync re-reading a page it already has.
                "notionBodyFetched": not is_done,
                "categories": [], "suggestedCategories": [],
                "team": "", "status": "pending", "reviewed": False,
            }
            db.update_ticket(key, record)
            tracked[key] = record
            by_page_id[page["id"]] = key
            added.append(key)
        else:
            key = existing_key
            patch = {k: v for k, v in fields.items() if k not in ("key", "updatedAt") and v != ticket.get(k)}
            description = ticket.get("description", "")
            edited = fields["notionLastEdited"] != ticket.get("notionLastEdited")
            if not is_done and (edited or not ticket.get("notionBodyFetched")):
                body, attachments = fetch_page_content(page["id"])
                attachments = attachments + property_attachments(page)
                description = _assemble_description(page, roles, body)
                patch["notionBodyFetched"] = True
                if description != ticket.get("description", ""):
                    patch["description"] = description
                if attachments != (ticket.get("attachments") or []):
                    patch["attachments"] = attachments
            if patch:
                db.update_ticket(key, patch)
                ticket = {**ticket, **patch}
                tracked[key] = ticket
                changed.append(key)

        if is_done:
            continue
        # Categories: ask once per ticket, and only for work that is still
        # open. `categoryGuessAt` is stamped ONLY after a classification call
        # actually succeeded, so a run where the CLI is signed out or broken
        # leaves tickets unstamped and they are retried next sync — stamping
        # at import regardless is what previously made this retry unreachable.
        current = tracked.get(key, {})
        if not current.get("reviewed") and not current.get("categories") and not current.get("categoryGuessAt"):
            classify_candidates.append({"key": key, "summary": fields["summary"], "description": description})

        tag_source_hash = content_tags.source_hash(fields["summary"], description, category_terms)
        if tag_source_hash != current.get("contentTagSourceHash") or not current.get("contentTags"):
            tag_candidates.append({"key": key, "summary": fields["summary"], "description": description,
                                   "sourceHash": tag_source_hash, "excludedTags": category_terms})

    categorized, category_error = [], None
    if classify_candidates:
        try:
            guesses = auto_categorize.classify_many(classify_candidates)
            for candidate in classify_candidates:
                guess = guesses.get(candidate["key"], [])
                db.update_ticket(candidate["key"], {
                    "categories": guess, "suggestedCategories": guess, "categoryGuessAt": _now_iso(),
                })
                if guess:
                    categorized.append(candidate["key"])
        except Exception as error:
            # No stamp written, so every candidate is retried next sync.
            category_error = str(error)

    tagged, tag_error = [], None
    if tag_candidates:
        try:
            generated = content_tags.generate(tag_candidates)
            for candidate in tag_candidates:
                tags = generated.get(candidate["key"])
                if not tags:
                    continue
                db.update_ticket(candidate["key"], {"contentTags": tags, "contentTagSourceHash": candidate["sourceHash"]})
                tagged.append(candidate["key"])
        except Exception as error:
            tag_error = str(error)  # fields still refreshed; next sync retries tags

    return {"checked": len(pages), "updated": len(changed), "changed": changed,
            "added": added, "categorized": categorized, "tagged": tagged,
            "sprints": sprint_summary(sprints),
            "tagError": tag_error, "categoryError": category_error,
            "truncated": truncated, "mappingProblems": problems}


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


# ---------- pushes back to Notion ----------

def _set_property(ticket: dict, role: str, value: str):
    if not configured():
        raise _not_configured_error()
    schema = get_schema()
    roles = resolve_roles(schema)
    entry = roles.get(role) or {}
    name, kind = entry.get("name"), entry.get("type")
    if not name:
        raise NotionError(entry.get("problem")
                          or f"no {role} column is mapped for this database — choose one under Settings, Notion connection")
    if kind not in ("status", "select"):
        raise NotionError(f"the {role} column “{name}” is a {kind} property, which this board cannot write back to")
    _request("PATCH", f"/pages/{ticket['notionPageId']}", json={"properties": {name: {kind: {"name": value}}}})


def set_status(ticket: dict, status_name: str):
    _set_property(ticket, "status", status_name)


def set_priority(ticket: dict, priority_name: str):
    _set_property(ticket, "priority", priority_name)
