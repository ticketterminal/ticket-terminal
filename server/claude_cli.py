"""The one place that knows how to invoke the local `claude` CLI for a small,
tool-less, non-interactive classification call (category guesses, content
tags, category review). Three modules used to each spell out their own
command line — and all three carried `--restricted`, a flag Claude Code
dropped (2.1.x rejects it as "unknown option"), which made every call fail
and, in auto_categorize's case, fail *silently* into "no category". Verified
2026-09-15 on Claude Code 2.1.218: `--tools ""` is what actually disables
tools; `--bare` is NOT usable (it skips the settings that hold the login).
"""
import os
import shutil

MODEL = "haiku"


def executable() -> str | None:
    """Honors WMP_CLAUDE_BIN (the same override the embedded terminal uses)."""
    return shutil.which(os.path.expanduser(os.environ.get("WMP_CLAUDE_BIN") or "claude"))


def command(exe: str) -> list[str]:
    """`--tools ""` only clears the BUILT-IN tools — it leaves the operator's
    MCP servers connected and their pre-approved tools callable. Since the
    entire prompt of every one of these calls is untrusted ticket text from
    Jira/Notion, that left a prompt-injected ticket able to reach real MCP
    tools (verified 2026-09-15: a call built without --safe-mode listed the
    workspace's Notion MCP tools, write tools included, under an auto-approve
    permission mode). `--safe-mode` is the flag that disables MCP servers,
    hooks, plugins, skills, custom agents and CLAUDE.md loading;
    --strict-mcp-config with no --mcp-config is belt and braces so no server
    can be reintroduced from a config file."""
    return [exe, "-p", "--safe-mode", "--strict-mcp-config", "--tools", "",
            "--model", MODEL, "--no-session-persistence", "--output-format", "json"]


def env() -> dict:
    """Strip the CLAUDE* vars a parent Claude Code session would leak in —
    a nested run refuses to start inside another session's environment."""
    return {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE") and k != "AI_AGENT"}
