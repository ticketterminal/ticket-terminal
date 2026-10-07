"""Normalize Claude Code and Codex transcript tool calls into one small UI feed.

The terminal's raw PTY log is meant for replay/forensics, not structured product
features. Both agents already persist JSONL session histories, so this module
reads those authoritative records and emits only actions the agent actually
took. Assistant prose and terminal redraws are deliberately ignored.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable


_SECRET_ASSIGNMENT_RE = re.compile(
    r"\b([A-Za-z_][A-Za-z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|API_KEY)[A-Za-z0-9_]*)=([^\s]+)",
    re.IGNORECASE,
)
_SECRET_FLAG_RE = re.compile(
    r"(--(?:token|secret|password|passwd|api-key|credential))(?:=|\s+)([^\s]+)",
    re.IGNORECASE,
)
MAX_TRANSCRIPT_BYTES = 8 * 1024 * 1024
_CACHE: dict[tuple, list[dict]] = {}


def _compact(value: Any, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _safe_command(command: Any) -> str:
    """Return a useful command summary without echoing common inline secrets."""
    first_line = str(command or "").splitlines()[0]
    text = _SECRET_ASSIGNMENT_RE.sub(lambda m: m.group(1) + "=•••", first_line)
    text = _SECRET_FLAG_RE.sub(lambda m: m.group(1) + " •••", text)
    return _compact(text)


def _resource_for_path(raw_path: Any, memory_dir: Path) -> dict | None:
    if not raw_path:
        return None
    path = Path(str(raw_path)).expanduser()
    try:
        is_memory = path.parent.resolve() == memory_dir.resolve() and path.suffix.lower() == ".md"
    except (OSError, RuntimeError):
        is_memory = False
    if is_memory:
        return {"type": "memory", "id": path.stem, "label": path.name, "path": str(path)}
    if path.name.lower() == "skill.md":
        return {"type": "skill", "id": path.parent.name, "label": path.parent.name, "path": str(path)}
    return {"type": "file", "label": path.name or str(path), "path": str(path)}


def _resource_from_inputs(inputs: dict, memory_dir: Path) -> dict | None:
    explicit = inputs.get("file_path") or inputs.get("path") or inputs.get("notebook_path")
    resource = _resource_for_path(explicit, memory_dir)
    if resource:
        return resource
    text = str(inputs.get("command") or inputs.get("cmd") or inputs.get("input") or "")
    # Shell-driven reads are common for both vendors. If the command establishes
    # the memory directory and names a markdown file, attribute that file without
    # pretending every arbitrary .md argument belongs to the graph.
    if str(memory_dir) in text:
        match = re.search(r"(?:^|[/\s'\"])([a-z0-9-]+)\.md\b", text, re.IGNORECASE)
        if match:
            path = memory_dir / (match.group(1) + ".md")
            return {"type": "memory", "id": path.stem, "label": path.name, "path": str(path)}
    skill = re.search(r"([^\s'\"]+/SKILL\.md)\b", text, re.IGNORECASE)
    return _resource_for_path(skill.group(1), memory_dir) if skill else None


def _event(tool: str, inputs: dict, timestamp: str, memory_dir: Path) -> dict:
    lowered = tool.lower()
    path = inputs.get("file_path") or inputs.get("path") or inputs.get("notebook_path")
    resource = _resource_from_inputs(inputs, memory_dir)
    event = {"kind": "tool", "title": _compact(tool) or "Tool action", "detail": "", "timestamp": timestamp or ""}

    if lowered in {"bash", "shell", "exec_command", "run_command", "command_execution"}:
        command = inputs.get("command") or inputs.get("cmd") or inputs.get("input") or ""
        safe = _safe_command(command)
        event.update(kind="command", title="Run command", detail=safe)
        if safe.startswith("aws sso login"):
            event["title"] = "Sign in to AWS"
        elif safe.startswith("git "):
            event["title"] = "Run Git command"
    elif lowered in {"read", "read_file"}:
        event.update(kind="read", title="Read " + (resource or {}).get("label", "file"), detail=str(path or ""))
    elif lowered in {"write", "write_file", "edit", "apply_patch", "multi_edit"}:
        event.update(kind="write", title="Change " + (resource or {}).get("label", "files"), detail=str(path or ""))
    elif lowered in {"grep", "glob", "find", "search_files", "toolsearch"}:
        query = inputs.get("pattern") or inputs.get("query") or inputs.get("glob") or ""
        title = "Find tools" if lowered == "toolsearch" else "Search files"
        event.update(kind="search", title=title, detail=_compact(query or path))
    elif lowered in {"webfetch", "web_fetch", "websearch", "web_search", "web__run"}:
        event.update(kind="web", title="Use the web", detail=_compact(inputs.get("url") or inputs.get("query") or inputs.get("q")))
    elif lowered in {"skill", "use_skill"}:
        skill = inputs.get("skill") or inputs.get("name") or inputs.get("id") or "skill"
        event.update(kind="skill", title="Use skill", detail=_compact(skill))
        event["resource"] = {"type": "skill", "id": str(skill), "label": str(skill)}
    elif lowered.startswith("mcp__"):
        event.update(kind="integration", title="Use integration", detail=_compact(tool.replace("mcp__", "").replace("__", " · ")))

    if resource:
        event["resource"] = resource
        if resource["type"] == "memory" and lowered in {"read", "read_file"}:
            event["kind"] = "memory"
            event["title"] = "Read memory"
        elif resource["type"] == "skill" and lowered in {"read", "read_file"}:
            event["kind"] = "skill"
            event["title"] = "Use skill"
    event["detail"] = _compact(event.get("detail"))
    return event


def _decode_args(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {"input": value}
    except json.JSONDecodeError:
        # Codex custom-tool calls can store a JavaScript invocation rather than
        # plain JSON. Extract the useful command without evaluating anything.
        cmd = re.search(r'\b(?:cmd|command)\s*:\s*(["\'])(.*?)\1', value, re.DOTALL)
        return {"cmd": cmd.group(2)} if cmd else {"input": value}


def _claude_calls(entry: dict) -> Iterable[tuple[str, dict, str, str]]:
    content = (entry.get("message") or {}).get("content")
    if not isinstance(content, list):
        return
    timestamp = str(entry.get("timestamp") or "")
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            yield str(block.get("name") or "tool"), _decode_args(block.get("input")), timestamp, str(block.get("id") or "")


def _codex_calls(entry: dict) -> Iterable[tuple[str, dict, str, str]]:
    timestamp = str(entry.get("timestamp") or "")
    payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else entry
    candidates = [payload]
    item = payload.get("item") if isinstance(payload, dict) else None
    if isinstance(item, dict):
        candidates.append(item)
    for candidate in candidates:
        kind = str(candidate.get("type") or "")
        if kind in {"function_call", "custom_tool_call", "mcp_tool_call"}:
            name = candidate.get("name") or candidate.get("tool_name") or "tool"
            args = candidate.get("arguments", candidate.get("input", {}))
            yield str(name), _decode_args(args), timestamp, str(candidate.get("call_id") or candidate.get("id") or "")
        elif kind == "command_execution":
            yield "command_execution", {"command": candidate.get("command", "")}, timestamp, str(candidate.get("id") or "")


def read_activity(log_path: Path | None, provider: str, memory_dir: Path, limit: int = 100) -> list[dict]:
    if not log_path or not log_path.exists():
        return []
    limit = max(1, min(limit, 250))
    stat = log_path.stat()
    cache_key = (str(log_path), provider, str(memory_dir), stat.st_size, stat.st_mtime_ns, limit)
    cached = _CACHE.get(cache_key)
    if cached is not None:
        return cached
    events: list[dict] = []
    seen: set[str] = set()
    extractor = _claude_calls if provider == "claude" else _codex_calls
    # Session transcripts are append-only and can grow into hundreds of MB.
    # The panel is a recent-action trail, so bound every poll to the tail rather
    # than making one old session freeze the UI. The first partial JSONL line is
    # intentionally discarded when seeking into the middle of the file.
    with log_path.open("rb") as raw:
        start = max(0, stat.st_size - MAX_TRANSCRIPT_BYTES)
        raw.seek(start)
        if start:
            raw.readline()
        for line_number, raw_line in enumerate(raw):
            try:
                entry = json.loads(raw_line.decode("utf-8", errors="replace"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            for tool, inputs, timestamp, call_id in extractor(entry):
                fingerprint = call_id or f"{line_number}:{tool}:{json.dumps(inputs, sort_keys=True, default=str)}"
                if fingerprint in seen:
                    continue
                seen.add(fingerprint)
                event = _event(tool, inputs, timestamp, memory_dir)
                event["id"] = fingerprint
                events.append(event)
    result = events[-limit:]
    if len(_CACHE) >= 32:
        _CACHE.clear()
    _CACHE[cache_key] = result
    return result
