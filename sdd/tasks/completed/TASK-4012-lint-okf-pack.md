# TASK-4012: OKF rule pack + lint_knowledge_base parity port

**Feature**: FEAT-625 — wikitoolkit lint
**Spec**: `sdd/specs/wikitoolkit-lint.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M
**Depends-on**: TASK-4009
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. Generalize OKF lint onto the engine without changing its public output (AC11).

---

## Scope

- Create `lint/packs/okf.py` with `okf_findings(graph, tree, content_store, stale_days=90) -> list[Finding]` (pure) — move the four check bodies there.
- Rewrite `okf/lint.py::lint_knowledge_base` to build its existing `LintReport` from `okf_findings()` (kind mapping: orphan/broken_link/missing_concept/stale ↔ rule ids `okf-orphan`/`okf-broken-link`/`okf-missing-concept`/`okf-stale`).
- Keep `LintFinding`/`LintReport` in okf/lint.py untouched.

**NOT in scope**: Plane rules; the wiki adapter.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/lint/packs/okf.py` | CREATE | okf_findings |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/lint.py` | MODIFY | Delegate to okf_findings |
| `packages/ai-parrot/tests/knowledge/lint/test_okf_pack.py` | CREATE | Parity tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ 350d206f0 (2026-10-03). Re-verify before coding.

### Verified Imports
```python
from parrot.knowledge.lint.models import Finding, FixResult, LintOptions, LintReport, Severity  # created by TASK-4009
from parrot.knowledge.lint.rule import LintRule, make_fingerprint  # created by TASK-4009
from parrot.knowledge.lint.context import LintContext  # created by TASK-4009
from parrot.knowledge.pageindex.okf.lint import LintFinding, LintReport, lint_knowledge_base  # verified: okf/lint.py:46, :63, :91
```

### Existing Signatures to Use
```python
# pageindex/okf/lint.py
class LintFinding(BaseModel):  # :46  kind: Literal["orphan","broken_link","missing_concept","stale"]; concept_id; detail; severity: Literal["warning","error"]="warning"
class LintReport(BaseModel):   # :63  tree_name, orphans, broken_links, missing_concepts, stale_claims, total_findings, total_concepts
def lint_knowledge_base(graph: KnowledgeGraph, tree: dict, content_store: NodeContentStore, stale_days: int = 90) -> LintReport:  # :91
# callers: pageindex/okf/tools.py:300; tests packages/ai-parrot/tests/knowledge/pageindex/test_okf_lint.py, test_okf_integration.py
```

### Does NOT Exist
- ~~changing `LintFinding`/`LintReport` fields~~ — forbidden (AC11)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/lint/packs/okf.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/okf/lint.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/lint/test_okf_pack.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/okf/lint.py#lint_knowledge_base",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/okf/lint.py#LintFinding",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/okf/lint.py#LintReport"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Async throughout; never block the event loop (file I/O via `asyncio.to_thread`).
- Pydantic v2; `self.logger` / `logging.getLogger(__name__)`; Google docstrings; 120 cols.
- Writes only through store/export APIs — never raw SQL from a rule; never delete pages or edges (spec AC2).

### References in Codebase
- Spec `sdd/specs/wikitoolkit-lint.spec.md` §2–§7 (rule ids, severities, decisions are fixed there).

---

## Implementation Blueprint

### Steps (in order)
1. Copy the four check bodies into `okf_findings`, emitting `Finding(data={'kind': ..., 'concept_id': ...})` — *why*: the round-trip back to LintFinding needs the original kind.
2. Make `lint_knowledge_base` map Findings back into its report lists in the SAME order — *why*: existing tests assert exact output.
3. Import `okf_findings` inside the function body — *why*: avoid a pageindex→lint import cycle at module load.

### `packages/ai-parrot/src/parrot/knowledge/lint/packs/okf.py` (CREATE)
```python
"""OKF rule pack: the four classic knowledge-base checks (FEAT-625)."""
from __future__ import annotations

from typing import Any

from parrot.knowledge.lint.models import Finding
from parrot.knowledge.lint.rule import make_fingerprint

KIND_TO_RULE: dict[str, str] = {
    "orphan": "okf-orphan",
    "broken_link": "okf-broken-link",
    "missing_concept": "okf-missing-concept",
    "stale": "okf-stale",
}


def okf_findings(graph: Any, tree: dict, content_store: Any, stale_days: int = 90) -> list[Finding]:
    """Run the four OKF checks and return engine Findings (pure, no I/O writes).

    Each Finding carries ``data={"kind": <okf kind>, "concept_id": <id>}`` so
    :func:`lint_knowledge_base` can rebuild its legacy report exactly.
    """
    # FILL IN: move the bodies of checks 1-4 from pageindex/okf/lint.py:91+ here unchanged,
    #          emitting Finding(rule_id=KIND_TO_RULE[kind], severity=<same as today>, subjects=[cid],
    #          message=<same detail>, fingerprint=make_fingerprint(rule_id, [cid]), data={...})
    raise NotImplementedError
```

### `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/lint.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def lint_knowledge_base(' pageindex/okf/lint.py)
# REPLACE the BODY of `def lint_knowledge_base(` (verified: pageindex/okf/lint.py:91); signature + docstring unchanged
    from parrot.knowledge.lint.packs.okf import okf_findings

    # FILL IN: keep the tree_name / total_concepts computation as today;
    #          for f in okf_findings(graph, tree, content_store, stale_days): append
    #          LintFinding(kind=f.data["kind"], concept_id=f.data["concept_id"], detail=f.message, severity=f.severity)
    #          into the matching list; set total_findings as today
```

**Why this shape**: AC11 demands byte-identical OKF output; the pack only relocates logic. The function-local import avoids an import cycle (lint.packs → pageindex at load time is fine, the reverse at module scope is not needed).

### FILL IN checklist
- [ ] relocated check bodies
- [ ] legacy report reassembly order

---

## Acceptance Criteria

- [ ] `test_okf_lint.py` and `test_okf_integration.py` pass unchanged
- [ ] `okf_findings` returns engine Findings with stable fingerprints
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/lint/test_okf_pack.py -v`
- [ ] No lint errors: `ruff check` on the touched files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/lint/test_okf_pack.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_okf_lint.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_okf_integration.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/lint/test_okf_pack.py
def test_okf_parity():
    # FILL IN: reuse the fixtures of tests/knowledge/pageindex/test_okf_lint.py; assert
    #          {(f.data["kind"], f.data["concept_id"]) for f in okf_findings(...)} matches lint_knowledge_base(...) lists
    ...
```

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug wikitoolkit-lint --feature-id FEAT-625`), never on `dev`.
2. Check every Depends-on task is `done` in `sdd/tasks/index/wikitoolkit-lint.json`.
3. Verify the Codebase Contract; fix it first if stale.
4. Implement from the blueprint; complete every `# FILL IN:`; never change fixed signatures/paths.
5. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
6. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4012 wikitoolkit-lint verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none

## Completion Note

Implemented by sonnet (native), 1 attempt; broken_link findings use subjects=[source,target,rel] for per-edge fingerprints (data.concept_id remains source). Merged via coder_merge. Verified: lint + store + OKF-related tests, 98 passed (worktree, scoped). Closed via close_task.sh.
