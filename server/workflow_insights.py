"""Pure-Python cost/performance/caching analysis over the spend ledger — no LLM involved.

This is a reporting page, not an agent: every number here is computed directly from real data
(the spend ledger, `codeburn optimize`, and the existing vendor-neutral memory-usage stats),
not summarized or guessed by a model. See spend_ledger.py for why the ledger exists at all, and
the "big picture"/staleness pillar this deliberately leaves out — see the plan this shipped
from for why that's a separate, later feature.
"""
import json
import statistics
import subprocess
import threading
import time
from datetime import datetime, timezone

import memory_analysis
import spend_ledger

# Heuristic defaults, not precise science — tune these if they flag too much or too little.
# A session is a caching "waste candidate" when its cache-read share of (cache-read + fresh
# input) tokens is below this ratio, AND its total token volume clears this floor (a tiny
# session with a low ratio isn't worth flagging; a huge one is).
LOW_CACHE_RATIO_THRESHOLD = 0.5
HIGH_TOKEN_VOLUME_THRESHOLD = 20_000
DIAGNOSTIC_CACHE_SECONDS = 300
_diagnostic_cache: dict[tuple, dict] = {}
_diagnostic_lock = threading.Lock()


def _parse_instant(value: str | None) -> datetime | None:
    """Parse codeburn/ledger ISO timestamps into comparable UTC instants."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def filter_entries(entries: list[dict], start: str | None = None, end: str | None = None) -> list[dict]:
    """Return sessions whose start instant falls in ``[start, end)``.

    ``startedAt`` is the meaningful accounting date: a session's full spend belongs to when
    the work began, rather than the later moment somebody happened to close its terminal.
    Older ledger rows with no start time fall back to ended/closed time. Timestamp-less rows
    remain visible only in the all-time view, where silently dropping history would be worse.
    """
    start_at = _parse_instant(start)
    end_at = _parse_instant(end)
    if start and start_at is None:
        raise ValueError("invalid insights start time")
    if end and end_at is None:
        raise ValueError("invalid insights end time")
    if start_at and end_at and start_at >= end_at:
        raise ValueError("insights start time must be before end time")
    if not start_at and not end_at:
        return entries

    filtered = []
    for entry in entries:
        instant = next((parsed for field in ("startedAt", "endedAt", "closedAt")
                        if (parsed := _parse_instant(entry.get(field))) is not None), None)
        if instant is None:
            continue
        if start_at and instant < start_at:
            continue
        if end_at and instant >= end_at:
            continue
        filtered.append(entry)
    return filtered


def _primary_model(models: list[str] | None) -> str:
    """codeburn's `models` list can include a "<synthetic>" placeholder alongside the real
    model name(s) actually used; prefer a real name for grouping/display, falling back to
    whatever's there (even the placeholder) rather than reporting "unknown" when codeburn did
    give us something."""
    real = [m for m in (models or []) if m and m != "<synthetic>"]
    if real:
        return real[0]
    return (models or ["unknown"])[0]


def vendor_model_stats(entries: list[dict]) -> dict:
    """Cost/performance grouped by (provider, model) and by (provider, model, category) — the
    two questions this exists to answer: "which vendor/model is cheapest overall" and "which is
    cheapest for this kind of work." Totals/averages are computed here, not left to a model,
    since arithmetic over many rows is exactly what LLMs get wrong."""
    by_vendor_model: dict[tuple, dict] = {}
    by_category: dict[tuple, dict] = {}

    for e in entries:
        model = _primary_model(e.get("models"))
        vm_key = (e.get("provider"), model)
        g = by_vendor_model.setdefault(vm_key, {
            "provider": e.get("provider"), "model": model, "sessions": 0,
            "totalCost": 0.0, "totalCalls": 0, "totalTurns": 0, "totalDurationMs": 0,
        })
        g["sessions"] += 1
        g["totalCost"] += e.get("cost") or 0
        g["totalCalls"] += e.get("calls") or 0
        g["totalTurns"] += e.get("turns") or 0
        g["totalDurationMs"] += e.get("durationMs") or 0

        for cat in (e.get("categories") or ["uncategorized"]):
            cat_key = (e.get("provider"), model, cat)
            cg = by_category.setdefault(cat_key, {
                "provider": e.get("provider"), "model": model, "category": cat,
                "sessions": 0, "totalCost": 0.0,
            })
            cg["sessions"] += 1
            cg["totalCost"] += e.get("cost") or 0

    vendor_model_rows = [
        {**g, "avgCost": g["totalCost"] / g["sessions"], "avgCalls": g["totalCalls"] / g["sessions"],
         "avgDurationMs": g["totalDurationMs"] / g["sessions"]}
        for g in by_vendor_model.values()
    ]
    vendor_model_rows.sort(key=lambda r: -r["totalCost"])

    category_rows = [{**cg, "avgCost": cg["totalCost"] / cg["sessions"]} for cg in by_category.values()]
    category_rows.sort(key=lambda r: -r["totalCost"])

    return {"byVendorModel": vendor_model_rows, "byCategory": category_rows}


def caching_stats(entries: list[dict]) -> dict:
    """Cache-read share of tokens per provider, plus the specific sessions that look like real
    waste (low cache reuse AND high absolute token volume) rather than just a low-traffic
    session that never had much to cache in the first place."""
    by_provider: dict[str, dict] = {}
    waste_candidates = []

    for e in entries:
        provider = e.get("provider")
        g = by_provider.setdefault(provider, {"provider": provider, "cacheReadTokens": 0, "inputTokens": 0})
        g["cacheReadTokens"] += e.get("cacheReadTokens") or 0
        g["inputTokens"] += e.get("inputTokens") or 0

        cache_read = e.get("cacheReadTokens") or 0
        input_tokens = e.get("inputTokens") or 0
        denom = cache_read + input_tokens
        ratio = (cache_read / denom) if denom else None
        total_tokens = input_tokens + (e.get("outputTokens") or 0)
        if ratio is not None and ratio < LOW_CACHE_RATIO_THRESHOLD and total_tokens >= HIGH_TOKEN_VOLUME_THRESHOLD:
            waste_candidates.append({
                "ticketKey": e.get("ticketKey"), "provider": provider, "sessionId": e.get("sessionId"),
                "cacheRatio": ratio, "totalTokens": total_tokens, "cost": e.get("cost") or 0,
            })

    provider_rows = []
    for g in by_provider.values():
        denom = g["cacheReadTokens"] + g["inputTokens"]
        provider_rows.append({
            "provider": g["provider"],
            "cacheEfficiency": (g["cacheReadTokens"] / denom) if denom else None,
        })

    waste_candidates.sort(key=lambda w: -w["totalTokens"])
    return {"byProvider": provider_rows, "wasteCandidates": waste_candidates[:20]}


def productivity_stats(entries: list[dict], tickets: dict) -> dict:
    """Measured delivery signals for the selected ledger window.

    Sessions and spend come directly from the filtered ledger. Outcomes are deliberately
    described as *current*: the ticket store has each ticket's present status, not a status
    transition history that could prove exactly when it completed. Likewise, linked change
    requests are evidence of delivered code, while terminal duration is intentionally absent
    because an open terminal is not the same thing as human attention or time saved.
    """
    worked_keys = {str(e.get("ticketKey") or "").strip() for e in entries}
    worked_keys.discard("")
    costs = [float(e.get("cost") or 0) for e in entries]
    total_cost = sum(costs)
    completed_statuses = {"done", "closed", "resolved", "complete", "completed"}
    completed: set[str] = set()
    awaiting_approval: set[str] = set()
    known_status: set[str] = set()
    delivery_tickets: set[str] = set()
    change_request_urls: set[str] = set()

    for key in worked_keys:
        ticket = tickets.get(key)
        if not isinstance(ticket, dict):
            continue
        status = str(ticket.get("jiraStatus") or ticket.get("status") or "").strip().lower()
        if status:
            known_status.add(key)
        if status in completed_statuses:
            completed.add(key)
        if "approval" in status:
            awaiting_approval.add(key)

        ticket_urls: set[str] = set()
        for change_request in ticket.get("changeRequests") or []:
            url = change_request.get("url") if isinstance(change_request, dict) else change_request
            if url and str(url).strip():
                ticket_urls.add(str(url).strip())
        if ticket.get("mrLink") and str(ticket["mrLink"]).strip():
            ticket_urls.add(str(ticket["mrLink"]).strip())
        if ticket_urls:
            delivery_tickets.add(key)
            change_request_urls.update(ticket_urls)

    ticket_count = len(worked_keys)
    return {
        "ticketsWorked": ticket_count,
        "sessions": len(entries),
        "totalCost": total_cost,
        "costPerTicket": total_cost / ticket_count if ticket_count else None,
        "medianSessionCost": statistics.median(costs) if costs else None,
        "completed": len(completed),
        "awaitingApproval": len(awaiting_approval),
        "knownStatusTickets": len(known_status),
        "changeRequests": len(change_request_urls),
        "deliveryTickets": len(delivery_tickets),
    }


def memory_structure_stats(tickets: dict, default_workdir: str) -> list[dict]:
    """Each memory file's read count across real tickets, and its rough size — sorted so a
    file that's both heavily read and large surfaces first, since every read of it costs input
    tokens on every session that touches it.

    `all_ticket_memory_usage` aliases each real session under two keys — the raw sessionId AND
    "<provider>:<ticketKey>" — pointing at the same usage dict. Counting every key would double
    every real session's reads; counting only the "<provider>:<ticketKey>" keys (identifiable
    by the ":") gives exactly one count per real ticket+provider combination."""
    usage = memory_analysis.all_ticket_memory_usage(tickets, default_workdir)
    read_counts: dict[str, int] = {}
    for key, mem_usage in usage.items():
        if ":" not in key:
            continue
        for memory_id in mem_usage:
            read_counts[memory_id] = read_counts.get(memory_id, 0) + 1

    sizes = memory_analysis.memory_file_stats()
    rows = [
        {"id": mid, "readByTickets": read_counts.get(mid, 0), "chars": sizes.get(mid, {}).get("chars", 0)}
        for mid in (set(read_counts) | set(sizes))
    ]
    rows.sort(key=lambda r: (-r["readByTickets"], -r["chars"]))
    return rows


def get_optimize_findings() -> dict | None:
    """codeburn's own token-waste analysis (`codeburn optimize --json`) — reused as-is rather
    than reimplemented. Returns None (not raised) if codeburn isn't installed or the call
    fails, so the rest of the dashboard still renders."""
    try:
        result = subprocess.run(
            ["codeburn", "optimize", "--period", "lifetime", "--provider", "all", "--json"],
            capture_output=True, text=True, timeout=60, check=True,
        )
        return json.loads(result.stdout)
    except Exception:
        return None


def clear_diagnostic_cache() -> None:
    with _diagnostic_lock:
        _diagnostic_cache.clear()


def lifetime_diagnostics(tickets: dict, default_workdir: str, include_optimize: bool) -> tuple[list[dict], dict | None]:
    """Cache transcript/memory diagnostics so changing a date window only reads the ledger."""
    memory_path = str(memory_analysis.memory_dir_info().get("path") or "")
    key = (default_workdir, memory_path, tuple(sorted(tickets)))
    now = time.monotonic()
    with _diagnostic_lock:
        cached = _diagnostic_cache.get(key)
        if not cached or now - cached["createdAt"] >= DIAGNOSTIC_CACHE_SECONDS:
            cached = {
                "createdAt": now,
                "memory": memory_structure_stats(tickets, default_workdir),
            }
            _diagnostic_cache[key] = cached
        if include_optimize and "optimize" not in cached:
            cached["optimize"] = get_optimize_findings()
        return cached["memory"], cached.get("optimize")


def compute_insights(tickets: dict, default_workdir: str, live_entries: list[dict] | None = None,
                     start: str | None = None, end: str | None = None) -> dict:
    """`live_entries` (see main.py's _live_spend_entries) are same-shaped rows for sessions
    that are still running — the ledger only gets an entry once a session actually closes, so
    without these, cost/category stats silently miss every ticket whose terminal is still open
    (which, in practice, is most of them: nothing here nudges anyone to click Stop). Entries are
    keyed by sessionId, so a live entry is dropped if the ledger already has that exact session
    (it closed between the two reads) rather than double-counting it."""
    entries = spend_ledger.read_entries()
    if live_entries:
        closed_ids = {e.get("sessionId") for e in entries}
        entries = entries + [e for e in live_entries if e.get("sessionId") not in closed_ids]
    total_entry_count = len(entries)
    entries = filter_entries(entries, start, end)
    bounded = bool(start or end)
    memory, optimize = lifetime_diagnostics(tickets, default_workdir, include_optimize=not bounded)
    return {
        "productivity": productivity_stats(entries, tickets),
        "vendorModel": vendor_model_stats(entries),
        "caching": caching_stats(entries),
        # memory usage has no per-read timestamps, so presenting it as if it respected the
        # selected period would be misleading. It is explicitly labelled lifetime in the UI.
        "memory": memory,
        # codeburn optimize only supports its own coarse lifetime period here. Suppress its
        # dollar totals in bounded views rather than mixing them into the selected window.
        "codeburnOptimize": None if bounded else optimize,
        "codeburnOptimizeLifetimeOnly": bounded,
        "ledgerEntryCount": len(entries),
        "totalLedgerEntryCount": total_entry_count,
        "range": {"start": start, "end": end},
    }
