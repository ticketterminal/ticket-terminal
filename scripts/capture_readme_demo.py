#!/usr/bin/env python3
"""Capture the README product tour from the real frontend with safe fixture data.

The capture page serves public/index.html and all production JavaScript/CSS unchanged.
Only the network/terminal edges are replaced with deterministic in-browser fixtures, so
the resulting frames exercise the same ticket, terminal, and agent-trail renderers users
see in the app without reading the operator's tracker or session data.
"""

from __future__ import annotations

import argparse
import http.server
import json
import shutil
import socketserver
import subprocess
import tempfile
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


TICKETS = {
    "TT-104": {
        "key": "TT-104",
        "summary": "Add retry guard to invoice sync",
        "description": "Retry transient provider failures with capped exponential backoff, while keeping permanent failures visible.",
        "categories": ["reliability"],
        "jiraStatus": "In Progress",
        "jiraPriority": "High",
        "team": "Platform",
        "reporterName": "Maya Chen",
        "assigneeName": "Alex Morgan",
        "assigneeAccountId": "alex",
        "createdAt": "2026-10-09T09:30:00Z",
        "updatedAt": "2026-10-11T09:14:00Z",
        "reviewed": True,
        "source": "jira",
        "url": "https://example.invalid/browse/TT-104",
        "codexSessionId": "demo-codex-session",
        "contentTags": ["billing", "retries", "sync"],
        "changeRequests": [{
            "url": "https://github.com/ticketterminal/ticket-terminal/pull/42",
            "provider": "github",
            "repository": "ticketterminal/ticket-terminal",
            "number": 42,
            "source": "transcript",
            "discoveredAt": "2026-10-11T09:14:00Z",
        }],
        "notes": [{"at": "2026-10-11 09:16", "text": "Reproduced the timeout path locally."}],
    },
    "TT-107": {
        "key": "TT-107",
        "summary": "Document the release rollback path",
        "description": "Turn the current rollback checklist into a shared runbook.",
        "categories": ["release"],
        "jiraStatus": "Backlog",
        "jiraPriority": "Medium",
        "team": "Platform",
        "reporterName": "Sam Rivera",
        "assigneeName": "Jordan Lee",
        "assigneeAccountId": "jordan",
        "createdAt": "2026-10-08T11:00:00Z",
        "updatedAt": "2026-10-10T14:00:00Z",
        "reviewed": True,
        "source": "notion",
        "url": "https://example.invalid/ticket/TT-107",
        "contentTags": ["release", "runbook"],
        "notes": [],
    },
    "TT-099": {
        "key": "TT-099",
        "summary": "Cache package metadata during startup",
        "description": "Avoid repeated metadata reads on every board refresh.",
        "categories": ["reliability"],
        "jiraStatus": "Done",
        "jiraPriority": "Low",
        "team": "Developer Experience",
        "reporterName": "Taylor Brooks",
        "assigneeName": "Alex Morgan",
        "assigneeAccountId": "alex",
        "createdAt": "2026-10-03T08:00:00Z",
        "updatedAt": "2026-10-09T16:20:00Z",
        "reviewed": True,
        "source": "jira",
        "url": "https://example.invalid/browse/TT-099",
        "contentTags": ["startup", "performance"],
        "notes": [],
    },
}

CATEGORIES = [
    {
        "id": "reliability",
        "name": "Reliability",
        "status": "covered",
        "color": "#ea7c55",
        "note": "Failure handling, retries, and operational safeguards.",
        "memories": ["retry-policy"],
        "skills": ["incident-debugging"],
        "docs": [],
    },
    {
        "id": "release",
        "name": "Release Engineering",
        "status": "partial",
        "color": "#6fb4a8",
        "note": "Release, rollback, and deployment practices.",
        "memories": ["release-checklist"],
        "skills": [],
        "docs": [],
    },
]

AGENT_EVENTS = [
    {
        "id": "evt-1", "timestamp": "2026-10-11T09:12:01Z", "kind": "memory",
        "title": "Read memory", "detail": "retry-policy.md",
        "resource": {"type": "memory", "id": "retry-policy", "label": "Retry policy", "path": "memory/retry-policy.md"},
    },
    {
        "id": "evt-2", "timestamp": "2026-10-11T09:12:08Z", "kind": "search",
        "title": "Search files", "detail": "retry|backoff",
        "resource": {"type": "file", "label": "server/", "path": "server/"},
    },
    {
        "id": "evt-3", "timestamp": "2026-10-11T09:12:21Z", "kind": "read",
        "title": "Read server/sync.py", "detail": "server/sync.py",
        "resource": {"type": "file", "label": "server/sync.py", "path": "server/sync.py"},
    },
    {
        "id": "evt-4", "timestamp": "2026-10-11T09:13:03Z", "kind": "write",
        "title": "Change server/retry.py", "detail": "server/retry.py",
        "resource": {"type": "file", "label": "server/retry.py", "path": "server/retry.py"},
    },
    {
        "id": "evt-5", "timestamp": "2026-10-11T09:13:40Z", "kind": "command",
        "title": "Run command", "detail": "pytest tests/test_retry.py -q",
    },
    {
        "id": "evt-6", "timestamp": "2026-10-11T09:14:02Z", "kind": "command",
        "title": "Git command", "detail": "git diff --check",
    },
]

AGENT_SUMMARY = {
    "headline": "Work recorded toward “Add retry guard to invoice sync”.",
    "why": "Retry transient provider failures without hiding permanent failures.",
    "facts": ["Changed 2 named objects", "Ran 2 verification commands", "Used the shared retry policy"],
    "flow": [
        {"id": "investigate", "label": "Investigate", "detail": "Trace the invoice sync failure path", "count": 2},
        {"id": "knowledge", "label": "Use knowledge", "detail": "Read the shared retry policy", "count": 1},
        {"id": "change", "label": "Make changes", "detail": "Add capped exponential backoff", "count": 1},
        {"id": "verify", "label": "Verify", "detail": "Run retry tests and diff checks", "count": 2},
    ],
    "objects": [
        {"type": "file", "label": "server/retry.py", "path": "server/retry.py", "action": "update"},
        {"type": "file", "label": "tests/test_retry.py", "path": "tests/test_retry.py", "action": "update"},
    ],
    "knowledge": [{"type": "memory", "id": "retry-policy", "label": "Retry policy", "path": "memory/retry-policy.md"}],
}

MANAGER_BRIEF = {
    "requestedChange": "Make invoice sync resilient to transient provider failures while keeping permanent errors visible.",
    "architecture": "Jira remains the source of truth. Ticket Terminal runs the local Codex session against the existing sync service and attaches the evidence back to TT-104.",
    "rationale": "A capped retry policy improves reliability without turning authentication, validation, or other permanent failures into silent delays.",
    "implementation": "The sync path now classifies provider failures and applies capped exponential backoff only to transient responses. Focused regression tests cover both retryable and permanent cases.",
    "rollout": "Merge PR #42 after review, deploy through staging, and watch retry volume plus terminal failure counts before production rollout.",
    "status": "Implementation is ready for review. Twelve retry tests and the repository diff check pass.",
}

TERMINAL_TEXT = """$ codex --resume demo-codex-session
Ticket TT-104 · Add retry guard to invoice sync

Reading the shared retry policy and tracing the sync path...
✓ Added capped exponential backoff for transient failures
✓ Kept permanent provider errors visible
✓ 12 retry tests passed

Ready for review: ticketterminal/ticket-terminal #42
"""

CAPTIONS = [
    "Keep Jira or Notion as the source of truth.",
    "Open the ticket. Launch the real local Claude or Codex CLI.",
    "The agent works in your repository, inside the ticket.",
    "See every memory read, file change, command, test, and PR.",
    "Turn the trail into a manager-ready brief. Clone it and run locally.",
]


def browser_fixture(stage: int) -> str:
    responses = {
        "/api/workspaces": {"ok": True, "defaultWorkspace": "default", "workspaces": [{"slug": "default", "name": "Default"}]},
        "/api/categories": CATEGORIES,
        "/api/config": {"jiraBaseUrl": "https://example.invalid", "jiraConfigured": True, "notionConfigured": True},
        "/api/jira-statuses": {"ok": True, "statuses": [{"id": "1", "name": "Backlog"}, {"id": "2", "name": "In Progress"}, {"id": "3", "name": "Done"}]},
        "/api/jira-assignable-users": {"ok": True, "users": [{"accountId": "alex", "displayName": "Alex Morgan"}, {"accountId": "jordan", "displayName": "Jordan Lee"}]},
        "/api/notion/options": {"ok": True, "statuses": ["Backlog", "In Progress", "Done"], "priorities": ["High", "Medium", "Low"], "doneStatuses": ["Done"], "sprints": []},
        "/api/tickets": TICKETS,
        "/api/people": {"maya": {"name": "Maya Chen", "team": "Platform"}, "sam": {"name": "Sam Rivera", "team": "Platform"}},
        "/api/team-options": ["Platform", "Developer Experience"],
        "/api/ticket-costs": {"ok": True, "costs": {"codex:TT-104": {"provider": "codex", "cost": 0.18, "inputTokens": 28400, "outputTokens": 3100, "models": ["gpt-5"]}}},
        "/api/ticket-memory-usage": {"ok": True, "usage": {"codex:TT-104": {"retry-policy": 1}}},
        "/api/running-processes": {"ok": True, "running": ["codex:TT-104"], "working": ["codex:TT-104"]},
        "/api/terminal-providers": {"providers": ["claude", "codex"]},
        "/api/category-management": {"ok": True, "data": {"revision": "demo", "onboarded": True, "categories": CATEGORIES, "reviews": [], "scan": {"status": "idle", "finishedAt": ""}}},
        "/api/agent-activity/TT-104": {
            "ok": True,
            "events": AGENT_EVENTS[:4] if stage == 3 else AGENT_EVENTS,
            "summary": AGENT_SUMMARY,
        },
        "/api/manager-summary/TT-104": {"ok": True, "brief": MANAGER_BRIEF},
        "/api/tickets/TT-104/change-requests/refresh": {"ok": True, "changeRequests": TICKETS["TT-104"]["changeRequests"]},
    }
    return f"""
<script>
(() => {{
  const stage = {stage};
  const responses = {json.dumps(responses)};
  const terminalText = {json.dumps(TERMINAL_TEXT)};
  localStorage.setItem('wmp.viewMode', 'grouped');
  localStorage.setItem('wmp.showNested', 'off');
  localStorage.setItem('wmp.hideGettingStarted', '1');

  const cleanPath = input => {{
    const url = new URL(typeof input === 'string' ? input : input.url, location.origin);
    return url.pathname;
  }};
  window.fetch = async input => {{
    const path = cleanPath(input);
    let body = responses[path];
    if (path.startsWith('/api/agent-activity/')) body = responses['/api/agent-activity/TT-104'];
    if (path.startsWith('/api/manager-summary/')) body = responses['/api/manager-summary/TT-104'];
    if (path.includes('/change-requests/refresh')) body = responses['/api/tickets/TT-104/change-requests/refresh'];
    if (body === undefined) body = {{ok: true}};
    return new Response(JSON.stringify(body), {{status: 200, headers: {{'Content-Type': 'application/json'}}}});
  }};

  const stripAnsi = text => String(text).replace(/\\u001b\\[[0-9;?]*[ -\\/]*[@-~]/g, '');
  window.Terminal = class {{
    constructor() {{ this.rows = 22; this.cols = 100; }}
    loadAddon() {{}}
    open(container) {{
      this.pre = document.createElement('pre');
      this.pre.className = 'capture-terminal';
      container.appendChild(this.pre);
    }}
    write(value) {{
      if (value instanceof Uint8Array) value = new TextDecoder().decode(value);
      this.pre.textContent += stripAnsi(value);
      this.pre.scrollTop = this.pre.scrollHeight;
    }}
    onData() {{ return {{dispose() {{}}}}; }}
    focus() {{}}
    dispose() {{}}
  }};
  window.FitAddon = {{FitAddon: class {{ fit() {{}} }}}};
  window.vis = {{Network: class {{ destroy() {{}} }}, DataSet: class {{}}}};
  window.mermaid = {{initialize() {{}}, render: async () => ({{svg: ''}})}};
  window.ResizeObserver = class {{ observe() {{}} disconnect() {{}} }};
  window.WebSocket = class extends EventTarget {{
    static OPEN = 1;
    constructor() {{
      super(); this.readyState = 0;
      setTimeout(() => {{
        this.readyState = 1;
        this.dispatchEvent(new Event('open'));
        setTimeout(() => this.dispatchEvent(new MessageEvent('message', {{data: terminalText}})), 80);
      }}, 40);
    }}
    send() {{}}
    close() {{ this.readyState = 3; this.dispatchEvent(new Event('close')); }}
  }};

  const style = document.createElement('style');
  style.textContent = `
    .capture-terminal {{ box-sizing:border-box; height:100%; margin:0; overflow:hidden; padding:18px;
      white-space:pre-wrap; color:#dce8ea; background:#0d1b24; font:500 14px/1.55 "IBM Plex Mono",monospace; }}
    .capture-caption {{ position:fixed; z-index:9999; left:50%; bottom:22px; transform:translateX(-50%);
      width:min(900px,calc(100vw - 56px)); box-sizing:border-box; padding:14px 22px; border:1px solid #ef9a72;
      border-radius:12px; color:#fff8ee; background:rgba(13,27,36,.94); box-shadow:0 12px 40px rgba(0,0,0,.38);
      font:700 19px/1.35 "Public Sans",sans-serif; text-align:center; }}
    .capture-brand {{ position:fixed; z-index:9998; top:18px; left:20px;
      padding:9px 13px; border:1px solid rgba(239,154,114,.72); border-radius:999px; color:#fff8ee;
      background:rgba(13,27,36,.92); box-shadow:0 8px 24px rgba(0,0,0,.28);
      font:700 12px/1 "IBM Plex Mono",monospace; letter-spacing:.08em; }}
    body.capture-focus .station-strip, body.capture-focus .titleblock, body.capture-focus #gettingStarted,
    body.capture-focus #categoryNotice, body.capture-focus #demoNotice, body.capture-focus #skillsSection,
    body.capture-focus .foot {{ display:none !important; }}
    body.capture-focus .wrap {{ padding-top:18px; }}
    body.capture-focus .refreshbar {{ margin-bottom:10px; }}
    body.capture-focus #ticketsSection > .sectionhead, body.capture-focus .searchwrap,
    body.capture-focus .teamfilterwrap, body.capture-focus .statusfilterwrap,
    body.capture-focus .assigneefilterwrap, body.capture-focus .categorytoolbar {{ display:none !important; }}
  `;
  document.head.appendChild(style);

  function findButton(root, text) {{
    return [...root.querySelectorAll('button')].find(button => button.textContent.includes(text));
  }}
  function run() {{
    const row = document.querySelector('.ticketrow[data-ticket-key="TT-104"]');
    if (!row) return setTimeout(run, 50);
    const brand = document.createElement('div');
    brand.className = 'capture-brand';
    brand.textContent = 'TICKET TERMINAL   ·   OPEN SOURCE   ·   RUNS LOCALLY';
    document.body.appendChild(brand);
    const caption = document.createElement('div');
    caption.className = 'capture-caption';
    caption.textContent = {json.dumps(CAPTIONS)}[stage];
    document.body.appendChild(caption);
    document.body.classList.add('capture-focus');
    if (stage === 0) return;
    row.querySelector('.rowtri').click();
    if (stage >= 2) {{
      findButton(row, 'Open Codex').click();
      setTimeout(() => {{
        const terminal = row.querySelector('.capture-terminal');
        if (terminal) terminal.textContent = terminalText;
      }}, 160);
    }}
    if (stage === 3) setTimeout(() => {{
      const toggle = [...row.querySelectorAll('.agenttrail-toggle')].find(button => !button.hidden && button.textContent.includes('Agent trail'));
      if (toggle) toggle.click();
    }}, 260);
    if (stage === 4) setTimeout(() => {{
      const toggle = [...row.querySelectorAll('.managersummary-toggle')].find(button => !button.hidden);
      if (toggle) toggle.click();
    }}, 260);
  }}
  window.addEventListener('load', () => setTimeout(run, 100));
}})();
</script>
"""


class CaptureHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/demo"}:
            stage = max(0, min(4, int(parse_qs(parsed.query).get("stage", ["0"])[0])))
            html = (PUBLIC / "index.html").read_text()
            for src in (
                '<script src="https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.js"></script>',
                '<script src="https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.js"></script>',
                '<script src="https://cdn.jsdelivr.net/npm/vis-network@9.1.9/standalone/umd/vis-network.min.js"></script>',
                '<script src="https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"></script>',
            ):
                html = html.replace(src, "")
            html = html.replace('<script src="/static/terminal.js"></script>', browser_fixture(stage) + '\n<script src="/static/terminal.js"></script>')
            payload = html.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if parsed.path.startswith("/static/"):
            relative = parsed.path.removeprefix("/static/")
            target = (PUBLIC / relative).resolve()
            if PUBLIC.resolve() not in target.parents or not target.is_file():
                self.send_error(404)
                return
            self.path = "/" + relative
            return http.server.SimpleHTTPRequestHandler.do_GET(self)
        self.send_error(404)

    def translate_path(self, path: str) -> str:
        relative = urlparse(path).path.lstrip("/")
        return str((PUBLIC / relative).resolve())


class ReusableServer(socketserver.TCPServer):
    allow_reuse_address = True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "docs/assets/ticket-terminal-demo.gif")
    parser.add_argument("--keep-frames", action="store_true")
    args = parser.parse_args()
    if not CHROME.exists():
        raise SystemExit(f"Chrome not found at {CHROME}")

    frame_dir = Path(tempfile.mkdtemp(prefix="ticket-terminal-demo-"))
    server = ReusableServer(("127.0.0.1", 0), CaptureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        frames = []
        for stage in range(5):
            frame = frame_dir / f"frame-{stage}.png"
            subprocess.run(
                [
                    str(CHROME), "--headless=new", "--hide-scrollbars", "--disable-gpu",
                    "--force-device-scale-factor=1", "--window-size=1440,900",
                    "--run-all-compositor-stages-before-draw", "--virtual-time-budget=2500",
                    f"--screenshot={frame}", f"http://127.0.0.1:{port}/demo?stage={stage}",
                ],
                check=True,
                stdout=subprocess.DEVNULL,
            )
            frames.append(frame)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["swift", str(ROOT / "scripts/assemble_demo_gif.swift"), str(args.output), *map(str, frames)],
            check=True,
        )
        print(args.output)
        if args.keep_frames:
            kept = args.output.parent / "ticket-terminal-demo-frames"
            if kept.exists():
                shutil.rmtree(kept)
            shutil.copytree(frame_dir, kept)
            print(kept)
    finally:
        server.shutdown()
        server.server_close()
        shutil.rmtree(frame_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
