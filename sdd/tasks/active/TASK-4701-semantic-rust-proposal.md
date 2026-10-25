# TASK-4701: Research-first proposal for FEAT-742 — Rust/PyO3 semantic compiler (/sdd-proposal)

**Feature**: FEAT-704 — Semantic Layer — governed metric queries for agents (`ai-parrot-semantic`)
**Spec**: `sdd/specs/semantic-layer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4468
**Assigned-to**: unassigned

---

## Context

Spec rev 0.3 §8 U3 (resolved 2026-10-25): the Rust/PyO3 phase gets its own feature, **FEAT-742**
(`semantic-layer-rust-compiler`, reserved 2026-10-25), with the crate inside the satellite at
`packages/ai-parrot-semantic/rust/`. FEAT-704 only fixes the IR/compiler shape FEAT-742 consumes
(AC23). This task produces FEAT-742's exploration document by running **`/sdd-proposal`** seeded
with the insights dossier below, so the Rust phase starts from grounded research instead of a cold
prompt. It runs after TASK-4468 so the proposal targets the *landed* sole-engine IR, not the spec's
sketch of it.

---

## Scope

- Assemble the insights dossier (Implementation Notes below) into a brief and run
  `/sdd-proposal` with it as the file source, producing
  `sdd/proposals/semantic-layer-rust-compiler.proposal.md` with frontmatter `id: FEAT-742`,
  `base_branch: dev`, committed to `dev` per the proposal auto-commit rule (research state under
  `sdd/state/FEAT-742/`).
- The proposal must take a position on: derivation slice (SemaFlow `sql_ast.rs` + `dialect/`),
  attribution mechanics (`THIRD_PARTY.md` before the first derived line), crate layout
  (navrules-style inside the satellite), Python↔Rust boundary (which side owns the IR → where
  `CompiledQuery` is produced), determinism oracle (byte-identical SQL vs the Python compiler),
  and packaging (`native_group`, `maturin-action`, manylinux).

**NOT in scope**: writing FEAT-742's spec (`/sdd-spec` is a later step), any Rust code, any
dependency change, editing `sdd/specs/semantic-layer.spec.md`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `sdd/proposals/semantic-layer-rust-compiler.proposal.md` | CREATE | FEAT-742 research-first proposal (via `/sdd-proposal`) |
| `sdd/state/FEAT-742/` | CREATE | proposal research state (source, findings, synthesis) |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified on `dev` @ `71999bd06` (2026-10-25). `grep` is aliased to `ugrep` by RTK:
> use `grep -F` for anchors with `(`, `[`, `{`.

### Verified References
```
packages/navrules/rust/Cargo.toml            # pyo3 0.29 {abi3-py311}, crate-type ["cdylib","rlib"],
                                             #   `extension-module` feature OFF for `cargo test` (lines 1-30)
pyproject.toml:301,312                       # [[tool.parrot.worktree.native_group]] entries (worktree .so sync)
.github/workflows/release.yml:388,450        # PyO3/maturin-action@v1 build steps
sdd/specs/semantic-layer.spec.md             # rev 0.3: Non-Goals (FEAT-742 stub), §8 U3/U5, AC23, §7 Rust risk
sdd/proposals/semantic-layer-rev2.proposal.md  # §3 "Rust phase (later, own FEAT)" — the dossier's primary source
sdd/tasks/completed/TASK-1437-ibis-connection-spike.md  # Ibis NO-GO scope (connections only) — U5 context
```

### Does NOT Exist
- ~~`packages/ai-parrot-semantic/rust/`~~ — created by FEAT-742, not by this task.
- ~~`THIRD_PARTY.md` / `NOTICE`~~ anywhere in the repo — FEAT-742 must create it; the proposal records this.
- ~~`sdd/proposals/semantic-layer-rust-compiler.*`~~, ~~`sdd/specs/semantic-layer-rust-compiler.*`~~ — created here / later.
- ~~A FEAT-742 ID reservation step~~ — already reserved 2026-10-25; the proposal reuses it, never calls `reserve_ids.py`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "sdd/proposals/semantic-layer-rust-compiler.proposal.md",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

**Insights dossier to seed `/sdd-proposal`** (every claim already evidenced in
`sdd/proposals/semantic-layer-rev2.proposal.md` §3/F001/F012 and spec rev 0.3):

1. **Derivation slice**: SemaFlow (MIT) `sql_ast.rs` + `dialect/{duckdb,postgres,bigquery}.rs`,
   ~1,150 lines, `serde_json`-only — derive under MIT **with attribution**; the rest of SemaFlow
   (HTTP server, `ring`-dependent parts) is not derived.
2. **Attribution first**: `THIRD_PARTY.md` with SemaFlow's MIT header lands **before** the first
   derived line; record upstream copyright as best known (upstream's own MIT template is unfilled —
   a hygiene risk the proposal must address).
3. **Precedents**: navrules crate layout (pyo3 0.29 abi3-py311, maturin backend,
   `extension-module` feature off for `cargo test`); parrot_codec's `serde_json preserve_order`
   determinism lesson (never iterate a HashMap into SELECT/GROUP BY/IN order); worktree `.so`
   sync via `[[tool.parrot.worktree.native_group]]`; release wheels via `PyO3/maturin-action@v1`;
   never `maturin develop` in automated paths.
4. **Known upstream risks**: SemaFlow's BigQuery dialect lives on a personal git fork; `ring`
   breaks manylinux wheels — open the upstream wheel issue, keep the derived slice `serde_json`-only.
5. **Input contract**: the typed `SemanticModel` graph + canonical `SemanticQuery` → `CompiledQuery`
   IR fixed by FEAT-704 M4/M5 (sole native compiler). The Rust compiler is a drop-in producer of
   the same `CompiledQuery`; **byte-identical SQL vs the Python compiler** per (model digest,
   canonical query, dialect) is the acceptance oracle.
6. **Crate location (U3, resolved)**: inside the satellite at `packages/ai-parrot-semantic/rust/`,
   navrules-style — not a separate distribution.
7. **BSL/Ibis is out** (U5): the joins-phase re-opening clause lives in FEAT-704's Non-Goals;
   FEAT-742 adds no Ibis/BSL dependency and the proposal must not reopen it.

### Key Constraints
- Follow the `/sdd-proposal` workflow end to end (research budget, findings, synthesis, §5 Open
  Questions with owners); commit on `dev` per the auto-commit rule.
- The proposal's frontmatter reuses `id: FEAT-742` — never reserve a new FEAT id.

---

## Implementation Blueprint

### Steps (in order)
1. Re-read `sdd/proposals/semantic-layer-rev2.proposal.md` §3 + spec rev 0.3 Non-Goals/§7/§8 U3 —
   *why*: the dossier must carry forward resolved decisions verbatim, not re-litigate them.
2. Write the dossier (Implementation Notes 1-7, plus anything the landed TASK-4468 compiler
   changed about the IR) to a brief file.
3. Run `/sdd-proposal` with that brief as the source; answer its gates; let it commit
   `sdd/proposals/semantic-layer-rust-compiler.proposal.md` to `dev`.

---

## Acceptance Criteria

- [ ] `sdd/proposals/semantic-layer-rust-compiler.proposal.md` exists on `dev`, frontmatter
      `id: FEAT-742`, `base_branch: dev`, status `review` or `accepted`.
- [ ] The proposal carries all seven dossier insights with evidence, and positions on derivation
      slice, attribution, crate layout, IR boundary, determinism oracle, packaging.
- [ ] U3/U5 resolutions are carried forward as resolved — not re-asked.
- [ ] No Rust code, crate, or dependency is added by this task (FEAT-704 AC23 holds).

---

## Validation Commands

> The deliverable is an SDD proposal document produced by the `/sdd-proposal` workflow — no source
> code changes. The pytest command below guards the only executable contract the document must
> satisfy: its frontmatter stays parseable by `scripts.sdd.sdd_meta.resolve_flow` (the parser
> `/sdd-spec` runs on it next). Document review itself happens at `/sdd-spec` time for FEAT-742.

- `pytest tests/sdd_scripts/test_sdd_meta_resolve_flow.py -q`
- Manual check: `python -c "from pathlib import Path; from scripts.sdd.sdd_meta import resolve_flow; m = resolve_flow(doc_path=Path('sdd/proposals/semantic-layer-rust-compiler.proposal.md')); print(m.type, m.base_branch)"` prints `feature dev`.

---

## Test Specification

None — SDD artifact task (see Validation Commands).

---

## Agent Instructions

When you pick up this task:

1. This is an **SDD-command task**: it is executed interactively with the `/sdd-proposal` skill,
   not by a coder seat. Work from the main checkout on `dev` (the proposal commits to
   `base_branch`, like every exploration doc) — the FEAT-704 worktree is NOT used.
2. **Check dependencies** — TASK-4468 is `done` in `sdd/tasks/index/semantic-layer.json`.
3. Verify the Codebase Contract references, then follow the Implementation Blueprint.
4. Commit message (made by `/sdd-proposal` itself): `sdd: research-grounded proposal for FEAT-742 — semantic-layer-rust-compiler`.
5. **Close** with `scripts/sdd/close_task.sh TASK-4701 semantic-layer verified` and fill in the
   Completion Note (include the proposal's open-question list).

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
