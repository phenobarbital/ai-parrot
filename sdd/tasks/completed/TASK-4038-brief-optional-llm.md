# TASK-4038: Optional model resolution and bounded fail-safe synthesis

---

**Feature**: FEAT-627 — wikitoolkit standup: entity attributes and daily/period briefs
**Spec**: `sdd/specs/wikitoolkit-standup.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4031
**Assigned-to**: unassigned

---

## Context

Implement M6 resolve_optional_llm in a new light module plus M5 llm.summarize and projection/fallback helpers. Do not modify existing inline extraction/triage sites. Reproduce _env_setting env/navconfig resolution without importing cli. Lazy-load detection/factory/adapter only inside resolver; honor PARROT_NO_AUTO_LLM. Set temperature=0 and a 20-second outer timeout including retries. Project only kind/title/status/project/age_days/urgent (the six listed keys in the spec), <=40 records, title[:120], no bodies/URLs/owners/IDs. Use a prompt forbidding invented facts and requesting <=3 bullets in the selected language. Failures return None and a logged diagnostic; pipeline records Hygiene failure and retains ranked fallback. Never call provider SDKs directly.

---

## Scope

Implement M6 resolve_optional_llm in a new light module plus M5 llm.summarize and projection/fallback helpers. Do not modify existing inline extraction/triage sites. Reproduce _env_setting env/navconfig resolution without importing cli. Lazy-load detection/factory/adapter only inside resolver; honor PARROT_NO_AUTO_LLM. Set temperature=0 and a 20-second outer timeout including retries. Project only kind/title/status/project/age_days/urgent (the six listed keys in the spec), <=40 records, title[:120], no bodies/URLs/owners/IDs. Use a prompt forbidding invented facts and requesting <=3 bullets in the selected language. Failures return None and a logged diagnostic; pipeline records Hygiene failure and retains ranked fallback. Never call provider SDKs directly.

**NOT in scope**: changes outside the declared file table; new runtime dependencies; unrelated cleanup. Follow the approved v1 non-goals for backend parity and pre-existing ledger import cost.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/llm_resolve.py` | CREATE | This new helper is additive; migrating old callers is explicitly out of scope. |
| `packages/ai-parrot/src/parrot/knowledge/wiki/standup/llm.py` | CREATE | The adapter is the sole LLM boundary; deterministic output remains available on every failure. |
| `packages/ai-parrot/tests/knowledge/wiki/standup/test_llm.py` | CREATE | Use fake adapters only and assert actual projected prompt content. |

---

## Codebase Contract (Anti-Hallucination)

Verified at `75fe680a0`. Dependency-created imports below are planned contracts, not claims of current existence.

### Verified Imports

```python
from collections.abc import Sequence  # stdlib or existing pyproject dependency/test environment
import logging  # stdlib or existing pyproject dependency/test environment
from typing import TYPE_CHECKING  # stdlib or existing pyproject dependency/test environment
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter  # verified source packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py
import asyncio  # stdlib or existing pyproject dependency/test environment
from parrot.knowledge.wiki.standup.models import BriefItem, BriefProjection, Period  # planned in TASK-4031; not present before that task
from pathlib import Path  # stdlib or existing pyproject dependency/test environment
import pytest  # stdlib or existing pyproject dependency/test environment
import parrot.knowledge.wiki.standup.llm as subject  # planned in TASK-4038; not present before that task
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:565
def _env_setting(name: str) -> str | None:

# packages/ai-parrot/src/parrot/clients/detection.py:19
def detect_coding_agent_llm() -> Optional[str]:

# packages/ai-parrot/src/parrot/clients/factory.py:257
    def create(
        llm: str, model_args: Optional[Dict[str, Any]] = None, tool_manager: Optional[Any] = None, **kwargs
    ) -> AbstractClient:

# packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py:61
    async def ask(
        self,
        prompt: str,
        structured_output: Union[type, StructuredOutputConfig, None] = None,
        temperature: float = 0.0,
        system_prompt: Optional[str] = None,
    ) -> str:

# packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py:42
class PageIndexLLMAdapter:
```

### Does NOT Exist

- `packages/ai-parrot/src/parrot/knowledge/wiki/llm_resolve.py` is created by this task; do not assume it already exists.
- `packages/ai-parrot/src/parrot/knowledge/wiki/standup/llm.py` is created by this task; do not assume it already exists.
- `packages/ai-parrot/tests/knowledge/wiki/standup/test_llm.py` is created by this task; do not assume it already exists.
- `list_pages(offset=...)`, `DecisionRecord.updated_at`, and a JiraPerson email field are not existing APIs. Do not invent them.
- Category names remain open strings; no new WikiPageCategory enum members are required.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/llm_resolve.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/standup/llm.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/standup/test_llm.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_env_setting",
    "sym:packages/ai-parrot/src/parrot/clients/detection.py#detect_coding_agent_llm",
    "sym:packages/ai-parrot/src/parrot/clients/factory.py#LLMFactory.create",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py#PageIndexLLMAdapter.ask",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py#PageIndexLLMAdapter"
  ]
}
```

---

## Implementation Notes

TASK-4031: consumes BriefProjection and BriefItem

Use async I/O paths, existing lifecycle/context managers, module logging, strict types and Google-style docstrings. Black uses 120 columns; ruff is the lint gate. Keep tests isolated and file-scoped. Fresh dependency code may shift anchors: reverify before edits, and retain the semantic attachment site.

---

## Implementation Blueprint

### Steps (in order)

1. Verify the existing references and completed dependency interfaces — because the blueprint must match the executing worktree.
2. Apply the per-file blocks below in declared order and complete only bounded FILL IN work — because each task owns a limited surface.
3. Implement the listed adversarial cases and run Validation Commands — because the acceptance criteria cover observable behavior, not only imports.

---

### `packages/ai-parrot/src/parrot/knowledge/wiki/llm_resolve.py` (CREATE)

```python
"""Lazy optional wiki model resolution without CLI/store import dependencies."""
from collections.abc import Sequence
import logging
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter

def resolve_optional_llm(
    env_names: Sequence[str], *, purpose: str, logger: logging.Logger,
) -> "PageIndexLLMAdapter | None":
    """Resolve explicit environment settings or allowed CLI detection, fail safely."""
    # FILL IN: lazy LLMFactory/detection/adapter imports; no cli/store import; AC8/13.
    raise NotImplementedError
```

**Why**: This new helper is additive; migrating old callers is explicitly out of scope.

---

### `packages/ai-parrot/src/parrot/knowledge/wiki/standup/llm.py` (CREATE)

```python
"""Bounded optional synthesis with deterministic fallback bullets."""
import asyncio
import logging
from typing import TYPE_CHECKING
from parrot.knowledge.wiki.standup.models import BriefItem, BriefProjection, Period
if TYPE_CHECKING:
    from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter
logger = logging.getLogger(__name__)

def project_items(items: list[BriefItem], *, period: Period, language: str) -> BriefProjection:
    """Whitelist at most forty ranked items and truncate titles to 120 characters."""
    # FILL IN: only six spec projection fields; AC8.
    raise NotImplementedError

def fallback_bullets(items: list[BriefItem], *, language: str) -> list[str]:
    """Return at most three deterministic ranked facts without a model."""
    # FILL IN: stable urgency/date/ID ranking and concise factual text; AC8.
    raise NotImplementedError

async def summarize(
    projection: BriefProjection, *, language: str, adapter: "PageIndexLLMAdapter", timeout_s: float = 20.0,
) -> list[str] | None:
    """Generate bounded factual bullets, returning None on failure or invalid output."""
    # FILL IN: timeout around adapter.ask(temperature=0), validate <=3 bullets; AC8.
    raise NotImplementedError
```

**Why**: The adapter is the sole LLM boundary; deterministic output remains available on every failure.

---

### `packages/ai-parrot/tests/knowledge/wiki/standup/test_llm.py` (CREATE)

```python
"""Regression cases for FEAT-627."""
from pathlib import Path
import pytest
import parrot.knowledge.wiki.standup.llm as subject


def test_bounded_projection_and_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify bounded projection and fallback."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError


def test_model_resolution_and_imports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify model resolution and imports."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError


def test_timeout_and_invalid_response(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify timeout and invalid response."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError
```

**Why**: Use fake adapters only and assert actual projected prompt content.

---

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/llm_resolve.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/standup/llm.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/standup/test_llm.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.

---

## Acceptance Criteria

- [ ] Model absent/disabled/detection failure yields None without changing startup imports.
- [ ] Adapter sees only bounded whitelisted facts; malformed/empty/timeout/raising output falls back.
- [ ] Fallback is <=3 deterministic urgent-first bullets; raw model exceptions cannot leak credentials.
- [ ] All declared-file tests pass; no ruff errors or unfinished implementation placeholders remain.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/standup/test_llm.py -q`

---

## Test Specification

- Model absent/disabled/detection failure yields None without changing startup imports.
- Adapter sees only bounded whitelisted facts; malformed/empty/timeout/raising output falls back.
- Fallback is <=3 deterministic urgent-first bullets; raw model exceptions cannot leak credentials.

Use temporary local state, deterministic clocks and fake network/model adapters. Test failures and negative cases as well as success. New tests live alongside the core distribution; legacy suites are validation references only unless explicitly declared MODIFY above.

---

## Agent Instructions

1. Run `$sdd-start TASK-4038`; implementation belongs in the feature worktree, never directly on dev.
2. Read the approved spec and verify dependency completion in `sdd/tasks/index/wikitoolkit-standup.json`.
3. Recheck imports/anchors, implement only declared files and run the validation commands.
4. Commit scoped implementation and finalize with `scripts.sdd.finalize_task` plus real `TaskCompletionEvidence` for the exact implementation HEAD. Do not manually move the task or manufacture completion evidence.

## Completion Note

Pending; owned by the evidence-based finalizer.
