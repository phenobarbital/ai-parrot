# TASK-5141: Expert tiers: EXPERT_<TIER>_LLM, per-tier keys, usage tag

**Feature**: FEAT-796 — Per-Component LLM Defaults
**Spec**: `sdd/specs/per-component-llm-defaults.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5138, TASK-5139
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (+M7). Expert tiers read `EXPERT_<TIER>_LLM`; keys are **per tier only** (`EXPERT_<TIER>_<PROVIDER>_API_KEY`, spec §8 resolved — no shared `EXPERT_<P>_API_KEY`). Expert calls are tagged `EXPERT_<TIER>`.

---

## Scope

- policy.py: keep `DEFAULT_TIER_POLICY` (exported, unchanged values); add `tier_policy(tier)` overlaying `resolve_component_llm(f'EXPERT_{tier.name}', builtin=...)`; `model_config_for` uses `tier_policy`.
- agent.py: inject `api_key` from `resolve_component_api_key((f'EXPERT_{tier.name}',), provider)` into kwargs when set and not already present; override `ask` to run inside `usage_component(f'EXPERT_{tier.name}')`.
- Tests.

**NOT in scope**: Registry override validation (`registry.py:75-102`) — unchanged and must still win. `ask_stream` tagging (async generator) — leave a docstring note.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/experts/policy.py` | MODIFY | tier_policy |
| `packages/ai-parrot/src/parrot/experts/agent.py` | MODIFY | api key + tagging |
| `packages/ai-parrot/tests/experts/test_expert_llm_defaults.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use these exact imports, names and signatures. Verify anything not listed
> before using it. Anchors verified at dev `e179aba02f`.

### Verified Imports
```python
from parrot.llm_defaults import resolve_component_llm, resolve_component_api_key  # TASK-5138
from parrot.observability.context import usage_component  # TASK-5139
from parrot.experts.models import ExpertTier  # verified: policy.py:7
from parrot.models.basic import ModelConfig  # verified: policy.py:8
```

### Existing Signatures to Use
```python
# experts/policy.py
DEFAULT_TIER_POLICY: Final[dict[ExpertTier, dict[str, Any]]] = {  # line 10
def model_config_for(tier: ExpertTier, *, overrides: Mapping[str, Any] | None = None) -> ModelConfig:  # 19
    return ModelConfig(**{**DEFAULT_TIER_POLICY[tier], **dict(overrides or {})})  # 21
# experts/agent.py
class ExpertAgent(IdentityMixin, Agent):  # 17
    def __init__(self, bundle: ExpertBundle, *, resolver, model_config: ModelConfig, toolkits, allowed_tools, workspace=None, **kwargs) -> None:  # 22
            llm=f"{model_config.provider}:{model_config.model}",  # 54
# bundle.manifest.tier : ExpertTier
```

### Does NOT Exist
- ~~`ModelConfig.api_key`~~ — no such field; do NOT add one
- ~~`EXPERT_GOOGLE_API_KEY` (shared)~~ — rejected in spec §8; must be ignored
- ~~`ExpertAgent.ask` override~~ — does not exist yet; added here

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/experts/policy.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/experts/agent.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/experts/test_expert_llm_defaults.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/experts/policy.py#model_config_for",
    "sym:packages/ai-parrot/src/parrot/experts/agent.py#ExpertAgent"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `tier.name` gives `JUDGMENT`/`BALANCED`/`TEMPLATED` — verify ExpertTier is an Enum with those member names before relying on it.
- Temperature comes from the builtin dict; env changes only provider/model.

---

## Implementation Blueprint

> Write each block nearly verbatim, then complete every `# FILL IN:` marker.
> Never change a signature, name or path the blueprint fixes.

### Steps (in order)
1. policy.py: add `tier_policy`, route `model_config_for` through it — *why*: env override, registry overrides still last.
2. agent.py: key injection before `super().__init__` — *why*: per-tier billing.
3. agent.py: `ask` override with tagging — *why*: AC10.
4. Tests.

### `packages/ai-parrot/src/parrot/experts/policy.py` (MODIFY)
```python
# occurrences: 1 — DEFAULT_TIER_POLICY at line 10 stays as is. Add after it:
def tier_policy(tier: ExpertTier) -> dict[str, Any]:
    """Builtin tier dict with provider/model overridden by EXPERT_<TIER>_LLM / DEFAULT_LLM (FEAT-796)."""
    from parrot.llm_defaults import resolve_component_llm  # noqa: PLC0415

    base = dict(DEFAULT_TIER_POLICY[tier])
    resolved = resolve_component_llm(f"EXPERT_{tier.name}", builtin=f"{base['provider']}:{base['model']}")
    base.update(provider=resolved.provider, model=resolved.model)
    return base
# and line 21 becomes:
    return ModelConfig(**{**tier_policy(tier), **dict(overrides or {})})
```

### `packages/ai-parrot/src/parrot/experts/agent.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '            llm=f"{model_config.provider}:{model_config.model}",' agent.py) — line 54
# BEFORE `super().__init__(` insert:
        tier_component = f"EXPERT_{bundle.manifest.tier.name}"
        api_key = resolve_component_api_key((tier_component,), model_config.provider)
        if api_key and "api_key" not in kwargs:
            kwargs["api_key"] = api_key
# AFTER `self.model_config = model_config` add:
        self._usage_component = tier_component

# New method on ExpertAgent:
    async def ask(self, *args: Any, **kwargs: Any) -> Any:
        """Run ``Agent.ask`` with usage tagged as this expert's tier (FEAT-796)."""
        with usage_component(self._usage_component):
            return await super().ask(*args, **kwargs)
# FILL IN: confirm Agent/AbstractBot passes `api_key` kwarg through to the client
#          (grep "api_key" in bots/abstract.py around _parse_llm/llm_kwargs); if not, pass it the way it is accepted — bounded by AC3
```

### FILL IN checklist
- [ ] api_key reaches the client; bounded by AC3
- [ ] `ExpertTier` member names

---

## Acceptance Criteria

- [ ] Unset env → `model_config_for` returns today's values for all tiers
- [ ] `EXPERT_BALANCED_LLM=openai:<m>` changes only BALANCED
- [ ] `DEFAULT_TIER_POLICY` values unchanged
- [ ] `EXPERT_<TIER>_GOOGLE_API_KEY` reaches only that tier; `EXPERT_GOOGLE_API_KEY` ignored
- [ ] Registry overrides still win
- [ ] Expert `ask` calls tagged `EXPERT_<TIER>`

---

## Validation Commands

- `pytest packages/ai-parrot/tests/experts/test_expert_llm_defaults.py -q`
- `pytest packages/ai-parrot/tests/experts/test_integration.py -q`

---

## Test Specification

```python
def test_tier_policy_env_override(monkeypatch): ...
def test_default_tier_policy_unchanged(): ...
def test_expert_agent_api_key_injected(monkeypatch): ...  # BALANCED key only; shared EXPERT_GOOGLE_API_KEY ignored
async def test_expert_ask_tagged(monkeypatch): ...
```

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug per-component-llm-defaults --feature-id FEAT-796`), never on `dev`.
2. Read the spec; confirm every `Depends-on` task is `done` in `sdd/tasks/index/per-component-llm-defaults.json`.
3. Verify the Codebase Contract (re-run the `grep -c` of every anchor) before writing code.
4. Mark the task `in-progress` in the index and commit only that file.
5. Implement from the blueprint; complete every `# FILL IN:`.
6. Run the Validation Commands with `PYTHONPATH` set to the changed packages' absolute `src` dirs; `ruff check` the touched files.
7. Commit only the listed files; close with `parrot sdd task close TASK-5141 per-component-llm-defaults verified`; fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker; seat gpt-5.6-sol (codex), 1 attempt, 0 retries
**Date**: 2026-11-04
**Notes**: Reviewed vs task; 34 feature tests pass. Review not recorded (coder_record_review server bug); 0 fix commits.

**Deviations from spec**: none
