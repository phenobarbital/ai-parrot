---
id: F009
query_id: Q012
type: git_log
intent: Review recent commit activity on bedrock.py and nova/ to detect in-flight work that could conflict
executed_at: 2026-08-03T00:13:00Z
parent_id: null
depth: 0
---

# F009 — Bedrock/Nova files are stable; last touches were credential and model-ID fixes

## Summary

13 commits in the last 4 months across `clients/bedrock.py` and `clients/nova/`,
all from two features: FEAT-302 (`bedrock-client-llm`, the original Converse
client) and FEAT-315 (`novaclient-amazon-aws`, which extracted
`BedrockConverseBase` in TASK-1806 and composed `NovaClient` in TASK-1809).
The most recent three commits are bug fixes (credentials, S3 bucket fallback,
`region_prefix` leakage) — no in-flight refactor of the tool loop, so there is
no conflict risk for instrumenting `ask()`. Notably the `BedrockConverseBase`
extraction (TASK-1806) is what makes the one-change-covers-both approach in
F004 possible; before it, Bedrock and Nova would have needed separate work.

## Citations

- commit: `a62803899` — fix(bedrock): drop generic AWS key fallback, add Bedrock API key support
- commit: `79cc24a58` — fix(novaclient-amazon-aws): fall back Reel S3 bucket_name resolution to 'default' profile
- commit: `f8c80e651` — fix(novaclient-amazon-aws): stop region_prefix leaking into Canvas/Reel/Sonic model IDs
- commit: `c807d34da` — test(novaclient-amazon-aws): TASK-1812 — migrate test suites to NovaClient, close coverage gaps
- commit: `f4128fbea` — feat(novaclient-amazon-aws): TASK-1811 — migrate call sites to NovaClient, delete nova_sonic.py
- commit: `4bedef0c2` — feat(novaclient-amazon-aws): TASK-1809 — NovaClient core, compose base + mixins
- commit: `5e66326c3` — feat(novaclient-amazon-aws): TASK-1806 — Extract BedrockConverseBase + fix aws_id credential resolution
- commit: `537d78acd` — feat(bedrock-client-llm): TASK-1746 — BedrockConverseClient Advanced Features
- commit: `a1c1b1fb4` — feat(bedrock-client-llm): TASK-1745 — BedrockConverseClient Core

## Notes

`sdd/tasks/completed/TASK-1806-bedrock-converse-base-extraction.md` documents
the extraction rationale and is worth reading before touching the base class.
