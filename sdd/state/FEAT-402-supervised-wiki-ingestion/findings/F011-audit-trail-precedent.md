# F011 — Attributed write log & bookkeeper: audit precedent for decisions

- `packages/ai-parrot/src/parrot/knowledge/wiki/bookkeeper.py:175` —
  `WikiBookkeeper.log_operation(wiki_dir, operation, details)`; called from
  `WikiIngestOrchestrator` (ingest.py:271-283) with `"INGEST"` tags.
- `cli.py:1599+` — `memories` and `audit` commands ("wiki operation log and
  graph write commits (audit trail)"); authoring surface `remember`/`note`/
  `link` landed in e9ea0378 ("Claude Code can now save knowledge").
- Implication: admission decisions (auto/human/audit) should be logged through
  the same bookkeeper + surfaced by `wikitoolkit audit` — no new log plane.

Method: grep + reads + git log.
