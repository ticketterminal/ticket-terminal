"""The server's own live read of Jira status/priority — independent of any
Claude Code session (which is how this data got refreshed before). Config
comes from the Settings page (data/settings.json, see settings_store.py) if
set, else JIRA_BASE_URL / JIRA_EMAIL / JIRA_API_TOKEN / JIRA_PROJECT_KEY in the
environment (see .env.example) as a scriptable fallback; if neither is set,
sync is simply unavailable and the rest of the app works fine without it.
Config is re-read on every call (not cached at import) so a Settings-page save
takes effect immediately, no server restart needed.
"""
import datetime
import os
import re
from pathlib import Path

import requests
from dotenv import load_dotenv

import auto_categorize
import content
import content_tags
import settings_store
import workspaces

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")


def _adf_to_text(node) -> str:
    """Jira API v3 returns `description` as Atlassian Document Format — a
    nested JSON tree, not plain text. Preserve its readable block structure."""
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return ""
    node_type = node.get("type", "")
    if node_type == "text":
        return node.get("text", "")
    if node_type == "hardBreak":
        return "\n"
    if node_type == "rule":
        return "\n---\n"

    children = node.get("content", []) or []
    if node_type in {"bulletList", "orderedList"}:
        start = int((node.get("attrs") or {}).get("order", 1))
        lines = []
        for index, child in enumerate(children):
            item = _adf_to_text(child).strip()
            prefix = "- " if node_type == "bulletList" else f"{start + index}. "
            item_lines = item.splitlines() or [""]
            lines.append(prefix + item_lines[0])
            lines.extend("  " + line for line in item_lines[1:])
        return "\n".join(lines) + "\n\n"

    text = "".join(_adf_to_text(child) for child in children)
    if node_type in {"paragraph", "heading", "codeBlock", "blockquote", "panel"}:
        return text.strip() + "\n\n" if text.strip() else ""
    if node_type == "doc":
        text = "\n".join(line.rstrip() for line in text.splitlines())
        return re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def get_config():
    jira = settings_store.read()["jira"]
    return {
        "base_url": (jira.get("baseUrl") or os.environ.get("JIRA_BASE_URL", "")).rstrip("/"),
        "email": jira.get("email") or os.environ.get("JIRA_EMAIL", ""),
        "api_token": jira.get("apiToken") or os.environ.get("JIRA_API_TOKEN", ""),
        "project": jira.get("projectKey") or os.environ.get("JIRA_PROJECT_KEY", "PROJ"),
    }


def configured() -> bool:
    c = get_config()
    return bool(c["base_url"] and c["email"] and c["api_token"])


def invalidate_cache():
    """Call after a Settings-page save — a new Jira instance/project can have
    a different workflow, so the cached status list (see
    get_workflow_statuses) can't be trusted across a config change."""
    _workflow_statuses_cache.pop(workspaces.current(), None)


def _chunks(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _newest_tracked_created_at(data):
    latest = None
    for t in data["jiraTickets"].values():
        raw = t.get("createdAt")
        if not raw:
            continue
        try:
            dt = datetime.datetime.fromisoformat(raw)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        if latest is None or dt > latest:
            latest = dt
    return latest


def discover_new_tickets(db) -> dict:
    """Pull in tickets created since the newest one already tracked —
    deliberately NOT a full backlog re-scan: whatever predates your own
    original import was left out on purpose, and this must never reach back
    into that. New tickets get a best-effort category guess from
    auto_categorize.classify() (an actual LLM call, not a keyword heuristic),
    but stay marked reviewed:false with the usual "new" badge regardless of
    whether the guess landed — a guess is not the same as human review. If
    classification fails for any reason the ticket still gets imported with
    empty categories, same as before this existed; a bad or missing guess
    must never block the import itself.

    A 6-hour safety margin on the cutoff means this can occasionally re-see
    an already-tracked ticket; the "already tracked" check below just skips
    those, so erring toward a wider window is harmless, unlike erring narrow
    and silently missing one."""
    if not configured():
        raise RuntimeError("Jira sync not configured — set it up on the Settings page, or copy .env.example to .env")
    c = get_config()

    data = db.read()
    newest = _newest_tracked_created_at(data)
    if newest is None:
        return {"found": 0, "added": []}
    cutoff = (newest - datetime.timedelta(hours=6)).strftime("%Y-%m-%d %H:%M")

    resp = requests.post(
        f"{c['base_url']}/rest/api/3/search/jql",
        json={
            "jql": f'project = {c["project"]} AND created > "{cutoff}" ORDER BY created ASC',
            "fields": ["summary", "description", "status", "priority", "reporter", "created", "updated", "issuetype"],
            "maxResults": 50,
        },
        auth=(c["email"], c["api_token"]),
        timeout=15,
    )
    resp.raise_for_status()
    issues = resp.json().get("issues", [])

    added = []
    for issue in issues:
        key = issue["key"]
        if key in data["jiraTickets"]:
            continue
        fields = issue.get("fields", {})
        summary = fields.get("summary", "")
        description = _adf_to_text(fields.get("description"))
        guess = auto_categorize.classify(summary, description)
        db.update_ticket(key, {
            "key": key,
            "summary": summary,
            "description": description,
            "url": f"{c['base_url']}/browse/{key}",
            "issueType": (fields.get("issuetype") or {}).get("name", "Task"),
            "jiraStatus": (fields.get("status") or {}).get("name", ""),
            "jiraPriority": (fields.get("priority") or {}).get("name", ""),
            "reporter": (fields.get("reporter") or {}).get("displayName", ""),
            "categories": guess,
            "suggestedCategories": guess,
            "team": "",
            "status": "pending",
            "reviewed": False,
            "createdAt": fields.get("created", ""),
            "updatedAt": fields.get("updated", ""),
        })
        added.append(key)

    return {"found": len(issues), "added": added}


def sync_all_tickets(db) -> dict:
    """Refresh Jira fields and content tags for every tracked ticket.

    Categories/team/notes remain human-owned. Tags are regenerated only when
    the Jira title or description hash changes, so periodic refreshes do not
    repeatedly spend model tokens on unchanged content.
    """
    if not configured():
        raise RuntimeError("Jira sync not configured — set it up on the Settings page, or copy .env.example to .env")
    c = get_config()

    added = discover_new_tickets(db)["added"]

    data = db.read()
    keys = list(data["jiraTickets"].keys())
    changed_keys = []
    tag_candidates = []
    category_terms = []
    for category in content.read_categories():
        category_terms.extend([category.get("id", ""), category.get("name", "")])

    for batch in _chunks(keys, 50):
        jql = "key in (%s)" % ",".join(batch)
        resp = requests.post(
            # Atlassian retired the old /rest/api/3/search (410 Gone, confirmed
            # live 2026-09-06) in favor of this one — same request/response shape.
            f"{c['base_url']}/rest/api/3/search/jql",
            json={"jql": jql, "fields": ["summary", "description", "status", "priority"], "maxResults": len(batch)},
            auth=(c["email"], c["api_token"]),
            timeout=15,
        )
        resp.raise_for_status()
        for issue in resp.json().get("issues", []):
            key = issue["key"]
            fields = issue.get("fields", {})
            status_name = (fields.get("status") or {}).get("name")
            priority_name = (fields.get("priority") or {}).get("name")
            ticket = data["jiraTickets"].get(key, {})
            summary = fields.get("summary") or ticket.get("summary", "")
            description = _adf_to_text(fields.get("description"))
            tag_source_hash = content_tags.source_hash(summary, description, category_terms)
            patch = {}
            if summary != ticket.get("summary", ""):
                patch["summary"] = summary
            if description != ticket.get("description", ""):
                patch["description"] = description
            if status_name and status_name != ticket.get("jiraStatus"):
                patch["jiraStatus"] = status_name
            if priority_name and priority_name != ticket.get("jiraPriority"):
                patch["jiraPriority"] = priority_name
            if patch:
                db.update_ticket(key, patch)
                changed_keys.append(key)

            if tag_source_hash != ticket.get("contentTagSourceHash") or not ticket.get("contentTags"):
                tag_candidates.append({
                    "key": key,
                    "summary": summary,
                    "description": description,
                    "sourceHash": tag_source_hash,
                    "excludedTags": category_terms,
                })

    tagged = []
    tag_error = None
    if tag_candidates:
        try:
            generated = content_tags.generate(tag_candidates)
            for candidate in tag_candidates:
                tags = generated.get(candidate["key"])
                if not tags:
                    continue
                db.update_ticket(candidate["key"], {
                    "contentTags": tags,
                    "contentTagSourceHash": candidate["sourceHash"],
                })
                tagged.append(candidate["key"])
        except Exception as error:
            # Jira status/priority refresh still succeeds. Existing tags and
            # hashes remain unchanged so the next refresh retries generation.
            tag_error = str(error)

    return {
        "checked": len(keys), "updated": len(changed_keys), "changed": changed_keys,
        "added": added, "tagged": tagged, "tagError": tag_error,
    }


def set_priority(key: str, priority_name: str):
    """Push a priority change from the board back to the real Jira issue.
    Verified live 2026-09-06: PUT /rest/api/3/issue/{key} with
    {"fields": {"priority": {"name": ...}}} returns 204 on success."""
    if not configured():
        raise RuntimeError("Jira sync not configured — set it up on the Settings page, or copy .env.example to .env")
    c = get_config()
    resp = requests.put(
        f"{c['base_url']}/rest/api/3/issue/{key}",
        json={"fields": {"priority": {"name": priority_name}}},
        auth=(c["email"], c["api_token"]),
        timeout=15,
    )
    resp.raise_for_status()


def get_transitions(key: str) -> list[dict]:
    """The workflow moves (e.g. Backlog -> In Progress) actually available on
    this issue right now — Jira only allows moving along edges its own
    workflow defines, so this can't be a fixed status list."""
    if not configured():
        raise RuntimeError("Jira sync not configured — set it up on the Settings page, or copy .env.example to .env")
    c = get_config()
    resp = requests.get(
        f"{c['base_url']}/rest/api/3/issue/{key}/transitions",
        auth=(c["email"], c["api_token"]),
        timeout=15,
    )
    resp.raise_for_status()
    return [
        {"id": t["id"], "name": t["to"]["name"]}
        for t in resp.json().get("transitions", [])
    ]


# Keyed by workspace slug: a different workspace is a different Jira instance
# and project, so its workflow is a different list.
_workflow_statuses_cache: dict[str, list[dict]] = {}


def get_workflow_statuses(sample_key: str) -> list[dict]:
    """The full status dropdown for the board's status-select — same list of
    {id, name} for every ticket in this project (verified live 2026-09-06:
    identical 6 statuses/ids on 5 real tickets sitting in 5 different
    statuses, i.e. this project's workflow allows moving from any status to
    any other), so it's fetched once from whichever tracked ticket is handy
    and cached, instead of hitting Jira again for every row's select. If a
    future workflow change makes this untrue, a stale entry just fails the
    POST with Jira's own error (surfaced + reverted in the UI) rather than
    silently doing the wrong thing. Cache is cleared on a Settings-page save —
    see invalidate_cache()."""
    slug = workspaces.current()
    if slug not in _workflow_statuses_cache:
        _workflow_statuses_cache[slug] = get_transitions(sample_key)
    return _workflow_statuses_cache[slug]


def transition_issue(key: str, transition_id: str):
    """Move an issue along one of the edges get_transitions() returned."""
    if not configured():
        raise RuntimeError("Jira sync not configured — set it up on the Settings page, or copy .env.example to .env")
    c = get_config()
    resp = requests.post(
        f"{c['base_url']}/rest/api/3/issue/{key}/transitions",
        json={"transition": {"id": transition_id}},
        auth=(c["email"], c["api_token"]),
        timeout=15,
    )
    resp.raise_for_status()
