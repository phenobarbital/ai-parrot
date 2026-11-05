---
id: F017
query_id: Q030
type: git_log
intent: "Recent history of the GoogleModel catalogue — FEAT-688 / FEAT-781 shape of the last edits."
executed_at: 2026-11-04T01:37:14Z
duration_ms: 400
parent_id: null
depth: 0
---

# F017 — models.py touched once in 90 days: the FEAT-688 Argon refresh (TASK-4369)

## Summary

Only two commits touch the catalogue in the window. The live one is `0137c6595d`
(2026-10-16, TASK-4369, merged via PR #1685): a 7-line edit to `models.py` paired with
44 lines of catalogue tests in `packages/ai-parrot/tests/test_google_models.py` and 15 lines
in `test_llm_factory.py`. The earlier commit (`7f7f6f1659`, 2026-09-04) is the PEP-420 move
that created the satellite. No commit since FEAT-688 has touched the 2.5 members — the
gemini-2.5 retirement is untouched work.

## Citations

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/models.py`
  lines: n/a
  symbol: `GoogleModel`
  excerpt: |
    0137c6595d 2026-10-16 Jesus feat(gemini-upgrade): TASK-4369 — engine-committed coder deliverable
      models.py (+/- 7) · packages/ai-parrot/tests/test_google_models.py (+44) · packages/ai-parrot/tests/test_llm_factory.py (+15)
    7f7f6f1659 2026-09-04 Jesus feat(pep-420-llm-clients): TASK-2851 - satellites ai-parrot-client-google, -gemma4, -hf

- path: `packages/ai-parrot/tests/test_google_models.py`
  lines: n/a
  symbol: n/a
  excerpt: |
    catalogue assertions edited together with the enum in 0137c6595d (precedent: enum + tests move as a pair)

## Notes

- Precedent shape for the retirement: enum edit + `test_google_models.py` + `test_llm_factory.py` in one task.
- [cross-lane: type=read, intent=confirm the current member list in models.py still carries GEMINI_2_5_* and the exact lines TASK-4369 changed]
