# TASK-2657: Research-partner passthrough (FEAT-482 coordinator wiring) — GATED

**Feature**: FEAT-486 — Refactor Dev-Flow — Per-Seat LLM Configuration, Multi-Agent Development Pool, Configurable Review
**Spec**: `sdd/specs/refactor-dev-flow.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2651, TASK-2656
**Assigned-to**: unassigned

> **✅ GATE CLEARED (2026-09-01).** FEAT-482 merged to `dev` via PR #1281/#1282
> and was merged into this feature branch (merge commit `c3feae208`).
> `dev_flow/research_partner.py` and `dev_flow/complementary_research.py` are
> on disk in this worktree; the contract below has been RE-ANCHORED to their
> real signatures, which differ materially from the ones this task predicted.

---

## Context

Spec §3 Module 5, partner half (goal G6). The partner stays disabled by
default; when the plan enables it, dev_flow builds/injects the FEAT-482
coordinator with the plan's backend+model.

---

## Scope

- In `dev_flow/factories.py`: when `model_plan.research_partner.enabled`,
  resolve the partner via FEAT-482's `resolve_research_partner_backend()` /
  `ResearchPartnerFactory` using the plan's `backend` (`"gpt"` → Mantle
  `gpt-5.6-sol`; `"nova"` → `us.amazon.nova-2-lite-v1:0`) and `model`,
  build the `ComplementaryResearchCoordinator`, and pass it to
  `IdeationNode` via the coordinator kwarg FEAT-482 added.
- Disabled (default) ⇒ no coordinator constructed, byte-identical wiring.
- Soft degradation is FEAT-482's job — do not add failure handling beyond
  passing the coordinator; assert in a test that a coordinator failure does
  not propagate (reusing FEAT-482's own test doubles if available).
- Unit tests: disabled ⇒ no coordinator; enabled ⇒ coordinator with plan
  backend/model; plan model overrides FEAT-482 env default.

**NOT in scope**: implementing any FEAT-482 machinery; console toggle UI
(TASK-2658, which may land before this and simply have the toggle produce
`enabled=true` plans that no-op until this task lands — acceptable, spec
contingency).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_flow/factories.py` | MODIFY | coordinator build + inject |
| `packages/ai-parrot/tests/flows/dev_flow/test_partner_passthrough.py` | CREATE | Unit tests |
| `packages/ai-parrot/src/parrot/flows/dev_flow/complementary_research.py` | MODIFY | **Option B** — additive `backend=`/`model=` injection points (both `None` ⇒ today's conf path) |
| `packages/ai-parrot/src/parrot/flows/dev_flow/research_partner.py` | MODIFY | **Option B** — additive `model=` on `BedrockResearchPartner` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_flow.model_plan import DevFlowModelPlan  # TASK-2651
```

### FEAT-482 signatures — VERIFIED ON DISK 2026-09-01
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py
def validate_research_partner_model(model: str) -> None: ...          # :124
#   raises ValueError for us.anthropic.* / global.anthropic.* / claude-*
def resolve_research_partner_backend(config_getter=None) -> str: ...  # :157
#   reads DEV_FLOW_RESEARCH_PARTNER; "" (unset) = DISABLED, else "gpt"|"nova";
#   also validates the resolved model via validate_research_partner_model.
#   NOTE: takes an INJECTABLE config_getter (same pattern as
#   resolve_adversarial_backend and TASK-2651's resolve_model_plan).
RESEARCH_PARTNER_BACKENDS: Tuple[BackendInfo, ...]   # separate from BACKENDS
#   (TASK-2629 Deviation 2: a non-coding backend in BACKENDS broke an
#   existing development-capability invariant)

# packages/ai-parrot/src/parrot/flows/dev_flow/research_partner.py
class AbstractResearchPartner(ABC):                                   # :87
    partner_name: str; advisory: bool = True
    async def research(*, brief, question, cwd, run_id, node_id,
                       session_host=None) -> ResearchFindings: ...    # :105
class ResearchPartnerFactory:                                         # :132
    register(name) / create(name, **kwargs)                           # :142,:152
def resolve_backend_model(backend: str) -> str: ...                   # :171
#   conf.DEV_FLOW_RESEARCH_PARTNER_GPT_MODEL | _NOVA_MODEL — module
#   attributes, NOT read through a config_getter.
class BedrockResearchPartner(AbstractResearchPartner):                # :197
    def __init__(self, *, backend: str | None = None) -> None: ...    # :216
    def _build_client(self) -> AbstractClient: ...                    # :238
#   _build_client's own docstring anticipates "a future caller that doesn't
#   go through the config-driven path" constructing this with explicit
#   backend= — that is THIS task.

# packages/ai-parrot/src/parrot/flows/dev_flow/complementary_research.py
class ComplementaryResearchCoordinator:                               # :68
    def __init__(self) -> None: ...                                   # :77
    async def research(*, brief, question, cwd, slug, run_id, node_id,
                       session_host=None) -> ComplementaryFindings|None  # :80
#   Resolves the backend from conf INSIDE research() (:117) and builds the
#   partner itself (:127). Never raises.
    @staticmethod _resolve_model_for_backend(backend) -> str           # :214

# packages/ai-parrot/src/parrot/flows/dev_flow/factories.py (post-merge)
#   :140 research_coordinator kwarg; :241 unconditional
#   `ComplementaryResearchCoordinator()` fallback; :253 coordinator=... on
#   IdeationNode. :139 model_plan kwarg (FEAT-486).
```

### Contract corrections vs. what this task predicted
| Predicted | Reality |
|---|---|
| `resolve_research_partner_backend()` in `research_partner.py` | lives in `dev_loop/catalog.py:157` |
| coordinator built "using the plan's backend and model" | `ComplementaryResearchCoordinator.__init__(self)` took **no parameters** |
| a partner accepting a model | `BedrockResearchPartner.__init__(*, backend=None)` — model was conf-only, via `resolve_backend_model` |
| conf keys `DEV_FLOW_RESEARCH_PARTNER_ENABLED/_BACKEND/_MODEL` | shipped as `DEV_FLOW_RESEARCH_PARTNER` (`""`\|`gpt`\|`nova`) + `_GPT_MODEL`/`_NOVA_MODEL` |

### Authorized scope extension (Option B, approved by the user 2026-09-01)
Delivering this task's AC ("enabled ⇒ coordinator built with plan
backend/model; plan overrides env") is IMPOSSIBLE without an injection point
on the coordinator. Implementing it inside this task's original two-file
list would instead have produced a console toggle that can **veto** the
partner but never **enable** it (conf `DEV_FLOW_RESEARCH_PARTNER` defaults to
`""`, so a plan-enabled coordinator still resolves to disabled and returns
`None`) — a silent no-op toggle, contradicting spec G6. The user approved
Option B: add additive, `None`-defaulted injection points to FEAT-482's two
modules. An unconfigured deployment stays byte-identical.

### Does NOT Exist
- ~~FEAT-482 unmerged~~ — CLEARED, see the gate banner above.
- A `model` override anywhere in FEAT-482's partner chain — ADDED by this
  task (Option B), not assumed.
- Any `JudgeSpec` / judge-panel involvement — out of scope, as always.

---

## Implementation Notes

- Plan wins over env for backend/model (consistent with TASK-2651
  precedence); FEAT-482's own env selector remains the fallback when the
  plan says enabled but names nothing.
- Anthropic partner models are rejected by FEAT-482's resolver by design —
  surface that `ValueError` untouched.

---

## Acceptance Criteria

- [ ] FEAT-482 modules verified on disk before any code written
- [ ] Disabled default ⇒ no coordinator, wiring byte-identical
- [ ] Enabled ⇒ coordinator built with plan backend/model; plan overrides env
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_flow/test_partner_passthrough.py -v`; `ruff check` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_flow/test_partner_passthrough.py
class TestPartnerPassthrough:
    def test_disabled_default_no_coordinator(self): ...
    def test_enabled_builds_coordinator_with_plan_selection(self): ...
    def test_plan_overrides_env_default(self, monkeypatch): ...
```

---

## Agent Instructions

1. **Read the spec**; 2. **Check dependencies** — TASK-2651/2656 completed AND the FEAT-482 gate above
3. **Verify the Codebase Contract** — the "expected FROM FEAT-482" block MUST be re-anchored to real file:line before implementing
4. **Update status** in `sdd/tasks/index/refactor-dev-flow.json` → `"in-progress"`
5. **Implement**; 6. **Verify**; 7. **Move this file** to `sdd/tasks/completed/`;
8. **Update index** → `"done"`; 9. **Fill in the Completion Note**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude Opus 5)
**Date**: 2026-09-01
**Notes**:
- **Gate cleared first**: FEAT-482 merged to `dev` (PR #1281/#1282) and into
  this branch (`c3feae208`) before any code was written. The task's
  Codebase Contract — explicitly marked "unverified — VERIFY ON DISK
  before starting" — turned out to be materially wrong and was re-anchored
  to verified file:line signatures BEFORE implementing (see the
  "Contract corrections" table above). Three of four predicted signatures
  differed.
- **Why Option B was necessary.** The blocker was narrow and specific:
  `ComplementaryResearchCoordinator.__init__(self)` took no parameters and
  resolved `DEV_FLOW_RESEARCH_PARTNER` (default `""` = disabled) *inside*
  `research()`. Wiring only the plan's `enabled` flag — the version that
  fits this task's original two-file list — would have produced a console
  toggle that can VETO the seat but never ENABLE it: tick the box, conf
  unset, a coordinator is built, resolves `""`, returns `None`, and the
  partner silently never runs. That is the same silent-no-op trap the
  TASK-2658 code review flagged, and it contradicts spec G6's "explicit
  console enable toggle". Escalated to the user, who approved Option B.
- **Two additive seams** (both `None`-defaulted, so an unconfigured
  deployment is byte-identical):
  * `ComplementaryResearchCoordinator(backend=None, model=None)` — an
    explicit backend bypasses the conf lookup via a new `_resolve_backend()`;
    both `None` preserves the conf path and the "unset ⇒ disabled"
    pure-addition guarantee.
  * `BedrockResearchPartner(model=None)` — `_build_client()` was the only
    place a model can enter the chain, and its own docstring already
    anticipated "a future caller that doesn't go through the config-driven
    path" constructing it with an explicit `backend=`. That caller is this
    task.
- **Neither seam weakens FEAT-482's guards.** An explicit backend is
  validated against `("gpt","nova")` and its effective model against
  `validate_research_partner_model`, so injection cannot smuggle a
  correlated `claude-*`/`us.anthropic.*` model into a seat whose entire
  purpose is decorrelation from the primary Claude seat. Four tests attack
  exactly that (`test_anthropic_model_still_rejected_via_injection`,
  `test_every_anthropic_prefix_rejected`,
  `test_build_client_rejects_injected_anthropic_model`,
  `test_invalid_explicit_backend_rejected`). `_resolve_backend()` raising is
  intentional and safe: `research()`'s existing degradation boundary turns
  it into a logged `partner.degraded`, never a failed run.
- Precedence in `_resolve_research_coordinator()`: explicit
  `research_coordinator` argument > `model_plan` > FEAT-482's
  always-construct default. A plan with `enabled=False` returns `None`, so
  the plan can veto a deployment-level `DEV_FLOW_RESEARCH_PARTNER`
  (tested); no plan at all leaves FEAT-482's behaviour untouched.
- `_EXPLICIT_BACKEND_CHOICES` is pinned equal to
  `catalog._RESEARCH_PARTNER_CHOICES` by test rather than importing a
  private cross-module name — the same convention `conf.py` uses for
  `_NOVA_DEFAULT_CONVERSE_MODEL`.
- 25 new tests pass, including `test_enabled_toggle_does_not_depend_on_env`
  — the direct regression for the veto-only trap. Two of my first-draft
  tests were wrong (they patched `conf.DEV_FLOW_RESEARCH_PARTNER`, but the
  resolver reads `conf.config.get(...)` via navconfig); corrected to pin
  DELEGATION to the resolver instead, matching how FEAT-482's own tests
  inject a `config_getter`.
- FEAT-482's own 52 tests pass unchanged. Full
  `packages/ai-parrot/tests/flows/`: 1820 passed, 15 skipped, 4 failed —
  the 4 pre-existing `dev` failures documented in TASK-2653. ruff clean on
  all four files.

**Deviations from spec**: ONE, user-approved. Two files outside this task's
original list were modified —
`dev_flow/complementary_research.py` and `dev_flow/research_partner.py`
(both FEAT-482's) — to add the injection points, without which this task's
own acceptance criterion ("enabled ⇒ coordinator built with plan
backend/model; plan overrides env") is unimplementable. The task's file
table was updated to record them.

**Root cause worth carrying forward** (raised by the user): this whole
contract-drift episode happened because FEAT-486's worktree was cut from a
`dev` that did not yet contain FEAT-482, even though the spec named
FEAT-482 a hard prerequisite. Tasks were then written and implemented
against a *predicted* upstream API. The fix is process, not code: when a
spec declares a cross-feature dependency, merge that dependency into the
worktree BEFORE decomposing or implementing tasks that consume it.

**Open follow-up (not fixed here — out of scope):** `model_plan.py` still
defines its own `DEV_FLOW_RESEARCH_PARTNER_ENABLED` / `_BACKEND` / `_MODEL`
env keys, which now duplicate FEAT-482's shipped
`DEV_FLOW_RESEARCH_PARTNER` (`""`|`gpt`|`nova`) + `_GPT_MODEL` /
`_NOVA_MODEL`. Two competing key sets for one seat is a trap; they should
be collapsed onto FEAT-482's, along with the key table in
`docs/dev_loop/dev-flow-model-plan.md` and `README`/`GUIA`. Needs its own
task (touches `model_plan.py`, `test_model_plan.py` and three docs).
