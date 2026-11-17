# F007: Guides inventory

From: FC-006

## Summary
Six guide files under `docs/guides/`:
- cli-agent-daemon.md (19K) — running agents as daemons
- jira-ticket-extractor.md (16K) — Jira ticket extraction
- jira-wiki-agent-integration.md (13K) — Jira + wiki agents
- llm-wiki-guide.md (64K) — comprehensive LLM Wiki guide (largest)
- llm-wiki-remote.md (5K) — remote wiki setup
- wiki-adr-decisions.md (12K) — ADR decisions

Most are developer/operator guides. The LLM Wiki guides are technical reference that
likely move to wiki under FEAT-801 M7.

## Citations
- docs/guides/ — all 6 files with sizes

## Notes
For an informative site, only the CLI agent daemon guide might stay as a "how to deploy"
guide. The Jira and wiki guides are integration-specific and belong in wiki. This leaves
the guides section very thin — an opportunity to create new user-facing tutorials.
