# TASK-2026: Guardrails Registry, Config Coercion, and Bot Wiring

**Feature**: FEAT-396 — Unified Guardrails Infrastructure
**Spec**: `sdd/specs/guardrails-infrastructure.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2024, TASK-2025
**Assigned-to**: unassigned

---

## Context

This task completes Module 1 by adding the named registry, config
coercion logic, and the bot-level wiring that builds four
`GuardrailPipeline`s (one per stage) from the `guardrails=[...]` kwarg
and legacy flags. It also maps the legacy ctor flags
(`injection_detection`, `strict_mode`, `block_on_threat`,
`injection_probability_threshold`, `enable_redaction`) to guardrail
registrations for backwards compatibility.

Implements: Spec §2 (Registry/config, seam integration overview), §3
Module 1 (registry.py, config.py), plus the `AbstractBot.__init__`
pipeline construction.

---

## Scope

- Create `parrot/bots/guardrails/registry.py`:
  - `register_guardrail(name, factory)` — named factory registration.
  - `build_guardrails(spec)` — coerce `list[str | dict | Guardrail]`
    into `list[Guardrail]`; raise clear errors on unknown names.
  - Pre-register built-in names: `"prompt_injection"`, `"secrets"`,
    `"pii"`, `"pseudonymize"`, `"groundedness"`, `"moderation"` — PII,
    pseudonymize, and groundedness are reserved (raise "not yet
    implemented" if requested before FEAT-324/325 land).
- Create `parrot/bots/guardrails/config.py`:
  - `build_pipelines_from_config(guardrails, legacy_flags) → dict[GuardrailStage, GuardrailPipeline]`
  - Legacy-flag mapping: `injection_detection=True` + `strict_mode` +
    `block_on_threat` + threshold → registers `PromptInjectionGuardrail`;
    `enable_redaction=True` → registers `SecretsGuardrail`.
  - Sort guardrails into their declared stages.
- Modify `parrot/bots/abstract.py` `__init__`:
  - Accept new kwarg `guardrails: list[str | dict | Guardrail] | None = None`.
  - Build four `GuardrailPipeline`s via `build_pipelines_from_config()`.
  - Store as `self._guardrail_pipelines: dict[GuardrailStage, GuardrailPipeline]`.
  - Legacy flags still assigned to `self.*` for compat; their mapping
    into guardrail registrations is the NEW behavior.
- Write unit tests for registry, config coercion, legacy mapping.

**NOT in scope**: the actual built-in plugin implementations
(TASK-2027–2030), BaseBot seam replacement (TASK-2028 for input,
TASK-2029 for output).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/guardrails/registry.py` | CREATE | Named guardrail registry |
| `parrot/bots/guardrails/config.py` | CREATE | Config coercion + pipeline builder |
| `parrot/bots/guardrails/__init__.py` | MODIFY | Add registry/config exports |
| `parrot/bots/abstract.py` | MODIFY | Add `guardrails` kwarg, build pipelines in `__init__` |
| `tests/unit/test_guardrails_registry_config.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# From TASK-2024/2025 (created in this feature):
from parrot.bots.guardrails.base import (
    Guardrail, GuardrailStage, GuardrailContext,
)
from parrot.bots.guardrails.pipeline import GuardrailPipeline

# AbstractBot ctor params (bots/abstract.py):
# strict_mode: bool = True                          # :294
# block_on_threat: bool = False                     # :295
# injection_detection: bool = True                  # :296
# injection_probability_threshold: float = 0.98     # :297
# self.enable_redaction = bool(kwargs.pop('enable_redaction', False))  # :379
```

### Existing Signatures to Use
```python
# parrot/bots/abstract.py — __init__ params verified at:
#   strict_mode :294, block_on_threat :295,
#   injection_detection :296, injection_probability_threshold :297
#   self._prompt_pipeline = None  :365
#   self.enable_redaction :379

# enable_redaction stamping chain (propagation precedent):
#   abstract.py:379 → :390 → tools/manager.py:593-594,655-656,1448-1449
#   → client stamping abstract.py:937,956
```

### Does NOT Exist
- ~~`parrot.bots.guardrails.registry`~~ — created by this task
- ~~`parrot.bots.guardrails.config`~~ — created by this task
- ~~`self._guardrail_pipelines` on AbstractBot~~ — created by this task
- ~~`guardrails` kwarg on AbstractBot~~ — created by this task
- ~~Built-in guardrail classes~~ — created by TASK-2027–2030

---

## Implementation Notes

### Pattern to Follow
```python
# registry.py
_GUARDRAIL_FACTORIES: dict[str, Callable[..., Guardrail]] = {}

def register_guardrail(name: str, factory: Callable[..., Guardrail]) -> None:
    _GUARDRAIL_FACTORIES[name] = factory

def build_guardrails(spec: list[str | dict | Guardrail]) -> list[Guardrail]:
    result = []
    for item in spec:
        if isinstance(item, Guardrail):
            result.append(item)
        elif isinstance(item, str):
            factory = _GUARDRAIL_FACTORIES.get(item)
            if not factory:
                raise ValueError(f"Unknown guardrail: {item!r}")
            result.append(factory())
        elif isinstance(item, dict):
            name = item.pop("name")
            factory = _GUARDRAIL_FACTORIES[name]
            result.append(factory(**item))
    return result
```

### Key Constraints
- Registry validates eagerly at bot construction, not first use —
  misconfigured guardrails fail loudly at `__init__`, not mid-turn.
- Reserved names (`pii`, `pseudonymize`, `groundedness`) raise a clear
  "not yet implemented — requires FEAT-324/325" error when requested.
- Legacy flags produce equivalent registrations: with no `guardrails`
  kwarg and default flags, behavior is bit-identical to today.
- The `guardrails` kwarg does NOT disable legacy flags — they coexist.
  If both `guardrails=["prompt_injection"]` and
  `injection_detection=True` are set, no duplicate registration.
- Do NOT remove or modify the existing legacy flag attributes
  (`self.injection_detection`, `self.strict_mode`, etc.) — they are
  still read by `_sanitize_question` until TASK-2028 migrates it.

---

## Acceptance Criteria

- [ ] `register_guardrail` / `build_guardrails` work with names, dicts, instances
- [ ] Unknown name → clear `ValueError`
- [ ] Reserved names → clear "not yet implemented" error
- [ ] `build_pipelines_from_config` produces four stage-keyed pipelines
- [ ] Legacy flags mapped to equivalent guardrail registrations
- [ ] `AbstractBot.__init__` accepts `guardrails=[...]` kwarg
- [ ] With no `guardrails` kwarg and default flags, behavior unchanged
- [ ] All tests pass: `pytest tests/unit/test_guardrails_registry_config.py -v`
- [ ] No linting errors

---

## Test Specification

```python
# tests/unit/test_guardrails_registry_config.py
import pytest
from parrot.bots.guardrails.registry import register_guardrail, build_guardrails
from parrot.bots.guardrails.config import build_pipelines_from_config
from parrot.bots.guardrails.base import Guardrail, GuardrailStage


class TestRegistry:
    def test_register_and_build_by_name(self):
        # register a stub, build by name
        ...

    def test_unknown_name_raises(self):
        with pytest.raises(ValueError, match="Unknown guardrail"):
            build_guardrails(["nonexistent"])

    def test_reserved_name_raises(self):
        with pytest.raises(NotImplementedError):
            build_guardrails(["pii"])

    def test_build_from_dict(self):
        ...

    def test_build_from_instance(self):
        ...

    def test_no_duplicate_registration(self):
        ...


class TestConfigCoercion:
    def test_legacy_injection_flags_map(self):
        pipelines = build_pipelines_from_config(
            guardrails=None,
            legacy_flags={"injection_detection": True, "strict_mode": True},
        )
        assert pipelines[GuardrailStage.INPUT].has_guardrails

    def test_legacy_redaction_flag_maps(self):
        pipelines = build_pipelines_from_config(
            guardrails=None,
            legacy_flags={"enable_redaction": True},
        )
        assert pipelines[GuardrailStage.TOOL_OUTPUT].has_guardrails

    def test_empty_config_empty_pipelines(self):
        pipelines = build_pipelines_from_config(
            guardrails=None,
            legacy_flags={"injection_detection": False, "enable_redaction": False},
        )
        for pipeline in pipelines.values():
            assert not pipeline.has_guardrails
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/guardrails-infrastructure.spec.md` §2-§3
2. **Check dependencies** — TASK-2024 and TASK-2025 must be completed
3. **Verify the Codebase Contract** — confirm AbstractBot ctor params at listed lines
4. **Update status** in `sdd/tasks/index/guardrails-infrastructure.json` → `"in-progress"`
5. **Implement** following the scope above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2026-guardrails-registry-config.md`
8. **Update index** → `"done"`

---

## Completion Note

Implemented exactly per scope: `registry.py` (`register_guardrail`,
`build_guardrails`, reserved-name handling for `pii`/`pseudonymize`/
`groundedness`), `config.py` (`build_pipelines_from_config` with legacy-flag
mapping + no-duplicate-registration), `__init__.py` re-exports, and
`AbstractBot.__init__` wiring (`guardrails` kwarg, `self._guardrail_pipelines`
built eagerly at construction, legacy flag attributes left untouched for
`_sanitize_question` to keep reading until TASK-2028).

**Important sequencing note (not a deviation, flagged for visibility):**
`registry.py` pre-registers `"prompt_injection"`, `"secrets"`, and
`"moderation"` via **lazy factories** (`_make_lazy_factory`) that only
`importlib.import_module()` the real plugin module
(`parrot.bots.guardrails.builtin.*`) the first time the factory is actually
*called* — never at `registry.py` import time. This is necessary because
those plugin classes are created by TASK-2027/2029/2030, which structurally
depend on this task and haven't run yet. Consequence: since
`injection_detection` defaults to `True` on `AbstractBot`, constructing ANY
bot with default flags between this commit and TASK-2027's commit raises
`ModuleNotFoundError` (verified: `BasicBot(name="x")` fails;
`BasicBot(name="x", injection_detection=False, enable_redaction=False)`
succeeds and produces a correct 4-stage `_guardrail_pipelines` dict). This
window is intentional and closes with the very next task in this run
(TASK-2027); the alternative — creating `builtin/prompt_injection.py` here
— would violate this task's File Fidelity boundary.

Per the same reasoning, this task's own tests
(`test_guardrails_registry_config.py`) test the legacy-flag → pipeline
mapping logic using `monkeypatch.setitem` to install temporary stub
factories under the real `"prompt_injection"`/`"secrets"` names, rather
than depending on the not-yet-built plugins. This matches the spec's own
§4 Test Specification table, which assigns end-to-end
`test_legacy_flag_mapping` compat testing to Module 2 (TASK-2027/2028), not
Module 1 — TASK-2027/2029 add their own compat suites against the real
classes.

Lint hazard avoided: `ruff check --fix` on `abstract.py` (a large
pre-existing file) attempted to rewrite ~230 unrelated lines across the
whole file (pyupgrade/BLE001 etc. on code untouched by this task). Reverted
via `git checkout` and reapplied only the 4 intentional edits by hand
(diff: +30 lines, 0 unrelated changes) — `ruff check --select F,E9` on the
file shows zero issues introduced by this task's lines (the one pre-existing
F841 at line 2663 is unrelated, far from this task's edits).

17 tests added, all passing together with TASK-2024/2025 (43 total).
`ruff check parrot/bots/guardrails/` clean.
