---
id: F011
query_id: Q011
type: read
intent: "Find how FEAT-713 (accounting layer) depends on FEAT-704's satellite and pause"
executed_at: 2026-10-25T10:54:00Z
duration_ms: 3000
parent_id: null
depth: 0
---

# F011 — FEAT-713 creates the sidemantic-free satellite skeleton and leaves FEAT-704's amendment as open question Q10

## Summary

FEAT-713 (draft spec, 2026-10-21, target 1.3.0, no task index yet) states FEAT-704 is paused until sidemantic is migrated away, places `parrot.semantic.accounting` as a standalone package inside `ai-parrot-semantic`, and makes its M1 a byte-level mirror of the branch's `pyproject.toml`/`version.py` minus `sidemantic`, `jsonschema` and the `bigquery` extra. §8 Q10 asks who edits `sdd/specs/semantic-layer.spec.md` so that FEAT-704's M1 becomes "extend the skeleton created by FEAT-713". Lowering accounting metrics into the generic layer is deferred "until FEAT-704 resumes".

## Citations

- path: `sdd/specs/accounting-metrics-layer.spec.md`
  lines: 36-40
  symbol: `Problem Statement`
  excerpt: |
    FEAT-704 is also **paused** until its AGPL-3.0 dependency (sidemantic) is

- path: `sdd/specs/accounting-metrics-layer.spec.md`
  lines: 389-402
  symbol: `### Module 1: ai-parrot-semantic distribution skeleton (sidemantic-free)`
  excerpt: |
    `pyproject.toml` is the FEAT-704 branch file with `sidemantic` and `jsonschema` removed from `dependencies` and `bigquery` extra dropped; `version.py` is byte-identical to the FEAT-704 branch file; [...] README carries a **Layering** section: "`parrot.semantic.accounting` is standalone; FEAT-704 adds the governed generic layer on top and must not be imported by it".

- path: `sdd/specs/accounting-metrics-layer.spec.md`
  lines: 1074
  symbol: `§8 Q10`
  excerpt: |
    - [ ] Q10 FEAT-704 amendment — when FEAT-704 resumes, its M1 ("Distribution skeleton") must become "extend the skeleton created by FEAT-713" and its `__init__.py` must keep `parrot.semantic.accounting` importable without sidemantic. Who edits `sdd/specs/semantic-layer.spec.md`, and when?

- path: `sdd/proposals/accounting-metrics-layer.brainstorm.md`
  lines: 38
  symbol: `Home and packaging (resolved 2026-10-21)`
  excerpt: |
    FEAT-704's satellite does not exist yet, so this feature creates its skeleton (PEP 420, **no sidemantic**) and FEAT-704 builds on it when it resumes.

## Notes

`ls sdd/tasks/index | grep accounting` → none: FEAT-713 has not been decomposed. Whichever of FEAT-713 / FEAT-704-rev2 lands first owns `packages/ai-parrot-semantic/pyproject.toml`; the other must "extend".
