---
id: FW-006
query_id: Q006
type: wiki_query
intent: "Orient: recorded decisions / lessons about the semantic layer (sidemantic removal, FEAT-742 compiler, governed DuckDB)."
executed_at: 2026-11-11T22:41:00Z
duration_ms: 0
parent_id: null
depth: 2
---

# FW-006 — Recorded decisions that bind the revision: sidemantic is gone (clean-room native compiler is the only engine), the owner already ruled that FEAT-704 creates the skeleton and FEAT-713 "extends" it (Q10 closed, edit still owed), the README requires accounting to stay independently importable, and the Rust compiler is a reserved follow-up (FEAT-742)

## Summary

FEAT-704 rev2 (proposal of 2026-10-25, spec rev 0.3/0.4) dropped sidemantic entirely — "no dependency, no code reference" — and made the native sqlglot compiler the only engine, so FEAT-713's stated reason for being standalone ("FEAT-704 is paused until its AGPL dependency is migrated away") no longer exists. The semantic-layer spec resolves U6 (owner, 2026-10-25): "FEAT-704 rev 0.3 creates the skeleton (M1); FEAT-713's M1 becomes 'extend'", and states this resolves FEAT-713 §8 Q10, the edit to be made "the next time FEAT-713's spec is touched". The shipped README carries a Layering section: the generic layer and "the future accounting extension share this namespace" and "the accounting extension must remain independently importable". The same rev2 decision block says the first native compiler was to be "without joins in v1" (later U4 kept one-to-many joins), keeps the governance stack as ai-parrot code "with any engine", stages SemaFlow (MIT) for the Rust/PyO3 phase under reserved FEAT-742 (TASK-4701 pending, a manual research follow-up), and narrows the Ibis NO-GO. The user-facing doc `wiki/tools/semantic-layer.md` mentions DuckDB only as a dialect/driver and the guarded hand-off; it has no accounting section.

## Citations

- wiki: `file:sdd/proposals/semantic-layer-rev2.proposal.md` (Q006 score=0.69; Q001 score=0.31)
- wiki: `file:sdd/state/FEAT-704/rev2/findings/F011-feat-713-coupling.md` (follow-up query score=0.28)
- wiki: `file:sdd/tasks/active/TASK-4701-semantic-rust-proposal.md` (Q006 score=0.11)
- wiki: `file:packages/ai-parrot-semantic/README.md` (Q001 score=0.99)

- path: `sdd/specs/semantic-layer.spec.md`
  lines: 1254
  symbol: `U6`
  excerpt: |
    - [x] U6 Who creates `packages/ai-parrot-semantic/` first, FEAT-704 or FEAT-713? — *Resolved 2026-10-25 (owner)*: **FEAT-704 rev 0.3 creates the skeleton (M1)**; FEAT-713's M1 becomes "extend" (resolves `accounting-metrics-layer.spec.md` §8 Q10 — that edit is out of scope for this spec and must be made the next time FEAT-713's spec is touched).

- path: `sdd/specs/semantic-layer.spec.md`
  lines: 1315-1319
  symbol: `Cross-feature dependencies`
  excerpt: |
    - **Cross-feature dependencies**: **FEAT-713** (`accounting-metrics-layer`, draft spec, not yet
      decomposed) extends the skeleton this feature creates (U6, 2026-10-25) — its own spec's §8 Q10 needs
      a follow-up edit (out of scope here) once this spec lands. **FEAT-742** (Rust/PyO3 phase, reserved
      2026-10-25) depends on this feature's IR/compiler shape but is not implemented by it.

- path: `sdd/specs/semantic-layer.spec.md`
  lines: 166-169
  symbol: `rev 0.3 resolutions`
  excerpt: |
    **(rev 0.3)** additionally resolved: no sidemantic dependency or reference (clean-room);
    single compiler with no dispatch; branch is salvage-only; one-to-many joins kept in v1 (U4); FEAT-704
    rev 0.3 creates the satellite skeleton, FEAT-713 extends it (U6); Rust phase gets its own reserved
    FEAT-742 (U3); Ibis NO-GO scope-narrowed to connections (U5).

- path: `packages/ai-parrot-semantic/README.md`
  lines: 6-9
  symbol: `Layering`
  excerpt: |
    ## Layering
    Generic semantic queries and the future accounting extension share this namespace.
    The accounting extension must remain independently importable.

- path: `sdd/proposals/semantic-layer-rev2.proposal.md`
  lines: null
  symbol: `§0 Origin (decision block 2026-10-21)`
  excerpt: |
    - **sidemantic queda descartado** del todo: ni dependencia, ni referencia de código.
    - **Implementación propia** [...]: un único compilador Pydantic → IR → sqlglot con gramática cerrada [...]
    - La gobernanza (RLS desde PBAC, allowlist por rol, guard sqlglot positivo, AuditLedger) es código de ai-parrot con cualquier motor

- path: `sdd/tasks/active/TASK-4701-semantic-rust-proposal.md`
  lines: null
  symbol: `Scope`
  excerpt: |
    - Preserve the owner-requested research follow-up: invoke sdd-proposal for already reserved FEAT-742 after the final Python compiler/IR lands. No Rust code/crate, dependency or THIRD_PARTY file is implemented by FEAT-704.

- path: `wiki/tools/semantic-layer.md`
  lines: 38
  symbol: (doc)
  excerpt: |
    SQL for DuckDB, Postgres, and BigQuery; compilation is CPU work and runs off

- path: `wiki/tools/semantic-layer.md`
  lines: 100-109
  symbol: `Guarded dataset hand-off`
  excerpt: |
    A bare `DatasetManager`, dataframe, or plain manager factory is rejected.

## Notes

- Consequences for the revision: (1) old M1, AC2 and Q10 are closed by a recorded owner decision, not merely by the merge; (2) the "standalone, never imports parrot.semantic.* outside itself" rule is now backed only by the README sentence "independently importable" — whether accounting may *reuse* the audit ledger, executor, PBAC gate or loader conventions is not decided anywhere in the graph; (3) a new accounting compiler is a second compiler in a package whose spec says "single compiler with no dispatch", and FEAT-742 will replace the generic one — the revision must say whether the accounting compiler is in or out of FEAT-742's scope.
- No decision, lesson or memory about a DuckDB-backed dataset store or about `parrot.semantic.accounting` exists beyond the FEAT-713 and FEAT-880 documents (queries Q003 and the follow-up "accounting extension independently importable" return only those).
- `sdd/specs/semantic-layer.spec.md` passages were read directly (1 file read, lines 164-170, 1254, 1313-1320); proposal and task excerpts come from wiki page content, hence no line numbers.
- [cross-lane: type=git_log, intent=check whether FEAT-742 has a branch or proposal yet (sdd/proposals/semantic-layer-rust-compiler.proposal.md does not appear in the graph)]
