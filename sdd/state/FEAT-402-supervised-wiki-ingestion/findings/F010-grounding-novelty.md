# F010 — Grounding/claim-checking exists and can back the novelty score

- `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:~1696` — `wikitoolkit
  ground` command: "Check a claim against the project knowledge graph
  (grounding)."
- `packages/ai-parrot/src/parrot/knowledge/graphindex/grounding.py` — grounding
  evaluator (commit 09fe7df6, "grounding evaluator + run→knowledge lineage").
- Implication: the `novelty` dimension (does the wiki already cover this?) can
  reuse this machinery + the store's search plane instead of new embedding code.

Method: grep + command docstring read + git log.
