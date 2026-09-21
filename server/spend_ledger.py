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
import uuid

import content
import cost_analysis


def _ledger_path():
    return content.data_dir() / "spend-ledger.json"


def read_entries() -> list[dict]:
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


def append_entry(ticket_key: str, provider: str, session_id: str | None, ticket: dict, close_reason: str) -> None:
    """Record this session's final cost, once. Idempotent on sessionId, since the two call
    sites in main.py (an explicit Stop click, and the PTY exiting on its own) could in theory
    both fire for the same session. Never raises — codeburn being unavailable, or any other
    failure here, must never block a terminal actually stopping."""
    if not session_id:
        return
    try:
        entries = read_entries()
        if any(e.get("sessionId") == session_id for e in entries):
            return
        row = cost_analysis.get_session_costs().get(session_id)
        if not row:
            return
        entries.append({
            "id": str(uuid.uuid4()),
            "ticketKey": ticket_key,
            "provider": provider,
            "sessionId": session_id,
            "models": row.get("models", []),
            "cost": row.get("cost", 0),
            "calls": row.get("calls", 0),
            "turns": row.get("turns", 0),
            "inputTokens": row.get("inputTokens", 0),
            "outputTokens": row.get("outputTokens", 0),
            "cacheReadTokens": row.get("cacheReadTokens", 0),
            "cacheWriteTokens": row.get("cacheWriteTokens", 0),
            "startedAt": row.get("startedAt"),
            "endedAt": row.get("endedAt"),
            "durationMs": row.get("durationMs"),
            "categories": ticket.get("categories") or [],
            "priority": ticket.get("jiraPriority") or "",
            "closedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "closeReason": close_reason,
        })
        _write_entries(entries)
    except Exception:
        pass
