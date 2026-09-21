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
