# TASK-5374: `parrot pageindex optimize` CLI

**Feature**: FEAT-846 — PageIndex Tree Optimizer
**Spec**: `sdd/specs/pageindex-tree-optimizer.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5373
**Assigned-to**: unassigned

---

## Context

Spec Module 5, CLI half: `parrot pageindex optimize TREE --storage-dir DIR [--node ID] [--apply] [--llm SPEC]
[--target-tokens N] [--json]` for any storage directory (the repository trees the MCP template serves).

## Scope

- New `knowledge/pageindex/cli.py` with click group `pageindex` and command `optimize`.
- Register `"pageindex": "parrot.knowledge.pageindex.cli"` after the `bookstore` entry.
- Extend the test file with the CLI half (CliRunner).

**NOT in scope**: other subcommands.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/cli.py` | CREATE | click group `pageindex` with `optimize` |
| `packages/ai-parrot/src/parrot/cli/__init__.py` | MODIFY | lazy-registry entry |
| `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_bookstore.py` | MODIFY | parrot pageindex optimize half |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.pageindex import PageIndexToolkit  # __init__.py
```

### Existing Signatures to Use
```python
# cli/__init__.py:176  "bookstore": "parrot.knowledge.bookstore.cli",  (lazy registry dict)
# cli/__init__.py:98-99 attr_name = cmd_name.replace("-", "_"); getattr(mod, attr_name) — the module must expose `pageindex`
# toolkit.py PageIndexToolkit(adapter=None, storage_dir=None, ...); `llm_client=` keyword builds an adapter (:147-178)
```

### Does NOT Exist
- ~~`parrot pageindex`~~ / ~~`knowledge/pageindex/cli.py`~~ — new here

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/cli.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/cli/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_bookstore.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit"
  ]
}
```

---

## Implementation Notes

- `--llm provider:model` → construct the toolkit with an LLM; without it, `adapter=None` (report says
  `skipped (no model)`). FILL IN how `--llm` is resolved by mirroring `bookstore add --llm` (read cli.py :102-155).

---

## Implementation Blueprint

### `packages/ai-parrot/src/parrot/knowledge/pageindex/cli.py` (CREATE)
```python
"""``parrot pageindex`` command group (FEAT-846)."""
from __future__ import annotations

import asyncio
import json
from typing import Optional

import click


@click.group()
def pageindex() -> None:
    """PageIndex trees (optimize, inspect)."""


@pageindex.command("optimize")
@click.argument("tree")
@click.option("--storage-dir", required=True)
@click.option("--node", default=None)
@click.option("--apply", is_flag=True)
@click.option("--llm", default=None, help="provider:model; default none")
@click.option("--target-tokens", type=int, default=None)
@click.option("--json", "as_json", is_flag=True)
def optimize(tree: str, storage_dir: str, node: Optional[str], apply: bool, llm: Optional[str],
             target_tokens: Optional[int], as_json: bool) -> None:
    """Dry-run (default) or apply the optimizer on TREE in STORAGE_DIR."""
    from parrot.knowledge.pageindex import PageIndexToolkit
    # FILL IN: toolkit construction (llm optional); report = asyncio.run(toolkit.optimize(...)); print JSON or summary
```

### `packages/ai-parrot/src/parrot/cli/__init__.py` (MODIFY)
```python
# AFTER `    "bookstore": "parrot.knowledge.bookstore.cli",` (cli/__init__.py:176; occurrences: 1)
    "pageindex": "parrot.knowledge.pageindex.cli",
```

### `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_bookstore.py` (MODIFY)
```python
def test_parrot_pageindex_optimize_cli(): ...   # FILL IN: CliRunner over a tmp storage dir; report printed
```

---

## Acceptance Criteria

- [ ] `parrot pageindex optimize` prints a report (dry run) and publishes with `--apply` (spec §4 `test_optimize_book_and_cli`).


## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_bookstore.py -q`

---

## Test Specification

CLI half of spec §4 `test_optimize_book_and_cli`.

---

## Agent Instructions

1. Read the spec sections named in Context, then this task's Codebase Contract — use only the listed imports.
2. Re-run `grep -c` on every MODIFY anchor before editing; a count that differs from the blueprint means drift — stop and report.
3. Write the blueprint blocks, then resolve every `FILL IN` within its stated bound.
4. Run `ruff check --fix` on the touched files and the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
5. Commit only the files listed above: `feat(pageindex-tree-optimizer): TASK-5374 — `parrot pageindex optimize` CLI`.

---

## Completion Note

**Completed**: 2026-11-09 | **Implementation commit**: 690063133d

Delivered via sdd-coder pool (merged). Scope: parrot pageindex CLI.
Validation: optimizer + bookstore suites run directly — 229 passed; only pre-existing bookstore/test_integration_graph.py sqlite failures (reproduced on baseline).
Deviations: none noted.

