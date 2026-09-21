# Memory format

The "memory" this app reads and edits (`server/memory_analysis.py`) is a plain folder of
markdown files. Nothing about the format is specific to Claude or to this app — any tool, or
any LLM vendor's agent (Claude, Codex, a future local model), can read or write it directly on
disk. This doc is the authoritative spec: if `memory_analysis.py`'s actual parsing ever
disagrees with what's written here, that's a bug in one of the two, not a license to guess.

Where this folder lives for a given install of this app is configurable (Settings page →
Memory source, `memoryDir`); by default it's Claude Code's own per-project memory location,
reused for convenience, but that's a default, not a requirement of the format itself.

## A memory is one `.md` file

The filename (minus `.md`) is that memory's id, unless overridden by a `name` in frontmatter
(see below) — in which case the frontmatter `name` is the id. Ids match `^[a-z0-9-]+$`.

Two filenames are reserved as index pages, not memories: `MEMORY.md` and `README.md`. Both are
skipped when building the graph.

## Optional YAML frontmatter

A memory file may start with a YAML frontmatter block:

```markdown
---
name: my-memory-id
description: one-line summary shown in the graph and in tooltips
metadata:
  type: user | feedback | project | reference
---

The rest of the file is plain markdown prose.
```

- `name` — overrides the id derived from the filename. Optional.
- `description` — a one-line summary. Shown in the graph UI. Optional.
- `metadata.type` — an open string, not a closed enum. `user` / `feedback` / `project` /
  `reference` are this app's own conventional values (used for the graph's color-coded filter
  buttons), but any tool producing memories in this format is free to use its own values — an
  unrecognized type just renders in a default color, it isn't rejected.

A file with no frontmatter at all is still a valid memory — its id is just the filename, with
no description or type.

## Cross-references: `[[other-file-id]]`

Anywhere in a memory's body, `[[some-id]]` is a link to another memory file. These become the
edges in the graph. A link to an id that doesn't exist (a stale reference, a typo) is silently
dropped from the graph rather than treated as an error.

## Diagrams: an optional ` ```mermaid ` fence

A memory's body may include a fenced Mermaid code block:

    ```mermaid
    flowchart TD
      A[Start] --> B[Do the thing]
    ```

When present, this app renders it as an editable diagram alongside the memory's prose in the
memory graph panel — a workflow-shaped memory typically as a `flowchart`, an architecture-
shaped one typically as a `graph`/`flowchart` of components and relationships. The diagram
lives in the same file as the prose (no separate field or sidecar file), so the memory stays
one portable, git-diffable file, and the diagram renders in any tool that already renders
markdown + Mermaid (GitHub, Obsidian, this app). A memory with no such fence simply has no
diagram; this app can draft one on request (via the signed-in `claude` CLI), but the fence
itself, once written, has no dependency on that or any other specific tool.

At most one `mermaid` fence per file is treated as *the* diagram — if a memory's prose happens
to include additional fenced Mermaid blocks as examples, only the first is read/replaced as the
canonical diagram.

## What this format deliberately doesn't specify

- **Storage/transport.** Plain files on a filesystem. Sync it with git, Dropbox, anything —
  the format doesn't care.
- **Who may write it.** Any process with filesystem access — a human editor, this app, a
  Claude Code session, a Codex session, a future local model's own tool calls.
- **A schema for the prose body.** It's markdown; write what you want.
