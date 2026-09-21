"""Tiny JSON-file store for the Settings-page-editable config (Jira credentials,
Notion connection, memory source directory) — same lock + atomic-write pattern
as db.py. Kept separate from db.json since this holds credentials, not board
data, and from .env since .env is deliberately still supported as the
bootstrap/scriptable fallback (see jira_sync.py / notion_sync.py /
memory_analysis.py for the precedence rule: a non-empty value here wins over
the corresponding env var)."""
import json
import threading

import workspaces

_lock = threading.Lock()


def settings_path():
    """Per-workspace: a different workspace is a different tracker connection
    (and, for Notion, possibly a different account entirely). Resolved per
    call through workspaces.py rather than pinned at import."""
    return workspaces.path("settings.json")

# Write-only secrets: a blank value in a Settings-page PUT means "leave the
# stored value alone", never "clear it" — the browser never sees the real value
# (only a last-4 preview), so it can't echo it back on save. Clearing goes
# through set_section_fields() (e.g. Notion disconnect), which writes exactly.
SECRET_FIELDS = {
    "jira": {"apiToken"},
    "notion": {"clientSecret", "accessToken", "refreshToken"},
}


def _empty():
    return {
        "jira": {"baseUrl": "", "email": "", "apiToken": "", "projectKey": ""},
        "notion": {
            # OAuth app credentials (a "public integration" in Notion's terms).
            "clientId": "", "clientSecret": "", "redirectUri": "",
            # Whatever is currently authorized — filled in by the OAuth callback,
            # or by pasting an internal-integration token (authMode "token").
            "authMode": "", "accessToken": "", "refreshToken": "",
            "workspaceName": "", "workspaceId": "", "botId": "",
            # Which database is the ticket source and how its columns map.
            "databaseId": "", "statusProperty": "", "priorityProperty": "",
            # {role: property name} — see notion_sync.ROLES. "-" disables a role.
            "roles": {},
            # Which sprint-status value means "running", and whether that was inferred or confirmed.
            "sprintActiveMarker": "", "sprintActiveMarkerSource": "",
        },
        "memoryDir": "",
    }


def read():
    path = settings_path()
    with _lock:
        if not path.exists():
            return _empty()
        with open(path) as f:
            data = json.load(f)
    # Tolerate a partially-shaped file (e.g. hand-edited, or written by an
    # older version of this store) rather than KeyError-ing on a missing field.
    defaults = _empty()
    for section in ("jira", "notion"):
        defaults[section].update(data.get(section) or {})
    defaults.update({k: v for k, v in data.items() if k not in ("jira", "notion")})
    return defaults


def write(settings):
    path = settings_path()
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w") as f:
            json.dump(settings, f, indent=2, sort_keys=True)
        tmp.replace(path)  # atomic on POSIX


def update(patch):
    """Merge patch into the stored settings — each section dict is merged
    field-by-field (not replaced wholesale), so e.g. saving just a new
    projectKey doesn't require resending the token. A blank value for any
    SECRET_FIELDS entry is treated as "leave unchanged", not "clear it" —
    see server/main.py's PUT /api/settings."""
    settings = read()
    for section, secrets in SECRET_FIELDS.items():
        for field, value in ((patch or {}).get(section) or {}).items():
            if field in secrets and not value:
                continue  # blank/omitted secret means "don't change it"
            settings[section][field] = value
    if "memoryDir" in (patch or {}):
        settings["memoryDir"] = patch["memoryDir"]
    write(settings)
    return settings


def set_section_fields(section, fields):
    """Write these fields exactly as given, blanks included — the server-side
    path (OAuth callback storing tokens, disconnect clearing them), where a
    blank genuinely means "clear"."""
    settings = read()
    settings[section].update(fields)
    write(settings)
    return settings
