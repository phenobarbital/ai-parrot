# TASK-5375: optimizer_eval harness and tuned_target rule

**Feature**: FEAT-846 — PageIndex Tree Optimizer
**Spec**: `sdd/specs/pageindex-tree-optimizer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5371
**Assigned-to**: unassigned

---

## Context

Spec Module 6 harness (G13, AC-17). Mirrors `layout_eval.py`. `TreeMetrics` holds numbers and the file-stem label only —
never a node title. The tuning RUN is TASK-5376, not this task.

## Scope

- Create `optimizer_eval.py` with the spec §3 M6 skeleton; `python -m parrot.knowledge.pageindex.optimizer_eval <pdf|dir>...`
  writes `optimizer_eval-<ts>.json` under `artifacts/logs/optimizer_eval/` and prints the path and `tuned_target`.
- Tests `test_optimizer_eval_report`, `test_tuned_target_bounds`.

**NOT in scope**: running the corpus or changing defaults.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_eval.py` | CREATE | EvalSettings, TreeMetrics, EvalReport, evaluate_*, tuned_target, main |
| `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_eval.py` | CREATE | test_optimizer_eval_report, test_tuned_target_bounds |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.pageindex import PageIndexToolkit
from parrot.knowledge.pageindex.optimizer import OptimizerSettings  # TASK-5364
```

### Existing Signatures to Use
```python
# layout_eval.py:25-59 — the shape to mirror (settings model, per-PDF metrics, corpus report, DEFAULT_OUT, main)
# toolkit.py import_pdf(tree_name, pdf_path, parent_node_id=None, with_summaries=True, with_doc_description=False,
#                       doc_id=None, structure_mode="auto") :1824
# fixture: packages/ai-parrot/tests/knowledge/pageindex/fixtures/arxiv_2408_09869.pdf
```

### Does NOT Exist
- ~~`optimizer_eval`~~ — new here; ~~any node title in the report~~ — forbidden (AICPA PDF is non-redistributable)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_eval.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_eval.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.import_pdf"
  ]
}
```

---

## Implementation Notes

- `suggested_target_leaf_tokens` = p75 of post-layout leaf tokens rounded to 100, `None` with fewer than three trees.
- `tuned_target`: suggestion when not None and in `[2*min_leaf_tokens, 2*target_leaf_tokens]`, else None.
- `llm_heading_splits` = count of `report.expanded` with `source == "llm"`.

---

## Implementation Blueprint

### `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_eval.py` (CREATE)
```python
"""Evaluation harness for the PageIndex tree optimizer (FEAT-846 M6). Numbers only, never node titles."""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from parrot.knowledge.pageindex.optimizer import OptimizerSettings

logger = logging.getLogger(__name__)
DEFAULT_OUT = Path("artifacts/logs/optimizer_eval")


class EvalSettings(BaseModel):
    target_leaf_tokens: int
    min_leaf_tokens: int
    llm: Optional[str] = None


class TreeMetrics(BaseModel):
    # FILL IN: every field from spec §3 M6 TreeMetrics, same names/types (incl. llm_heading_splits)
    ...


class EvalReport(BaseModel):
    created_at: str
    settings: EvalSettings
    results: list[TreeMetrics]
    suggested_target_leaf_tokens: Optional[int]


async def evaluate_pdf(pdf: Path, *, settings: EvalSettings, storage_dir: Path) -> TreeMetrics:
    """Import ``pdf`` into ``storage_dir`` (optimize_on_import=False), then optimize(apply=True); measure."""
    # FILL IN


async def evaluate_corpus(pdfs: list[Path], *, settings: EvalSettings, out_dir: Path = DEFAULT_OUT) -> EvalReport:
    """Writes ``optimizer_eval-<ts>.json``; suggested target = p75 of post-layout leaf tokens rounded to 100."""
    # FILL IN


def tuned_target(report: EvalReport, current: OptimizerSettings) -> Optional[int]:
    """Suggestion inside [2*min_leaf_tokens, 2*target_leaf_tokens], else None."""
    s = report.suggested_target_leaf_tokens
    if s is None:
        return None
    return s if 2 * current.min_leaf_tokens <= s <= 2 * current.target_leaf_tokens else None


def main(argv: Optional[list[str]] = None) -> int:
    """``python -m parrot.knowledge.pageindex.optimizer_eval <pdf|dir>...``"""
    # FILL IN: expand dirs to *.pdf; tmp storage dir; asyncio.run(evaluate_corpus(...)); print path + tuned_target
    return 0


if __name__ == "__main__":
    sys.exit(main())
```
**Why**: `tuned_target` is spec-exact so it is complete; measuring needs judgement.

### `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_eval.py` (CREATE)
```python
def test_optimizer_eval_report(): ...   # FILL IN: arxiv fixture, fake adapter; no node title in JSON
def test_tuned_target_bounds(): ...     # FILL IN: inside / below / above / fewer than three trees
```

---

## Acceptance Criteria

- [ ] AC-17: module entry point writes the JSON report with the M6 metrics (numbers + file-stem labels only) and prints `tuned_target`.


## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_eval.py -q`

---

## Test Specification

Spec §4 rows `test_optimizer_eval_report`, `test_tuned_target_bounds`.

---

## Agent Instructions

1. Read the spec sections named in Context, then this task's Codebase Contract — use only the listed imports.
2. Re-run `grep -c` on every MODIFY anchor before editing; a count that differs from the blueprint means drift — stop and report.
3. Write the blueprint blocks, then resolve every `FILL IN` within its stated bound.
4. Run `ruff check --fix` on the touched files and the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
5. Commit only the files listed above: `feat(pageindex-tree-optimizer): TASK-5375 — optimizer_eval harness and tuned_target rule`.

---

## Completion Note

*(Agent fills this in when done)*
