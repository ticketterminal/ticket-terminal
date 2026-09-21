"""Pure-Python cost/performance/caching analysis over the spend ledger — no LLM involved.

This is a reporting page, not an agent: every number here is computed directly from real data
(the spend ledger, `codeburn optimize`, and the existing vendor-neutral memory-usage stats),
not summarized or guessed by a model. See spend_ledger.py for why the ledger exists at all, and
the "big picture"/staleness pillar this deliberately leaves out — see the plan this shipped
from for why that's a separate, later feature.
"""
import json
import subprocess

import memory_analysis
import spend_ledger

# Heuristic defaults, not precise science — tune these if they flag too much or too little.
# A session is a caching "waste candidate" when its cache-read share of (cache-read + fresh
# input) tokens is below this ratio, AND its total token volume clears this floor (a tiny
# session with a low ratio isn't worth flagging; a huge one is).
LOW_CACHE_RATIO_THRESHOLD = 0.5
HIGH_TOKEN_VOLUME_THRESHOLD = 20_000


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


def compute_insights(tickets: dict, default_workdir: str) -> dict:
    entries = spend_ledger.read_entries()
    return {
        "vendorModel": vendor_model_stats(entries),
        "caching": caching_stats(entries),
        "memory": memory_structure_stats(tickets, default_workdir),
        "codeburnOptimize": get_optimize_findings(),
        "ledgerEntryCount": len(entries),
    }
