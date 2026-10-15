---
id: F007
query_id: Q012
type: git_log
intent: "How the same operation (SDK bump + model refresh) was carried out before"
executed_at: 2026-10-15T17:52:00Z
parent_id: null
depth: 0
---

# F007 — This exact operation has been done twice; both shapes are on record

## Summary

The catalogue has 17 commits. Two are direct precedents and they bracket the
cost. `f1dda8ffd` (2026-08-17) is the full version of this task — SDK floor
raise in two pyprojects + a 279-line rewrite of the catalogue (the "retire the
deprecated" half) + 91 lines of `client.py` (the prefix gates) + two test
files, 6 files total. `b4427bb66` (2026-09-03) is the minimal "add one model"
shape: enum +5, `client.py` +1 (one prefix added to the whitelist), tests +6.
Both confirm the same three-part footprint: **enum, prefix whitelist, tests**.

## Citations

- path: `packages/ai-parrot/src/parrot/models/google.py`
  lines: n/a
  symbol: `f1dda8ffd`
  excerpt: |
    f1dda8ffd 2026-08-17 Jesus
    new version of google-genai with support for 3.6 and 3.7 models
     packages/ai-parrot-embeddings/pyproject.toml       |   2 +-
     packages/ai-parrot/pyproject.toml                  |   6 +-
     .../ai-parrot/src/parrot/clients/google/client.py  |  91 ++++---
     packages/ai-parrot/src/parrot/models/google.py     | 279 ++++++++-------------
     packages/ai-parrot/tests/test_google_client.py     |  10 +-
     packages/ai-parrot/tests/test_google_models.py     |  19 ++
     6 files changed, 194 insertions(+), 213 deletions(-)

- path: `packages/ai-parrot/src/parrot/models/google.py`
  lines: n/a
  symbol: `b4427bb66`
  excerpt: |
    b4427bb66 2026-09-03 Jesus
    feat(models): add Gemini 3.8 Flash to GoogleModel and VertexAIModel enums
     packages/ai-parrot/src/parrot/clients/google/client.py | 1 +
     packages/ai-parrot/src/parrot/models/google.py         | 5 ++++-
     packages/ai-parrot/tests/test_google_models.py         | 6 ++++++
     3 files changed, 11 insertions(+), 1 deletion(-)

- path: `packages/ai-parrot-client-google/src/parrot/clients/google/models.py`
  lines: n/a
  symbol: catalogue history
  excerpt: |
    7f7f6f165 feat(pep-420-llm-clients): TASK-2851 - satellites ai-parrot-client-google, -gemma4, -hf
    77b599141 feat(pep-420-llm-clients): TASK-2841 — core convention prerequisites
    b4427bb66 feat(models): add Gemini 3.8 Flash to GoogleModel and VertexAIModel enums
    e6916227d fixing the supported google models
    f1dda8ffd new version of google-genai with support for 3.6 and 3.7 models
    70d6ea27e feat(computer-use-agent): TASK-1480 — GoogleModel computer-use entries

## Notes

Both precedents predate the FEAT-523 split, so their paths
(`parrot/models/google.py`, `parrot/clients/google/client.py` under core) are
now `packages/ai-parrot-client-google/src/parrot/clients/google/`. Neither
precedent introduced a `deprecated_models` registry — the 279-line rewrite
deleted and remapped names in place.
