/* Embedded terminal: opens a real PTY running `claude` for one ticket, over
   a WebSocket to the local server (see server/main.py). This is the whole
   reason this stopped being a Claude Artifact — a sandboxed page can never
   spawn a local process. */
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
