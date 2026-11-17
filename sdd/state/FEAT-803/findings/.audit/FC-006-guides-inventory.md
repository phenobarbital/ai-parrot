# FC-006: Guides inventory

## Query
`ls docs/guides/`

## Result
Six guide files:
- `cli-agent-daemon.md` (19K) — running agents as daemons via `agentd`
- `jira-ticket-extractor.md` (16K) — extracting Jira tickets for knowledge
- `jira-wiki-agent-integration.md` (13K) — integrating Jira with wiki agents
- `llm-wiki-guide.md` (64K) — comprehensive LLM Wiki guide (largest)
- `llm-wiki-remote.md` (5K) — remote wiki setup
- `wiki-adr-decisions.md` (12K) — ADR decisions in the wiki

Most are developer/operator guides. The LLM Wiki guides are technical reference material that will likely move to the wiki under FEAT-801 M7.

## Citations
- docs/guides/ — all 6 files with sizes

## Notes
For an informative site, only the CLI agent daemon guide might stay as a "how to deploy" guide. The Jira and wiki guides are integration-specific and belong in the wiki's technical reference.
