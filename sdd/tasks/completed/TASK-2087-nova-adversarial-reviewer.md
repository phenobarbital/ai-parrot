# TASK-2087: NovaAdversarialReviewDispatcher — read-only, no-tools reviewer

**Feature**: FEAT-405 — Nova (AWS Bedrock) Dispatcher & Per-Agent Usage Report
**Spec**: `sdd/specs/novaclient-dev-loop.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2084
**Assigned-to**: unassigned

---

## Context

Implements **Module 3b** of the spec — the adversarial review seat on Claude
Opus 5. Today the adversarial slot is codex-only
(`catalog.ADVERSARIAL_BACKEND = "codex"`, `catalog.py:48`) because
`CodexAdversarialReviewDispatcher` is the only reviewer with a read-only sandbox.

This reviewer achieves read-only differently and more strongly: it passes **no
tools at all**. The diff, the acceptance criteria and the review question go in
the prompt; the model returns the verdict JSON. Read-only holds by construction
— there is no enforcement code that could be wrong.

That also makes it a single `ask()` call, which `BedrockConverseBase.ask()`
(`clients/bedrock.py:578`) already serves — no tool loop, no adapter. Anthropic
models on Bedrock have no Chat Completions, so Converse is the correct transport
here (unlike the dev seat, which uses `bedrock-mantle`).

---

## Scope

- Add `NovaAdversarialReviewDispatcher` to `dev_loop/dispatchers/nova.py`,
  registered via `@CodeReviewDispatcherFactory.register("nova-adversarial")`.
- Set `agent_name = "nova-adversarial"` and `advisory = True`.
- Implement `build_review_profile()` returning `NovaAdversarialReviewProfile`.
- Implement `review()` to: assemble the neutral brief (diff + criteria +
  question) with deterministic truncation at `max_diff_chars`, issue **one**
  `NovaClient.ask()` with no tools, parse the `CodeReviewVerdict`, then apply
  the post-dispatch hardening — force `files_modified = []` and tag every
  finding with `source="nova-adversarial"`, mirroring `code_review.py:337`.
- Write unit tests.

**NOT in scope**: making the adversarial seat selectable — turning
`ADVERSARIAL_BACKEND` into a config choice is TASK-2088; the dev-seat dispatcher
(TASK-2086); changing `CodexAdversarialReviewDispatcher`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/nova.py` | MODIFY | Add `NovaAdversarialReviewDispatcher` (file created by TASK-2086) |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/__init__.py` | MODIFY | Export it |
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | `DEV_LOOP_NOVA_REVIEW_MODEL` key |
| `packages/ai-parrot/tests/flows/dev_loop/test_nova_adversarial.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.flows.dev_loop.code_review import (
    AbstractCodeReviewDispatcher, CodeReviewDispatcherFactory,
)   # verified: code_review.py:85, :164
from parrot.flows.dev_loop.models import NovaAdversarialReviewProfile  # TASK-2084
from parrot.flows.dev_loop.session_state import SessionHost
from parrot.clients.nova import NovaClient          # verified: clients/nova/__init__.py
```

`CodeReviewVerdict`, `CodeReviewFinding` and `AdversarialFinding` are used by
`code_review.py` — import them from the same place that module does (verify the
exact source before use; they are re-exported through
`parrot.flows.dev_loop.models`).

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py
class AbstractCodeReviewDispatcher(ABC):                              # line 85
    agent_name: str                                                   # line 99
    advisory: bool = False                                            # line 100
    async def review(self, *, brief: BaseModel, run_id: str, node_id: str,
                     cwd: str, session_host: Optional[SessionHost] = None,
                     round: str = "") -> CodeReviewVerdict: ...       # line 106
        # base impl delegates to self._dispatcher.dispatch(...) and DEGRADES
        # any exception to a PASSING verdict with a nit-level finding (lines 145-157)
    @abstractmethod
    def build_review_profile(self) -> BaseModel: ...                  # line 159

class CodeReviewDispatcherFactory:                                    # line 164
    @classmethod
    def register(cls, name: str): ...                                 # line 170
    @classmethod
    def create(cls, name: str, **kwargs) -> AbstractCodeReviewDispatcher: ...  # line 180

@CodeReviewDispatcherFactory.register("codex-adversarial")            # line 266 — MIRROR THIS
class CodexAdversarialReviewDispatcher(AbstractCodeReviewDispatcher): # line 267
    agent_name = "codex-adversarial"                                  # line 277
    advisory = True                                                   # line 278
    def __init__(self, *, dispatcher, model=None, review_scope="uncommitted",
                 review_base="", review_commit="") -> None: ...       # line 280
        self._model = model or conf.DEV_LOOP_ADVERSARIAL_MODEL        # line 290
    def build_review_profile(self) -> CodexAdversarialReviewProfile: ...  # line 296
    async def review(self, *, brief, run_id, node_id, cwd,
                     session_host=None, round="") -> CodeReviewVerdict:   # line 304
        verdict = await super().review(...)                           # line 323
        tagged_findings = [                                           # line 331
            f if isinstance(f, AdversarialFinding)
            else AdversarialFinding(**f.model_dump(), source=self.agent_name)
            for f in verdict.findings
        ]
        return verdict.model_copy(
            update={"files_modified": [], "findings": tagged_findings})  # line 337

# packages/ai-parrot/src/parrot/clients/bedrock.py
async def ask(self, ..., tools=None, use_tools=None, ...): ...        # line 578
# tools param line 589, use_tools line 590; use_tools defaults to self.enable_tools
# line 638; toolConfig only injected when _use_tools is truthy (lines 724-731)

# packages/ai-parrot/src/parrot/conf.py
DEV_LOOP_ADVERSARIAL_MODEL: str = config.get(..., fallback="gpt-5.5")  # line 1048
DEV_LOOP_ADVERSARIAL_SCOPE  # line 1053    DEV_LOOP_ADVERSARIAL_BASE_REF  # line 1076
```

### Does NOT Exist

- ~~`NovaAdversarialReviewDispatcher`~~ — this task creates it
- ~~`"nova"` or `"nova-adversarial"` in `catalog.ADVERSARIAL_BACKEND`~~ — it is the bare string `"codex"` (`catalog.py:48`); TASK-2088 makes it selectable
- ~~A read-only *sandbox* concept for Nova~~ — there is none and none is needed: no tools are passed, so there is nothing to sandbox
- ~~`ClaudeCodeDispatchProfile.subagent == "sdd-secondopinion"`~~ — that Literal does not admit it; irrelevant here since Nova uses its own profile
- ~~`NovaClient._chat_completion`~~ — does not exist; use `ask()`
- ~~`conf.DEV_LOOP_NOVA_REVIEW_MODEL`~~ — this task adds it

---

## Implementation Notes

### Pattern to Follow

Mirror `CodexAdversarialReviewDispatcher` (`code_review.py:266-337`) exactly for
structure, including the belt-and-braces hardening:

```python
@CodeReviewDispatcherFactory.register("nova-adversarial")
class NovaAdversarialReviewDispatcher(AbstractCodeReviewDispatcher):
    """Read-only adversarial second-opinion reviewer on Claude Opus 5.

    Read-only BY CONSTRUCTION: no tools are ever passed to the model. The diff,
    criteria and question go in the prompt; the model returns the verdict JSON.
    Findings are advisory and must be triaged (CONFIRM/REJECT/ESCALATE) by the
    primary worker downstream.
    """

    agent_name = "nova-adversarial"
    advisory = True
```

Because there is no underlying `DevLoopCodeDispatcher` to delegate to, `review()`
does **not** call `super().review()` — it drives `NovaClient.ask()` directly and
must therefore implement its own degrade-on-error behaviour consistent with the
base class (`code_review.py:145-157`: infra error → passing verdict + nit finding).

### Key Constraints

- **Pass no tools.** Call `ask()` with `use_tools=False` explicitly — do not rely
  on the default (`clients/bedrock.py:638` reads `self.enable_tools`).
- Truncate the diff deterministically at `max_diff_chars` with an explicit
  marker; never silently.
- Always return `files_modified == []`, regardless of what the model claims.
- Tag every finding with `source="nova-adversarial"`.
- The degrade path turns an outage into a **passing** verdict — this is inherited
  behaviour and must be covered by an explicit test so it is a known property.
- async throughout; `self.logger`.

### References in Codebase

- `packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py:266-337` — the class to mirror
- `packages/ai-parrot/src/parrot/flows/dev_loop/code_review.py:145-157` — the degrade contract to reproduce
- `packages/ai-parrot/src/parrot/clients/bedrock.py:578-731` — `ask()` and its `toolConfig` gating

---

## Acceptance Criteria

- [ ] `CodeReviewDispatcherFactory.create("nova-adversarial", ...)` returns the dispatcher
- [ ] `agent_name == "nova-adversarial"` and `advisory is True`
- [ ] `ask()` is called with `use_tools=False` and **no** `tools` argument
- [ ] The returned verdict always has `files_modified == []`
- [ ] Every finding carries `source="nova-adversarial"`
- [ ] A diff longer than `max_diff_chars` is truncated with an explicit marker
- [ ] An infra error degrades to a passing verdict with a nit-level finding
      (explicit test — documents that an outage passes the gate)
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_nova_adversarial.py -v` passes
- [ ] `ruff check` + `mypy` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_nova_adversarial.py
import pytest
from unittest.mock import AsyncMock
from parrot.flows.dev_loop.code_review import CodeReviewDispatcherFactory


@pytest.fixture
def reviewer(monkeypatch):
    return CodeReviewDispatcherFactory.create("nova-adversarial")


class TestRegistration:
    def test_registered_in_factory(self, reviewer):
        assert reviewer.agent_name == "nova-adversarial"

    def test_is_advisory(self, reviewer):
        assert reviewer.advisory is True


class TestNoTools:
    async def test_ask_called_without_tools(self, reviewer, monkeypatch):
        fake_ask = AsyncMock(return_value=...)
        monkeypatch.setattr(reviewer, "_client", type("C", (), {"ask": fake_ask})())
        await reviewer.review(brief=..., run_id="r", node_id="n", cwd=".")
        kwargs = fake_ask.await_args.kwargs
        assert kwargs.get("use_tools") is False
        assert not kwargs.get("tools")


class TestHardening:
    async def test_files_modified_always_empty(self, reviewer):
        verdict = await reviewer.review(brief=..., run_id="r", node_id="n", cwd=".")
        assert verdict.files_modified == []

    async def test_findings_tagged_with_source(self, reviewer):
        verdict = await reviewer.review(brief=..., run_id="r", node_id="n", cwd=".")
        assert all(getattr(f, "source", None) == "nova-adversarial"
                   for f in verdict.findings)

    async def test_diff_truncated_with_marker(self, reviewer):
        """A huge diff is cut deterministically, never silently."""

    async def test_infra_error_degrades_to_passing_verdict(self, reviewer, monkeypatch):
        """DOCUMENTS a known property: a Bedrock outage PASSES the adversarial gate."""
        verdict = await reviewer.review(brief=..., run_id="r", node_id="n", cwd=".")
        assert verdict.passed is True
        assert any(f.severity == "nit" for f in verdict.findings)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§2 Overview, Module 3, §7 "Adversarial degrade path")
2. **Check dependencies** — verify TASK-2084 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm `CodexAdversarialReviewDispatcher`'s structure at `code_review.py:266-337`
   - Confirm where `CodeReviewVerdict` / `AdversarialFinding` are actually imported from
   - Confirm `ask()`'s `use_tools` gating at `clients/bedrock.py:638,724-731`
   - If anything has changed, update the contract FIRST, then implement
4. **Update status** in `sdd/tasks/index/novaclient-dev-loop.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2087-nova-adversarial-reviewer.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Sonnet 5)
**Date**: 2026-08-03
**Notes**: Added `NovaAdversarialReviewDispatcher` to `dispatchers/nova.py`,
registered `@CodeReviewDispatcherFactory.register("nova-adversarial")`,
`agent_name = "nova-adversarial"`, `advisory = True`. `__init__` takes only
optional kwargs (no `dispatcher=` — there is no underlying
`DevLoopCodeDispatcher` to wrap) and builds its own `NovaClient()` (or
accepts an injected `client=` for tests). `review()` does NOT call
`super().review()` (no dispatcher to delegate to); it drives
`_collect_diff()` (an `asyncio.create_subprocess_exec("git", "diff"/"show",
...)` helper keyed on `review_scope`, truncated via `_truncate_diff` at
`max_diff_chars` with an explicit marker) + `_build_prompt()`, then one
`NovaClient.ask(..., use_tools=False, structured_output=CodeReviewVerdict)`
call — no `tools` kwarg passed at all. Reproduces the ABC's
degrade-on-infra-error contract locally (any exception — diff collection,
the Bedrock call, or a non-`CodeReviewVerdict` structured-output result —
degrades to a passing verdict with a nit finding). Post-dispatch hardening
mirrors `CodexAdversarialReviewDispatcher`: `files_modified` forced to `[]`,
every finding tagged `AdversarialFinding(source="nova-adversarial")` unless
already an `AdversarialFinding`. Added `conf.DEV_LOOP_NOVA_REVIEW_MODEL`
(fallback `"us.anthropic.claude-opus-5"`). Exported from
`dispatchers/__init__.py`. 12 new unit tests in `test_nova_adversarial.py`
(own design — the task's own Test Specification scaffold used `...`
placeholders and omitted the mocking needed to make `TestHardington`/
`TestDegradeOnError` meaningfully assert without live AWS calls; my tests
cover every acceptance-criteria bullet with explicit mocks of `_client.ask`).
All pass; ran the full `tests/flows/dev_loop/` suite (912 passed, 6 skipped)
— the 2 failures present are pre-existing and reproduce identically on `git
stash -u` (verified before/after): `test_lazy_import.py::test_models_module_is_pure`
(order-dependent, passes in isolation) and
`test_qa_codereview.py::test_review_brief_carries_deterministic_qa_results`
(fails identically without this task's changes). No new mypy errors beyond
the pre-existing `LLMCodeDispatcher` override pattern already noted in
TASK-2086. Verified the `code_review.py` <-> `dispatchers/nova.py` import
does NOT create a circular-import failure: traced the actual import order
(`code_review.py`'s own `from ...dispatchers import (Google/Claude/Codex/
Gemini)Dispatcher` line resolves before `dispatchers/__init__.py` reaches
the `nova` import), then empirically confirmed with `python -c "import
parrot.flows.dev_loop.code_review"` / `dispatchers` / `dev_loop` — all
three exit 0.

**Deviations from spec**: none.
