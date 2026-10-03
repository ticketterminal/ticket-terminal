// Standalone Help popup: Casey the stationmaster (see mascot.js) walks through
// a handful of real, grounded tips about the app. Not a guided tour tied to
// page state — just a dialog you can open any time from the header.
import { el } from "./dom-utils.js";
import { mascotSay } from "./mascot.js";

const TIPS = [
  {
    title: "Categories are the knowledge index",
    text: "Tickets are filed into meta-categories — the lanes on the board. Click a lane header or a tile to open the real SKILL.md / CLAUDE.md / memory notes behind that category, not just a label.",
  },
  {
    title: "Trackers feed in on their own",
    text: "New tickets from your connected trackers (Jira, Notion) get filed into a suggested category automatically, marked NEW — confirm the suggestion or move it yourself.",
  },
  {
    title: "Terminals are the real thing",
    text: "Opening a ticket starts a genuine Claude or Codex session in a real terminal on your machine — not a sandbox, not a replay of a transcript.",
  },
  {
    title: "The memory graph is shared",
    text: "Markdown notes any agent session writes land in the memory graph — a knowledge base every session (yours and theirs) can read and build on.",
  },
  {
    title: "Insights track the real cost",
    text: "The Insights page breaks down cost, model, and cache usage across every Claude/Codex session that's run — nothing estimated.",
  },
];

let dialog = null;
let index = 0;

function render(){
  dialog.replaceChildren();
  const tip = TIPS[index];
  dialog.appendChild(mascotSay([
    el("h2", null, tip.title),
    el("p", "sub", tip.text),
  ]));
  const nav = el("div", "helpnav");
  const back = document.createElement("button");
  back.type = "button"; back.className = "refreshbtn"; back.textContent = "Back";
  back.disabled = index === 0;
  back.addEventListener("click", () => { index = Math.max(0, index - 1); render(); });
  const count = el("span", "helpcount", (index + 1) + " / " + TIPS.length);
  const isLast = index === TIPS.length - 1;
  const next = document.createElement("button");
  next.type = "button"; next.className = "refreshbtn"; next.textContent = isLast ? "Got it!" : "Next";
  next.addEventListener("click", () => {
    if (isLast){ dialog.close(); return; }
    index += 1; render();
  });
  nav.append(back, count, next);
  dialog.appendChild(nav);
}

export function initHelp(){
  const btn = document.getElementById("helpBtn");
  if (!btn) return;
  btn.addEventListener("click", () => {
    if (!dialog){
      dialog = document.createElement("dialog");
      dialog.className = "helpdialog";
      document.body.appendChild(dialog);
    }
    index = 0;
    render();
    dialog.showModal();
  });
}
