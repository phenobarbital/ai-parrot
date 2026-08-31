# TASK-2632: ComplementaryResearchCoordinator — parallel fan-out, soft degradation, .research.md

**Feature**: FEAT-482 — Complementary (Collaborative) Research for the Dev Flow
**Spec**: `sdd/specs/devflow-complementary-research.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2629, TASK-2631
**Assigned-to**: unassigned

---

## Context

Implements **spec §3 Module 4** — the shared seam both `IdeationNode` and
`ResearchNode` call, and the feature's **soft-degradation boundary**.

Its contract is narrow and absolute: it returns `Optional[ComplementaryFindings]`
and **never raises into a node**. Every failure — disabled, timeout, credential
error, Bedrock outage, structured-output parse failure, commit failure — becomes
`None` plus a warning plus a `partner.degraded` event.

This is the research-phase analogue of `ParallelPerspectiveReviewDispatcher`
(`code_review.py:341`), which composes a primary and a second seat with
`asyncio.gather` (`code_review.py:392`) and merges. Same shape, cooperative merge.

---

## Scope

- Implement `ComplementaryResearchCoordinator` with
  `async def research(*, brief, question, cwd, slug, run_id, node_id, session_host=None) -> Optional[ComplementaryFindings]`.
- Resolve the backend; return `None` immediately when disabled (no client built,
  no work performed).
- Run the partner under `asyncio.timeout(DEV_FLOW_RESEARCH_PARTNER_TIMEOUT)`,
  composed with the caller's own work via `asyncio.gather`.
- On success: render findings to `sdd/proposals/<slug>.research.md` and commit it,
  **staging only that path**.
- Emit `partner.started` / `partner.completed` / `partner.degraded` events.
- Treat empty/trivial findings as absent: no file written, no empty section.
- Truncate oversized findings with an explicit marker for the dispatch payload while
  keeping full text in `.research.md`.
- Unit tests for every degradation path.

**NOT in scope**: node wiring (TASK-2633/2634); the partner implementation
(TASK-2631); any telemetry *rendering* — emit events only, touch no
`usage_report.py` / `run_bundle.py` (FEAT-479 owns those).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_flow/complementary_research.py` | CREATE | Coordinator |
| `packages/ai-parrot/tests/flows/dev_flow/test_complementary_research.py` | CREATE | Degradation + artifact tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import asyncio
from pathlib import Path
from typing import Optional
from parrot import conf
from parrot.flows.dev_flow.research_partner import (
    AbstractResearchPartner, ResearchPartnerFactory,
    ResearchFindings, ComplementaryFindings,
)
from parrot.flows.dev_loop.catalog import resolve_research_partner_backend
```

### Existing Signatures to Use

```python
# PATTERN SOURCE — packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py
class ParallelPerspectiveReviewDispatcher(AbstractCodeReviewDispatcher):  # line 341
    primary_result, adversary_result = await asyncio.gather(...)          # line 392
    def _resolve_side(self, result, source) -> CodeReviewVerdict          # line 436
    def _merge_verdicts(self, primary, adversary)                         # line 462

# DEGRADATION CONTRACT TO MIRROR —
# packages/ai-parrot/src/parrot/flows/dev_loop/wiki_search.py
class DevLoopWikiSearch:                                                  # line 26
    async def build_research_context(self, query, budget_tokens) -> Optional[str]:  # line 91
        # "Best-effort: returns None on ANY internal error, never raises."
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(...)
            return None

# From TASK-2629:
class ComplementaryFindings(BaseModel):
    backend: str; model: str; findings: ResearchFindings
    document_path: str = ""; rendered: str; duration_ms: float; degraded: bool = False

# Config (TASK-2629):
conf.DEV_FLOW_RESEARCH_PARTNER          # "" => disabled
conf.DEV_FLOW_RESEARCH_PARTNER_TIMEOUT  # 600
```

### Does NOT Exist

- ~~code that writes `sdd/proposals/*.research.md`~~ — `agents-flow-refactor.research.md`
  is **hand-written**; there is no generator. This task creates the first one.
- ~~a "degrade to a passing verdict" pattern here~~ — that is
  `NovaAdversarialReviewDispatcher`'s inherited behavior for *reviews*
  (`dispatchers/nova.py:240`). Research has no verdict: **absence is absence**, so a
  parse failure returns `None`, not a fabricated success.
- ~~`usage_report.py` / `run_bundle.py` hooks~~ — out of scope; FEAT-479 owns them
  and has 11 in-progress tasks there. Emit events only.
- ~~a retry or backend-fallback path~~ — explicitly a non-goal (spec §1). One attempt.

---

## Implementation Notes

### Pattern to Follow

```python
async def research(self, *, brief, question, cwd, slug, run_id, node_id, session_host=None):
    backend = resolve_research_partner_backend()
    if not backend:
        return None                      # disabled: no client, no work
    try:
        async with asyncio.timeout(conf.DEV_FLOW_RESEARCH_PARTNER_TIMEOUT):
            findings = await partner.research(...)
    except Exception as exc:             # noqa: BLE001 — degradation boundary
        self.logger.warning("Complementary research degraded: %s", exc)
        await self._emit("partner.degraded", ...)
        return None
```

### Key Constraints

- **Never raise.** A bare `except Exception` is correct here and is the one place in
  this feature where it is. Document why inline.
- Commit `.research.md` staging **only that path** — never `git add -A` / `git add .`
  (SDD auto-commit rule; a stray sweep of a shared checkout is a known hazard).
- A `.research.md` write or commit failure must NOT lose the findings: still return
  them in-memory with `document_path=""` and warn.
- Cancellation must not leak the partner's subprocesses/connections.
- Async throughout; `self.logger`; Pydantic.

### References in Codebase

- `packages/ai-parrot/src/parrot/flows/dev_loop/wiki_search.py:91-130` — the exact
  best-effort contract to mirror.
- `packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py:392` — gather composition.
- `sdd/proposals/agents-flow-refactor.research.md` — formatting precedent for the artifact.

---

## Acceptance Criteria

- [ ] Returns `None` when disabled, with no client constructed
- [ ] Soft-degrades to `None` on timeout, credential error, outage, and parse failure — never raises
- [ ] Emits `partner.started` / `partner.completed` / `partner.degraded`
- [ ] Writes and commits `sdd/proposals/<slug>.research.md` staging only that path
- [ ] Empty/trivial findings => no file, no empty section
- [ ] `.research.md` write failure still returns findings in-memory with a warning
- [ ] Oversized findings truncated with a marker; full text retained in the file
- [ ] Touches no telemetry rendering code
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_flow/test_complementary_research.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_flow/complementary_research.py`

---

## Test Specification

```python
class TestComplementaryResearchCoordinator:
    async def test_returns_none_when_disabled(self):
        """No partner constructed, no work performed."""

    async def test_soft_degrades_on_timeout(self):
        """Returns None, emits partner.degraded, does not raise."""

    async def test_soft_degrades_on_parse_failure(self):
        """Invalid structured output => None (NOT a fabricated passing result)."""

    async def test_writes_research_md_staging_only_that_path(self):
        """Artifact committed; `git add` receives exactly one path."""

    async def test_empty_findings_treated_as_absent(self):
        """Trivial findings => no file written, returns None."""

    async def test_commit_failure_still_returns_findings(self):
        """document_path == "" but findings survive; warning logged."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§3 Module 4, §2 Edge Cases table, §7 Known Risks).
2. **Check dependencies** — TASK-2629 and TASK-2631 in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before writing code.
4. **Update status** in `sdd/tasks/index/devflow-complementary-research.json` → `"in-progress"`.
5. **Implement** — the degradation boundary is the point of this class.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-2632-complementary-research-coordinator.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
