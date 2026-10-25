---
id: F002
query_id: Q002
type: read
intent: "Locate every place the approved FEAT-704 spec commits to sidemantic, Ibis or an engine choice"
executed_at: 2026-10-25T10:12:00Z
duration_ms: 6000
parent_id: null
depth: 0
---

# F002 — FEAT-704 spec (approved, rev 0.2) is built around a sidemantic core with a native fallback

## Summary

The spec (1170 lines) names sidemantic ~45 times. Goals G5 (satellite confines the AGPL dependency) and G7 (native sqlglot fallback "so sidemantic can be bypassed per model or dropped later") already anticipate a sidemantic-free path. Non-Goals record **Ibis as a NO-GO** (TASK-1437) and reject BSL-over-Ibis. §2 Overview makes sidemantic `==0.12.0` the semantic core; `engine ∈ {sidemantic, native}` is a `Literal` in both `CompiledQuery` and `ModelPolicy`; M1 pins `sidemantic==0.12.0`, `sqlglot>=30.1,<31`, `jsonschema>=4.20`; M4 is the sidemantic loader/engine (opened by a spike); M5 the native compiler with parity tests. AC1/AC11/AC16/AC18 and §8 Q1 (legal sign-off 2026-10-19) / Q2 (reentrancy spike) all reference sidemantic.

## Citations

- path: `sdd/specs/semantic-layer.spec.md`
  lines: 44-46
  symbol: `Facts the design rests on`
  excerpt: |
    3. **Ibis is a recorded NO-GO** in this repo (TASK-1437 / FEAT-219; `dataset_manager/spatial/compiler.py:19`).

- path: `sdd/specs/semantic-layer.spec.md`
  lines: 60-67
  symbol: `G5`, `G7`
  excerpt: |
    - G5. One opt-in satellite distribution `ai-parrot-semantic` confines the AGPL-3.0 dependency (sidemantic) [...]
    - G7. A native fallback compiler (sqlglot) covers the simple-aggregation subset so sidemantic can be bypassed per model (`engine: native`) or dropped later, with parity tests on DuckDB.

- path: `sdd/specs/semantic-layer.spec.md`
  lines: 71-75
  symbol: `Non-Goals`
  excerpt: |
    - Symmetric aggregates, cumulative / time-comparison / cohort metrics in the **native** engine (sidemantic-only in v1).
    - BSL-over-Ibis or Ibis-direct compilation — rejected as brainstorm Option A (Ibis NO-GO, TASK-1437).

- path: `sdd/specs/semantic-layer.spec.md`
  lines: 89-100
  symbol: `## 2. Architectural Design › Overview`
  excerpt: |
    **Option B (brainstorm):** sidemantic (`==0.12.0`, AGPL accepted) owns the semantic core [...]
    2. **Compile** (`asyncio.to_thread`) via one internal `compile()` that dispatches on `model.engine ∈ {sidemantic, native}`

- path: `sdd/specs/semantic-layer.spec.md`
  lines: 240, 269, 390
  symbol: `engine: Literal["sidemantic", "native"]`
  excerpt: |
    engine: Literal["sidemantic", "native"]

- path: `sdd/specs/semantic-layer.spec.md`
  lines: 329
  symbol: `### Module 1`
  excerpt: |
    pinned `sidemantic==0.12.0`, `sqlglot>=30.1,<31`, `jsonschema>=4.20`, `pyyaml>=6`, `ai-parrot`; extras `bigquery` [...], `duckdb` (`duckdb>=1.0`); `license = "MIT"` + README section "License notice: sidemantic is AGPL-3.0"

- path: `sdd/specs/semantic-layer.spec.md`
  lines: 406-444
  symbol: `### Module 4`, `### Module 5`
  excerpt: |
    The first task of this module is a bounded **spike** that confirms the sidemantic 0.12.0 API names [...]
    Module 5 [...] compile the v1 subset — metrics with `sum/count/count_distinct/avg/min/max`, dimensions, `DATE_TRUNC` grains, declared one-to-many joins (fan-out ⇒ `SemanticValidationError`), filter tree (WHERE vs HAVING), order/limit/offset [...] Parity tests against the sidemantic engine on DuckDB fixtures.

- path: `sdd/specs/semantic-layer.spec.md`
  lines: 762-779
  symbol: `AC1`, `AC11`, `AC16`, `AC18`
  excerpt: |
    - [ ] AC1 `pip install ai-parrot-semantic` [...] installs `sidemantic==0.12.0` [...]
    - [ ] AC11 The native engine compiles the v1 subset and matches sidemantic row-for-row on the DuckDB parity fixtures
    - [ ] AC18 Release gates: [...] sidemantic↔native normalized-AST parity on the DuckDB fixtures

- path: `sdd/specs/semantic-layer.spec.md`
  lines: 1099-1100
  symbol: `§8 Q1`, `§8 Q2`
  excerpt: |
    - [x] Q1 Written legal sign-off for the AGPL-3.0 dependency — *Resolved 2026-10-19*: approved by **Jesus Lara (2026-10-19)**.
    - [x] Q2 sidemantic `SemanticLayer.compile` reentrancy [...] decided by the M4 spike task

## Notes

Spec frontmatter: `type: feature`, `base_branch: dev`, `projects: [ai-parrot-semantic, ai-parrot-server, ai-parrot]`, `tags: [semantic-layer, sidemantic, ...]`, Status approved, target 1.3.0.
