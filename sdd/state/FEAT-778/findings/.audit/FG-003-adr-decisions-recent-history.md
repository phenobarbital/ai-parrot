---
id: FG-003
query_id: Q062
type: git_log
intent: "Recent activity on ADR decisions subsystem."
executed_at: 2026-10-30T16:41:30Z
duration_ms: 350
parent_id: null
depth: 0
---

# FG-003 — knowledge/wiki/decisions/: 15 commits in 90 days; ADR subsystem (FEAT-578) matured, prefixed aliases (FEAT-760) landed 2026-10-27

## Summary

15 commits (Jesus / Jesus Lara) in three waves: FEAT-578 wiki-ADR (2026-09-20/21: perf fixes, no LLM client import when reading decisions, stale-section fix), graphindex-core-seams (2026-10-15: `parrot_tools.wiki` planes, SDK transport descriptors from the operations registry, decisions CLI `--ns` guard, TASK-4349), and FEAT-760 adr-prefixed-aliases (2026-10-27: TASK-4817/4818/4820 + tech-debt fix touching `ingest.py` and `models.py` — prefix normalization split into `_normalize_prefix` / `_validate_local_prefix` / `_validate_known_prefixes`). The subsystem is real, recently hardened, and exposes an operations registry + toolkit — the "soporte ADR" the source relies on exists and is namespaced by prefix.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py`
  lines: n/a
  symbol: `_normalize_prefix`, `_validate_local_prefix`, `_validate_known_prefixes`
  excerpt: |
    cb512e51ac 2026-10-27 Jesus fix(adr-prefixed-aliases): FEAT-760 — ADR resolution tech debt (issue:201a92abdd12)
    +    def _normalize_prefix(prefix: str) -> str:  # uppercase; reject compact citations ADR0001/RFC12
    +    @field_validator("local_prefix") def _validate_local_prefix(...)
    +    @field_validator("known_prefixes") def _validate_known_prefixes(...)
    (files: decisions/ingest.py, decisions/models.py, tests .../decisions/test_ingest.py, test_parser.py)

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/`
  lines: n/a
  symbol: commits
  excerpt: |
    74b5471b13/902218066e/efcc924f6c 2026-10-27 feat(adr-prefixed-aliases): TASK-4820/4818/4817
    4bef2a3c8d 2026-10-15 fix(graphindex-core-seams): build SDK transport descriptors from the operations registry, not framework tools
    c87da7595c 2026-10-15 feat(decisions-cli-fixes): TASK-4349 — single-namespace --ns guard + e2e write-command --ns tests
    4b8c32ebc1 2026-10-15 feat(graphindex-core-seams): TASK-4310 — parrot_tools.wiki planes + lazy old paths
    1210900477 2026-09-21 perf(wiki-adr): FEAT-578 — don't import the LLM client stack to read decisions
    0ea73f5ca8 2026-09-21 fix(wiki-adr): FEAT-578 — last ADR section no longer reports stale forever

## Notes

- Reading decisions is deliberately LLM-free (1210900477): a deterministic `KnowledgeResolver` can load accepted ADRs without pulling the client stack — matches the source's "reproducible sin LLM" requirement.
- [cross-lane: type=read, intent=decisions/models.py — confirm ADR status enum values (proposed/accepted/superseded) and whether tags/components exist for the manifest filter]
