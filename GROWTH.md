# Ticket Terminal growth and launch plan

Last updated: 2026-10-11

This document is the working source of truth for positioning, competitive evidence,
launch assets, experiments, and traction. Time-sensitive figures should be rechecked
on launch day.

## Current constraint: activation proof, not reach

As of 2026-10-11 the public repository has 4 stars, 0 forks, 0 issues, and no
verified external activation or retention records. GitHub's rolling 14-day traffic
reports 7 unique repository visitors and 236 unique cloners; the clone count is
clearly contaminated by automation and must not be treated as 236 humans.

The only company-level objective until it is met is:

> Get three people who are not the founder to open a real Jira/Notion ticket as a
> real Claude/Codex session, record the elapsed time, and watch or interview each
> attempt.

Until then: no Product Hunt, no broad feature roadmap, no provider expansion, no
landing-page rewrite, and no second major launch channel. Documentation fixes that
remove observed setup friction ship immediately. Everything else waits for user
evidence.

## 1. The position to own

**Category:** the local agent execution layer for the tickets a team already has.

**One-line position:**

> Turn existing Jira or Notion tickets into durable Claude and Codex work sessions
> in your real environment, with the transcript, memory use, and cost attached to
> the ticket.

**Short pitch:**

> Ticket Terminal connects the work already tracked in Jira or Notion to real
> Claude and Codex CLI sessions running in the developer's own environment. It
> preserves the ticket, terminal transcript, shared markdown memory, activity
> trail, and cost in one local, inspectable workflow. It is Apache-2.0, local-first,
> and does not require moving the backlog or code into another agent platform.

Do not lead with "AI Kanban," "multi-agent orchestrator," or "run agents in
parallel." That category is crowded and makes the product sound interchangeable
with Kamaji, AI Agent Board, Vibe Kanban, Kanban Code, and similar launch posts.
The product's defensible wedge is continuity across four things that are usually
separate:

1. the team's existing system of record (Jira or Notion);
2. the real local or company execution environment;
3. durable evidence of what the agent did;
4. reusable team memory and per-ticket cost.

### Ideal first user

A senior developer, tech lead, SRE, platform engineer, or engineering manager who:

- already uses Jira or Notion and one or both CLI agents;
- has more than one agent session or ticket in flight;
- cannot move code, credentials, or execution into a hosted agent sandbox;
- has felt the pain of reconstructing context, finding the right transcript, or
  explaining what an agent changed and what it cost.

This is not initially for someone seeking a hosted multiplayer PM suite, a fully
autonomous swarm, or an IDE replacement. The current product is a single-local-user
tool whose tracker remains the collaboration surface.

### Message hierarchy

1. **Keep Jira/Notion.** No new backlog or duplicate source of truth.
2. **Run the real CLI in the real environment.** The session can use the same repo,
   credentials, and tools as the developer.
3. **Every ticket keeps its evidence.** Resume the session; inspect the transcript
   and normalized activity trail.
4. **Memory survives the session.** Shared notes remain plain markdown, readable by
   humans, Claude, Codex, GitHub, and Obsidian.
5. **See spend where work happens.** Cost and cache/memory signals are attached to
   tickets rather than buried in a provider dashboard.
6. **Stay portable.** Apache-2.0, local data, provider-neutral architecture.

### Recommended public copy

**Tagline:** Your tickets already know what needs doing. Now they can open the agent
that does it.

**GitHub description:** Connect Jira and Notion tickets to real local Claude and
Codex sessions, with durable transcripts, shared markdown memory, and per-ticket
cost.

**Landing-page hero:**

> Your existing tickets, wired to real coding agents.
>
> Open a Jira or Notion ticket as a genuine Claude or Codex session in your own
> environment. Keep the transcript, memory, activity trail, and cost attached to
> the work—not locked inside another platform.

Primary CTA: **Run it locally**. Secondary CTA: **See a 45-second ticket run**.

### Pre-launch copy corrections

The current `docs/index.html` is visually polished but obscures the wedge. Before
sending launch traffic:

- replace "The ticket board where AI agents actually do the work" with the
  Jira/Notion-to-real-agent position above;
- remove "built for every engineering role" from the hero; it broadens the audience
  before the primary user and job are clear;
- replace "or run it fully agentic" with the exact interaction the product supports;
  a new Codex prompt is deliberately inserted as an editable, unsubmitted draft;
- replace "See exactly what Claude and Codex spent" and "actual token cost, ...
  instead of guessing" with "See a token-based cost estimate per ticket." The
  README correctly states that these are estimates, not provider invoices;
- route the hero CTA to a launch-ready GitHub section containing the short demo and
  one recommended install path, not the top of a long feature inventory.

The README's current line—"Your ticket board, wired directly into the coding agents
doing the work"—is a useful secondary description. The public headline should add
the harder-to-copy fact that these are the team's existing Jira/Notion tickets.

## 2. Competitive snapshot

Competitive evidence checked on 2026-10-07. Ticket Terminal's public GitHub baseline
was rechecked on 2026-10-11; Multica was added from current public evidence on
2026-10-21.

| Product | Position and workflow | Public traction | Price / license | Where discussion is visible | Implication |
|---|---|---:|---|---|---|
| Ticket Terminal | Existing Jira/Notion tickets open real local Claude/Codex PTYs; durable transcripts, memory, activity, and cost | [4 GitHub stars, 0 forks](https://github.com/ticketterminal/ticket-terminal) | Free, Apache-2.0; users pay their own agent costs | GitHub is the current public surface | Baseline is pre-launch. Measure qualified users, not only stars. |
| Multica | Its own team workspace and issue tracker treats agents as assignees; a connected local runtime claims runs, invokes the configured coding CLI, and writes progress and results back to the Multica issue | [53,403 stars, 7,007 forks, and 1,875 open issues](https://github.com/multica-ai/multica) on 2026-10-21 | Source-available Multica License: internal self-hosting is free; hosted service, commercial embedding, and some branding changes require separate permission or licensing | GitHub, its product site and extensive docs, Discord, and social channels | Closest direct competitor found so far. It already owns the broader multi-user, multi-agent workspace story. Ticket Terminal should not chase parity; its wedge is keeping Jira/Notion as the source of truth while adding local execution evidence, graph memory, estimated cost, and reviewed manager-digest write-back without migrating the backlog. Treat the very large GitHub counts as visible reach, not proof of activation or retention. |
| Kamaji | Agent-native Kanban; each new ticket gets a git worktree and zellij session; TUI and browser board; auto-review and container mode | [0 stars, 0 forks, 7 issues, 153 commits](https://github.com/alveflo/kamaji) at the check; dedicated [product site](https://getkamaji.com/) | Free, MIT; users bring an agent subscription/API | GitHub/issues and its own docs/site; no meaningful indexed Reddit or HN launch found | Polished positioning and installation, but effectively no visible community traction yet. Competes on parallel worktrees and terminal ergonomics, not existing tracker continuity. |
| AI Agent Board | Agent-native drag-and-drop board; six providers, task groups, optional worktrees, streamed events, merge/PR flow | [63 stars, 17 forks, 3 open issues, 240 commits](https://github.com/DanWahlin/ai-agent-board) at the check | Free, MIT; users bring provider access | GitHub, a [founder LinkedIn post](https://www.linkedin.com/posts/danwahlin_been-working-on-a-few-fun-side-projects-over-activity-7476899137070923776-IQ1q), and a few third-party mentions; no strong indexed Reddit/HN launch found | The strongest named comparison by visible adoption. It owns breadth of providers and parallel task execution. Do not feature-match it before validating the Ticket Terminal wedge. |

The detailed Multica acquisition, activation, retention, monetization, and public
customer-evidence teardown is in [MULTICA_GROWTH_INTEL.md](MULTICA_GROWTH_INTEL.md).

### What broader launches say about demand

The broader category is validated, but "a board for agents" is no longer novel:

- A 2025 Vibe Kanban launch in r/ClaudeCode reached [193 votes](https://www.reddit.com/r/ClaudeCode/comments/1luv8iq/claude_code_meets_kanban/).
- A native Kanban Code launch reached [91 votes](https://www.reddit.com/r/ClaudeCode/comments/1rji1gx/kanbancode_macos_native_ui_for_managing_claude/).
- A Vibeyard agent-board post in r/ClaudeAI reached [341 votes](https://www.reddit.com/r/ClaudeAI/comments/1sye8bs/i_built_a_kanban_board_for_claude_code_so_i_can/); one of its top requests was usage metrics per task.
- Users still explicitly ask for agent Kanban/task tools and existing tracker
  integration, including [this r/ClaudeCode request](https://www.reddit.com/r/ClaudeCode/comments/1u2t93q/what_kanbantask_board_do_you_use_with_claude_code/) and [this r/AI_Agents request](https://www.reddit.com/r/AI_Agents/comments/1vzk6nl/project_management_tool_for_agents/).
- The recurring objections are trust, install friction, abandonment risk, context
  loss, and whether a new board duplicates the tracker users already have.

The launch should answer those objections directly. It should not imply that Docker
is a security sandbox: this product deliberately operates against real files and
credentials, and localhost is the boundary.

## 3. Channel order

### Tier 0 — make GitHub convert before sending traffic

GitHub is the product page, trust surface, install funnel, support forum, and the
only durable place every launch channel can share.

Before the first post:

- [Completed 2026-10-11] Published `v0.1.0` as a named public-preview release
  from `main` commit `0572ff0`, with concise notes and explicit limitations;
- [Completed 2026-10-11] Placed a 31-second demo GIF immediately below the first
  paragraph, showing the current board, terminal, PR/memory context, and agent trail;
- [Completed 2026-10-11] Made Python + `uv` the recommended route with a complete
  clone-to-server command block;
- show Jira/Notion -> ticket -> live terminal -> activity trail -> cost/memory in
  the first screenful;
- [Completed 2026-10-11] Added `claude-code`, `codex`, `jira`, `notion`,
  `local-first`, `developer-tools`, `ai-agents`, and `kanban` repository topics;
- [Completed 2026-10-11] Added an "Install report" issue form with OS, install
  path, agent, tracker, outcome, time-to-first-session, friction, and data-safety
  confirmation;
- create a "Good first integration" issue only after a user asks for another
  tracker or provider; do not advertise an empty roadmap.

### Tier 1 — r/ClaudeCode

This is the highest-signal first launch. The community has repeatedly engaged with
agent boards, local workflows, worktrees, context continuity, and cost visibility.
The post must be written or substantially rewritten in the founder's own voice,
include a real demo, and ask a specific workflow question instead of asking for
stars.

Post once, then spend the next 24 hours answering every substantive question. The
success metric is successful installs and detailed workflow comments, not votes.

### Tier 1 — Show HN

Post 24–72 hours after the Reddit launch, once the top install problems and FAQ are
fixed. HN is a good match for local-first, plain files, Apache-2.0, genuine PTYs,
and the security/trust tradeoff. A previous Vibe Kanban Show HN drew extensive
discussion about broad local privileges, so lead with an exact threat model and
avoid "safe" or "sandboxed" claims.

### Tier 1.5 — r/codex

This is a better Codex-specific target than a standalone r/ChatGPTCoding post. A
local-first Codex workflow project recently reached [69 votes](https://www.reddit.com/r/codex/comments/1tyba25/i_built_a_local_mcp_to_make_chatgpt_codex/).
Use a Codex-focused demo and emphasize session identity, resume behavior, editable
drafts that are never auto-submitted, and compatibility with the user's actual CLI.

### Tier 2 — r/AI_Agents

Use this for a value-first post about keeping an existing tracker as the human/agent
system of record. Current reported rules require at least 100 words, correct flair,
roughly nine value contributions per promotional post, and no repeat launch within
a month ([rule audit published 2026-09-27](https://www.reddit.com/r/PromptEngineering/comments/1wrld6q/i_read_the_selfpromotion_rules_of_35_ai/)). Confirm all live rules before posting. Do not cold-drop a launch link from an
account that has not participated in the community.

### Tier 2 — r/ChatGPTCoding

Use the [pinned self-promotion thread](https://www.reddit.com/r/ChatGPTCoding/comments/1seq7us/self_promotion_thread/), not a standalone launch. Its current thread rules
permit one promotion per project; the subreddit also bans raw AI output. The founder
must rewrite any draft in a natural personal voice. A concise Codex-specific note
and demo are enough.

### Tier 3 — Product Hunt

Launch only after there are 10–20 people willing to say they have run the product,
three short user quotes, a polished video, and a smooth installation path. Product
Hunt should amplify demonstrated activation, not be used to discover whether the
product installs. The first Reddit/HN cohort should become the launch-day advocate
list; do not manufacture votes or ask for a particular ranking.

## 4. Fourteen-day launch sequence

### T-3 to T-1: conversion readiness

- Record the canonical 45-second demo below.
- Establish the baseline: stars (4), forks (0), unique visitors, clones, and open
  install reports.
- Release completed on 2026-10-11. Repository topics and the install-report issue
  template remain to be completed.
- Clean install handled and reported complete by the founder on 2026-10-11. The
  tracker does not yet contain the number of testers, time to first real ticket, or
  interventions, so record those before treating the Show HN measurement gate as
  verified.
- Do not launch if fewer than two of three can open a real Claude or Codex session
  from a tracker ticket in 15 minutes.

### Day 0: r/ClaudeCode

- Publish in the first half of the US workday only if someone can respond for the
  following six hours.
- Use one demo and one repository link. No marketing site detour.
- Tag every inbound comment as: install, trust/security, existing-tool comparison,
  missing integration, or unclear value.
- Ship documentation fixes the same day. Defer feature requests until patterns
  repeat.

### Day 1–2: learn and tighten

- Personally help every person who attempted installation.
- Convert repeated questions into a short README FAQ.
- Ask successful users one question: "What were you doing immediately before you
  opened Ticket Terminal?" This reveals the real alternative, which may be terminal
  tabs rather than another board.
- Re-record the demo only if users misunderstood the workflow.

### Day 2–3: Show HN

- Publish the Show HN draft below with the exact local security model.
- Stay available for technical questions.
- Add a comparison section only in response to actual confusion; do not create a
  broad feature matrix that frames the product as a Kamaji clone.

### Day 4–7: segment tests

- Publish a Codex-specific version in r/codex.
- Contribute useful, non-promotional answers in r/AI_Agents before considering a
  launch post there.
- Add the project once to the current r/ChatGPTCoding self-promotion thread.
- Direct-message only people who explicitly asked for a tool like this or offered
  to test; no scraped outreach.

### Day 8–14: decide the wedge

- Interview every activated user for 15 minutes.
- Compare the three message variants below using distinct campaign links or
  referrer data.
- Keep the winning headline for the next 30 days.
- Decide whether Product Hunt readiness has been met. If not, continue community
  learning instead of scheduling it.

## 5. Scorecard and experiments

### Funnel definitions

- **Qualified visit:** a visitor from a target channel who reaches GitHub or the
  landing page and stays long enough to open install/demo content.
- **Install intent:** clone, release download, Docker quick-start click, or install
  report opened.
- **Activated user:** connects Jira/Notion or loads real tickets and opens at least
  one Claude/Codex session.
- **Retained user:** opens a session from a second ticket or returns on another day
  within seven days.
- **Advocate:** files useful feedback, contributes, or agrees to provide a truthful
  quote/demo reference.

Because the product has no telemetry, measure activation through opt-in install
reports, short interviews, GitHub traffic/clones, and explicit replies. Never equate
stars with usage.

### First 14-day targets

| Metric | Baseline | Target | Decision use |
|---|---:|---:|---|
| Qualified visits | 7 unique GitHub visitors / 14 days | 250 | Whether channel hooks earn attention |
| Install intents | unknown; clone traffic is bot-contaminated | 40 | Whether the repository converts |
| Activated users | unknown | 10 | Primary proof of value |
| Median time to first session | unknown | <=15 min | Whether launch traffic is supportable |
| Seven-day retained users | unknown | 5 | Whether this is a workflow, not a demo |
| Actionable interviews | 0 | 8 | Whether roadmap evidence is strong enough |
| Advocates | 0 | 3 | Minimum seed for later Product Hunt launch |

### Experiment A — position

Use one message per channel, not several messages in one post:

- A: "Keep Jira/Notion; attach real agents to the tickets."
- B: "Every agent run leaves a transcript, memory trail, and cost on the ticket."
- C: "Run Claude and Codex in your real environment without a hosted-agent lock-in."

Winner: highest activated users per 100 qualified visits, with at least 100 visits
per variant. If volume is lower, use interview recall ("what made you try it?") and
do not pretend the result is statistically conclusive.

### Experiment B — demo opening

- A opens on a Jira ticket becoming a Claude session.
- B opens on several terminal tabs becoming one inspectable board.

Winner: install intent per demo view plus accurate comprehension in five interviews.

### Experiment C — setup route

- A: native Python/uv first.
- B: Docker first, with the host bridge explained after success.

Winner: median time to first session and install failure rate. Do not call Docker a
sandbox; it bind-mounts real user files by design.

### Stop / continue rules

- If fewer than 5 of 40 install intents activate, stop channel expansion and fix
  setup/onboarding.
- If activation is >=25% but seven-day retention is below 30%, interview around
  repeat workflow and tracker fit before adding providers.
- If at least 3 users independently cite tracker continuity or provenance, double
  down on that position.
- If most users only want parallel worktrees, treat Kamaji/AI Agent Board as the
  chosen category leaders and do not chase them without a differentiated use case.

## 6. Launch assets

These are working drafts. Reddit copy must be rewritten by the founder before use,
especially in communities that prohibit AI-generated posts.

### Canonical 45-second demo

1. **0–5s:** Jira or Notion ticket on the existing board. Caption: "Keep the tracker
   your team already uses."
2. **5–12s:** Open the ticket and click Claude or Codex. Show the genuine terminal
   prompt. Caption: "A real CLI session in your environment."
3. **12–24s:** The agent reads a file and runs a command. Show the normalized
   activity trail beside it. Caption: "See what it touched while it works."
4. **24–32s:** Collapse and reopen/resume the ticket session. Caption: "The session
   stays with the ticket."
5. **32–39s:** Show memory resource links and the graph. Caption: "Plain markdown
   memory that humans and agents share."
6. **39–45s:** Show the ticket cost badge and repository URL. Caption: "Local-first.
   Apache-2.0. Claude + Codex."

Use real captured interaction, readable text, and subtitles. Avoid a voiceover-heavy
product tour, stock animation, or an unedited two-minute terminal recording.

### r/ClaudeCode draft

**Title:** I connected our existing Jira tickets to real Claude Code sessions—so the
transcript and memory stay with the work

**Body:**

> I kept ending up with two histories: Jira knew what the team asked for, while my
> terminal knew what Claude actually did. Reconstructing the connection later was
> mostly guesswork.
>
> I built Ticket Terminal to keep those together. It syncs the Jira or Notion
> tickets you already have and opens a real Claude Code or Codex CLI session from
> each ticket, in your own working directory. The session is resumable and the
> ticket keeps its transcript, activity trail, shared markdown memory, and estimated
> cost.
>
> It is local-only by default, Apache-2.0, and it does not replace Jira/Notion or
> send execution to a hosted runner. That also means it has real access to the
> environment you start it in; localhost is the security boundary, not a sandbox.
>
> [demo]
>
> Repo: https://github.com/ticketterminal/ticket-terminal
>
> I would especially like feedback from people already using Claude Code against
> company tickets: is the missing link for you the ticket-to-session handoff,
> reviewing what the agent did, or preserving context for the next session?

### Show HN draft

**Title:** Show HN: Ticket Terminal – Run Claude and Codex from existing Jira/Notion tickets

**Body:**

> Ticket Terminal is an Apache-2.0 local app that syncs existing Jira and Notion
> tickets and gives each one a real embedded Claude Code or Codex CLI session.
>
> I built it because the ticket, terminal transcript, team knowledge, and usage cost
> lived in separate places. A session launched from Ticket Terminal runs as a real
> PTY process in the configured working directory. It can be resumed from the same
> ticket, and the app preserves its transcript, normalized file/command/memory
> activity, shared markdown memory, and per-ticket cost estimate.
>
> The design is intentionally local-first: the server binds to 127.0.0.1, data stays
> on disk, and Jira/Notion remain the system of record. There is no auth layer and
> it can spawn a real shell, so it must not be exposed to a network. Docker is a
> packaging option, not a security sandbox.
>
> It currently supports Claude and Codex, Jira and Notion, native Python and Docker.
> I am looking for feedback on the workflow and threat model, especially from teams
> that cannot move their code or credentials into a hosted agent environment.
>
> Demo: [link]
>
> Code: https://github.com/ticketterminal/ticket-terminal

### r/codex draft

**Title:** I wired existing Jira/Notion tickets to resumable local Codex CLI sessions

**Body angle:** Use the r/ClaudeCode body, but show Codex in the demo. Add that each
ticket's opening prompt carries a unique marker so the app finds the correct Codex
session rather than resuming another session in the same directory, and that the
initial composer text remains an editable draft until the user submits it.

### r/AI_Agents draft angle

**Title:** What if the human/agent system of record stayed in Jira instead of another agent dashboard?

Write a 300–500 word teardown of the architectural choice: Jira/Notion owns work
state; the local tool owns execution evidence; transcripts and memory are pointers
to durable artifacts; the human remains responsible for launching/submitting. End
with one architecture question. Disclose affiliation and place the repository link
at the end. Only post after the account satisfies the live participation rules.

### r/ChatGPTCoding self-promotion thread comment

> I built Ticket Terminal for developers whose Jira/Notion tickets and Codex CLI
> sessions have become two separate histories. It opens a real local Codex or Claude
> session from a ticket and keeps the resumable transcript, activity trail, shared
> markdown memory, and estimated cost attached to the work. Local-first and
> Apache-2.0: https://github.com/ticketterminal/ticket-terminal

### Product Hunt launch scheduled

Product Hunt confirmed the Ticket Terminal launch for 2026-11-10 at 12:01am PT
(10:01am Israel time). The founder explicitly chose to launch before the activation
gate below was met. Treat the launch as a bounded acquisition experiment, not as
evidence that activation or retention has been validated. Do not coordinate upvotes,
and do not schedule another major launch within 48 hours.

**Name:** Ticket Terminal

**Tagline:** Ship Jira and Notion work faster, see LLM cost per ticket

**Description:** Connect Jira and Notion tickets to local Claude and Codex sessions.
Keep every resumable transcript, activity trail, shared markdown memory, and cost
attached to the work—without moving your backlog or code into another platform.

## 7. Objection handling

**"Isn't this another Multica/Vibe Kanban/Kamaji/AI Agent Board?"**

Those products begin with their own agent-native backlog and emphasize team
orchestration, parallel worktrees, or autonomous assignment. Ticket Terminal begins
with existing Jira/Notion work and focuses on the durable connection between that
ticket, a real environment, the session's evidence, shared memory, and cost. If a
user wants to replace the current tracker with a new human-and-agent workspace,
Multica may be the better fit. Ticket Terminal is for teams that want the agent
execution layer without migrating or duplicating their backlog.

**"Why not just use Jira plus a terminal?"**

That is the actual alternative. Ticket Terminal removes the manual copy/paste and
keeps the correct resumable session, transcript, touched resources, memory, and cost
discoverable from the ticket.

**"Is it safe?"**

It is intentionally powerful, not sandboxed. It binds to localhost and has no auth
layer. It can run a real agent process against real files and credentials, so users
must keep it off the network and apply the same care they apply to the agent CLI.

**"Does it replace Jira/Notion?"**

No. The tracker remains the shared work surface. Ticket Terminal is the local
execution and evidence layer.

**"Is this for teams?"**

It currently runs for one local user. Teams collaborate through their tracker and
shared repositories/markdown; this is not yet a shared hosted control plane.

**"What does it cost?"**

The software is free under Apache-2.0. Users bring their own Claude/Codex access.
Displayed per-ticket cost is a token-based estimate from codeburn, not an invoice.

## 8. Traction log

Update this after every launch or interview. Keep raw counts and qualitative notes;
do not overwrite prior weeks.

| Date | Channel / cohort | Qualified visits | Install intents | Activated | Retained D7 | Main objection | Main value phrase | Next action |
|---|---|---:|---:|---:|---:|---|---|---|
| 2026-11-11 | Product Hunt launch | 5 unique GitHub visitors on 2026-11-10; Product Hunt absent from the rolling referrer list | 2 unique cloners on 2026-11-10, not attributable or verified as installs | 0 verified | 0 verified | Insufficient reach and no external feedback; value comprehension is unknown | No user evidence yet | Preserve the 48-hour channel gap, then recruit one named warm tester and observe one complete real-ticket session before buying or launching more reach |
| 2026-10-11 | Public-preview baseline | 7 unique GitHub visitors / 14 days | Unknown; 236 unique cloners is bot-contaminated | 0 verified | 0 verified | No user evidence yet | No user evidence yet | Recruit and observe three external install attempts |

### Interview notes template

- What were you doing immediately before trying Ticket Terminal?
- Which tracker and agent do you use today?
- Show the last time you lost or reconstructed agent context.
- What made you hesitate during installation?
- Which screen or feature made the value click?
- What would make you use it on a second ticket tomorrow?
- What would prevent use on company work?
- Would you be comfortable being quoted accurately? If yes, capture exact wording
  and approval scope.

## 9. Reddit response queue

Checked 2026-10-07. These are discussions where a disclosed Ticket Terminal mention
can answer the question. They are not permission to paste the same link repeatedly.
Recheck the community rules while logged in immediately before commenting.

| Priority | Thread | Why it is relevant | Recommended action |
|---|---|---|---|
| 1 | [Project Management tool for Agents? — r/AI_Agents](https://www.reddit.com/r/AI_Agents/comments/1vzk6nl/project_management_tool_for_agents/) | Recent, 22 votes. The author explicitly wants free/low-cost or self-hosted task management for local Codex and other agents and is considering Notion/Trello. | Reply only if the account already meets the community's participation ratio. Disclose affiliation and explain the single-local-user limitation. |
| 2 | [What task tracker and documentation system do you use for building large projects with AI agents? — r/ClaudeCode](https://www.reddit.com/r/ClaudeCode/comments/1vq6qm7/what_task_tracker_and_documentation_system_do_you/) | Recent, 21 votes. The author is choosing between Notion, Jira-style trackers, markdown state, and MCP for a large agent project. Ticket Terminal directly combines existing Notion/Jira tickets with shared markdown memory. | Strong reply opportunity. Contrast honestly with pure markdown/MCP tools; ask whether local execution provenance or agent-written task state matters more. |
| 3 | [What task tracker are you using with Claude Code? — r/ClaudeCode](https://www.reddit.com/r/ClaudeCode/comments/1v91nk4/what_task_tracker_are_you_using_with_claude_code/) | Two months old and explicitly asks for a tracker agents can understand without recreating Jira. Discussion includes markdown, Obsidian, GitHub Issues, and homegrown Jira clones. | Useful if framed as the option for people who cannot abandon Jira/Notion. Say it is not file-based task storage and may not fit the OP's preference. |
| 4 | [Using Jira/DevOps as the planning store? — r/ClaudeCode](https://www.reddit.com/r/ClaudeCode/comments/1tdju9n/using_jiradevops_as_the_planning_store/) | Exact system-of-record question: whether Jira should remain the planning store while agents execute work. | Add a technical answer about the split: Jira owns work state; the local app owns PTY session evidence and memory. Link only after the useful explanation. |
| 5 | [What agent orchestrator are you using? — r/ClaudeCode](https://www.reddit.com/r/ClaudeCode/comments/1t1q54w/what_agent_orchestrator_are_you_using/) | The author wants a Kanban flow with human approval and is comparing agent-board products. | Medium fit. Be explicit that Ticket Terminal is not an autonomous multi-agent orchestrator; recommend it only if keeping Jira/Notion and real interactive sessions is the priority. |
| 6 | [What Kanban/task board do you use with Claude Code? — r/ClaudeCode](https://www.reddit.com/r/ClaudeCode/comments/1u2t93q/what_kanbantask_board_do_you_use_with_claude_code/) | The author asked for free, open-source integration but later built a small solution themselves. | Low priority. Do not revive just for exposure; reply only if contributing a substantive comparison useful to later readers. |

### Threads to avoid for promotion

- Do not post Ticket Terminal under another maker's launch merely because the
  product is adjacent, for example [Hive's Codex workspace launch](https://www.reddit.com/r/codex/comments/1sjo3gc/i_turned_codex_into_a_full_dev_workspace/), [Vibe Kanban's launch](https://www.reddit.com/r/ClaudeCode/comments/1luv8iq/claude_code_meets_kanban/), or [the markdown Kanban launch](https://www.reddit.com/r/ClaudeAI/comments/1v3aky6/kanban_board_for_claude_code_no_paywalls_no_sign/).
- Do not use r/LocalLLaMA's agent/human board thread for a product mention without
  moderator approval; current third-party rule audits classify that community as
  restrictive toward promotion.
- Do not paste a reference into a thread that only shares a workflow and does not
  ask for alternatives. Relevance is determined by the author's question, not by
  keyword overlap.

### Comment structure

Write each comment freshly in the founder's own voice:

1. Answer the author's actual choice or architecture question first.
2. State the tradeoff between an agent-native backlog and keeping Jira/Notion as
   the system of record.
3. Disclose: "I build Ticket Terminal, so this is a product suggestion, not an
   independent recommendation."
4. State one limitation that could disqualify it: single local user, not a hosted
   collaborative control plane, and not an autonomous swarm orchestrator.
5. Add the repository link once, at the end, only if the product fits.

Example for the highest-priority thread:

> The main choice is whether you want a new board that the agents own, or whether
> Notion/Jira should remain the shared source of truth and the agent tool should sit
> beside it. For your local Codex setup, the second model avoids maintaining a
> second backlog.
>
> Disclosure: I build Ticket Terminal, so this is a product suggestion rather than
> an independent recommendation. It syncs existing Jira or Notion tickets and opens
> a real local Codex or Claude session from each one, keeping the transcript,
> activity trail, markdown memory use, and estimated cost with the ticket. It is
> Apache-2.0 and self-hosted.
>
> The important limitation for your use case is that it is currently a single-local-
> user execution layer, not a shared control plane where agents on several machines
> assign work to one another. If cross-machine agent collaboration is the priority,
> Hermes or an MCP-native shared board is probably a better fit. If keeping Notion
> or Jira and attaching local execution evidence is the priority, this is the repo:
> https://github.com/ticketterminal/ticket-terminal

Reddit's site-wide spam policy prohibits repeated or unsolicited mass engagement,
including manual repetition. It recommends authentic participation and thoughtful
frequency when most contributions link to something the commenter benefits from.
Transparent disclosure and relevance make a comment more legitimate, but they do
not override subreddit-specific rules or turn a campaign of repeated comments into
organic participation.
