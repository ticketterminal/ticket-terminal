"""Durable, workspace-scoped history of what each terminal session actually cost.

`cost_analysis.get_session_costs()` is live-only, keyed to whatever session id currently sits
on a ticket (`claudeSessionId`/`codexSessionId`). The moment that id is replaced — main.py
mints a fresh uuid once it decides an old session is dead/unresumable — the old session's cost
history is orphaned: nothing on the ticket points back to it, and codeburn itself has no
concept of "this ticket." This module records a session's final cost the moment it's known to
be over (see main.py's two call sites), so vendor/model/caching comparisons in
workflow_insights.py have real history to work from instead of a snapshot that can vanish.
"""
import datetime
import json
import re
import threading
import uuid

import content
import cost_analysis

_lock = threading.RLock()
_TICKET_KEY_RE = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b", re.IGNORECASE)
_COST_FIELDS = (
    "models", "cost", "calls", "turns", "inputTokens", "outputTokens",
    "cacheReadTokens", "cacheWriteTokens", "startedAt", "endedAt", "durationMs",
)


def _cost_patch(row: dict) -> dict:
    patch = {field: row.get(field) for field in _COST_FIELDS}
    patch["models"] = patch["models"] or []
    for field in ("cost", "calls", "turns", "inputTokens", "outputTokens",
                  "cacheReadTokens", "cacheWriteTokens", "durationMs"):
        patch[field] = patch[field] or 0
    return patch


def _ledger_path():
    return content.data_dir() / "spend-ledger.json"


def read_entries() -> list[dict]:
    with _lock:
        path = _ledger_path()
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text()).get("entries", [])
        except (json.JSONDecodeError, OSError):
            return []


def _write_entries(entries: list[dict]) -> None:
    path = _ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"entries": entries}, indent=2))
    tmp.replace(path)


def _ticket_sessions(tickets: dict) -> dict[str, tuple[str, str]]:
    sessions = {}
    for key, ticket in tickets.items():
        for provider in ("claude", "codex"):
            session_id = ticket.get(provider + "SessionId")
            if session_id:
                sessions[str(session_id)] = (key, provider)
    return sessions


def _ticket_for_cost(session_id: str, row: dict, tickets: dict,
                     sessions: dict[str, tuple[str, str]]) -> tuple[str, str] | None:
    """Map a codeburn row to a Ticket Terminal ticket without importing unrelated sessions.

    Current sessions map exactly by id. Historical sessions no longer referenced by db.json
    retain the ticket key in codeburn's title (the prompt always starts with it), which is the
    durable backfill path. A ticket can have aged out of the current tracker window and is
    still valid history, so a syntactically valid key does not have to remain in ``tickets``.
    """
    if session_id in sessions:
        return sessions[session_id]
    match = _TICKET_KEY_RE.search(str(row.get("title") or ""))
    if not match:
        return None
    return match.group(0).upper(), str(row.get("provider") or "unknown")


def sync_from_costs(tickets: dict, costs: dict[str, dict] | None = None) -> dict:
    """Upsert every ticket-linked codeburn session into the durable JSON ledger.

    This is deliberately separate from Insights range reads: codeburn is scanned by the
    board's existing cost refresh (or the explicit Insights Refresh button), then date-window
    changes are cheap, deterministic reads over this file. Returns counts for observability.
    """
    if costs is None:
        costs = cost_analysis.get_session_costs()
    sessions = _ticket_sessions(tickets)
    with _lock:
        entries = read_entries()
        by_session = {str(entry.get("sessionId")): entry for entry in entries if entry.get("sessionId")}
        changed = False
        imported = 0
        for session_id, cost_row in costs.items():
            mapping = _ticket_for_cost(str(session_id), cost_row, tickets, sessions)
            if not mapping:
                continue
            ticket_key, provider = mapping
            ticket = tickets.get(ticket_key, {})
            existing = by_session.get(str(session_id))
            if existing is None:
                existing = {
                    "id": str(uuid.uuid4()), "ticketKey": ticket_key, "provider": provider,
                    "sessionId": str(session_id), "categories": ticket.get("categories") or [],
                    "priority": ticket.get("jiraPriority") or "", "closeReason": "codeburn-sync",
                }
                entries.append(existing)
                by_session[str(session_id)] = existing
                imported += 1
                changed = True
            patch = _cost_patch(cost_row)
            patch["provider"] = existing.get("provider") or provider
            patch["ticketKey"] = existing.get("ticketKey") or ticket_key
            if ticket:
                patch["categories"] = ticket.get("categories") or existing.get("categories") or []
                patch["priority"] = ticket.get("jiraPriority") or existing.get("priority") or ""
            if any(existing.get(key) != value for key, value in patch.items()):
                existing.update(patch)
                changed = True
        if changed:
            _write_entries(entries)
        return {"entries": len(entries), "imported": imported, "changed": changed}


def append_entry(ticket_key: str, provider: str, session_id: str | None, ticket: dict, close_reason: str) -> None:
    """Record this session's final cost, once. Idempotent on sessionId, since the two call
    sites in main.py (an explicit Stop click, and the PTY exiting on its own) could in theory
    both fire for the same session. Never raises — codeburn being unavailable, or any other
    failure here, must never block a terminal actually stopping."""
    if not session_id:
        return
    try:
        row = cost_analysis.get_session_costs().get(session_id)
        if not row:
            return
        with _lock:
            entries = read_entries()
            existing = next((e for e in entries if e.get("sessionId") == session_id), None)
            if existing is None:
                existing = {"id": str(uuid.uuid4()), "sessionId": session_id}
                entries.append(existing)
            existing.update({
                "ticketKey": ticket_key, "provider": provider,
                **_cost_patch(row),
                "categories": ticket.get("categories") or [],
                "priority": ticket.get("jiraPriority") or "",
                "closedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "closeReason": close_reason,
            })
            _write_entries(entries)
    except Exception:
        pass
