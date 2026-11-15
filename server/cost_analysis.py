"""Per-ticket cost analysis via the real `codeburn` CLI (github.com/getagentseal/codeburn,
`npm install -g codeburn`) — not a hand-rolled pricing table. codeburn already parses the same
~/.claude/projects/**/*.jsonl transcripts this server reads for session-resume checks (see
main.py:_claude_session_exists) and applies its own maintained Anthropic pricing/model-alias/
tiered-cost/cache-multiplier logic, which is substantial enough (alias tables, per-model tiered
rates, 1h vs 5m cache-write rates) that reimplementing it here would be a maintenance trap. One
row per session id is exactly what a ticket's own claudeSessionId needs to key against.
"""
import json
import subprocess
import threading


_cache_lock = threading.Lock()
_cached_signature = None
_cached_rows: dict[str, dict] | None = None


def get_session_costs() -> dict[str, dict]:
    """{claudeSessionId: {cost, calls, models, inputTokens, outputTokens, ...}} for every
    Claude Code session codeburn can see on this machine, across all time. Cheap to call live
    (codeburn keeps its own on-disk cache of already-parsed transcripts — a warm run is well
    under a second here), so this isn't cached again on top."""
    result = subprocess.run(
        ["codeburn", "sessions", "--period", "lifetime", "--format", "json", "--provider", "all"],
        capture_output=True, text=True, timeout=60, check=True,
    )
    rows = json.loads(result.stdout)
    return {row["sessionId"]: row for row in rows}


def get_session_costs_cached(transcript_signature: tuple) -> tuple[dict[str, dict], bool]:
    """Return codeburn's session rows, rescanning only when a TT transcript changed.

    The caller supplies a cheap tuple of ticket-linked transcript size/mtime values.  This
    deliberately does not pretend codeburn itself is cheap: unchanged signatures reuse the
    last parsed result, while a real agent write invalidates it.  The bool says whether this
    call performed the scan, which is useful to API/UI observability and tests.
    """
    global _cached_signature, _cached_rows
    with _cache_lock:
        if _cached_rows is not None and transcript_signature == _cached_signature:
            return _cached_rows, False
        rows = get_session_costs()
        _cached_signature = transcript_signature
        _cached_rows = rows
        return rows, True


def clear_cache() -> None:
    global _cached_signature, _cached_rows
    with _cache_lock:
        _cached_signature = None
        _cached_rows = None
