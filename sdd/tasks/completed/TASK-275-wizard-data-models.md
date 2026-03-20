# TASK-275: Wizard Data Models

**Feature**: CLI Wizard Setup (FEAT-041)
**Spec**: `sdd/specs/cli-wizard-setup.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: claude-session

---

## Context

> Foundation task for FEAT-041. Defines the three dataclasses used throughout the
> wizard pipeline. Must be created first — all other modules import from here.
> Implements spec Section 2 — Data Models.

---

## Scope

Create `parrot/setup/__init__.py` (empty, marks package) and `parrot/setup/wizard.py`
with only the three dataclass definitions:

- `ProviderConfig` — provider name, model, env_vars dict, llm_string
- `AgentConfig` — agent name, agent_id slug, reference to ProviderConfig, file path
- `WizardResult` — top-level result: provider config, environment, env file path,
  optional agent config, app_bootstrapped flag

**NOT in scope**: `BaseClientWizard` ABC (TASK-276), provider implementations (TASK-277),
scaffolding (TASK-278), CLI command (TASK-280).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/setup/__init__.py` | CREATE | Empty package marker |
| `parrot/setup/wizard.py` | CREATE | Three dataclass definitions only |

---

## Implementation Notes

```python
# parrot/setup/wizard.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class ProviderConfig:
    """Collected configuration for a single LLM provider.

    Attributes:
        provider: Provider key used by LLMFactory (e.g. "anthropic").
        model: Model identifier (e.g. "claude-sonnet-4-6").
        env_vars: Environment variable name → value pairs to write.
        llm_string: Combined string for LLMFactory (e.g. "anthropic:claude-sonnet-4-6").
    """
    provider: str
    model: str
    env_vars: Dict[str, str]
    llm_string: str


@dataclass
class AgentConfig:
    """Collected configuration for agent scaffolding.

    Attributes:
        name: Human-readable agent name (e.g. "My Research Agent").
        agent_id: URL-safe slug (e.g. "my-research-agent").
        provider_config: The LLM provider config for this agent.
        file_path: Absolute path where the agent .py file will be written.
    """
    name: str
    agent_id: str
    provider_config: ProviderConfig
    file_path: str


@dataclass
class WizardResult:
    """Full result of a completed setup wizard run.

    Attributes:
        provider_config: Provider and credentials that were collected.
        environment: Target environment string (e.g. "dev", "prod").
        env_file_path: Path to the .env file that was written.
        agent_config: Agent scaffolding result, if an agent was created.
        app_bootstrapped: True if app.py and run.py were generated.
    """
    provider_config: ProviderConfig
    environment: str
    env_file_path: str
    agent_config: Optional[AgentConfig] = None
    app_bootstrapped: bool = False
```

### Key Constraints
- Use `from __future__ import annotations` for forward reference support.
- Use stdlib `dataclasses` — no Pydantic for these internal models.
- Keep the module lightweight: no click imports, no file I/O.

---

## Acceptance Criteria

- [ ] `parrot/setup/__init__.py` exists (empty)
- [ ] `parrot/setup/wizard.py` exists with `ProviderConfig`, `AgentConfig`, `WizardResult`
- [ ] `from parrot.setup.wizard import ProviderConfig, AgentConfig, WizardResult` works
- [ ] All three dataclasses have complete Google-style docstrings
- [ ] All fields have type hints
- [ ] No linting errors: `ruff check parrot/setup/wizard.py`

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/cli-wizard-setup.spec.md` — Section 2 Data Models
2. **Check dependencies** — none
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** per scope above
5. **Verify** all acceptance criteria
6. **Move this file** to `sdd/tasks/completed/TASK-275-wizard-data-models.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: claude-session
**Date**: 2026-03-10
**Notes**: Created `parrot/setup/__init__.py` (package marker) and `parrot/setup/wizard.py`
with `ProviderConfig`, `AgentConfig`, and `WizardResult` dataclasses. Removed unused
`field` import caught by ruff. All imports verified, dataclass behavior confirmed, linting clean.
**Deviations from spec**: none
