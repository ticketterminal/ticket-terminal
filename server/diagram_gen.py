"""Draft a Mermaid diagram for one memory file's prose body, by shelling out to `claude` in
non-interactive print mode — same reused-authenticated-CLI pattern as auto_categorize.py.
The diagram itself is stored as an ordinary ```mermaid fenced block inside the memory file's
own markdown body (see memory_analysis.extract_diagram/splice_diagram), so it stays plain-
markdown/git-diffable and renderable by any tool that understands markdown+Mermaid — this
module only drafts the fence text, it never invents a separate storage format for it.
"""
import json
import re
import subprocess

GENERATE_TIMEOUT_SECONDS = 60

# Mermaid node ids must be bare (unquoted) tokens — only a node's bracket LABEL may be a
# quoted string. Models asked to use an exact id as a node id (see _build_category_prompt)
# sometimes wrap that id in quotes anyway, e.g. "orca-ai-access-guide"["..."], which fails to
# parse. A quoted span containing only identifier-safe characters (letters/digits/underscore/
# hyphen, no spaces or markup) is never a real label either — a plain label with no special
# characters never needed quoting in the first place — so it's always safe to strip those
# quotes; a genuine label (which has a space or markup like <br/>) never matches this and is
# left untouched.
_QUOTED_BARE_ID_RE = re.compile(r'"([A-Za-z0-9_-]+)"')


def _repair_mermaid(source: str) -> str:
    return _QUOTED_BARE_ID_RE.sub(r"\1", source)


def _build_prompt(body: str, mem_type: str) -> str:
    return (
        "Produce a Mermaid diagram for the memory note below. Respond with ONLY the Mermaid "
        "source (no ``` fences, no prose, no explanation).\n\n"
        "If the note describes a sequence of steps or a workflow, use `flowchart TD`. If it "
        "describes components and how they relate (an architecture), use `graph LR` or "
        "`flowchart LR` with one node per component. Keep labels short — a handful of words "
        "each. If the note is neither (e.g. a single fact, a list of gotchas), do your best to "
        "still capture its structure as a small diagram rather than refusing.\n\n"
        f"Memory type: {mem_type or 'unspecified'}\n\nMemory body:\n{body}"
    )


def _run_claude(prompt: str, timeout: int) -> str | None:
    """Shared claude -p invocation + response unwrapping for both generate() and
    generate_category_diagram() — returns the raw Mermaid source (no fence markers), or None
    on any failure. Deliberately never raises — a failed generation must never corrupt or
    block editing the memory/category it was drafting for."""
    try:
        proc = subprocess.run(
            ["claude", "-p", "--restricted", "--model", "haiku", "--output-format", "json"],
            input=prompt,
            capture_output=True, text=True, timeout=timeout,
        )
        if proc.returncode != 0:
            return None
        result = json.loads(proc.stdout).get("result", "")
        source = result.strip().strip("`").strip()
        if source.startswith("mermaid\n"):
            source = source[len("mermaid\n"):]
        if not source:
            return None
        return _repair_mermaid(source)
    except Exception:
        return None


def generate(body: str, mem_type: str = "") -> str | None:
    """Returns Mermaid source for this memory's body, or None on any failure (claude not
    authenticated, a timeout, an empty/malformed response)."""
    if not body.strip():
        return None
    return _run_claude(_build_prompt(body, mem_type), GENERATE_TIMEOUT_SECONDS)


CATEGORY_GENERATE_TIMEOUT_SECONDS = 90
_BODY_EXCERPT_CHARS = 600


def _build_category_prompt(category_name: str, memories: list[dict]) -> str:
    entries = "\n\n".join(
        f"id: {m['id']}\n"
        f"description: {m.get('description', '')}\n"
        f"body: {m.get('body', '')[:_BODY_EXCERPT_CHARS]}"
        for m in memories
    )
    ids = ", ".join(m["id"] for m in memories)
    return (
        f"These are memory notes filed under one category, \"{category_name}\". Produce ONE "
        "Mermaid diagram (flowchart or graph) showing how they fit together as a whole — the "
        "big picture of this subject, not a separate diagram per note. Respond with ONLY the "
        "Mermaid source (no ``` fences, no prose).\n\n"
        f"For any node that represents one of these notes, its node id MUST be exactly that "
        f"note's id, verbatim and UNQUOTED (these ids: {ids}) — this is required so the app can "
        "link each node back to its source file; do not invent a different id, add a prefix/"
        "suffix, or wrap the id itself in quotes. Only the bracket label may be a quoted "
        'string, e.g. `orca-ai-access-guide["Access guide"]` — NOT '
        '`"orca-ai-access-guide"["Access guide"]`. You may add a small number of extra '
        "connective or grouping nodes with other ids if that clarifies the structure, but "
        f"every listed id must appear as its own node exactly once.\n\nNotes:\n{entries}"
    )


def generate_category_diagram(category_name: str, memories: list[dict]) -> str | None:
    """Returns Mermaid source for one overarching diagram of a category's memories, using each
    memory's own id as its node id (see _build_category_prompt) so the frontend can route a
    node click back to that memory — or None on any failure. memories: [{id, description,
    body}], already filtered to ones that actually exist."""
    if not memories:
        return None
    return _run_claude(_build_category_prompt(category_name, memories), CATEGORY_GENERATE_TIMEOUT_SECONDS)
