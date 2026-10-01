// A small, fixed set of illustrative tickets shown only while the board has
// no real tracker connected and no real tickets yet (see polling.js's
// reloadBoard) — so a brand-new install shows what a populated board looks
// like instead of six empty lanes. Every doc below carries `isDemo: true`;
// ticket-row.js and terminal-controller.js check that flag at each place a
// real row would otherwise push a change back to a tracker, edit local state,
// or spawn a real agent session, and disable/neutralize it instead. These
// tickets are never sent to the server and never written to db.json — they
// exist only in the browser, for exactly as long as this condition holds.
import { state } from "./state.js";
import { makeSnapshot } from "./api.js";

// Category ids are resolved from whatever lanes the board already has
// (the two generic placeholders, or a chosen role's starter set) rather than
// hardcoded, so this set always lands somewhere visible regardless of where
// the viewer is in onboarding.
function categoryAt(index){
  if (!state.categories.length) return undefined;
  return state.categories[index % state.categories.length].id;
}

export function buildDemoDocs(){
  if (!state.categories.length) return [];
  const catA = categoryAt(0);
  const catB = categoryAt(1);
  const now = new Date();
  const daysAgo = n => new Date(now.getTime() - n * 86400000).toISOString();

  const tickets = [
    {
      key: "DEMO-101",
      summary: "Set up the staging database replica",
      description: "Point the staging environment at a read replica instead of prod, so load testing stops competing with real traffic.",
      jiraStatus: "In Progress",
      jiraPriority: "High",
      categories: [catA],
      createdAt: daysAgo(2),
      contentTags: ["infrastructure", "database"],
    },
    {
      key: "DEMO-102",
      summary: "Document the deploy runbook",
      description: "The deploy steps only live in one engineer's head right now — write them down.",
      jiraStatus: "Backlog",
      jiraPriority: "Medium",
      categories: [catB ?? catA],
      createdAt: daysAgo(5),
      contentTags: ["documentation", "runbook"],
    },
    {
      key: "DEMO-103",
      summary: "Migrate the ingest pipeline to the new queue",
      description: "Replace the old polling-based ingest with the new message queue once DEMO-104 lands.",
      jiraStatus: "Backlog",
      jiraPriority: "Low",
      categories: [catB ?? catA],
      issueType: "Epic",
      createdAt: daysAgo(10),
    },
    {
      key: "DEMO-104",
      summary: "Update the consumer for the new queue schema",
      description: "Subtask of DEMO-103 — the consumer side of the migration.",
      jiraStatus: "Selected for Development",
      jiraPriority: "Medium",
      categories: [catB ?? catA],
      parentKey: "DEMO-103",
      createdAt: daysAgo(3),
    },
    {
      key: "DEMO-105",
      summary: "Rotate the shared ingress certificate",
      description: "The current cert expires soon — cut a new one and roll it out before then.",
      jiraStatus: "Awaiting Approval",
      jiraPriority: "High",
      categories: [catA],
      createdAt: daysAgo(1),
      linkedIssues: [{key: "DEMO-106", label: "blocks", summary: "Cut the new base image"}],
    },
    {
      key: "DEMO-106",
      summary: "Cut the new base image",
      description: "The other half of DEMO-105's link — a new base image the cert rollout depends on.",
      jiraStatus: "Backlog",
      jiraPriority: "Medium",
      categories: [catB ?? catA],
      createdAt: daysAgo(4),
      linkedIssues: [{key: "DEMO-105", label: "is blocked by", summary: "Rotate the shared ingress certificate"}],
    },
  ];

  // A fake cost badge on one ticket — same shape codeburn's real entries use
  // (see badges.js), so DEMO-101 shows what a session that has actually run
  // looks like. Laid directly over whatever reloadBoard() just fetched; real
  // costs (there are none yet, by definition of demo mode showing at all)
  // would simply have nothing to collide with.
  state.sessionCosts["claude:DEMO-101"] = {
    models: ["Sonnet 5"], cost: 2.14, calls: 18, turns: 6,
    inputTokens: 4200, outputTokens: 1800, cacheReadTokens: 112000, cacheWriteTokens: 9000,
    durationMs: 640000,
  };

  return tickets.map(t => makeSnapshot(t.key, {...t, isDemo: true, reviewed: true}));
}
