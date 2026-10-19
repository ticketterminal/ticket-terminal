"""Normalize Claude Code and Codex transcript tool calls into one small UI feed.

The terminal's raw PTY log is meant for replay/forensics, not structured product
features. Both agents already persist JSONL session histories, so this module
reads those authoritative records and emits only actions the agent actually
took. Assistant prose and terminal redraws are deliberately ignored.
"""
from __future__ import annotations

import json
import re
from collections import Counter
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
_STORY_CACHE: dict[tuple, dict] = {}


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


def _resources_from_inputs(inputs: dict, memory_dir: Path) -> list[dict]:
    """Every named object touched by one call, including multi-file patches."""
    resources = []
    explicit = _resource_from_inputs(inputs, memory_dir)
    if explicit:
        resources.append(explicit)
    patch_text = "\n".join(str(inputs.get(key) or "") for key in ("patch", "input", "command", "cmd"))
    for match in re.finditer(r"^\*\*\* (Add|Update|Delete) File: (.+?)\s*$", patch_text, re.MULTILINE):
        resource = _resource_for_path(match.group(2).strip(), memory_dir)
        if resource:
            resource = {**resource, "action": match.group(1).lower()}
            resources.append(resource)
    unique = {}
    for resource in resources:
        identity = resource.get("path") or (resource.get("type"), resource.get("id"), resource.get("label"))
        previous = unique.get(identity)
        if previous is None or (resource.get("action") and not previous.get("action")):
            unique[identity] = resource
    return list(unique.values())


def _event(tool: str, inputs: dict, timestamp: str, memory_dir: Path) -> dict:
    lowered = tool.lower()
    path = inputs.get("file_path") or inputs.get("path") or inputs.get("notebook_path")
    resources = _resources_from_inputs(inputs, memory_dir)
    resource = resources[0] if resources else None
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
        label = (resource or {}).get("label", "files")
        title = f"Change {len(resources)} files" if len(resources) > 1 else "Change " + label
        detail = str(path or "") or ", ".join(item.get("label", "") for item in resources[:3])
        event.update(kind="write", title=title, detail=detail)
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
    if resources:
        event["resources"] = resources
    event["detail"] = _compact(event.get("detail"))
    return event


def _flow_stage(event: dict) -> tuple[str, str]:
    kind = event.get("kind") or "tool"
    detail = (event.get("detail") or "").lower()
    if kind in {"read", "search", "web"}:
        return "investigate", "Investigate"
    if kind in {"memory", "skill"}:
        return "knowledge", "Use knowledge"
    if kind == "write":
        return "change", "Make changes"
    if kind == "integration":
        return "coordinate", "Coordinate"
    if kind == "command":
        if re.search(r"\b(test|pytest|unittest|npm test|cargo test|go test|lint|typecheck|compile|build)\b", detail):
            return "verify", "Verify"
        if re.search(r"\b(git (commit|push)|gh pr|glab mr)\b", detail):
            return "deliver", "Deliver"
        if "login" in detail or "auth" in detail:
            return "access", "Get access"
        if re.search(r"\bgit (status|diff|log|show)\b", detail):
            return "investigate", "Inspect changes"
        return "operate", "Run tooling"
    return "operate", "Use tooling"


def summarize_activity(events: list[dict], ticket: dict) -> dict:
    """Evidence-only manager view derived from ticket intent + recorded calls."""
    counts = Counter(event.get("kind") or "tool" for event in events)
    objects = {}
    knowledge = {}
    phases = []
    for event in events:
        stage, label = _flow_stage(event)
        detail = event.get("title") or event.get("detail") or "Agent action"
        if phases and phases[-1]["id"] == stage:
            phases[-1]["count"] += 1
            phases[-1]["detail"] = detail
        else:
            phases.append({"id": stage, "label": label, "detail": detail, "count": 1})
        resources = event.get("resources") or ([event["resource"]] if event.get("resource") else [])
        for resource in resources:
            identity = resource.get("path") or resource.get("id") or resource.get("label")
            if not identity:
                continue
            if event.get("kind") == "write":
                existing = objects.get(identity, {})
                objects[identity] = {
                    "type": resource.get("type") or "file",
                    "label": resource.get("label") or str(identity),
                    "path": resource.get("path") or "",
                    "action": resource.get("action") or existing.get("action") or "change",
                }
            if resource.get("type") in {"memory", "skill"}:
                knowledge[identity] = resource

    summary = _compact(ticket.get("summary") or ticket.get("key") or "this ticket", 180)
    description = str(ticket.get("description") or "").strip()
    why = _compact(description.split("\n\n", 1)[0] if description else summary, 320)
    facts = []
    if objects:
        facts.append(f"Changed {len(objects)} named object{'s' if len(objects) != 1 else ''}")
    elif counts["write"]:
        facts.append(f"Made {counts['write']} change action{'s' if counts['write'] != 1 else ''}; paths were not exposed")
    if counts["command"]:
        facts.append(f"Ran {counts['command']} command{'s' if counts['command'] != 1 else ''}")
    if counts["memory"] + counts["skill"]:
        total = counts["memory"] + counts["skill"]
        facts.append(f"Used {total} memory/skill reference{'s' if total != 1 else ''}")
    if counts["web"] + counts["integration"]:
        total = counts["web"] + counts["integration"]
        facts.append(f"Made {total} external lookup{'s' if total != 1 else ''}")
    return {
        "headline": ("Work recorded toward “" + summary + "”.") if events else "No recorded work yet.",
        "why": why,
        "facts": facts,
        "actionCount": len(events),
        "flow": phases[-10:],
        "objects": list(objects.values()),
        "knowledge": list(knowledge.values()),
    }


def _message_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(
            str(item.get("text") or "") for item in value
            if isinstance(item, dict) and item.get("type") in {"text", "input_text", "output_text"}
        )
    if isinstance(value, dict):
        return str(value.get("text") or value.get("message") or "")
    return ""


def _conversation_message(entry: dict, provider: str) -> tuple[str, str] | None:
    if provider == "claude":
        message = entry.get("message") if isinstance(entry.get("message"), dict) else {}
        role = str(message.get("role") or entry.get("type") or "")
        if role not in {"user", "assistant"}:
            return None
        text = _message_text(message.get("content"))
        return (role, text) if text.strip() else None

    payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else entry
    kind = str(payload.get("type") or "")
    role = str(payload.get("role") or "")
    if kind == "user_message":
        role, text = "user", _message_text(payload.get("message") or payload.get("content"))
    elif kind in {"agent_message", "assistant_message"}:
        role, text = "assistant", _message_text(payload.get("message") or payload.get("content"))
    elif kind == "message" and role in {"user", "assistant"}:
        text = _message_text(payload.get("content"))
    else:
        return None
    return (role, text) if text.strip() else None


def _sentences(text: str) -> list[str]:
    clean = " ".join(str(text or "").replace("**", "").replace("`", "").split())
    return [part.strip(" -") for part in re.split(r"(?<=[.!?])\s+", clean) if part.strip(" -")]


def _story_request(messages: list[tuple[str, str]], ticket: dict) -> str:
    for role, text in messages:
        if role != "user":
            continue
        stripped = text.strip()
        if stripped.startswith("<task-notification>") or stripped.startswith("<system-reminder>"):
            continue
        stripped = re.sub(r"^Work on\s+\S+\s*(?:\([^)]*\))?:\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"https?://\S+", "", stripped).strip()
        if len(stripped) >= 12:
            return _compact(stripped, 500)
    return _compact(ticket.get("description") or ticket.get("summary") or ticket.get("key") or "Work on this ticket.", 500)


def _pick_story_sentences(assistant_texts: list[str], pattern: re.Pattern, limit: int,
                          exclude_last: bool = False) -> str:
    pool = assistant_texts[:-1] if exclude_last and len(assistant_texts) > 1 else assistant_texts
    chosen = []
    seen = set()
    for text in pool:
        for sentence in _sentences(text):
            normalized = sentence.lower()
            if normalized in seen or sentence.endswith("?") or not pattern.search(sentence):
                continue
            seen.add(normalized)
            chosen.append(sentence)
    return _compact(" ".join(chosen[-limit:]), 900)


def read_story(log_path: Path | None, provider: str, ticket: dict) -> dict:
    """Human-readable story from the real request and assistant narrative.

    No model call is made here: this preserves the agent's own explanation of
    its decisions instead of generating a second, potentially fictional one.
    """
    fallback_request = _compact(ticket.get("description") or ticket.get("summary") or ticket.get("key") or "Work on this ticket.", 500)
    if provider not in {"claude", "codex"} or not log_path or not log_path.exists():
        return {"request": fallback_request, "rationale": fallback_request, "approach": "No implementation narrative has been recorded yet.", "outcome": "Work has not started in this session."}
    stat = log_path.stat()
    cache_key = (str(log_path), provider, stat.st_size, stat.st_mtime_ns, fallback_request)
    cached = _STORY_CACHE.get(cache_key)
    if cached is not None:
        return cached
    messages = []
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
            message = _conversation_message(entry, provider)
            if message:
                messages.append(message)
    assistant_texts = [text for role, text in messages if role == "assistant" and len(text.strip()) >= 20]
    rationale_pattern = re.compile(r"\b(because|so that|so we|to avoid|rather than|means that|only means|reliable|safest|needed|requires?|in order to|therefore|which is why)\b", re.IGNORECASE)
    approach_pattern = re.compile(r"\b(first|then|next|finally|checked|test(?:ed| passed)?|verified|added|changed|updated|created|restored|copied|implemented|fixed|submitt?\w*|ran|used|wrote|moved|deployed)\b", re.IGNORECASE)
    request = _story_request(messages, ticket)
    rationale = _pick_story_sentences(assistant_texts, rationale_pattern, 3)
    approach = _pick_story_sentences(assistant_texts, approach_pattern, 4, exclude_last=True)
    outcome = _compact(assistant_texts[-1].replace("**", "").replace("`", ""), 1200) if assistant_texts else "No outcome has been recorded yet."
    result = {
        "request": request,
        "rationale": rationale or _compact(ticket.get("description") or ticket.get("summary") or request, 700),
        "approach": approach or "The recorded tool flow below shows how the work was carried out.",
        "outcome": outcome,
    }
    if len(_STORY_CACHE) >= 32:
        _STORY_CACHE.clear()
    _STORY_CACHE[cache_key] = result
    return result


def read_manager_evidence(log_path: Path | None, provider: str, ticket: dict) -> dict:
    """Return bounded conversational evidence for a manager-level synthesis.

    Tool output is intentionally excluded. The summary model needs the agent's
    architectural reasoning and conclusions, not terminal noise or a second
    copy of the action trail. Transcript text remains untrusted input to the
    tool-less summarizer.
    """
    request = _compact(ticket.get("description") or ticket.get("summary") or ticket.get("key") or "", 1200)
    if provider not in {"claude", "codex"} or not log_path or not log_path.exists():
        return {"request": request, "conversation": []}
    stat = log_path.stat()
    messages: list[tuple[str, str]] = []
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
            message = _conversation_message(entry, provider)
            if message:
                messages.append(message)

    # Preserve the initiating request plus the most recent reasoning. Repeated
    # terminal redraws/tool results never enter this list.
    selected = messages[:2] + messages[-14:]
    conversation = []
    seen = set()
    for role, text in selected:
        compact = _compact(
            _SECRET_FLAG_RE.sub(lambda m: m.group(1) + " •••", _SECRET_ASSIGNMENT_RE.sub(lambda m: m.group(1) + "=•••", text)),
            1600,
        )
        identity = (role, compact)
        if len(compact) >= 12 and identity not in seen:
            seen.add(identity)
            conversation.append({"role": role, "text": compact})
    return {"request": _story_request(messages, ticket) or request, "conversation": conversation}


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
