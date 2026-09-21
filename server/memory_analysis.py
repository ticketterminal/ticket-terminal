"""Reads this app's own knowledge-base folder — a plain folder of markdown files any LLM
vendor's agent can read or write (see MEMORY_FORMAT.md at the repo root for the format spec,
including the optional ```mermaid diagram convention). By default this folder is Claude Code's
own per-project memory location (~/.claude/projects/<sanitized-cwd>/memory/), reused for
convenience since Claude Code's built-in memory tool already writes there for free and every
ticket terminal already has live read/write access to it (confirmed empirically: a fresh,
unrelated `claude -p` call in that cwd can recall a fact from these files with no extra wiring)
— but it's a plain folder, fully overridable via the Settings page's memoryDir (see
memory_dir_info below), and not tied to Claude in format or in who may read/write it. This
module reads that folder to build a graph view, and counts how a ticket's own session actually
used it across whichever agent vendor ran that ticket (see all_ticket_memory_usage).
"""
import glob
import json
import os
import re
from pathlib import Path

import yaml

import settings_store


def claude_project_dir(cwd: str) -> Path:
    """The ~/.claude/projects/<sanitized-cwd> directory Claude Code itself uses for a given
    working directory — same sanitization scheme Claude Code applies internally."""
    return Path.home() / ".claude" / "projects" / cwd.replace("/", "-")


DEFAULT_WORKDIR = os.environ.get("WMP_DEFAULT_WORKDIR") or str(Path.home())


def memory_dir_info() -> dict:
    """Where the memory corpus is read from, and why — precedence is: the
    Settings page's memoryDir (data/settings.json) if set, else WMP_MEMORY_DIR
    (a dedicated env var, independent of WMP_DEFAULT_WORKDIR — pointing the
    embedded terminal at a workdir and pointing this feature at a knowledge-
    base folder are different concerns), else today's default of deriving it
    from Claude Code's own per-workdir memory convention. Re-read on every
    call (not cached at import) so a Settings-page save takes effect
    immediately."""
    from_settings = (settings_store.read().get("memoryDir") or "").strip()
    if from_settings:
        return {"path": Path(from_settings), "source": "settings"}
    from_env = os.environ.get("WMP_MEMORY_DIR", "").strip()
    if from_env:
        return {"path": Path(from_env), "source": "env"}
    return {"path": claude_project_dir(DEFAULT_WORKDIR) / "memory", "source": "default"}


def _memory_dir() -> Path:
    return memory_dir_info()["path"]


_SKIP_FILES = {"MEMORY.md", "README.md"}
_LINK_RE = re.compile(r"\[\[([a-z0-9-]+)\]\]")
_ID_RE = re.compile(r"^[a-z0-9-]+$")
_MERMAID_RE = re.compile(r"```mermaid\n(.*?)```", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    try:
        meta = yaml.safe_load(text[3:end].strip()) or {}
    except yaml.YAMLError:
        meta = {}
    return meta, text[end + 4:]


def read_graph() -> dict:
    """{nodes: [{id, description, type}], edges: [{from, to}]} — nodes are every memory file's
    own frontmatter `name`/`description`/`metadata.type`; edges are [[wikilink]] references
    found in each doc's body, deduped, and only kept when the target is a real node (a stale
    or typo'd link just doesn't render as an edge, rather than erroring)."""
    nodes = []
    bodies = {}
    ids = set()
    for path in sorted(_memory_dir().glob("*.md")):
        if path.name in _SKIP_FILES:
            continue
        meta, body = _parse_frontmatter(path.read_text())
        node_id = meta.get("name") or path.stem
        ids.add(node_id)
        bodies[node_id] = body
        nodes.append({
            "id": node_id,
            "description": meta.get("description", ""),
            "type": (meta.get("metadata") or {}).get("type", ""),
        })
    seen = set()
    edges = []
    for node_id, body in bodies.items():
        for m in _LINK_RE.finditer(body):
            target = m.group(1)
            if target == node_id or target not in ids:
                continue
            key = (node_id, target)
            if key in seen:
                continue
            seen.add(key)
            edges.append({"from": node_id, "to": target})
    return {"nodes": nodes, "edges": edges}


def read_doc(memory_id: str) -> str | None:
    if not _ID_RE.match(memory_id):
        return None
    path = _memory_dir() / f"{memory_id}.md"
    return path.read_text() if path.exists() else None


def write_doc(memory_id: str, content: str) -> None:
    if not _ID_RE.match(memory_id):
        raise ValueError("invalid memory id")
    path = _memory_dir() / f"{memory_id}.md"
    if not path.exists():
        raise FileNotFoundError(memory_id)
    path.write_text(content)


def extract_diagram(body: str) -> str | None:
    """The Mermaid source inside a ```mermaid fenced block in this memory's body, per the
    diagram convention in MEMORY_FORMAT.md — None when the memory has no diagram yet."""
    m = _MERMAID_RE.search(body)
    return m.group(1).strip() if m else None


def splice_diagram(body: str, mermaid_source: str) -> str:
    """Returns body with its existing ```mermaid fence replaced by mermaid_source, or a new
    "## Diagram" section appended when body has none yet."""
    fence = "```mermaid\n" + mermaid_source.strip() + "\n```"
    if _MERMAID_RE.search(body):
        return _MERMAID_RE.sub(fence.replace("\\", "\\\\"), body, count=1)
    sep = "" if not body or body.endswith("\n\n") else ("\n" if body.endswith("\n") else "\n\n")
    return body + sep + "## Diagram\n\n" + fence + "\n"


def _memory_ids() -> set[str]:
    return {p.stem for p in _memory_dir().glob("*.md") if p.name not in _SKIP_FILES}


def memory_file_stats() -> dict[str, dict]:
    """{memoryId: {"chars": int}} — a rough size for every real memory file, for spotting
    docs that are both bloated and heavily read (see workflow_insights.py's memory-structure
    section, and all_ticket_memory_usage above for the read-count side of that)."""
    stats = {}
    for path in _memory_dir().glob("*.md"):
        if path.name in _SKIP_FILES:
            continue
        stats[path.stem] = {"chars": len(path.read_text())}
    return stats


def session_memory_usage(cwd: str, session_id: str) -> dict[str, int]:
    """{memoryId: times read} for one Claude ticket session's own transcript. Deliberately
    conservative: only counts a `Read` tool call whose file_path is exactly one memory file —
    a Grep/Glob sweep across the memory dir isn't attributable to any one file without also
    parsing its tool_result, so it's left out rather than approximated."""
    log_path = claude_project_dir(cwd) / f"{session_id}.jsonl"
    if not log_path.exists():
        return {}
    ids = _memory_ids()
    memory_dir = _memory_dir()
    counts: dict[str, int] = {}
    with open(log_path) as f:
        for line in f:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            content = (entry.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                if block.get("name") != "Read":
                    continue
                file_path = (block.get("input") or {}).get("file_path", "")
                p = Path(file_path)
                if p.parent == memory_dir and p.stem in ids:
                    counts[p.stem] = counts.get(p.stem, 0) + 1
    return counts


def _codex_transcript_path(session_id: str, home: Path | None = None) -> Path | None:
    home = Path(home or os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    matches = glob.glob(str(home / "sessions" / "**" / f"*{session_id}.jsonl"), recursive=True)
    return Path(matches[0]) if matches else None


def codex_session_memory_usage(session_id: str) -> dict[str, int]:
    """{memoryId: times mentioned} for one Codex ticket session's own transcript.
    Codex's own tool-call event shape varies by CLI build (observed here: a
    ```custom_tool_call``` whose `input` is a JS string invoking `tools.exec_command({cmd:...})`
    — not the plain {"command": [...]} shell-call shape another build might use), so rather
    than parsing one exact field, this scans each raw transcript line for the memory file's
    absolute path as a literal substring — tolerant of whichever shape actually produced the
    line, at the cost of being a coarser signal than Claude's exact-Read-tool-call count above."""
    log_path = _codex_transcript_path(session_id)
    if not log_path or not log_path.exists():
        return {}
    ids = _memory_ids()
    memory_dir = _memory_dir()
    counts: dict[str, int] = {}
    with open(log_path) as f:
        for line in f:
            for memory_id in ids:
                if str(memory_dir / f"{memory_id}.md") in line:
                    counts[memory_id] = counts.get(memory_id, 0) + 1
    return counts


def all_ticket_memory_usage(tickets: dict, default_workdir: str) -> dict[str, dict[str, int]]:
    """{sessionId: {memoryId: count}} across every ticket that has a session, for every agent
    vendor a ticket might have run under (today: claude, codex — same pair main.py's
    /api/ticket-costs already iterates). Also aliases each entry under "<provider>:<ticketKey>"
    so a ticket that has run under more than one vendor over its lifetime can show a usage
    badge per vendor, same convention /api/ticket-costs already uses for its own per-provider
    badges."""
    result = {}
    for key, ticket in tickets.items():
        for provider in ("claude", "codex"):
            session_id = ticket.get(provider + "SessionId")
            if not session_id:
                continue
            if provider == "claude":
                cwd = ticket.get("workDir") or default_workdir
                usage = session_memory_usage(cwd, session_id)
            else:
                usage = codex_session_memory_usage(session_id)
            if usage:
                result[session_id] = usage
                result[provider + ":" + key] = usage
    return result
