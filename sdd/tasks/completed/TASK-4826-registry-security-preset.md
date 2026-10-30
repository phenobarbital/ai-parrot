# TASK-4826: Registry — `jailbreak` / `prompt_leakage` names + `security` preset

**Feature**: FEAT-761 — Agent Security Guardrails (Jailbreak, Tool-Output Injection, Prompt Leakage)
**Spec**: `sdd/specs/agent-security-guardrails.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 item 7 + §3 Module 7 (registry part). The registry already registers names
whose plugin module lands later, via lazy factories (precedent: `registry.py:139-145`,
"registering their names here now … the actual plugin module is only imported the
first time one is actually built"). This task registers `jailbreak` and
`prompt_leakage` the same way (modules land in TASK-4835 / TASK-4836) and adds the
`security` preset — resolved user decision: ships in v1, expands to
`prompt_injection + jailbreak + prompt_leakage` with defaults.

The preset must also be visible to `config.py`'s legacy-flag dedupe: today
`build_pipelines_from_config` skips the legacy `prompt_injection` registration only if
`"prompt_injection"` is literally in the explicit spec (`config.py:81-86`). With
`guardrails=["security"]` + `injection_detection=True` that check would miss and
register `prompt_injection` twice. Presets are therefore expanded at the top of
`build_pipelines_from_config`, before `requested_names` is computed.

---

## Scope

- Add `GUARDRAIL_PRESETS: dict[str, tuple[str, ...]]` and `expand_presets(spec)` to
  `registry.py`; make `build_guardrails()` expand presets (idempotent).
- Register lazy factories `jailbreak` → `parrot.bots.guardrails.builtin.jailbreak.JailbreakGuardrail`
  and `prompt_leakage` → `parrot.bots.guardrails.builtin.prompt_leakage.PromptLeakageGuardrail`.
- In `config.py`, expand presets before computing `requested_names`.
- Tests (monkeypatch the two new factories — their modules do not exist yet).

**NOT in scope**: the guardrail classes themselves; dict-form presets
(`{"name": "security", ...}` is NOT supported — a preset name inside a dict raises
`ValueError` with a clear message, because per-member policy belongs to the members).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/guardrails/registry.py` | MODIFY | presets + 2 lazy factories |
| `packages/ai-parrot/src/parrot/bots/guardrails/config.py` | MODIFY | expand presets before legacy dedupe |
| `packages/ai-parrot/tests/unit/test_guardrails_security_preset.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.guardrails.registry import register_guardrail, build_guardrails  # registry.py:41, :95
from parrot.bots.guardrails.config import build_pipelines_from_config            # config.py:39
from parrot.bots.guardrails.base import Guardrail, GuardrailStage                # base.py:97, :15
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/guardrails/registry.py
_GUARDRAIL_FACTORIES: dict[str, Callable[..., Guardrail]] = {}           # :26
_RESERVED_NAMES: dict[str, str] = {...}                                  # :35-38 (pii, pseudonymize)
def register_guardrail(name: str, factory: Callable[..., Guardrail]) -> None:          # :41
def _make_lazy_factory(module_path: str, class_name: str) -> Callable[..., Guardrail]: # :52
def _build_by_name(name: str, **kwargs: Any) -> Guardrail:                             # :69
def build_guardrails(spec: list[str | dict[str, Any] | Guardrail]) -> list[Guardrail]: # :95
    # str branch: elif isinstance(item, str): result.append(_build_by_name(item))      # :121-122
    # dict branch pops "name" :123-131
# last registration: pbac  :171-174

# packages/ai-parrot/src/parrot/bots/guardrails/config.py
def _requested_name(item) -> str | None:                                  # :17
def build_pipelines_from_config(guardrails=None, legacy_flags=None, on_telemetry=None)  # :39
    explicit_spec: list[str | dict[str, Any] | Guardrail] = list(guardrails or [])     # :80
    requested_names = {...}                                               # :81-83
```

### Does NOT Exist
- ~~`parrot.bots.guardrails.builtin.jailbreak`~~ / ~~`...builtin.prompt_leakage`~~ — land in TASK-4835 / TASK-4836; tests MUST monkeypatch `_GUARDRAIL_FACTORIES`, never import them.
- ~~`GUARDRAIL_PRESETS` / `expand_presets`~~ — created here.
- ~~any existing preset mechanism~~ in the registry or config.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/bots/guardrails/registry.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/bots/guardrails/config.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/test_guardrails_security_preset.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/guardrails/registry.py#build_guardrails",
    "sym:packages/ai-parrot/src/parrot/bots/guardrails/registry.py#register_guardrail",
    "sym:packages/ai-parrot/src/parrot/bots/guardrails/registry.py#_make_lazy_factory",
    "sym:packages/ai-parrot/src/parrot/bots/guardrails/config.py#build_pipelines_from_config"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add presets + `expand_presets` to `registry.py` — *why*: one expansion function used by both `build_guardrails` and `config.py`.
2. Register the two lazy factories after `pbac` — *why*: names usable in config immediately; plugin imported only when built.
3. Expand presets at the top of `build_pipelines_from_config` — *why*: legacy dedupe must see concrete names.
4. Tests with monkeypatched factories.

### `packages/ai-parrot/src/parrot/bots/guardrails/registry.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^def register_guardrail' registry.py)
# BEFORE — insert above `def register_guardrail(name: str, factory: Callable[..., Guardrail]) -> None:` (verified: registry.py:41)
#: Named bundles expanded in place by `expand_presets` (FEAT-761). Members
#: are built with their own defaults; per-member policy is configured by
#: listing the member explicitly instead of the preset.
GUARDRAIL_PRESETS: dict[str, tuple[str, ...]] = {
    "security": ("prompt_injection", "jailbreak", "prompt_leakage"),
}


def expand_presets(
    spec: list[str | dict[str, Any] | Guardrail],
) -> list[str | dict[str, Any] | Guardrail]:
    """Replace preset names in ``spec`` with their member names, in order.

    Idempotent; non-preset entries pass through unchanged. A member that is
    already present elsewhere in ``spec`` (by name) is not duplicated — the
    explicit entry wins, so ``["security", {"name": "jailbreak", ...}]``
    yields one configured ``jailbreak``.

    Raises:
        ValueError: A preset name appears inside a dict entry.
    """
    # FILL IN: expansion with explicit-entry-wins dedupe — bounded by "no guardrail name registered twice"
```
```python
# occurrences: 1 (verified: grep -c '    result: list\[Guardrail\] = \[\]' registry.py)
# BEFORE — insert above `    result: list[Guardrail] = []` (inside build_guardrails, verified: registry.py:117)
    spec = expand_presets(spec)
```
```python
# occurrences: 1 (verified: grep -c '    _make_lazy_factory("parrot.bots.guardrails.builtin.pbac", "PBACToolCallGuardrail"),' registry.py)
# AFTER — insert below the closing `)` of the pbac registration (verified: registry.py:173-174)
# FEAT-761: plugin modules land in later tasks of the feature; lazy factories
# keep the onnx/rapidfuzz boundary untouched until a bot requests them.
register_guardrail(
    "jailbreak",
    _make_lazy_factory("parrot.bots.guardrails.builtin.jailbreak", "JailbreakGuardrail"),
)
register_guardrail(
    "prompt_leakage",
    _make_lazy_factory("parrot.bots.guardrails.builtin.prompt_leakage", "PromptLeakageGuardrail"),
)
```

### `packages/ai-parrot/src/parrot/bots/guardrails/config.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from .registry import build_guardrails' config.py)
# REPLACE `from .registry import build_guardrails` (verified: config.py:14) with:
from .registry import build_guardrails, expand_presets
```
```python
# occurrences: 1 (verified: grep -c '    explicit_spec: list\[str | dict\[str, Any\] | Guardrail\] = list(guardrails or \[\])' config.py)
# REPLACE (verified: config.py:80) with:
    explicit_spec: list[str | dict[str, Any] | Guardrail] = expand_presets(list(guardrails or []))
```
**Why**: everything downstream (`requested_names`, legacy dedupe, `build_guardrails`) then sees concrete names.

### `packages/ai-parrot/tests/unit/test_guardrails_security_preset.py` (CREATE)
```python
"""FEAT-761 TASK-4826 — registry names + security preset."""
import pytest

from parrot.bots.guardrails import registry
from parrot.bots.guardrails.config import build_pipelines_from_config
from parrot.bots.guardrails.registry import GUARDRAIL_PRESETS, build_guardrails, expand_presets

# FILL IN: fixture monkeypatching registry._GUARDRAIL_FACTORIES for prompt_injection/jailbreak/prompt_leakage
# with stub Guardrail factories (record kwargs); tests:
#  - expand_presets(["security"]) == ["prompt_injection", "jailbreak", "prompt_leakage"]
#  - explicit member wins, no duplicates; idempotent; non-preset passthrough
#  - {"name": "security"} -> ValueError
#  - build_guardrails(["security"]) builds 3 instances
#  - build_pipelines_from_config(["security"], legacy_flags={"injection_detection": True}) registers prompt_injection ONCE
#  - "jailbreak"/"prompt_leakage" are registered names (in registry._GUARDRAIL_FACTORIES) — bounded by AC list
```

### FILL IN checklist
- [ ] `registry.py::expand_presets` — order-preserving expansion, explicit-wins dedupe, dict-preset error
- [ ] tests

---

## Acceptance Criteria

- [ ] `guardrails=["security"]` yields exactly `prompt_injection`, `jailbreak`, `prompt_leakage`.
- [ ] Legacy `injection_detection=True` + `"security"` registers `prompt_injection` once.
- [ ] Registering the names imports neither plugin module (lazy).
- [ ] Existing registry/config tests pass unchanged.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/test_guardrails_security_preset.py -q`
- `pytest packages/ai-parrot/tests/unit/test_guardrails_registry_config.py -q`

---

## Test Specification

See CREATE block. Stub factories only — never import `builtin.jailbreak`/`builtin.prompt_leakage`.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug agent-security-guardrails --feature-id FEAT-761`).
2. Confirm `Depends-on` are `done`; re-verify anchors with `grep -c`.
3. Mark `in-progress`; implement; complete every `# FILL IN:`.
4. Run Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
5. Commit only listed files; `scripts/sdd/close_task.sh TASK-4826 agent-security-guardrails verified`; fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Seat: gpt-5.6-sol · Backend: codex · Attempts: 1)
**Date**: 2026-10-27
**Notes**: Delivered and merged; merge-tier validation green. Closed via close_task.sh (no durable review-evidence artifact writable). Deliverable reviewed by worker at merge.

**Deviations from spec**: none
