---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [flows, sdd, ledger-fix]
docs:
  policy: none
---

# Feature Specification: `coder_task_context` and `coder_delivery_report` Find Brief Indexes

**Feature ID**: FEAT-871
**Date**: 2026-11-10
**Author**: /sdd-fix (agent:sdd-fix:9824d687)
**Status**: approved
**Target version**: 2.1.3

**Discovered-from**: `issue:36d572b7feae`

> Ledger-driven fix. Drains the `/sdd-fix` group `fixgroup:01f249557fd5` (`issue:36d572b7feae`, minor bug), a
> follow-up found while implementing FEAT-869 (PR #2078, merged into `dev`) and left out of it because
> `issue:b9ff30bf709e` scoped only the review-artifact producers. No brainstorm or proposal: the issue body is the
> requirement.

---

## 1. Motivation & Business Requirements

### Problem Statement

`SddCoderEngine.task_context` and `SddCoderEngine.delivery_report` (the `coder_task_context` and
`coder_delivery_report` tools) resolve the feature to an index path, then hand
`feature=Path(ctx.index_path).stem` to `inspection.task_context` / `inspection.delivery_report`. Those functions
find the index again through `resolve_index_path(worktree, feature)`, which looks for
`sdd/tasks/index/<feature>.json` and then `sdd/briefs/<feature>.index.json`.

For a per-spec index the stem is the slug, so the lookup succeeds. For a brief index
`sdd/briefs/<slug>.index.json` the stem is `<slug>.index`. `resolve_index_path` then looks for
`sdd/tasks/index/<slug>.index.json` and `sdd/briefs/<slug>.index.index.json`, finds neither, and both tools fail
with `CoderFailure("index_unreadable", "per-spec index unreadable or missing for feature '<slug>.index' ...")`.
So no brief task can be inspected through these tools.

Reproduced on `origin/dev` @ `432c69b706`: with the test sandbox's index moved to `sdd/briefs/demo.index.json`,
`begin_execution` and `prepare_native` succeed (they use the resolved `ctx.index_path`), while `task_context` and
`delivery_report` both raise `index_unreadable` for `'demo.index'`.

FEAT-869 added `engine._index_slug(index_path)`, the inverse of `resolve_index_path`: it strips `.index.json` from a
brief index name and returns the stem of a per-spec index. It is the slug these two calls need.

### Goals
- `task_context` and `delivery_report` pass `_index_slug(ctx.index_path)` to `inspection`, so both work for brief
  indexes and keep working for per-spec indexes.
- Engine-level tests cover both tools on a brief index; both fail without the fix.

### Non-Goals (explicitly out of scope)
- `inspection.py`: unchanged; it already resolves a correct slug for both index kinds.
- `nodes/planner.py:327` (`Path(planner_out.task_index_path).stem`): the planner's index comes from `/sdd-task`,
  always a per-spec index; outside this issue.
- No change to `_index_slug`, `resolve_index_path`, the tool schemas or the snapshot shapes.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:4d131d182d54f428e28f41870ab2d7d9cfa6d9909d3d7e62971addaca80bd0ef evaluation_digest=sha256:71bb1c3280f03a03e48d3bbe5ce8c2c14cf927617c238ccb53341f924514856c rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

One source file, one test file, no new module. In `engine.py`, replace both
`feature=Path(ctx.index_path).stem,` arguments (in `task_context` and `delivery_report`) with
`feature=_index_slug(ctx.index_path),`. `_index_slug` is a module-level function in the same file; no import
changes.

### Integration Points
| Existing component | Interaction |
|---|---|
| `toolkit` → `SddCoderEngine.task_context` / `.delivery_report` | unchanged signatures; brief features now resolve |
| `engine._index_slug` (FEAT-869) | reused, unchanged |
| `inspection.task_context` / `.delivery_report` → `resolve_index_path` | unchanged; now receive the slug it expects |

## 3. Module Breakdown

### Module 1: inspection tools pass the index slug
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py`
- **Responsibility**: the overview above.
- **Interface Skeleton**:
```python
            return await inspection.task_context(
                feature=_index_slug(ctx.index_path),
                ...
            )
            ...
            return await inspection.delivery_report(
                feature=_index_slug(ctx.index_path),
                ...
            )
```
- **Tests**: `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_brief_index_resolution.py`.

### Delegation-eligible modules
| Module | Eligible | Decided patterns / contracts |
|---|---|---|
| 1 | no | two-line edit; implemented in the `/sdd-fix` session |

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_engine_task_context_reads_brief_index` | 1 | `git_sandbox_feature`; `git mv sdd/tasks/index/demo.json sdd/briefs/demo.index.json` and commit; `begin_execution`; `task_context("demo", …, "TASK-0001", …)` returns `feature == "demo"`, `index_path == "sdd/briefs/demo.index.json"`, `status == "pending"`; fails on `dev` with `index_unreadable` |
| `test_engine_delivery_report_reads_brief_index` | 1 | same setup plus `prepare_native(… "TASK-0001" …)`; `delivery_report` returns `feature == "demo"`, `task_id == "TASK-0001"` and `branch == prep.branch`; fails on `dev` with `index_unreadable` |
| `test_index_slug_inverts_resolve_index_path` | 1 | existing (`test_feedback.py`); unchanged |

### Validation Contract

tests:
- packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_brief_index_resolution.py
- packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_feedback.py
markers: none

## 5. Acceptance Criteria
- [ ] `task_context` and `delivery_report` pass `_index_slug(ctx.index_path)` as `feature` to `inspection`; no
      `Path(ctx.index_path).stem` remains in `engine.py`.
- [ ] For a brief index `sdd/briefs/<slug>.index.json`, `task_context` returns a snapshot whose `index_path` is that
      file, and `delivery_report` returns the execution's attempt; neither raises `index_unreadable`.
- [ ] Per-spec indexes behave as before (`_index_slug` returns their stem).
- [ ] The two new tests exist, fail without the fix and pass with it.
- [ ] Both Validation Contract files pass; `ruff check` is clean on the changed files.

## 6. Codebase Contract

Verified against `origin/dev` @ `432c69b706`.

### Verified Imports
```python
from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine  # verified: test_brief_index_resolution.py:13
from parrot.flows.dev_loop.sdd_coder.models import RosterConfig, RosterSeat  # verified: test_brief_index_resolution.py:14
from .conftest import _run_git  # verified: conftest.py:113; test_feedback.py imports it locally inside a test
```

### Existing Signatures
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py
def _index_slug(index_path: str) -> str  # :188; brief index -> name minus ".index.json", else Path.stem
async def SddCoderEngine.begin_execution(...)  # :669
async def SddCoderEngine.task_context(self, feature: str, worktree: str, task_id: str, execution_id: str) -> Dict[str, Any]  # :1733; feature=Path(ctx.index_path).stem :1768
async def SddCoderEngine.delivery_report(self, feature: str, worktree: str, task_id: str, execution_id: str) -> Dict[str, Any]  # :1781; feature=Path(ctx.index_path).stem :1820
async def SddCoderEngine._resolve_feature(self, feature: str, worktree: str) -> _FeatureCtx  # :1833
async def SddCoderEngine.prepare_native(...)  # :2437; the result carries task_id, branch, attempt_uid
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/inspection.py
def _load_scheduler(worktree: Path, feature: str) -> TaskScheduler  # :108; FileNotFoundError when the index is missing
async def task_context(*, feature: str, worktree: Path, task_id: str, execution_id: str, store: ExecutionEvidenceStore) -> dict[str, object]  # :141; "index_path" key :192
async def delivery_report(*, feature: str, worktree: Path, task_id: str, execution_id: str, store: ExecutionEvidenceStore) -> dict[str, object]  # :251
# packages/ai-parrot/tests/flows/dev_loop/sdd_coder/conftest.py
FEATURE_SLUG = "demo"  # :78; index file sdd/tasks/index/demo.json
async def _run_git(*args: str, cwd: Path) -> None  # :113
async def git_sandbox_feature(tmp_path)  # :141; returns (worktree, feature_branch, base_path, index_path)
def noop_probe() -> RosterProbe  # :210 (fixture)
```

### Does NOT Exist
- No engine-level test of `task_context` or `delivery_report` (only `inspection`-level tests in
  `test_inspection_reports.py` and schema tests in `test_toolkit.py`).
- No brief-index coverage for either tool.

### Edit Sites (Blueprint Anchors)
| File | Anchor | Line | Count | Action |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | `                feature=Path(ctx.index_path).stem,` | 1768, 1820 | 2 | MODIFY (both) |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_brief_index_resolution.py` | end of file | 130 | 1 | MODIFY (new helper + two tests) |

## 7. Implementation Notes & Constraints
- The test helper creates `sdd/briefs/` before `git mv` and commits the move: `begin_execution` and
  `prepare_native` work from the committed tree.
- Use distinct execution ids per test (the sandbox shares no state, but ids must be valid UUIDs).
- Run the tests in the worktree with `PYTHONPATH=packages/ai-parrot/src`.
- Ledger linkage: `issue:36d572b7feae`.

### Known Risks / Gotchas
- The anchor appears twice; replace both, and check that no `Path(ctx.index_path).stem` remains.
- `delivery_report` needs an execution-owned attempt branch, so its test calls `prepare_native` first; without it
  the fixed code raises `branch_not_found`, not `index_unreadable`.

## Worktree Strategy
One feature worktree, one module, one task. No shared files, no exclusive resources, no cross-feature dependency:
FEAT-869, which last touched `engine.py`, is merged into `dev`.

## Decisions

## Decision Waivers

## Consequences

<!-- decision-audit: input_digest=sha256:4d131d182d54f428e28f41870ab2d7d9cfa6d9909d3d7e62971addaca80bd0ef evaluation_digest=sha256:71bb1c3280f03a03e48d3bbe5ce8c2c14cf927617c238ccb53341f924514856c rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /home/jesuslara/proyectos/ai-parrot/sdd/specs/sdd-coder-engine-fixes-5.spec.md; message: no fenced yaml block under '## Decisions'

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, sdd-tooling, skills, tools
- Unmapped tags: ledger-fix
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
      "ledger-fix"
    ]
  },
  "diagnostics": [
    {
      "code": "SPEC_BLOCK_MISSING",
      "decision_id": null,
      "message": "no fenced yaml block under '## Decisions'",
      "path": "/home/jesuslara/proyectos/ai-parrot/sdd/specs/sdd-coder-engine-fixes-5.spec.md"
    }
  ],
  "evaluation_digest": "sha256:71bb1c3280f03a03e48d3bbe5ce8c2c14cf927617c238ccb53341f924514856c",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:4d131d182d54f428e28f41870ab2d7d9cfa6d9909d3d7e62971addaca80bd0ef",
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
- [x] Fix in `engine.py` or make `inspection` accept an index path? — *Resolved in /sdd-fix research*: `engine.py`,
      as the issue specifies; `inspection`'s slug contract matches `resolve_index_path` and stays unchanged.

## 9. Design Research Cross-Check
Status: skipped (no accepted exploration document)

## 10. Documentation
None: internal fix; no wiki page documents these tools' index lookup.

## Revision History
| Date | Change |
|---|---|
| 2026-11-10 | Initial spec from `/sdd-fix` group `fixgroup:01f249557fd5` |
