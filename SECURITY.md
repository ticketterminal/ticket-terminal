# Security Policy

Ticket Terminal is a local-first tool: it runs on your own machine with your own credentials,
and there's no hosted service that could be attacked on your behalf. Still, if you find a
security issue in the code itself (the server, the board, a workflow, a dependency), please
report it privately rather than opening a public issue.

## Reporting a vulnerability

Preferred: open a [GitHub Security Advisory](https://github.com/ticketterminal/ticket-terminal/security/advisories/new)
for this repo (private by default, visible only to maintainers until resolved).

Alternatively, email **ticketterminal@zohomail.com** with a description of the issue and steps
to reproduce it.

Please don't include real credentials, tokens, or other sensitive data in a report — describe
the issue, and a maintainer will follow up if a reproduction needs more from you.

## Response

This is presently maintained by one person. Expect an acknowledgement within a few days, and a
fix or mitigation timeline once the report is confirmed. Coordinated disclosure is fine — we'll
agree on a timeline before anything is made public.

## Supported versions

There are no released versions yet; `main` is the only line that gets fixes.
