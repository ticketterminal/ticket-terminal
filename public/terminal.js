/* Embedded terminal: opens a real PTY running `claude` for one ticket, over
   a WebSocket to the local server (see server/main.py). This is the whole
   reason this stopped being a Claude Artifact — a sandboxed page can never
   spawn a local process. */
async function copyTerminalText(text) {
  if (!text) return false;
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch (_) {
    // Clipboard permission can be unavailable on file:// or older browsers.
    // The user gesture is still active, so the textarea fallback can work.
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.className = "terminal-copy-fallback";
  document.body.appendChild(textarea);
  textarea.select();
  let copied = false;
  try { copied = document.execCommand("copy"); } catch (_) { /* unsupported */ }
  textarea.remove();
  return copied;
}

function installTerminalCopy(term, container) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "terminal-copy-button";
  button.textContent = "Copy selection";
  button.title = "Copy selected terminal text (⌘C / Ctrl+C / Ctrl+Shift+C)";
  button.hidden = true;
  container.appendChild(button);

  const copySelection = async () => {
    const text = term.getSelection();
    if (!text) return false;
    const copied = await copyTerminalText(text);
    button.textContent = copied ? "Copied" : "Copy failed";
    button.title = copied ? "Terminal selection copied" : "Clipboard access failed";
    return copied;
  };

  term.onSelectionChange(() => {
    button.hidden = !term.hasSelection();
    button.textContent = "Copy selection";
    button.title = "Copy selected terminal text (⌘C / Ctrl+C / Ctrl+Shift+C)";
  });
  button.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    copySelection();
  });

  // xterm owns keyboard input, so browser copy shortcuts do not reliably reach the system
  // clipboard. Keep Ctrl+C as SIGINT when nothing is selected; with a selection it copies,
  // matching integrated terminals. Cmd+C and Ctrl+Shift+C are always copy-only shortcuts.
  term.attachCustomKeyEventHandler((event) => {
    if (event.type !== "keydown" || String(event.key).toLowerCase() !== "c") return true;
    const macCopy = event.metaKey && !event.ctrlKey;
    const terminalCopy = event.ctrlKey && event.shiftKey;
    const selectedCtrlCopy = event.ctrlKey && !event.shiftKey && term.hasSelection();
    if (!macCopy && !terminalCopy && !selectedCtrlCopy) return true;
    if (term.hasSelection()) copySelection();
    return false;
  });
}

window.openTicketTerminal = function (container, ticketKey, promptText, opts) {
  opts = opts || {};
  if (container.disposeTicketTerminal) container.disposeTicketTerminal();
  container.replaceChildren();
  const term = new Terminal({
    convertEol: true,
    fontFamily: '"IBM Plex Mono", monospace',
    fontSize: 13,
    theme: { background: "#0d1b24", foreground: "#dce8ea" },
  });
  const fitAddon = new FitAddon.FitAddon();
  term.loadAddon(fitAddon);
  term.open(container);
  installTerminalCopy(term, container);
  fitAddon.fit();

  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const workspaceParam = opts.workspace ? "&w=" + encodeURIComponent(opts.workspace) : "";
  const ws = new WebSocket(proto + "//" + location.host + "/ws/terminal/" + encodeURIComponent(ticketKey) + "?provider=" + encodeURIComponent(opts.provider || "claude") + workspaceParam);

  ws.binaryType = "arraybuffer";
  ws.addEventListener("open", () => {
    ws.send(JSON.stringify({ type: "start", prompt: promptText }));
    ws.send(JSON.stringify({ type: "resize", rows: term.rows, cols: term.cols }));
  });
  ws.addEventListener("message", (ev) => {
    if (ev.data instanceof ArrayBuffer) {
      term.write(new Uint8Array(ev.data));
    } else {
      term.write(ev.data);
    }
  });
  ws.addEventListener("close", () => {
    term.write("\r\n\x1b[90m[session ended]\x1b[0m\r\n");
    resizeObserver.disconnect();
    if (opts.onClose) opts.onClose();
  });

  term.onData((data) => {
    if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "input", data }));
  });

  const resizeObserver = new ResizeObserver(() => {
    if (!container.getClientRects().length) return;
    fitAddon.fit();
    if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "resize", rows: term.rows, cols: term.cols }));
  });
  resizeObserver.observe(container);

  container.disposeTicketTerminal = () => { resizeObserver.disconnect(); ws.close(); term.dispose(); };
  term.focus();
};
