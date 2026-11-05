---
id: FG-005
query_id: Q034
type: git_log
intent: "History of the google-genai pin bumps (which versions the floor has been at, and when)."
executed_at: 2026-11-04T01:37:14Z
duration_ms: 600
parent_id: null
depth: 0
---

# FG-005 — Floor history: 2.6.0 → 2.18.1 / 2.23.0 → 2.31.0 (unified on 2026-10-16)

## Summary

The embeddings satellite started at `google-genai>=2.6.0` (`7974022177`, 2026-05-28; comment
cleanup `dd90aeba0c` 2026-06-01). The client-google satellite was born with `>=2.18.1`
(`7f7f6f1659`, 2026-09-04) and was at `>=2.23.0` before FEAT-688. TASK-4371 (`bf7d588bff`,
2026-10-16) raised BOTH packages to `>=2.31.0` and regenerated `uv.lock` (88 lines; workspace
packages 0.4.1 → 0.4.2 in the same lock refresh). The current declared floor is therefore
2.31.0 — any "upgrade" means going above that, not to it.

## Citations

- path: `packages/ai-parrot-client-google/pyproject.toml`
  lines: n/a
  symbol: n/a
  excerpt: |
    bf7d588bff 2026-10-16: -    "google-genai>=2.23.0"   +    "google-genai>=2.31.0"
    7f7f6f1659 2026-09-04: +    "google-genai>=2.18.1"   (file created)

- path: `packages/ai-parrot-embeddings/pyproject.toml`
  lines: n/a
  symbol: n/a
  excerpt: |
    bf7d588bff 2026-10-16: -    "google-genai>=2.18.1"   +    "google-genai>=2.31.0"
    dd90aeba0c 2026-06-01: "google-genai>=2.6.0" kept; dropped google-cloud-aiplatform from the google extra
    7974022177 2026-05-28: +    "google-genai>=2.6.0"    (file created)

- path: `uv.lock`
  lines: n/a
  symbol: n/a
  excerpt: |
    bf7d588bff: -    { name = "google-genai", specifier = ">=2.23.0" },  +    { name = "google-genai", specifier = ">=2.31.0" },

## Notes

- The locked (resolved) google-genai version in uv.lock was not extracted (files_read budget spent).
- [cross-lane: type=grep, intent=grep uv.lock for the resolved google-genai version block and compare with PyPI latest]
- [cross-lane: type=read, intent=TASK-4371 completion note for the introspection gate procedure used to pick 2.31.0]
