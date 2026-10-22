# TASK-4017: LLM contradiction pack (opt-in, capped)

**Feature**: FEAT-625 — wikitoolkit lint
**Spec**: `sdd/specs/wikitoolkit-lint.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: M
**Depends-on**: TASK-4009
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 / AC10. Not delegation-eligible: prompt and verdict schema are design judgement (spec §8 open).

---

## Scope

- `resolve_lint_llm_spec(explicit)`: `--llm-model` > env `WIKI_LINT_LLM` > env `WIKI_EXTRACT_LLM` > `detect_coding_agent_llm()` unless `PARROT_NO_AUTO_LLM`.
- `ContradictionLLMRule(client, max_pairs=50, timeout_s=30)`: candidate pairs = memories and accepted ADR pages linking the same page, ranked by shared links, capped at `max_pairs`.
- Each pair: one `asyncio.wait_for(client.ask(...), timeout_s)` call; JSON verdict `{contradicts: bool, explanation: str}`; `contradicts` → `contradiction-llm` warning.
- Any provider failure → ONE `llm-skipped` info finding; never raise.
- `build_llm_rule(options)` factory: `LLMFactory.create(spec, model_args={"temperature": 0.0})`; returns None when no spec.

**NOT in scope**: Running by default — only when `options.llm`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/lint/packs/llm.py` | CREATE | LLM pack |
| `packages/ai-parrot/tests/knowledge/lint/test_llm_pack.py` | CREATE | Tests with a fake client |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ 350d206f0 (2026-10-03). Re-verify before coding.

### Verified Imports
```python
from parrot.knowledge.lint.models import Finding, FixResult, LintOptions, LintReport, Severity  # created by TASK-4009
from parrot.knowledge.lint.rule import LintRule, make_fingerprint  # created by TASK-4009
from parrot.knowledge.lint.context import LintContext  # created by TASK-4009
from parrot.clients.factory import LLMFactory  # verified: used at wiki/cli.py:3747, LLMFactory.create(spec, model_args={...}) at :3753
from parrot.clients.detection import detect_coding_agent_llm  # verified: wiki/cli.py:3730
```

### Existing Signatures to Use
```python
# wiki/cli.py:3727-3753 — reference resolution order for WIKI_EXTRACT_LLM:
#   spec = _env_setting("WIKI_EXTRACT_LLM"); if not spec and not _env_setting("PARROT_NO_AUTO_LLM"): detect_coding_agent_llm()
#   client = LLMFactory.create(spec, model_args={"temperature": 0.0})
# AbstractClient.ask(...) — FILL IN: verify exact kwargs in parrot/clients/base.py before calling (do not modify base.py)
```

### Does NOT Exist
- ~~`WIKI_LINT_LLM`~~ — introduced here
- ~~`_env_setting` importable as a public API~~ — it is private to cli.py; read `os.environ` here

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/lint/packs/llm.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/lint/test_llm_pack.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
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
1. Read env with `os.environ.get` — *why*: `_env_setting` is CLI-private; FILL IN whether .env loading matters (cli loads it at startup).
2. Ask for strict JSON and parse defensively — *why*: a malformed reply is a skip, not a crash (AC10).

### `packages/ai-parrot/src/parrot/knowledge/lint/packs/llm.py` (CREATE)
```python
"""LLM contradiction pack — opt-in, pair-capped (FEAT-625)."""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from parrot.knowledge.lint.context import LintContext
from parrot.knowledge.lint.models import Finding, FixResult, LintOptions
from parrot.knowledge.lint.rule import make_fingerprint

DEFAULT_MAX_PAIRS = 50


def resolve_lint_llm_spec(explicit: str | None) -> str | None:
    """--llm-model > WIKI_LINT_LLM > WIKI_EXTRACT_LLM > coding-agent auto-detect (unless PARROT_NO_AUTO_LLM)."""
    spec = explicit or os.environ.get("WIKI_LINT_LLM") or os.environ.get("WIKI_EXTRACT_LLM")
    if spec or os.environ.get("PARROT_NO_AUTO_LLM"):
        return spec or None
    try:
        from parrot.clients.detection import detect_coding_agent_llm

        return detect_coding_agent_llm()
    except Exception:  # noqa: BLE001 — detection is best-effort
        return None


class ContradictionLLMRule:
    """Ask an LLM whether two memories/ADRs about the same page contradict."""

    rule_id, pack, default_severity = "contradiction-llm", "llm", "warning"

    def __init__(self, client: Any, max_pairs: int = DEFAULT_MAX_PAIRS, timeout_s: float = 30.0) -> None:
        self.client = client
        self.max_pairs = max_pairs
        self.timeout_s = timeout_s

    async def _pairs(self, ctx: LintContext) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        # FILL IN: memories (ctx.memories()) + adr: pages; group by linked target via ctx.edges(); rank by shared links; [: self.max_pairs]
        raise NotImplementedError

    async def _judge(self, a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
        # FILL IN: prompt design (spec §8 open — record the chosen prompt in the Completion Note);
        #          await asyncio.wait_for(self.client.ask(...), self.timeout_s); json.loads the reply
        raise NotImplementedError

    async def check(self, ctx: LintContext) -> list[Finding]:
        # FILL IN: for each pair -> _judge; on ANY exception return [llm-skipped info finding] immediately (AC10)
        raise NotImplementedError

    async def fix(self, ctx: LintContext, finding: Finding) -> FixResult | None:
        return None


def build_llm_rule(options: LintOptions) -> ContradictionLLMRule | None:
    """Create the rule with a temperature-0 client, or None when no model is configured."""
    spec = resolve_lint_llm_spec(options.llm_model)
    if not spec:
        return None
    from parrot.clients.factory import LLMFactory

    client = LLMFactory.create(spec, model_args={"temperature": 0.0})
    return ContradictionLLMRule(client, max_pairs=options.llm_max_pairs)
```

**Why this shape**: Model resolution and default cap were decided in spec §8 (user deferred to spec). Imports of the client stay inside functions so `import parrot.knowledge.lint.packs.llm` never builds a client (mirrors decisions/service.py AC5 rule).

### FILL IN checklist
- [ ] `_pairs` candidate selection
- [ ] `_judge` prompt + parsing
- [ ] `check` failure degradation

---

## Acceptance Criteria

- [ ] At most `max_pairs` client calls (AC10)
- [ ] Client failure → single `llm-skipped` info, run succeeds
- [ ] Resolution order honoured
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/lint/test_llm_pack.py -v`
- [ ] No lint errors: `ruff check` on the touched files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/lint/test_llm_pack.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/lint/test_llm_pack.py
async def test_llm_pair_cap(tmp_path): ...
async def test_llm_skipped_on_failure(tmp_path): ...
def test_resolve_spec_order(monkeypatch):
    monkeypatch.setenv("WIKI_EXTRACT_LLM", "b:y"); monkeypatch.setenv("WIKI_LINT_LLM", "a:x")
    from parrot.knowledge.lint.packs.llm import resolve_lint_llm_spec
    assert resolve_lint_llm_spec(None) == "a:x" and resolve_lint_llm_spec("c:z") == "c:z"
```

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug wikitoolkit-lint --feature-id FEAT-625`), never on `dev`.
2. Check every Depends-on task is `done` in `sdd/tasks/index/wikitoolkit-lint.json`.
3. Verify the Codebase Contract; fix it first if stale.
4. Implement from the blueprint; complete every `# FILL IN:`; never change fixed signatures/paths.
5. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
6. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4017 wikitoolkit-lint verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none

## Completion Note

Implemented by glm (nova), 1 attempt. Review fix 1664b9a09: client failures now surface as one llm-skipped finding; tests repaired (feedback coder-feedback:694240012e0c525f85013ebe). Closed via close_task.sh. Verified: lint package + store tests 44 passed (scoped), ruff clean.
