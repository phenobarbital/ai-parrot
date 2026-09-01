# TASK-2651: DevFlowModelPlan — per-seat LLM configuration model + resolver

**Feature**: FEAT-486 — Refactor Dev-Flow — Per-Seat LLM Configuration, Multi-Agent Development Pool, Configurable Review
**Spec**: `sdd/specs/refactor-dev-flow.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 Data Models / §3 Module 1. Foundation of FEAT-486: one Pydantic
config object grouping every dev-flow LLM seat (research primary, research
partner, dev pool, review pair) with env-key defaults and fail-fast
validation. Every other task consumes this model.

---

## Scope

- Implement `DevFlowModelPlan`, `ResearchPartnerPlan`, `ReviewPairPlan`
  (Pydantic v2) in a NEW module `dev_flow/model_plan.py`, per the spec §2
  sketch. Defaults: `research_primary="claude-opus-5"`, partner
  `enabled=False`/`backend="gpt"`/`model="gpt-5.6-sol"`, `dev_pool=[]`,
  review primary `claude-code`/`claude-opus-5` + `counter_model="gpt-5.6-sol"`.
- Implement a resolver that (a) applies env-key defaults (spec §8: exact key
  names settle here — follow `DEV_FLOW_*` conventions via `parrot.conf`,
  e.g. `DEV_FLOW_IDEATION_MODEL` for research_primary, new
  `DEV_FLOW_DEV_POOL` (JSON list) and `DEV_FLOW_REVIEW_COUNTER_MODEL`;
  explicit arguments beat env, env beats built-ins); (b) validates every
  `dev_pool` entry's `agent` against `DevAgentBackend`, raising
  `ValueError` naming the supported backends BEFORE any dispatch;
  (c) produces a `DevAgentPoolConfig` from `dev_pool` for TASK-2652.
- Export the models from `dev_flow/models.py` and `dev_flow/__init__.py`.
- Write unit tests: defaults, env override precedence, unknown-backend
  fail-fast, pool-config production, empty-pool passthrough.

**NOT in scope**: threading the plan into `build_dev_flow` (TASK-2652),
review-pair dispatcher assembly (TASK-2654/2655), ideation/console changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_flow/model_plan.py` | CREATE | Plan models + resolver |
| `packages/ai-parrot/src/parrot/flows/dev_flow/models.py` | MODIFY | Re-export plan models |
| `packages/ai-parrot/src/parrot/flows/dev_flow/__init__.py` | MODIFY | Public export |
| `packages/ai-parrot/tests/flows/dev_flow/test_model_plan.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.models.base import DevAgentSpec  # models/base.py:412
# DevAgentPoolConfig also lives in dev_loop/models/base.py — grep its exact
# class definition and fields before use (verified to exist as a
# DevelopmentNode constructor type, development.py:87-98).
from parrot import conf  # config access pattern used throughout dev_loop (see conf.py:947,:991)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py:407-423
DevAgentBackend = Literal["claude-code","codex","gemini","nvidia","grok","zai","moonshot","google_coding","nova"]
class DevAgentSpec(BaseModel):
    agent: DevAgentBackend   # :420
    model: str = ""          # :421
    count: int = 1           # :422
    escalation_model: str = ""  # :423

# Config-key precedent (env-var-with-fallback pattern):
# conf.py:947  DEV_LOOP_ADVERSARIAL_MODEL (fallback "gpt-5.5")
# conf.py:991  DEV_LOOP_JUDGE_PANEL (JSON)
# catalog.py:63-91 resolve_adversarial_backend(config_getter) — triad-resolver pattern to mirror
```

### Does NOT Exist
- ~~`DevFlowModelPlan` / `dev_flow/model_plan.py`~~ — created BY this task.
- ~~`DEV_FLOW_IDEATION_MODEL` / `DEV_FLOW_RESEARCH_PARTNER*` conf keys~~ — not in `conf.py` as of 2026-09-01 (FEAT-482 will add some; grep `conf.py` first and reuse rather than duplicate if they landed meanwhile).
- ~~`gpt-5.6-sol` wired anywhere~~ — enum member only (`parrot/models/openai.py:22`).
- ~~A model whitelist~~ — model strings are free text by catalog policy (`dev_loop/catalog.py:22-24`); validate backends strictly, never models.

---

## Implementation Notes

### Key Constraints
- Pydantic v2, keyword defaults exactly as in spec §2 sketch.
- Fail-fast `ValueError` message must enumerate the supported backends
  (mirror `server.py:1051-1054` wording style).
- No I/O, no client construction in this module — pure config + resolution.
- Google-style docstrings + strict type hints.

### References in Codebase
- `dev_loop/models/base.py` — DevAgentSpec/JudgeSpec model style
- `dev_loop/catalog.py:63-91` — env-resolution pattern

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_flow/test_model_plan.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_flow/model_plan.py`
- [ ] Imports work: `from parrot.flows.dev_flow.model_plan import DevFlowModelPlan`
- [ ] Unknown backend in `dev_pool` raises `ValueError` naming supported backends

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_flow/test_model_plan.py
import pytest
from parrot.flows.dev_flow.model_plan import DevFlowModelPlan

class TestDevFlowModelPlan:
    def test_defaults(self):
        plan = DevFlowModelPlan()
        assert plan.research_primary == "claude-opus-5"
        assert plan.research_partner.enabled is False
        assert plan.research_partner.model == "gpt-5.6-sol"
        assert plan.dev_pool == []
        assert plan.review.counter_model == "gpt-5.6-sol"

    def test_unknown_backend_fails_fast(self):
        with pytest.raises(ValueError, match="claude-code"):
            DevFlowModelPlan.model_validate(
                {"dev_pool": [{"agent": "not-a-backend", "model": "x"}]}
            )

    def test_env_override_precedence(self, monkeypatch):
        """env beats built-in default; explicit argument beats env."""
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — before writing ANY code, confirm every
   import/signature above still exists; grep `conf.py` for `DEV_FLOW_` keys
   in case FEAT-482 landed some meanwhile — reuse, don't duplicate
4. **Update status** in `sdd/tasks/index/refactor-dev-flow.json` → `"in-progress"`
5. **Implement**, 6. **Verify**, 7. **Move this file** to `sdd/tasks/completed/`,
8. **Update index** → `"done"`, 9. **Fill in the Completion Note**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude Opus 5)
**Date**: 2026-09-01
**Notes**:
- Created `dev_flow/model_plan.py` with `ResearchPartnerPlan`,
  `ReviewPairPlan`, `DevFlowModelPlan` exactly per the spec §2 sketch
  (defaults: research primary `claude-opus-5`; partner disabled/`gpt`/
  `gpt-5.6-sol`; empty `dev_pool`; review `claude-code`/`claude-opus-5`
  + counter `gpt-5.6-sol`).
- `resolve_model_plan(plan, *, config_getter)` implements the
  *explicit > env > built-in* precedence per field, using Pydantic v2
  `model_fields_set` (top level AND nested, so setting one partner field
  does not freeze its siblings). It mirrors
  `dev_loop.catalog.resolve_adversarial_backend`'s injectable
  `config_getter` shape, which means **no `conf.py` edit was needed** —
  keys are read at resolution time via `conf.config.get`. This also keeps
  file fidelity (conf.py is not in this task's file list) and avoids a
  merge conflict with FEAT-482, which will add
  `DEV_FLOW_IDEATION_MODEL` as a module constant.
- Env keys settled (spec §8 open question): `DEV_FLOW_IDEATION_MODEL`
  (shared with FEAT-482), `DEV_FLOW_RESEARCH_PARTNER_ENABLED` /
  `_BACKEND` / `_MODEL`, `DEV_FLOW_DEV_POOL` (JSON array),
  `DEV_FLOW_REVIEW_PRIMARY_BACKEND` / `_MODEL`,
  `DEV_FLOW_REVIEW_COUNTER_MODEL`.
- Fail-fast validation is a `mode="before"` field validator on
  `dev_pool`, so the `ValueError` names the offending backend AND the
  supported set (wording mirrors `server.py:1051-1054`) instead of
  Pydantic's raw `Literal` message. Supported set is read off
  `get_args(DevAgentBackend)` — a new dev_loop backend is picked up
  automatically. Model ids are never validated (catalog free-text policy).
- `to_pool_config()` returns `DevAgentPoolConfig(agents=..., isolation_mode="shared")`
  for TASK-2652, or `None` for an empty pool (leaving DevelopmentNode's
  existing cascade untouched). It copies the spec list.
- 36 unit tests pass; `ruff check` clean (one justified
  `# noqa: TRY004` — a bad `DEV_FLOW_DEV_POOL` JSON *shape* is a config
  value error, and the resolver's documented contract raises `ValueError`).

**Deviations from spec**: none. Two judgement calls recorded:
`ResearchPartnerPlan.backend` is typed `str` (not a `Literal`) exactly as
the spec §2 sketch specifies — validation is deliberately delegated to
FEAT-482's `resolve_research_partner_backend()`; and no
`isolation_mode` knob was added to the plan, since per-agent worktrees
are an explicit spec non-goal.
