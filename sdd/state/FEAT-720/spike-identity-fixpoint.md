# FEAT-720 Amendment A — identity fixpoint (strategy (a′))

**Run at**: 2026-10-23, worktree `feat-FEAT-720-tests-test-wheel-layout-tech-debt-2`, pytest 9.1.1
**Supersedes the verdict of** `spike-collect.md` (kept as history: strategy (a) alone is REFUTED).
**Tools**: `identity_fixpoint.py` (derives the plan), `identity-plan.json` (its output).

## Finding
`spike-collect.md` §3 attributed 89 of 129 new errors to class (vii). Root cause, measured:
with the top-level `tests/__init__.py` gone, pytest derives a module's identity from the topmost
contiguous `__init__.py` chain. Two things then collide:

* **(vii)** in-tree gap — `tests/unit/` has no `__init__.py`, so `tests/unit/bots/database/conftest.py`
  and `tests/bots/database/conftest.py` both become `bots.database.conftest` (`ValueError: Plugin already registered`).
* **(viii)** cross-tree — 11 first-level package names are shared between trees (`unit` ×20, `integration` ×3, …)
  and 4 conftest module names collide (`handlers`, `integration`, `unit`, `voice`).
* **(ix)** a first-level test package shadows an importable top-level name: installed (`mcp`, `outputs`,
  `docker`, `google`, `pulumi`, `querysource`) or a repo-root dir on `sys.path` under `python -m pytest`
  (`benchmarks`, `agents`, `examples`, `helpers`).

## Remedy (a′): unique derived identity, by `__init__.py` placement only
Fixpoint rules (`identity_fixpoint.py`): (R3) no first-level package may be importable elsewhere →
drop its `__init__.py`; (R2) no derived module name may occur twice, in one tree or across trees →
keep the largest tree's (`ai-parrot`), drop the others, or, for an in-tree gap, add the gap's `__init__.py`.

Result (`identity-plan.json`): **1 file added** (`packages/ai-parrot/tests/unit/__init__.py`),
**51 nested files removed**. Nested `__init__.py` count: 242 → **192**. Plus the 25 top-level deletions.

## Validation of the remedy (real pytest, importlib mode, all 28 roots in ONE session)
| | strategy (a) alone | (a′) |
|---|---|---|
| collected | — | 43,037 |
| `Plugin already registered` / `ImportPathMismatchError` | many | **0** |
| collection errors | 129 (per-root sum) | 69 |

The 69 remaining errors are NOT identity collisions: class (i) `tests.<x>` (~27), (ii)/(iii)/(iv) relative or
`scripts.*` imports (9), and **(xi)** test-level pollution that only a mega-session exposes — a test module that
replaces `sys.modules['aiohttp']`/`parrot._imports` at import time, plus pre-existing missing deps (`fakeredis`).
(xi) is out of scope: it needs no path-identity change and cannot occur in a single-root run; it is
filed as a ledger issue, and AC1 is the pair gate, not the 28-way one.

## Verdict
STRATEGY (a′) CONFIRMED
