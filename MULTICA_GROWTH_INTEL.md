# Multica public growth and funnel intelligence

Checked 2026-10-21. This report uses public sources only. It does not use private
accounts, access controls, impersonation, leaked data, or non-public customer
information. Statements are separated into verified facts, evidence-backed
inferences, and unknowns.

## Executive read

Multica's apparent growth is not primarily explained by a conventional paid-ad
campaign. The visible engine is a GitHub-first distribution system backed by an
experienced developer-product team, a very large adjacent content repository,
extreme shipping cadence, broad provider coverage, self-hosting, and a cloud path
that removes installation friction.

The most consequential acquisition asset is
[`multica-ai/andrej-karpathy-skills`](https://github.com/multica-ai/andrej-karpathy-skills),
which had 221,695 stars and 22,251 forks at the check. The first three lines of its
README promote and link to Multica. Multica itself had 53,404 stars and 7,008 forks.
This creates an unusually powerful adjacent-audience funnel: a broadly shareable
Claude Code guidance artifact attracts developers, then sends them to the more
complex agent-management product.

The product funnel is also unusually legible because its source contains explicit
analytics and onboarding definitions. Their activation keystone is not a signup,
star, workspace, or install. It is the first completed agent execution for an
issue (`issue_executed`). That is the correct benchmark for Ticket Terminal too:
the comparable success event is a real external ticket completed through a local
agent session, not a repository visit or clone.

No reliable public evidence of a current paid Google, Meta, Reddit, or X campaign
was found. Their code is ready to attribute paid campaigns through UTMs, but that
does not prove campaigns are running. Do not infer ad spend from the existence of
tracking code.

## Funding status

Multica is funded, but the public disclosure is incomplete. In an April 2026
interview, founder Jiayuan Zhang said the company had completed two financing
rounds and described an existing backer only as a "top-tier USD fund." A 2024
profile of the predecessor product, devv.ai, separately reported an angel round
from a top-tier USD fund. Multica and devv.ai are operated through the same legal
company, Index Labs (Hong Kong) Limited.

The founder said a new round would open in May 2026 to expand cloud-agent compute
infrastructure and the open-source community. No reliable public announcement was
found confirming that this later round closed. Investor names, round sizes,
valuation, ownership, and total capital raised remain undisclosed in the sources
reviewed. Therefore the defensible description is **venture-backed, at least two
rounds claimed by the founder, financial terms undisclosed** — not bootstrapped,
and not a confirmed large institutional round.

Primary funding evidence:

- [April 2026 founder interview](https://aitntnews.com/newDetail.html?newId=24491)
- [2024 founder/profile interview covering the devv.ai angel round](https://www.10100.com/article/1005023)
- [Multica privacy policy identifying Index Labs (Hong Kong) Limited](https://multica.ai/privacy)

## Reconstructed funnel

### 1. Awareness

Verified surfaces:

- GitHub is the dominant public surface. The product repository is large and
  active, and the landing page repeatedly asks visitors to star it.
- The 221k-star Karpathy-inspired skills repository links to Multica above the
  fold. This is probably the highest-leverage owned distribution asset.
- The same organization maintains the product, the skills repository, a Homebrew
  tap, a Multica CLI skill, and provider-specific runtime integrations.
- The team previously built devv.ai. Multica's own About page confirms the shared
  team and product lineage. Public founder material says devv.ai previously reached
  more than 600,000 users, giving the team a pre-existing developer audience and
  launch experience. The degree of direct list cross-promotion is not public.
- Launch coverage appeared on Reddit, YouTube, blogs, directories, tutorials, and
  Hacker News. The identified HN launch was weak at two points and no comments,
  while GitHub and YouTube coverage were much stronger.
- The first-party product and docs are localized across several languages, and the
  runtime list includes tools popular in both Western and Asian developer markets.
- Third parties have published install guides, reviews, Docker/Railway templates,
  npm extensions, and training material. These create search coverage around many
  long-tail adoption questions without requiring every page to be written by the
  Multica team.

Evidence-backed interpretation:

- The top-of-funnel asset is not "a project-management app." It is a portfolio of
  useful, highly shareable developer artifacts. Multica captures the audience after
  trust and attention have already been earned elsewhere.
- Provider breadth creates repeated launch hooks. Every added CLI can produce a
  changelog item, integration page, provider-community mention, and search landing
  path.
- Their category hook is intentionally larger than the feature set: "Your next 10
  hires won't be human" and "hire your first AI employee in the next hour." It
  sells a workforce transformation, not another Kanban board.

### 2. Acquisition and attribution

The public frontend code captures `utm_source`, `utm_medium`, `utm_campaign`,
`utm_content`, `utm_term`, and the referrer's origin in a 30-day first-touch cookie.
The onboarding questionnaire recognizes these acquisition categories:

- friends or colleagues;
- search;
- X, LinkedIn, YouTube, GitHub, or other social;
- blog or newsletter;
- AI assistant;
- work;
- event or conference;
- other / unknown.

The source question is deliberately collected after agent work completes rather
than before activation. That avoids adding friction to the most fragile part of
onboarding and produces a cleaner answer from an activated user.

Their primary calls to action are:

- start a free trial;
- download the desktop app;
- star or inspect the GitHub repository;
- talk to sales.

This supports three adoption psychologies without forcing one route: hosted trial
for speed, desktop for lower setup friction, and self-hosting/source inspection for
control and trust.

### 3. Activation

The public event catalog exposes the sequence they measure:

1. `signup`
2. `workspace_created`
3. `onboarding_started`
4. questionnaire/source responses
5. `runtime_registered`
6. `runtime_ready`
7. `agent_created`
8. `issue_created`
9. `issue_executed`
10. `onboarding_completed`

`issue_executed` is described in the public metrics code as the first completed
task per issue and the "activation keystone." Runtime readiness is timed in buckets
from under one second through ten minutes, showing that connection latency and setup
failure are treated as core funnel problems.

The product reduces activation friction by:

- automatically creating a workspace after email verification;
- offering a desktop app with a bundled daemon;
- auto-detecting installed agent CLIs;
- supporting a cloud route, desktop route, CLI route, and full self-host route;
- ending onboarding with an agent ready to talk and guided first-task prompts;
- preserving skip paths for runtime setup and a cloud-runtime waitlist rather than
  treating every incomplete setup as the same loss.

### 4. Retention

Public code and product surfaces suggest that retention is measured through depth
and recurrence, not merely return visits:

- number of completed issue executions, with milestone logic for at least 1, 2, 5,
  and 10;
- chat messages and continued issue discussions;
- Autopilot creation and recurring run completion/failure;
- squad creation and multi-agent use;
- reusable skills and accumulated issue/run history;
- runtime online/offline health;
- activity, token usage, and cost views;
- frequent updates through desktop auto-update and CLI update paths.

Self-hosted deployments send an optional anonymous daily deployment snapshot unless
`DO_NOT_TRACK=1` is set. The documented snapshot contains a random deployment ID,
version, bucketed counts of workspaces/members/agents/daemons, and daily agent-run
outcomes. That gives Multica visibility into self-host activation and retention that
GitHub stars and download counts cannot provide.

### 5. Expansion and revenue

Expansion events include team invitations sent and accepted, squads, Autopilots,
additional workspaces, and sales inquiries. The cloud code contains per-seat
subscription checkout, seat reconciliation and purchases, Stripe billing portal,
and separate cloud-runtime credit/top-up mechanics.

The apparent commercial ladder is:

1. free trial / cloud exploration;
2. free internal self-hosting;
3. paid cloud Pro seats and runtime usage;
4. commercial license for external hosted service or embedding;
5. contact sales for larger or licensing-sensitive deployments.

The public sales form rejects common free-email providers and asks for company size,
use case, goals, and region. That is a deliberate B2B qualification gate rather
than an undifferentiated lead form.

## Shipping as distribution

The GitHub releases API showed 166 releases from `v0.1.0` on 2026-01-16 through
`v0.6.5` on 2026-10-21. During parts of the summer the team released almost every
weekday. This does several jobs simultaneously:

- keeps the repository visibly alive;
- creates a constant changelog/content stream;
- produces new provider- and feature-specific search terms;
- turns community requests into public proof of responsiveness;
- makes third-party reviews go stale quickly, encouraging new coverage;
- reduces perceived abandonment risk for a new infrastructure product.

The large contributor list is real, but contribution volume is concentrated in a
small core team. Public community analysis also found a low maintainer response rate
on recent external issues. Treat the huge star number as reach, not proof that the
support burden or activated user base scales proportionally.

## Public customer and user evidence

### Named or attributable use

| Evidence | What is publicly claimed | Confidence |
|---|---|---|
| Multica / former devv.ai team | Multica says it emerged from the team's own need to work alongside agents, and the launch post says the team builds Multica using Multica | High for internal dogfooding |
| [Flowtivity](https://flowtivity.ai/blog/multica-case-study-managing-ai-agents-australian-businesses/) | A named consultancy claims four client engagements, five to eight concurrent agents, and a reduction in weekly coordination overhead | Medium: detailed first-party customer account, but not independently verified or endorsed by Multica |
| [yizhisec deployment](https://github.com/multica-ai/multica/pull/1675) | An external contributor says a proposed fresh-run feature was built and battle-tested on its Multica deployment for Windows kernel-security research | Medium-high for a real deployment; scale and commercial status unknown |
| [ZCode feature request](https://github.com/multica-ai/multica/issues/5361) | A contributor says their team uses Multica to orchestrate Claude Code, Codex, Kimi, and ZCode tasks | Medium: credible public product-use statement, organization unnamed |
| Third-party ecosystem | Community npm packages, Docker images, a Railway template, guides, and an external iOS client exist | High for ecosystem activity; not equivalent to paying customers |
| 9Expert training | A paid course includes managing AI agents through Multica | High for inclusion in a commercial training curriculum; not evidence that 9Expert is a Multica customer |

### What is not publicly established

- No official named-customer logo wall or first-party case-study library was found.
- No verified count of cloud accounts, activated workspaces, retained users, paid
  seats, commercial licenses, revenue, or self-host deployments is public.
- GitHub stars, forks, Discord membership, downloads, and anonymous deployment
  telemetry cannot be converted into customers without private data.
- The Flowtivity metrics are self-reported. They should not be repeated as audited
  outcomes.

## Paid-ad assessment

No direct public evidence of an active paid campaign was found in indexed Google,
Meta, Reddit, or X results. The site has mature UTM and first-referrer capture, so
paid testing would be measurable. Current evidence supports "no campaign verified,"
not "they have never advertised."

The likely reason paid ads are not the visible core is economic and behavioral:
this product needs trust, local code access, a runtime, an existing coding-agent
subscription, and several setup steps. GitHub artifacts, technical proof, tutorials,
and provider communities pre-qualify that audience better than broad paid traffic.

## What Ticket Terminal should copy

1. **Adopt the same activation truth.** Track a completed real Jira/Notion ticket
   session as the keystone, then milestones at 1, 2, 5, and 10 completed tickets.
2. **Instrument runtime readiness.** Measure install start, server ready, provider
   detected, ticket loaded, agent started, and first useful result, including time
   and failure reason.
3. **Create an adjacent utility with independent value.** The Multica lesson is not
   "buy ads." It is to own a useful artifact that the target user wants before they
   want the full product. For Ticket Terminal this could be a high-quality,
   provider-neutral agent-session evidence format, Jira-to-agent prompt exporter,
   or local agent cost/audit utility. It must stand on its own and link honestly to
   Ticket Terminal.
4. **Turn integrations into distribution.** Each Jira, Notion, Claude Code, Codex,
   manager-digest, and memory feature should have its own exact demo and searchable
   page, not only a row in a feature matrix.
5. **Offer one paved activation path.** Multica has many routes because it has the
   engineering capacity to support them. Ticket Terminal should first make one path
   reach a completed ticket in under 15 minutes before expanding installers.
6. **Publish at a dependable cadence.** Weekly substantive proof is enough. Do not
   imitate 166 releases unless the changes are real and supportable.
7. **Use honest customer evidence early.** One named developer completing three real
   Jira tickets is more strategically useful than hundreds of low-intent stars.
8. **Keep the wedge explicit.** Multica asks users to adopt its workspace. Ticket
   Terminal should repeatedly show that Jira/Notion remains the system of record.

## What Ticket Terminal should not copy

- Do not optimize for stars as the north-star metric.
- Do not broaden into a replacement project-management suite.
- Do not claim "open source" if future licensing adds source-available restrictions.
- Do not cross-post generic launch copy across multiple communities.
- Do not use an adjacent repository as disguised promotion; the utility must be
  genuinely useful and the affiliation obvious.
- Do not buy broad ads before the activation path and instrumentation are working.

## High-value experiment derived from this analysis

Run a $100 maximum search-intent experiment only after events are recorded end to
end. Send traffic to a focused Jira-to-local-agent landing page, not the repository
home. Optimize for this sequence:

`qualified visit -> install started -> provider detected -> Jira ticket opened ->`
`agent session started -> first session completed`

Kill the campaign if it produces clicks without install attempts. Continue only if
at least two unrelated users reach a completed ticket and one returns for a second
ticket. This tests Ticket Terminal's wedge rather than whether "AI agents" can buy
cheap clicks.

## Principal sources

- [Multica repository](https://github.com/multica-ai/multica)
- [Multica landing page](https://multica.ai/)
- [How Multica works](https://multica.ai/docs/how-multica-works)
- [Multica About page](https://multica.ai/about)
- [Multica licensing](https://multica.ai/licensing)
- [Multica privacy and self-host telemetry disclosure](https://multica.ai/privacy)
- [Karpathy-inspired skills repository](https://github.com/multica-ai/andrej-karpathy-skills)
- [Public launch discussion](https://www.reddit.com/r/ClaudeAI/comments/1sg4ugr/i_built_an_opensource_platform_that_turns_claude/)
- [Independent ecosystem review](https://repodispatch.online/en/dispatches/100-multica-ai-multica/)
- GitHub public API results for repository, organization, contributors, releases,
  and public source files, checked 2026-10-21.
