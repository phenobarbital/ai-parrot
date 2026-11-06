---
type: feature
base_branch: dev
feature_id: FEAT-830
projects: [ai-parrot]
tags: [sdd, test-scope, green-cache, baseline, ledger-fix]
discovered_from: issue:bfb29d4ffe49
docs:
  policy: required
  pages: [wiki/sdd-tooling/sdd/test-selection-validation-contract.md]
  api_modules: [parrot.flows.dev_loop.test_scope.green_cache]
---

# Feature Specification: test-scope — directory operands, one cache namespace, honest cached count, baseline robustness

**Feature ID**: FEAT-830
**Date**: 2026-11-07
**Author**: Jesus Lara
**Status**: approved
**Target version**: next patch

---

## 1. Motivation & Business Requirements

### Problem Statement

Ledger `issue:bfb29d4ffe49` (discovered from FEAT-699, opened 2026-10-18) lists five defects in the
scoped test selector (`parrot/flows/dev_loop/test_scope/`) and its two drivers — the CLI
`parrot/sdd/scripts/select_tests.py` and the MCP supervisor `parrot/flows/dev_loop/sdd_coder/background.py`.
Each was re-checked against `origin/dev` @ `aa91d76896` (2026-11-07):

1. **Directory operands narrow a contract silently — still open (partly fixed).**
   `contract._normalize_pytest` (contract.py:209) accepts a non-broad directory operand such as
   `packages/ai-parrot/tests/flows`; the contract-operand lint in `check_task_graph.py:512` uses
   `exists()`, so a directory passes; `plan_tests` then skips it as "contract operand missing on disk"
   (select.py:185, `is_file()`), quietly narrowing the gate. `_declared_targets` (select.py:115) lets a
   non-broad directory from a Validation Command through as a target, breaking the "never a directory or
   suite" rule. *Already fixed:* the Validation-Commands lint now errors `directory-validation-target`
   (check_task_graph.py:383) — kept as is. A scan of all 92 cached `test_contract` headers on
   `origin/dev` found zero non-`.py` pytest operands, so tightening normalization breaks no stored contract.
2. **Two green-cache namespaces — still open.** The CLI computes the namespace with
   `contract_digest=contract.digest if contract else "none"` (select_tests.py:413-416); the supervisor
   uses `""` for "no contract" at background.py:621-626 (via `_index_runtime_metadata`) and :867-871.
   The store keeps one namespace and wipes on change, so the CLI and the MCP supervisor clear each
   other's entries on every alternating run of a contract-less feature.
3. **Cached count inflated — still open.** background.py:632-644 calls `report.append_cached` once per
   task id with the same `plan.cached`; `report.render_markdown` sums `len(record.cached)` over records
   (report.py:556), so N tasks report N× the cached targets.
4. **Baseline/selector robustness — still open.** (a) `baseline._classify_group` replaces `PYTHONPATH`
   with the one distribution's `src` (baseline.py:165), so every other distribution resolves from the
   main checkout's editable install, not the baseline commit. (b) `remove_baseline_checkout` runs an
   unconditional, repository-global `git worktree prune` (baseline.py:131) that can drop the admin data
   of any other session's worktree whose directory is momentarily missing. (c) select_tests.py:378 builds
   `origin/None` when the index header carries `"base_branch": null`.
5. **Undocumented depth-1 cache key — still open.** The issue names
   `docs/sdd/test-selection-validation-contract.md`, which no longer exists; the doc is
   `wiki/sdd-tooling/sdd/test-selection-validation-contract.md` ("Green cache and baseline verdict").
   It says nothing about the depth-1 limit and names a cache file (`.sdd_test_cache.json`) that is not
   the real one (`green_cache.CACHE_FILENAME == "parrot-test-scope-green.json"`, green_cache.py:31).

### Goals
- A directory is never a contract operand (rejected at normalization and flagged by the lint) and never a
  declared target (dropped with a note).
- The CLI and the supervisor compute the same green-cache namespace for the same feature/base/contract.
- The rendered cached count is the number of distinct cached targets.
- Baseline runs import every distribution from the baseline checkout; cleanup touches only its own
  worktree; a null `base_branch` falls back to `dev`.
- The doc states the depth-1 limit and the real cache file name.

### Non-Goals (explicitly out of scope)
- `issue:3ae0b2ae0ef4` (declared `parrot e2e run` dropped by the selector) — handed to FEAT-829
  `test-scope-planner-fixes` together with `issue:a3aebc40ef48`; this spec does not touch
  `runners/parrot_e2e.py`, `planner.py` or the e2e branch of `_declared_targets`.
- `issue:dee91130fa06` (foreign-repo validation phase, v1.1) — design undecided, stays open.
- No change to the cache key depth itself, the store format (`CACHE_SCHEMA`) or the report record schema.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:d2aaf18cbefa8fa6b9fea4da52519fcddd365eefb2c12d281d81816b975c333c evaluation_digest=sha256:26055617434993522b7317996c7b8f9ee69f6282e488cdff3d2a60258fd1dad4 rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

Five independent, local corrections; no new subsystem.

- **M1 directory operands.** `_normalize_pytest` raises `ValueError` when an operand's file part does not
  end in `.py` (pure check, no filesystem). Every contract reader goes through it —
  `parse_spec_contract` (so `cache_test_contract` refuses to cache), `contract_from_index_header` (re-normalizes
  each pytest block before the digest check) and `lift_schema1` — so `check_task_graph` already reports such a
  header as `test-contract-malformed` with the operand in the message, and `plan_tests` never receives a
  directory from a contract. No new lint code and no `plan_tests` change: both would be unreachable (rev 0.2).
  `_declared_targets` drops a pytest operand whose file part is a directory in the worktree, appending
  `"declared path is a directory, dropped: <operand>"`.
- **M2 one namespace.** New `green_cache.namespace_for(*, feature_id, base_ref, contract)` returns
  `cache_namespace(feature_id=…, base_ref=…, contract_digest=contract.digest if contract is not None else "")`.
  `select_tests` and both supervisor sites call it, so "no contract" is `""` everywhere (the supervisor's
  existing value — supervisor-written entries survive the upgrade; CLI entries written under `"none"`
  are invalidated once, which is harmless).
- **M3 cached union.** `render_markdown` counts `len(set().union(*(r.cached for r in records.values())))`.
- **M4 baseline + base ref.** `PYTHONPATH` = the target distribution's `src` first, then every other
  existing `checkout/packages/*/src` in sorted order, `os.pathsep`-joined. The unconditional
  `git worktree prune` is removed: `git worktree remove --force` already deletes the admin entry on
  success, and on failure the existing warning is logged. select_tests computes
  `origin/{index_header.get("base_branch") or "dev"}` through a small helper `_default_base_ref(header)`.
- **M5 doc.** Add the depth-1 limit and correct the cache file name in the wiki page.

### Component Diagram
```
select_tests.py ──┐                       ┌─→ green_cache.namespace_for ─→ cache_namespace
background.py ────┴─→ plan_tests (select) ┤
                                          └─→ contract._normalize_pytest (operands)
check_task_graph ──→ contract_from_index_header ─→ _normalize_pytest (test-contract-malformed)
background.py ──→ report.append_cached ─→ report.render_markdown (union count)
baseline.classify_failures ─→ _classify_group (PYTHONPATH) ; remove_baseline_checkout (no prune)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `contract._normalize_pytest` | modifies | new `.py` rule beside the existing unsafe-operand checks |
| `check_task_graph` contract lint | uses (unchanged) | surfaces the new `ValueError` as `test-contract-malformed` |
| `select._declared_targets` | modifies | directory drop note (pytest only) |
| `green_cache` | extends | `namespace_for` wraps `cache_namespace` |
| `select_tests.main` / `BackgroundRunner` | uses | three call sites switch to `namespace_for` |
| `report.render_markdown` | modifies | union count |
| `baseline._classify_group` / `remove_baseline_checkout` | modifies | env + cleanup |

### Data Models
No new models. `TestContract` (datatypes.py) is consumed read-only for `.digest`.

### New Public Interfaces
```python
# parrot/flows/dev_loop/test_scope/green_cache.py
def namespace_for(*, feature_id: str, base_ref: str, contract: TestContract | None) -> str:
    """The one namespace every driver uses; a missing contract digests as ""."""
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: directory operands | yes | `.py` suffix rule + error message; declared-directory note string fixed in §2 | — |
| M2: one cache namespace | yes | `namespace_for` signature in §2; `""` for no contract | — |
| M3: cached union count | yes | one-line change, existing test asserts the string | — |
| M4: baseline + base ref | yes | PYTHONPATH order and prune removal fixed in §2; `_default_base_ref(header) -> str` | — |
| M5: doc | yes | two bullets in an existing section | — |

### Module 1: Directory operands
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/contract.py`, `.../test_scope/select.py`
- **Responsibility**: reject/flag/drop directory operands end to end.
- **Depends on**: existing code only.
- **Interface Skeleton**:
  ```python
  # modifies contract.py:209
  def _normalize_pytest(tests: Sequence[object], markers: Sequence[object]) -> RunnerContract:
      """Validate pytest operands and markers and return a normalized runner block.

      Raises:
          ValueError: If an operand or marker cannot safely be used by pytest, or an operand's
              file part is not a ``.py`` file (a directory or suite is never a contract operand).
      """
  # modifies select.py:115 (inside _declared_targets) — no signature change
  ```

### Module 2: One green-cache namespace
- **Path**: `.../test_scope/green_cache.py`, `packages/ai-parrot/src/parrot/sdd/scripts/select_tests.py`,
  `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py`
- **Responsibility**: a single namespace helper used by both drivers.
- **Depends on**: existing code only.
- **Interface Skeleton**:
  ```python
  # green_cache.py (new function after cache_namespace, verified: green_cache.py:38)
  def namespace_for(*, feature_id: str, base_ref: str, contract: TestContract | None) -> str:
      """Return ``cache_namespace`` for this feature/base/contract; ``contract=None`` digests as ``""``."""
  ```
  Call sites: select_tests.py:413, background.py:621-626 (currently passes the digest from
  `_index_runtime_metadata`; switch to the parsed contract or keep the digest but via the helper — the
  value must equal `namespace_for(...)` for the same inputs) and background.py:867-871.

### Module 3: Cached union count
- **Path**: `.../test_scope/report.py`
- **Responsibility**: count distinct cached targets in `render_markdown` (report.py:556).
- **Depends on**: none.

### Module 4: Baseline + base ref
- **Path**: `.../test_scope/baseline.py`, `packages/ai-parrot/src/parrot/sdd/scripts/select_tests.py`
- **Responsibility**: baseline imports from the baseline checkout; cleanup is local; null base_branch safe.
- **Depends on**: none.
- **Interface Skeleton**:
  ```python
  # select_tests.py (new helper; replaces the expression at select_tests.py:378)
  def _default_base_ref(index_header: Mapping[str, object]) -> str:
      """``origin/<base_branch>``; a missing, null or blank base_branch falls back to ``origin/dev``."""

  # baseline.py (new private helper used by _classify_group, verified: baseline.py:140)
  def _baseline_pythonpath(checkout: Path, src_dist: str) -> str:
      """``checkout/packages/<src_dist>/src`` first, then every other existing ``packages/*/src``, sorted."""
  ```

### Module 5: Documentation
- **Path**: `wiki/sdd-tooling/sdd/test-selection-validation-contract.md`
- **Responsibility**: depth-1 limit + correct cache file name.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_contract.py` — directory operand rejected | M1 | `_normalize_pytest(["packages/ai-parrot/tests/flows"], [])` raises `ValueError` |
| `test_check_task_graph.py` — directory contract operand | M1 | a header whose pytest target is a directory lints as `test-contract-malformed` naming the operand |
| `test_select.py` — declared directory dropped | M1 | `pytest <dir>` Validation Command yields no target and the note |
| `test_green_cache.py` — `namespace_for` | M2 | equals `cache_namespace(..., contract_digest="")` for None and `contract.digest` otherwise |
| `test_background_contract.py` — same namespace | M2 | supervisor namespace == `namespace_for` for a contract-less index |
| `test_report.py` — union count | M3 | two tasks with the same two cached targets render "2 target(s)" |
| `test_baseline.py` — PYTHONPATH + no prune | M4 | env starts with target dist src and includes the others; cleanup never invokes `worktree prune` |
| `test_select_tests_base_ref.py` (new) | M4 | `_default_base_ref({"base_branch": None})` == `origin/dev`; `"staging"` → `origin/staging` |

### Integration Tests
None beyond the files above.

### Validation Contract

tests:
- packages/ai-parrot/tests/flows/dev_loop/test_scope/test_contract.py
- packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select.py
- packages/ai-parrot/tests/flows/dev_loop/test_scope/test_select_contract_mode.py
- packages/ai-parrot/tests/flows/dev_loop/test_scope/test_green_cache.py
- packages/ai-parrot/tests/flows/dev_loop/test_scope/test_report.py
- packages/ai-parrot/tests/flows/dev_loop/test_scope/test_baseline.py
- packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_contract.py
- packages/ai-parrot/tests/sdd/test_select_tests_base_ref.py
- tests/sdd_scripts/test_check_task_graph.py
markers: none

---

## 5. Acceptance Criteria

- [ ] AC-1 `_normalize_pytest` raises `ValueError` for an operand whose file part does not end in `.py`; `.py` files and `file.py::node` are accepted unchanged.
- [ ] AC-2 `check_task_graph` reports `test-contract-malformed` (level `error`), message naming the operand, for an index header whose pytest target is a directory; `check_task_graph.py` itself is unchanged.
- [ ] AC-3 A declared `pytest <directory>` yields no target and the note `declared path is a directory, dropped: <operand>`.
- [ ] AC-4 `namespace_for(feature_id=f, base_ref=b, contract=None) == cache_namespace(feature_id=f, base_ref=b, contract_digest="")`; select_tests and the merge-tier site in background.py (`_plan_selection`) call it; the run-validation site keeps `_index_runtime_metadata`'s digest, which is already `contract.digest` or `""`, and a test pins that it equals `namespace_for` for a contract-less index. No `"none"` digest remains in select_tests.
- [ ] AC-5 `render_markdown` with two task records sharing the same two cached targets prints `cached (skipped, unchanged since green): 2 target(s)`.
- [ ] AC-6 `_classify_group`'s `PYTHONPATH` begins with `checkout/packages/<dist>/src` and contains every other existing `checkout/packages/*/src`; `remove_baseline_checkout` never runs `git worktree prune`.
- [ ] AC-7 `_default_base_ref` returns `origin/dev` for a missing, null or blank `base_branch`.
- [ ] AC-8 The wiki page states the depth-1 cache-key limit and names `parrot-test-scope-green.json`.
- [ ] AC-9 Every Validation Contract file passes; `ruff check` is clean on changed files.

---

## 6. Codebase Contract

Verified against `origin/dev` @ `aa91d76896`.

### Verified Imports
```python
from parrot.flows.dev_loop.test_scope import baseline, green_cache  # verified: sdd_coder/background.py:47
from .datatypes import GreenCacheEntry, ScopePlan, TestContract, TestTarget  # verified: test_scope/green_cache.py:19
from parrot.sdd.scripts import cache_test_contract, select_tests, test_report  # verified: tests/sdd/test_test_command_fallback.py:17
# select_tests imports the kernel path-dependently:
import test_scope.green_cache as green_cache  # verified: sdd/scripts/select_tests.py:411 (noqa PLC0415)
```

### Existing Class Signatures
```python
# test_scope/contract.py
def is_broad_pytest(argv: Sequence[str], *, worktree: Path | None = None) -> bool:  # line 163
def _normalize_pytest(tests: Sequence[object], markers: Sequence[object]) -> RunnerContract:  # line 209
# test_scope/select.py
def _declared_targets(declared, notes, *, worktree, registry=None, tier="task") -> list[TestTarget]:  # ~line 95
def plan_tests(*, worktree, changed_files, tier, declared=(), contract=None, policy=None, registry=None) -> ScopePlan:  # ~line 140
# test_scope/green_cache.py
CACHE_FILENAME: str = "parrot-test-scope-green.json"  # line 31
def cache_namespace(*, feature_id: str, base_ref: str, contract_digest: str) -> str:  # line 38
def filter_cached(worktree, plan, *, namespace, contract=None) -> ScopePlan:  # line 168
# test_scope/report.py
def append_cached(feature_id, task_id, targets, *, head_sha, base_ref, tier, source) -> Path | None:  # line 368
def render_markdown(...):  # line 491; cached count at line 556
# test_scope/baseline.py
def remove_baseline_checkout(worktree: Path, path: Path) -> None:  # line 125
def _classify_group(checkout: Path, dist: str, nodeids: list[str], timeout_s: int, tmp_dir: Path) -> dict[str, BaselineVerdict]:  # line 140
# sdd_coder/background.py
def _base_ref_from_header(header: dict[str, object]) -> str:  # line 916 (staticmethod; already null-safe)
def _index_runtime_metadata(cls, index_path: Optional[Path]) -> tuple[str, str]:  # line 924 (returns "" digest when no contract)
# sdd/scripts/select_tests.py
def main(argv: list[str] | None = None) -> int:  # line 355; base_ref at 378; namespace at 413-416
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `namespace_for` | `cache_namespace` | call | `green_cache.py:38` |
| select_tests | `namespace_for` | call (replaces) | `select_tests.py:413` |
| background | `namespace_for` | call (replaces, 2 sites) | `background.py:623`, `background.py:868` |

### Does NOT Exist (Anti-Hallucination)
- ~~`docs/sdd/test-selection-validation-contract.md`~~ — gone; the doc is `wiki/sdd-tooling/sdd/test-selection-validation-contract.md`.
- ~~`green_cache.namespace_for`~~ — created by M2, does not exist yet.
- ~~`select_tests._default_base_ref`~~ — created by M4.
- ~~`.sdd_test_cache.json`~~ — not the cache file name.

### Edit Sites (Blueprint Anchors)

Verified against: `aa91d76896`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/contract.py` | MODIFY | `            or is_broad_pytest(["pytest", operand])` | `contract.py:225` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py` | MODIFY | `        for operand in adapter.operands(argv) or ():` | `select.py:115` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/green_cache.py` | MODIFY | `def cache_namespace(*, feature_id: str, base_ref: str, contract_digest: str) -> str:` | `green_cache.py:38` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/select_tests.py` | MODIFY | `        namespace = green_cache.cache_namespace(` | `select_tests.py:413` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/select_tests.py` | MODIFY | `    base_ref = args.base or f"origin/{index_header.get('base_branch', 'dev')}"` | `select_tests.py:378` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` | MODIFY | `            namespace = await asyncio.to_thread(` + next line `                green_cache.cache_namespace,` + `                feature_id=feature_id,` | `background.py:622-624`, `background.py:867-869` | 2 (both sites change) |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py` | MODIFY | `    cached = sum(len(record.cached) for record in records.values())` | `report.py:556` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/baseline.py` | MODIFY | `    env["PYTHONPATH"] = str(checkout / "packages" / src_dist / "src")` | `baseline.py:165` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/baseline.py` | MODIFY | `        _git(worktree, "worktree", "prune")` | `baseline.py:131` | 1 |
| `wiki/sdd-tooling/sdd/test-selection-validation-contract.md` | MODIFY | `- **Cached targets**:` | `test-selection-validation-contract.md:45` | 1 |
| `packages/ai-parrot/tests/sdd/test_select_tests_base_ref.py` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Stdlib only inside `test_scope/` (the kernel is loaded path-dependently by `select_tests`).
- Notes are plain strings appended to the `notes` list, as the surrounding code does.
- `background.py` calls kernel functions via `asyncio.to_thread`; keep that for `namespace_for`.

### Known Risks / Gotchas
- **Parallel FEAT-829** (`test-scope-planner-fixes`, `issue:a3aebc40ef48` + `issue:3ae0b2ae0ef4`) edits
  `select.py` (`_declared_targets`) and the parrot-e2e adapter at the same time. M1's
  `select.py` edits are confined to the pytest branch (a directory check on an operand) and the
  missing-on-disk note; whichever feature lands second rebases on the other.
- `issue:55ad6c71c101` (claimed elsewhere) concerns a `conftest.py` contract operand — `conftest.py`
  ends in `.py`, so M1's rule neither fixes nor conflicts with it.
- A CLI-written cache under the old `"none"` digest is invalidated once after M2 — expected.
- Removing the prune leaves stale admin data only if `worktree remove --force` fails, which is already
  logged; never prune globally from a shared checkout.

### External Dependencies
None.

---

## Consequences

<!-- decision-audit: input_digest=sha256:d2aaf18cbefa8fa6b9fea4da52519fcddd365eefb2c12d281d81816b975c333c evaluation_digest=sha256:26055617434993522b7317996c7b8f9ee69f6282e488cdff3d2a60258fd1dad4 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /tmp/claude-1000/-home-jesuslara-proyectos-ai-parrot/971bcae5-141d-4da7-b937-120d4aeea422/scratchpad/dev-clone/sdd/specs/test-scope-report-fixes.spec.md; message: no fenced yaml block under '## Decisions'

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, sdd-tooling, skills, tools
- Unmapped tags: baseline, green-cache, ledger-fix, test-scope
- Targets resolved: 0/0
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "bots",
      "clients",
      "config",
      "flows",
      "knowledge-graphindex",
      "knowledge-pageindex",
      "knowledge-wiki",
      "memory",
      "sdd-tooling",
      "skills",
      "tools"
    ],
    "targets_resolved": 0,
    "targets_total": 0,
    "unmapped_tags": [
      "baseline",
      "green-cache",
      "ledger-fix",
      "test-scope"
    ]
  },
  "diagnostics": [
    {
      "code": "SPEC_BLOCK_MISSING",
      "decision_id": null,
      "message": "no fenced yaml block under '## Decisions'",
      "path": "/tmp/claude-1000/-home-jesuslara-proyectos-ai-parrot/971bcae5-141d-4da7-b937-120d4aeea422/scratchpad/dev-clone/sdd/specs/test-scope-report-fixes.spec.md"
    }
  ],
  "evaluation_digest": "sha256:26055617434993522b7317996c7b8f9ee69f6282e488cdff3d2a60258fd1dad4",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:d2aaf18cbefa8fa6b9fea4da52519fcddd365eefb2c12d281d81816b975c333c",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {
      "adr:doc:171b17ccd26bdbd2d71040746b22371a335d364d": "b22c79daae2a187f2091ea23449825e8769e2c07",
      "adr:doc:34394c36f5bf140678b8e17d43c3628e3d2c1440": "3fa15352d0e9ed972bd5de7ac1fd60e06906e60b",
      "adr:doc:666d8f740c695673063f76777db7b7b0e9d95a2e": "47f1bebe56724843f6c0981f67bbba72917b4b0b",
      "adr:doc:87781d348dff80cbfb25c253989a8940badd08d1": "49458f64f4bb614a9ff42750b53d9caa806f81a0",
      "adr:doc:89e808b78adee5c727e047ac239817bfd29e5cfe": "9feeb90ec52cb53395d978a3b946323a7b9072ab",
      "adr:doc:96dabb33251cd210186d7ab5c456ded102a4b025": "b537050f62f77a85b651af8c2595f4dc7fd4cebe",
      "adr:doc:c3c29b415ba46e730ee37c6fc520914a1905d022": "0cd9cc9f082b9d988da023e3886d310f8eed8eae",
      "adr:doc:c6b0e17a26d4b1ae2be8569a33db9a3aeedc0fbd": "804496ec336c99570df5502580ff980a38f56bfc",
      "adr:doc:e7c5ae770b06db3b35cdd4cba93001a58bfa7bef": "394f4656c71618a256427d81350fdc32335fa791"
    },
    "rules_version": 1,
    "structural_revision": "sha256:b11fe8e33d80455017c18de7c66615b790b28eae29c88d3cc6defc398db393fb",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions

None.

---

## 9. Design Research Cross-Check

Status: skipped (no accepted exploration document — spec authored by /sdd-fix from a ledger issue).

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

---

## 10. Documentation

- **Policy**: `required`
- **Pages**:
  - `wiki/sdd-tooling/sdd/test-selection-validation-contract.md` — update: depth-1 cache-key limit, real cache file name.
- **API modules**:
  - `parrot.flows.dev_loop.test_scope.green_cache`

---

## Worktree Strategy

One feature worktree `feat-FEAT-830-test-scope-report-fixes` off `origin/dev`.

- Module graph: no edges — M1–M5 are independent and may run concurrently.
- Shared files: `select_tests.py` (M2 + M4); `select.py` is M1 only — M2 and M4 tasks are
  serialized or merged into one task.
- Exclusive resources: none.
- Cross-feature: FEAT-829 touches `select.py`; no merge order required.

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-07 | Jesus Lara | Created by /sdd-fix from `issue:bfb29d4ffe49` (fixgroup:c35e7383e48a); `issue:3ae0b2ae0ef4` handed to FEAT-829 |
| 0.2 | 2026-11-07 | Jesus Lara | /sdd-task: dropped the new lint code and the `plan_tests` directory note — every contract reader re-normalizes, so a directory surfaces as `test-contract-malformed`; both would be dead code |
