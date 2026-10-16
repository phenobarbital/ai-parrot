---
type: feature
base_branch: dev
projects: [ai-parrot, dev-loop]
tags: [sdd-coder, complexity, wiki, worktree, seat-routing]
---

# Feature Specification: sdd-coder blast collector must read the wiki plane from the main checkout

**Feature ID**: FEAT-697
**Date**: 2026-10-17
**Author**: Jesus (jlara@trocglobal.com)
**Discovered-from**: `issue:9448f28680e0`

---

## 1. Motivation & Business Requirements

### Problem Statement

`_collect_wiki_blast` (`complexity_collectors.py:591-666`) invokes

```
python -m parrot.knowledge.wiki.cli symbols blast --path <worktree> --depth 2 \
       --no-inferred --tests --json <symbol>
```

with `--path` pointing at the **feature worktree**. The wiki plane
(`.parrot/wiki`) is git-ignored and exists **only in the main checkout**. Every
feature worktree therefore makes the CLI exit 1 with
`Error: Wiki not built yet for <path>. Run 'wikitoolkit build' first.`

Verified 2026-10-17 on this repository, same symbol and same flags:

| `--path` | exit | stdout |
|---|---|---|
| `.claude/worktrees/fix-sdd-coder-mcp-deadlock` | **1** | `Error: Wiki not built yet for …` |
| main checkout | **0** | valid `BlastRadiusOutput` JSON |

A structural sweep of `git worktree list` confirmed the plane is present in the
main checkout and absent in **all 50** linked worktrees. The failure is
therefore universal and deterministic, not intermittent.

The consequence is a routing regression rather than a visible error. The
collector marks every root unreliable (`f"{symbol}: exit {result.returncode}"`),
`blast_symbols` becomes `state="unknown"` with reason
`"Blast radius incomplete (…: exit 1)"`, and `ComplexityPolicy` routes `unknown`
exactly like `complex` — strong-models allowlist only (commit `957c15d96`).

Net measured effect (`artifacts/logs/sdd-coder-usage`, October 2026): **93
unknown + 186 complex vs 26 standard** assessments. Roughly 91% of tasks bypass
the cheap seats (nova glm/minimax/qwen/mistral, gemini, codex-spark, haiku) and
land on `gpt-5.6-terra` / native sonnet. Any task that declares Codebase
Contract symbols is systematically misclassified.

### Goals

- G1. `_collect_wiki_blast` resolves the wiki plane from the **main checkout**
  when the worktree has none, so blast radius is actually measured in worktrees.
- G2. A genuinely absent plane (none in worktree *and* none in the main
  checkout) still yields `unknown` — fail-closed — but with a **distinct,
  greppable reason** that is not conflated with "symbol missing from plane".
- G3. Symbols genuinely absent from the plane keep yielding missing-root
  `unknown` exactly as today. Plane-absent and symbol-absent stay separable.
- G4. No change to any other collector. `_collect_ruff_cyclomatic` and
  `_collect_ruff_syntax` legitimately analyse worktree code and keep `cwd` and
  their paths bound to the worktree.

### Non-Goals (explicitly out of scope)

- N1. Changing `ComplexityPolicy`'s `unknown` → strong-seat routing. `unknown`
  staying conservative is correct; this feature removes the *false* unknowns.
- N2. Building or refreshing the wiki plane automatically from the collector.
  No `wikitoolkit build` is ever invoked here — that is an operator action.
- N3. Giving worktrees their own plane, or making `.parrot/wiki` tracked.
- N4. Re-running or back-filling the October 2026 assessments in
  `artifacts/logs/sdd-coder-usage`.
- N5. Any change to the `symbols blast` CLI itself.

---

## 2. Architectural Design

### Overview

Introduce one private resolver in `complexity_collectors.py` that answers "where
does the wiki plane live for this worktree?", and have `_collect_wiki_blast` use
its answer for both the `--path` argument and the subprocess `cwd`.

Resolution order (first hit wins):

1. `<worktree>/.parrot/wiki` exists → the worktree itself. Preserves today's
   behaviour whenever a plane really is local (main-checkout runs, test
   fixtures), so no existing green test changes meaning.
2. Otherwise derive the main checkout with
   `git rev-parse --path-format=absolute --git-common-dir` run with
   `cwd=<worktree>`, take `.parent` of the result, and use it if
   `<main>/.parrot/wiki` exists. This is the identical pattern already proven in
   `telemetry.resolve_durable_root` (`telemetry.py:107-157`), which exists for
   the same reason: `--git-common-dir` points at the MAIN repository's `.git`
   even when called from inside a linked worktree.
3. Otherwise `None` — no plane anywhere.

### Component Diagram

```
collect_complexity(worktree, …)
  └─ _collect_all_evidence
       ├─ _collect_ruff_cyclomatic   cwd=worktree       (unchanged)
       ├─ _collect_ruff_syntax       cwd=worktree       (unchanged)
       └─ _collect_wiki_blast
            └─ _resolve_wiki_plane_root(worktree)   ← NEW
                 ├─ worktree/.parrot/wiki?        → worktree
                 ├─ git --git-common-dir → parent → main checkout (if plane)
                 └─ else                          → None  ⇒ unknown, distinct reason
```

### Integration Points

- `complexity_collectors._collect_wiki_blast` — the single wiki CLI call site in
  the module (`grep '"--path"'` returns exactly one hit, line 649).
- `ComplexityPolicy.timeout_seconds` / `max_output_bytes` — the resolver's own
  `git rev-parse` call must be bounded too; it is a blocking subprocess and must
  not be run bare on the event loop.

### Data Models

No new Pydantic models. `MetricEvidence` keeps its existing
`state`/`value`/`reason`/`source` shape.

### New Public Interfaces

None. `_resolve_wiki_plane_root` is private to the module.

---

## 3. Module Breakdown

### Module 1: Wiki plane resolver

`_resolve_wiki_plane_root(worktree: Path, policy: ComplexityPolicy) -> Optional[Path]`
in `complexity_collectors.py`, implementing the three-step order above. The
`git rev-parse` invocation goes through the module's existing async
`_run_subprocess` helper so it inherits the timeout and output bound and never
blocks the event loop. Any git failure is swallowed into `None` — the resolver
never raises.

### Module 2: Collector wiring and plane-absent evidence

`_collect_wiki_blast` calls the resolver once, before the per-symbol loop:

- Resolver returns a path → that path is used for `--path` **and** as the
  `_run_subprocess` `cwd`, replacing both current uses of `worktree`.
- Resolver returns `None` → return immediately with
  `MetricEvidence(state="unknown", source="wiki_collector")` and reason
  `"Wiki plane unavailable (no .parrot/wiki in worktree or main checkout)"`,
  without spawning any CLI subprocess.

Everything downstream of the subprocess call — the union of impacted ids, the
stale/truncation/missing-root unreliability rules, the evidence hashes, the
lower-bound semantics of `metric_value` — is untouched.

---

## 4. Test Specification

### Unit Tests

In `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_complexity_collectors.py`:

- T1. Worktree has its own `.parrot/wiki` → resolver returns the worktree; the
  CLI is invoked with the worktree path (today's behaviour is preserved).
- T2. Worktree has no plane, main checkout does → resolver returns the main
  checkout; the recorded `cmd` carries the **main checkout** path after
  `--path`, never the worktree path.
- T3. No plane anywhere → resolver returns `None`; `blast_symbols` is `unknown`
  with the plane-unavailable reason, and **no subprocess is spawned**.
- T4. Regression for the actual bug: plane only in the main checkout and the CLI
  stubbed to return valid blast JSON → `blast_symbols.state == "ok"`, i.e. a
  contract-symbol task in a worktree is no longer forced to `unknown`.
- T5. Plane resolves, but the stubbed CLI exits 1 for a symbol → still
  `unknown`, reason still `"… exit 1"`. Fail-closed behaviour is intact (G3).
- T6. `git rev-parse` failing or timing out → resolver returns `None` rather
  than raising; collector degrades to T3's evidence.

### Integration Tests

- T7. `collect_complexity` end-to-end over a temp git worktree whose parent
  checkout holds a fixture plane: `blast_symbols` is not `unknown`.

### Test Data / Fixtures

Reuse the suite's existing `tmp_path` git-worktree helpers and the hermetic
durable-root fixture in
`packages/ai-parrot/tests/flows/dev_loop/sdd_coder/conftest.py`
(`_hermetic_durable_root`). A fixture "plane" only needs the `.parrot/wiki`
directory to exist — the CLI itself is stubbed in unit tests.

---

## 5. Acceptance Criteria

- AC1. In a linked worktree with no local plane but a built main-checkout plane,
  `_collect_wiki_blast` produces `blast_symbols.state == "ok"` for a symbol
  present in the plane.
- AC2. The `--path` argument of the spawned command equals the resolved plane
  root, never the worktree, whenever the two differ.
- AC3. With no plane in either location, `blast_symbols.state == "unknown"` and
  the reason is the plane-unavailable string, distinct from both
  `"Blast radius incomplete (…)"` and `"… missing root"`.
- AC4. A symbol absent from an otherwise-present plane still yields `unknown`
  via the existing missing-root path.
- AC5. `_collect_ruff_cyclomatic` and `_collect_ruff_syntax` are byte-identical
  to `origin/dev`.
- AC6. `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_complexity_collectors.py
  test_complexity.py test_complexity_routing.py` passes.
- AC7. `ruff check` clean on the changed file; no blocking subprocess call is
  introduced on the event loop (ASYNC2xx clean).

---

## 6. Codebase Contract

### Verified Imports

- `from pathlib import Path` — already imported in `complexity_collectors.py`.
- `_run_subprocess(cmd: List[str], cwd: Path, timeout_seconds: int, max_output_bytes: int) -> SubprocessResult`
  — `complexity_collectors.py:1076`.
- `MetricEvidence` — already imported and used throughout the module.
- `ComplexityPolicy` with `.timeout_seconds` and `.max_output_bytes` — used at
  `complexity_collectors.py:414`, `570`, `662`.

### Existing Signatures

- `_collect_wiki_blast(worktree: Path, contract: ComplexityContract, policy: ComplexityPolicy, semaphore: asyncio.Semaphore) -> Tuple[Dict[str, MetricEvidence], Dict[str, Optional[str]], Dict[str, str], Dict[str, str], Dict[str, object]]`
  — `complexity_collectors.py:591-593`. The 5-tuple shape is unchanged by this feature.
- `resolve_durable_root(configured: Optional[str], *, worktree_base_path: str) -> Path`
  — `telemetry.py:107`. **Reference pattern only** — do not import or call it;
  it resolves a telemetry directory, not a wiki plane, and it raises.

### Verified Facts

- The wiki CLI module path is `parrot.knowledge.wiki.cli`; `--path` is a
  `symbols blast`-leaf option and must follow `symbols blast` on the command
  line (already correct in the current code, keep it that way).
- `git rev-parse --path-format=absolute --git-common-dir` returns the MAIN
  repository's `.git` from inside a linked worktree; its `.parent` is the main
  checkout root (`telemetry.py:146`).
- `.parrot/wiki` is git-ignored and exists only in the main checkout.

### Does NOT Exist

- There is no existing `_resolve_wiki_plane_root`, no `plane_root` field on
  `ComplexityPolicy`, and no `wiki_plane` setting in `conf.py`. Do not reference
  any of these as if they were already present.
- `complexity_collectors.py` imports nothing from `telemetry.py` today; do not
  add such an import.

---

## 7. Implementation Notes & Constraints

- The plane reflects the **main checkout's** indexed state, not the worktree's
  in-progress branch. This is accepted and correct for a *pre-implementation*
  complexity assessment: contract symbols are by definition pre-existing symbols
  the task will touch, and the task's own edits do not exist yet. The existing
  `stale` handling already demotes a plane that has drifted from disk.
- Never run `git` with `subprocess.run` directly inside the async collector —
  route it through `_run_subprocess` like every other call in the module.
- Touch only `complexity_collectors.py` and its test module. In particular do
  not "fix" the unrelated open `issue:455ae7a3d8ea` (`coder_run_validation`
  pending handle) that `ledger context` reports against the same file.
- Worktree test runs need `PYTHONPATH=packages/ai-parrot/src`; never `uv sync`
  inside the worktree.

---

## 8. Open Questions

None. The failure, its mechanism and its measured cost are all reproduced; the
resolution pattern is already proven in `telemetry.resolve_durable_root`.

---

## 9. Design Research Cross-Check

Reproduction, the 50-worktree structural sweep, and the October 2026 assessment
counts are recorded on `issue:9448f28680e0` and reproduced in §1 of this spec.

---

## Revision History

| Rev | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-17 | Jesus | Initial spec from `issue:9448f28680e0` via `/sdd-fix` |
