# Ticket Terminal channel tracker

Last updated: 2026-11-03

This tracker covers non-Reddit distribution. Reddit activity remains in
`REDDIT_OUTREACH.md`. The aim is to earn qualified installs and feedback without a
coordinated launch blast.

## Channel order

| Rank | Channel | When it is ready | Goal | Promotion risk |
|---:|---|---|---|---|
| 1 | GitHub repository and release | Now | Convert every referral into a credible install attempt | Low |
| 2 | Founder LinkedIn post | After the 45-second demo exists | Reach engineering leads who already use Jira/Notion and can introduce real testers | Low if posted once from a personal account |
| 3 | Show HN | After three clean-machine trials, with at least two reaching a real ticket session in 15 minutes | Technical feedback, installs, and trust scrutiny | Medium; one launch only, founder-written |
| 4 | Technical article on DEV/Hashnode or the project site | After the first interviews reveal the winning problem language | Durable explanation and search discovery | Low if the article stands alone without the product link |
| 5 | Relevant GitHub awesome lists/directories | After a named release and stable README/demo | Long-tail discovery from agent-tool researchers | Low if the list explicitly accepts self-submissions |
| 6 | Product Hunt | After 10–20 activated users, three approved quotes, and a smooth install | Amplification and social proof | High opportunity cost; relaunch generally requires six months and a significant update |
| 7 | Developer-tool newsletters/podcasts | After measurable usage or an interesting technical story exists | Third-party credibility | Low volume, high selectivity |

## 1. GitHub conversion checklist

Complete before sending another large audience:

- [Completed 2026-10-11] Published `v0.1.0` as **Ticket Terminal v0.1.0 —
  Public Preview**, marked pre-release and targeting commit `0572ff0` on `main`.
- [Completed 2026-10-11] Added a 31-second captioned demo near the top of the README.
- [Completed, user-reported 2026-10-11] Set a 1280x640 social preview image so
  shared links do not use GitHub's generic card.
- [Completed 2026-10-11] Added precise repository topics: `claude-code`, `codex`,
  `jira`, `notion`, `local-first`, `developer-tools`, `ai-agents`, and `kanban`.
- [Completed 2026-10-11] Made Python + `uv` the recommended path and labeled Docker
  as the alternative.
- [Completed 2026-10-11] Added an install-report issue form; respond quickly to every
  submission.
- [Baseline 2026-10-11] 4 stars, 0 forks, 0 issues, 7 unique visitors and 236 unique
  cloners over GitHub's rolling 14-day window. Treat clone traffic as automation-
  contaminated until a human confirms an install; stars measure reach, not activation.

GitHub's own documentation recommends a useful README, license, topics, and custom
social preview for public repositories. Draft releases before publication so the
assets, tag, and notes can be checked as one unit.

## 2. Founder LinkedIn post

Do not copy the Reddit launch. Use a personal founder story with the demo:

- Problem: Jira knew what was requested; terminal history knew what the agent did.
- Design decision: keep Jira/Notion as the source of truth instead of creating
  another autonomous backlog.
- Proof: show one ticket opening a real Claude/Codex session, then its activity,
  memory, and cost.
- Ask: request three engineering leads willing to test the README on a real ticket.
- Link once to GitHub. Do not ask for likes, reposts, or stars.

Success is three qualified conversations or introductions, not impression count.
Follow up only with people who volunteer or ask a substantive question.

## 3. Show HN gate

Hacker News explicitly allows runnable, non-trivial projects made by the submitter,
including software people can run locally. Ticket Terminal fits. It also explicitly
requires easy trial, discourages landing pages, prohibits soliciting votes/comments,
and says not to post generated or AI-edited submission text.

Post only when all gates pass:

1. Three people have attempted the exact public instructions from a clean setup.
2. At least two reached a real tracker ticket and opened a real agent session within
   15 minutes.
3. The README opens with the product distinction, demo, security boundary, and one
   recommended install path.
4. Someone can answer technical questions for at least six hours after submission.
5. The founder writes the title and first comment personally, without using generated
   or AI-edited prose.

Recommended title concept for the founder to rewrite:

`Show HN: Ticket Terminal – Run local coding agents from existing Jira/Notion tickets`

Link directly to the GitHub repository, not a signup or marketing landing page.

## 4. Technical article

Best article thesis:

> Why we kept Jira as the system of record and made agent execution local

Useful sections:

- the two-history problem: ticket intent versus terminal evidence;
- why a second agent-native backlog creates reconciliation work;
- PTY execution and the exact localhost security boundary;
- durable transcript/activity pointers instead of stuffing everything into model
  context;
- plain markdown memory and provider portability;
- where this architecture is the wrong choice.

Publish the full article in one canonical location. Cross-post with a canonical URL
where supported. The article should remain worthwhile if the Ticket Terminal link
is removed.

## 5. Directories and curated lists

Search for maintained lists covering Claude Code tools, Codex tools, local-first
developer tools, or AI coding orchestration. Submit only when:

- the repository has accepted comparable projects recently;
- its contribution guide permits project-owner submissions;
- Ticket Terminal matches an existing category without stretching the definition;
- the PR uses neutral third-person copy and discloses the submitter's relationship.

Avoid bulk directory submissions and paid "top tools" placements. One relevant,
maintained list is worth more than dozens of abandoned catalogs.

## 6. Product Hunt gate

Product Hunt currently features live products based on usefulness, novelty, craft,
and creativity. It generally requires six months and a significant update before a
relaunch, so do not spend the first launch before activation is demonstrated.

Minimum gate:

- 10–20 activated users;
- at least five seven-day retained users;
- three short quotes approved for public use;
- polished demo and social card;
- median time to first real agent session at or below 15 minutes;
- capacity to respond throughout the launch day.

The maker can post the product directly; an external hunter is not required. Never
coordinate votes or manufacture reviews.

## Activity ledger

| Date | Channel | Action | Asset / URL | Result | Next action |
|---|---|---|---|---|---|
| 2026-11-11 | Product Hunt | Checked the live launch near the end of its 24-hour launch window | [Ticket Terminal on Product Hunt](https://www.producthunt.com/products/ticket-terminal?launch=ticket-terminal) | Public page showed `Launching today`, 1 point, 2 followers, and only the pinned maker comment; no external comment was visible. GitHub remained at 5 stars and 0 forks with no open non-PR issue. GitHub traffic for 2026-11-10 was 5 unique visitors and 2 unique cloners; Product Hunt was not present in the rolling referrer list. No install or activation can be verified. | Treat Product Hunt as a low-reach, zero-activation result. Do not spend on Product Hunt promotion or immediately launch elsewhere. Preserve the 48-hour channel gap, then recruit one named tester through warm outreach and observe the complete setup. |
| 2026-11-09 | Product Hunt | Scheduled the Ticket Terminal launch for the earliest available slot | [Ticket Terminal on Product Hunt](https://www.producthunt.com/products/ticket-terminal) | Product Hunt confirmed the launch for 2026-11-10 at 12:01am PT (10:01am Israel time). The page uses the verified logo, a terminal-workflow GIF as the lead gallery item, the train artwork second, a real board screenshot third, Free pricing, tags for Productivity / Developer Tools / Artificial Intelligence, and a founder comment that asks for a real-ticket workflow test without asking for upvotes. This launch was scheduled before the documented activation gate was met, so it is an acquisition experiment rather than evidence of validation. | Be available at launch time, answer substantive questions promptly, and measure repository visits, explicit install attempts, completed first sessions, and feedback. Do not coordinate upvotes or run another major launch within 48 hours. |
| 2026-11-03 | Reddit Ads | Checked cumulative performance and paused the campaign | `TT tester signal - Nov 2026` | Paused and publicly verified as Inactive on 2026-11-03. The campaign row showed 7,569 impressions, 112 clicks, 1.480% CTR, $0.31 CPC, $4.62 eCPM, and $34.94 spend when paused; Reddit notes that reporting is not real-time. The campaign generated inexpensive attention, but no verified install, tester conversation, or activation can be attributed to it. | Keep paused. Do not treat CTR as validation. Audit the destination and add an explicit lightweight tester conversion path before considering another paid test. |
| 2026-11-03 | DevHunt | Rechecked launch page and comments | [Ticket Terminal listing](https://devhunt.org/tool/ticket-terminal) | 629 impressions, 2 upvotes, #48 for its launch week, and 4 comments. A substantive unanswered comment asks whether Notion usage is anywhere near Jira and argues that Atlassian now owns the basic Jira-to-agent search intent, making local graph memory the stronger content wedge. | Reply honestly that external usage is not sufficient to compare Jira with Notion; do not invent adoption. Acknowledge the search observation and ask which cross-ticket memory failure the commenter would want demonstrated. |
| 2026-11-03 | GitHub | Rechecked public repository baseline and rolling traffic | [Repository](https://github.com/ticketterminal/ticket-terminal) | 5 stars, 0 forks, and 0 open non-PR issues. Rolling 14-day traffic shows 48 views from 16 unique visitors and 85 clones from 29 unique cloners; Nov 1-2 account for 19 views and at most 8 daily uniques, while GitHub reports only 2 unique visitors from `reddit.com` plus 1 from the Reddit app referrer. Clone data remains automation-contaminated and is not activation proof. The public preview release remains a prerelease with no attached downloadable assets. | The next milestone is one attributable install/tester conversation from the 112 paid clicks, not another reach channel. Audit the ad destination and conversion path because Reddit's click count is not appearing as comparable qualified GitHub traffic. |
| 2026-11-01 | Reddit Ads | Published a seven-day paid traffic experiment, `TT tester signal - Nov 2026` | Free-form product post linking to the repository quick-start with `utm_source=reddit&utm_medium=paid_social&utm_campaign=tester_signal_nov_2026` | Active on 2026-11-02. That day's verified dashboard totals were 998 impressions, 6 clicks, 0.601% CTR, $0.26 CPC, $1.54 eCPM, and $1.54 spend. Budget is $15/day with a hard $100 campaign cap; targeting is r/ClaudeCode, r/codex, and r/jira in the US, UK, Canada, and Australia. Founder reported completing account email verification. No activation may be inferred from ad clicks. | Do not change creative after only six clicks. Check for qualified GitHub behavior and explicit install/tester signals; reassess the message after materially more traffic rather than impressions alone. |
| 2026-10-20 | DevHunt | Launch went live and first-day public metrics were checked | [Ticket Terminal listing](https://devhunt.org/tool/ticket-terminal) | Six hours after launch: #35 for the week, 67 impressions, 1 upvote, and 3 displayed comments comprising the maker note, one visitor question, and the maker reply. The reply accurately explained local transcript retention, graph-memory enrichment, and reviewed manager-digest write-back. | Do not manufacture launch-day votes. Wait for the visitor's answer and measure qualified GitHub visits, install attempts, and tester conversations rather than DevHunt impressions alone. |
| 2026-10-19 | DevHunt | Received first substantive pre-launch product question | [Ticket Terminal listing](https://devhunt.org/tool/ticket-terminal) | Commenter validated the Jira-as-source-of-truth positioning and asked whether a completed session automatically writes its transcript back to the ticket | Reply accurately that transcripts remain local today; ask whether an approved summary or full transcript is the desired write-back behavior |
| 2026-10-14 | Reddit / r/jira | Posted a non-promotional process-design answer | [Direct comment](https://www.reddit.com/r/jira/comments/1x381cb/comment/pgolbm7/) | Publicly visible on 2026-10-15 with no Ticket Terminal mention or link; no substantive reply or moderator action visible | Do not pitch by DM; respond only if the OP asks a genuine follow-up |
| 2026-10-11 | GitHub release | Published `v0.1.0` public preview from `main` commit `0572ff0` | [Ticket Terminal v0.1.0 — Public Preview](https://github.com/ticketterminal/ticket-terminal/releases/tag/v0.1.0) | Publicly visible and labeled pre-release | Add the short demo, repository topics, and install-report issue form |
| 2026-10-11 | GitHub readiness | Clean install and social preview reported complete by founder | Repository onboarding and social card | Completion reported; tester count and time-to-first-session were not recorded in this tracker | Record the clean-install sample size and timing if using it to satisfy the Show HN gate |
| 2026-10-11 | GitHub conversion | Added README demo, recommended Python/uv path, install-report form, label, and eight discovery topics | [Repository](https://github.com/ticketterminal/ticket-terminal) | Conversion surface complete; external activation remains unverified | Recruit three non-founder testers and observe every attempt before another major launch |
| 2026-10-08 | Reddit / r/aiagents | Non-promotional technical contribution posted | [Direct comment](https://www.reddit.com/r/aiagents/comments/1wzp250/comment/pemnnuj/) | Publicly visible on 2026-10-11; OP's substantive reply remains visible | Counted as 1 of 9; no product reference and no forced follow-up |
| 2026-10-07 | Reddit / r/AI_Agents | First disclosed contextual reference posted | [Direct comment](https://www.reddit.com/r/AI_Agents/comments/1vzk6nl/comment/peefo92/) | Still publicly visible on 2026-10-11; no reply or moderator action visible | Pause Reddit product references; build genuine participation through at least 2026-10-21 |
| 2026-10-11 | GitHub | Public baseline rechecked | https://github.com/ticketterminal/ticket-terminal | 4 stars, 0 forks, 0 issues, 3 pull requests before publishing the first release | Prepare the short demo before a broad launch |

## Decision rule

Recommend one channel action at a time. Do not launch on two major channels on the
same day. Allow at least 48 hours to absorb questions and fix onboarding between a
high-attention Reddit post, Show HN, or Product Hunt launch. LinkedIn and a technical
article can support the sequence, but should tell different, useful stories rather
than repeat identical launch copy.
