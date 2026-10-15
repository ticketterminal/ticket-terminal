"""Discover pull/merge requests created during a ticket's agent sessions.

Claude records first-class ``pr-link`` JSONL entries.  Codex does not expose a
stable equivalent across CLI versions, so its structured command/assistant
results are scanned for canonical GitHub/GitLab change-request URLs.  Raw PTY
logs are deliberately excluded: terminal redraws repeat URLs many times and
are not a trustworthy product-data source.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit


MAX_TRANSCRIPT_BYTES = 8 * 1024 * 1024
_CACHE: dict[tuple, list[dict]] = {}
_URL_RE = re.compile(r"https?://[^\s\"'<>\\]+", re.IGNORECASE)
_GITHUB_PATH_RE = re.compile(r"^/(.+?)/pull/(\d+)(?:/.*)?$")
_GITLAB_PATH_RE = re.compile(r"^/(.+?)/(?:-/)?merge_requests/(\d+)(?:/.*)?$")


def _canonical(raw: str, *, source: str, timestamp: str = "", repository: str = "") -> dict | None:
    raw = raw.rstrip(".,;:!?)]}")
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    path = parsed.path.rstrip("/")
    match = _GITHUB_PATH_RE.match(path)
    provider = "github"
    if not match:
        match = _GITLAB_PATH_RE.match(path)
        provider = "gitlab"
    if not match:
        return None
    repo = (repository or match.group(1)).strip("/").removesuffix(".git")
    number = int(match.group(2))
    # Fragments commonly point at one comment, not the change request itself.
    url = urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
    return {
        "url": url,
        "provider": provider,
        "repository": repo,
        "number": number,
        "source": source,
        "discoveredAt": timestamp or "",
    }


def normalize_change_request(value: Any, *, source: str = "manual") -> dict | None:
    """Validate a stored/manual record and return the stable public shape."""
    if isinstance(value, str):
        return _canonical(value, source=source)
    if not isinstance(value, dict):
        return None
    return _canonical(
        str(value.get("url") or ""),
        source=str(value.get("source") or source),
        timestamp=str(value.get("discoveredAt") or value.get("timestamp") or ""),
        repository=str(value.get("repository") or ""),
    )


def merge_change_requests(*groups: Iterable[Any]) -> list[dict]:
    """Stable URL-deduped merge; explicit Claude events beat inferred ones."""
    by_url: dict[str, dict] = {}
    rank = {"transcript": 0, "manual": 1, "legacy-manual": 1, "claude-pr-link": 2}
    for group in groups:
        for value in group or []:
            item = normalize_change_request(value, source="transcript")
            if not item:
                continue
            previous = by_url.get(item["url"])
            if previous is None or rank.get(item["source"], 0) > rank.get(previous["source"], 0):
                by_url[item["url"]] = item
    return sorted(by_url.values(), key=lambda item: (item.get("discoveredAt") or "", item["url"]))


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for child in value:
            yield from _strings(child)
    elif isinstance(value, dict):
        for child in value.values():
            yield from _strings(child)


def _candidate_strings(entry: dict, provider: str) -> Iterable[str]:
    """Only agent/tool output, never arbitrary user prompt text."""
    if provider == "claude":
        message = entry.get("message") if isinstance(entry.get("message"), dict) else {}
        content = message.get("content")
        if entry.get("type") == "assistant":
            yield from _strings(content)
        elif entry.get("type") == "user" and isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    yield from _strings(block.get("content"))
        return

    payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else entry
    kind = str(payload.get("type") or "")
    role = str(payload.get("role") or "")
    if role == "assistant" or kind in {
        "function_call_output", "custom_tool_call_output", "command_execution_output",
        "agent_message", "assistant_message",
    }:
        yield from _strings(payload)


def read_change_requests(log_path: Path | None, provider: str) -> list[dict]:
    if provider not in {"claude", "codex"} or not log_path or not log_path.exists():
        return []
    stat = log_path.stat()
    cache_key = (str(log_path), provider, stat.st_size, stat.st_mtime_ns)
    cached = _CACHE.get(cache_key)
    if cached is not None:
        return cached

    found: list[dict] = []
    with log_path.open("rb") as raw:
        start = max(0, stat.st_size - MAX_TRANSCRIPT_BYTES)
        raw.seek(start)
        if start:
            raw.readline()
        for raw_line in raw:
            try:
                entry = json.loads(raw_line.decode("utf-8", errors="replace"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            timestamp = str(entry.get("timestamp") or "")
            if provider == "claude" and entry.get("type") == "pr-link":
                item = _canonical(
                    str(entry.get("prUrl") or ""), source="claude-pr-link",
                    timestamp=timestamp, repository=str(entry.get("prRepository") or ""),
                )
                if item:
                    found.append(item)
            for text in _candidate_strings(entry, provider):
                for match in _URL_RE.finditer(text):
                    item = _canonical(match.group(0), source="transcript", timestamp=timestamp)
                    if item:
                        found.append(item)

    result = merge_change_requests(found)
    if len(_CACHE) >= 64:
        _CACHE.clear()
    _CACHE[cache_key] = result
    return result
