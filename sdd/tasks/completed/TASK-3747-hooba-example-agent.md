# TASK-3747: examples/agents/finance/hooba_agent.py (CLI agent on HoobaToolkit + broker) with a --smoke mode tested against the fake server

**Feature**: FEAT-602 — HoobaToolkit — OpenAPI-first Hooba automation with a private Playwright fallback and BBVA expense drafts
**Spec**: `sdd/specs/hooba-toolkit.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3744
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 11** (example half), AC-16. A tracked replacement for the untracked local
`examples/agents/web/services/hooba_agent.py`: an `Agent` wired with `HoobaToolkit` and a
broker-backed credential provider, plus a deterministic `--smoke` mode (no LLM) that calls
`hooba_whoami` and lists draft invoices. `examples/**/*.py` is git-ignored, so the file
must be committed with `git add -f`.

---

## Scope

- `examples/agents/finance/hooba_agent.py`: `build_toolkit()`, `smoke(toolkit) -> dict`, `main()` with `--smoke`, system
  prompt stating drafts-only and dry-run-first for BBVA imports.
- `tests/hooba/test_example_agent.py`: load the example by path (`importlib.util.spec_from_file_location`) and run
  `smoke()` against the fake server.

**NOT in scope**: moving or committing the untracked `examples/agents/web/services/` assets.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/agents/finance/hooba_agent.py` | CREATE | CLI example (commit with git add -f) |
| `packages/ai-parrot-tools/tests/hooba/test_example_agent.py` | CREATE | smoke() against the fake server |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (re-verified 2026-09-25 against `dev` at `ad42d9aff`).
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports
```python
from parrot.bots.agent import Agent                                           # verified: examples/agents/web/services/hooba_agent.py:33 (untracked reference)
from parrot.auth.broker import CredentialBroker                               # verified: parrot/auth/__init__.py:64
from parrot_tools.hooba import HoobaSettings, HoobaToolkit                    # TASK-3742
from parrot_tools.hooba.credentials import register_hooba_provider            # TASK-3734
```

### Existing Signatures to Use
```python
# Reference shape (untracked, local only): examples/agents/web/services/hooba_agent.py — SYSTEM_PROMPT, build_toolkit(),
#   a --smoke branch that runs deterministic actions without an LLM, asyncio.run(main()).
# tests/hooba/fake_server.py (TASK-3744): FakeHoobaState, build_fake_hooba_app(state), USERNAME, PASSWORD, ACCOUNT_ID
```

### Does NOT Exist
- ~~`examples/agents/finance/`~~ — the directory does not exist yet; create it.
- ~~An importable `examples` package~~ — load the file by path in the test.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "examples/agents/finance/hooba_agent.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/tests/hooba/test_example_agent.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- `smoke(toolkit)` must not need an LLM: call `await toolkit.hooba_whoami()` and `await toolkit.hooba_list_drafts("invoice")`
  and return both envelopes.
- Commit with `git add -f examples/agents/finance/hooba_agent.py` (ruff per-file ignores for examples already exist).

### Key Constraints (all FEAT-602 tasks)
- async-first: no blocking I/O inside `async def` — wrap pandas/openpyxl/filesystem work in `asyncio.to_thread` (spec §7, S10).
- aiohttp only in new code: `httpx` and `requests` are banned by ruff TID251; the only httpx surface is inside the exempt `HTTPService` / `openapitoolkit.py`.
- Pydantic v2 models for every structured value; `self.logger` (or a module `logger = logging.getLogger(__name__)`), never `print`.
- Never log cookie values, passwords, IBANs or full bank rows at INFO or above.
- Google-style docstrings and strict type hints on every function and class; `black` line length 120; `ruff check` clean.
- Drafts only: no code path may call `:issue`, `:confirm`, `:cancel`, `:send*`, a DELETE, or any write outside `DRAFT_OPERATIONS` (spec G3, AC-5).
- Worktree testing: the shared `.venv` is editable-installed against the MAIN checkout. Run tests with
  `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-loaders/src pytest ...` so the worktree's code is imported. Never `uv sync` in a worktree.
- Fixtures are synthetic: never commit real Hooba selectors, credentials, bank exports or personal data (AC-17).

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Blocks were derived
> from the spec's Interface Skeletons (§3) and re-verified against the Codebase Contract
> above. Business-logic branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Write the example — *why*: AC-16, a tracked, broker-based entry point.
2. Test `smoke()` by path against the fake server — *why*: the example must not rot.

### `examples/agents/finance/hooba_agent.py` (CREATE)
```python
"""Hooba bookkeeping assistant (drafts only) — FEAT-602 example.

Usage::

    python examples/agents/finance/hooba_agent.py --smoke          # no LLM: whoami + draft invoices
    python examples/agents/finance/hooba_agent.py "crea un borrador de factura para ACME por 100 €"
"""
import argparse
import asyncio
import json
import logging
from typing import Any, Dict

from parrot.auth.broker import CredentialBroker
from parrot.bots.agent import Agent
from parrot_tools.hooba import HoobaSettings, HoobaToolkit
from parrot_tools.hooba.credentials import register_hooba_provider

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You help a Spanish autónomo keep Hooba up to date. You can ONLY create drafts: sales-invoice drafts,
purchase-invoice (expense) drafts, and drafts from a BBVA movements Excel. You never issue, confirm, send or delete.
Always run a BBVA import with dry_run=true first, show the plan, and apply only after the user agrees.
Every expense draft needs human review before it is confirmed in Hooba."""


def build_toolkit(settings: HoobaSettings | None = None) -> HoobaToolkit:
    """HoobaToolkit with an env-backed broker provider."""
    broker = CredentialBroker()
    register_hooba_provider(broker)
    return HoobaToolkit(settings or HoobaSettings.from_env(), broker)


async def smoke(toolkit: HoobaToolkit) -> Dict[str, Any]:
    """Deterministic check without an LLM."""
    # FILL IN: whoami + list_drafts("invoice"); return {"whoami": ..., "drafts": ...}
    raise NotImplementedError


async def main() -> None:
    # FILL IN: argparse (--smoke | prompt); smoke → log a JSON summary without personal fields;
    #          else Agent(name="HoobaAssistant", system_prompt=SYSTEM_PROMPT, tools=build_toolkit().get_tools()),
    #          configure, ask, log the answer
    raise NotImplementedError


if __name__ == "__main__":
    asyncio.run(main())
```

### `packages/ai-parrot-tools/tests/hooba/test_example_agent.py` (CREATE)
```python
"""FEAT-602 TASK-3747 — the example's --smoke path against the fake server."""
import importlib.util
from pathlib import Path

import pytest

from parrot_tools.hooba import HoobaSettings
from .fake_server import FakeHoobaState, build_fake_hooba_app

EXAMPLE = Path(__file__).resolve().parents[4] / "examples" / "agents" / "finance" / "hooba_agent.py"


async def test_example_smoke_against_fake_server(aiohttp_server, monkeypatch):
    # FILL IN: load EXAMPLE by path; env HOOBA_USERNAME/PASSWORD from fake_server; build_toolkit(HoobaSettings(...));
    #          await module.smoke(tk); both envelopes status "success"
```

### FILL IN checklist
- [ ] `smoke`, `main`
- [ ] test body; verify the `Agent(...)` constructor kwargs against `parrot/bots/agent.py` before using them
- [ ] commit with `git add -f`

---

## Acceptance Criteria

- [ ] AC-16 (spec, example half): `examples/agents/finance/hooba_agent.py --smoke` works; the test runs `smoke()` against the fake server.
- [ ] The example is committed (`git add -f`) and contains no credentials.

---

## Validation Commands

> File-level pytest only — no directories, no package roots. In a worktree, prefix with the
> `PYTHONPATH=` shown in Key Constraints.

- `pytest packages/ai-parrot-tools/tests/hooba/test_example_agent.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_example_smoke_against_fake_server` | example wiring end to end |

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context (§2, §3 module, §6, §7).
2. **Check dependencies** — verify every `Depends-on` task is done in `sdd/tasks/index/hooba-toolkit.json`.
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every anchor in the blueprint still has the stated occurrence count (`grep -c`)
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/hooba-toolkit.json` → `"in-progress"`.
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes.
6. **Verify** all acceptance criteria and run every Validation Command.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update the index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (seat=glm5, backend=nova, model=zai.glm-5,
attempt_uid=9dfcc3e8f07e482e986cb8bcf7c9b591, execution_id=85c083ec-56b6-42fe-8884-e686fbcf7a61)
**Date**: 2026-09-26
**Notes**: `examples/agents/finance/hooba_agent.py` (CLI agent on `HoobaToolkit` + broker,
`--smoke` mode) and `test_example_agent.py`. Delivered in 1 attempt, 0 retries, 0 lint
residuals. Full `packages/ai-parrot-tools/tests/hooba/` suite post-merge: 62 passed,
2 skipped (opt-in live/browser). This is the FINAL task of FEAT-602 — all 17 tasks done.

**Deviations from spec**: none | describe if any
