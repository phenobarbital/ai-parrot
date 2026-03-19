# TASK-276: BaseClientWizard ABC and WizardRunner

**Feature**: CLI Wizard Setup (FEAT-041)
**Spec**: `sdd/specs/cli-wizard-setup.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-275
**Assigned-to**: claude-session

---

## Context

> Core extensibility mechanism for FEAT-041. Defines the `BaseClientWizard` abstract
> base class that all provider wizards inherit from, and the `WizardRunner` that
> orchestrates the full pipeline (provider selection → credential collection →
> env writing → agent scaffolding → app bootstrap).
> Implements spec Section 2 — New Public Interfaces and Module 1.

---

## Scope

Extend `parrot/setup/wizard.py` (already has data models from TASK-275) with:

1. `BaseClientWizard` — ABC with `display_name`, `provider_key`, `default_model`
   class vars and abstract `collect()` method; `all_wizards()` classmethod for
   auto-discovery via `__subclasses__()`
2. `WizardRunner` — orchestrates the full pipeline:
   - Present numbered provider selection menu using `click.echo`
   - Instantiate and call the chosen wizard's `collect()` method
   - Ask for target environment name (default: `"dev"`)
   - Check for existing env vars — if any key already exists in the target `.env`,
     ask the user whether to overwrite (per open question answer: yes, detect & offer overwrite)
   - Delegate to `scaffolding.write_env_vars()`
   - Optionally prompt for agent creation → delegate to `scaffolding.scaffold_agent()`
   - Optionally prompt for app bootstrap → delegate to `scaffolding.bootstrap_app()`
   - Return a `WizardResult`

**NOT in scope**: The 5 concrete provider wizards (TASK-277), scaffolding functions
(TASK-278), CLI command registration (TASK-280).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/setup/wizard.py` | MODIFY | Append `BaseClientWizard` ABC and `WizardRunner` class |

---

## Implementation Notes

```python
# Additions to parrot/setup/wizard.py

import re
import click
from abc import ABC, abstractmethod
from typing import ClassVar, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from parrot.setup.scaffolding import AgentScaffolding  # avoid circular at runtime


class BaseClientWizard(ABC):
    """Abstract base class for provider-specific credential wizards.

    To add support for a new LLM provider:
    1. Subclass BaseClientWizard in parrot/setup/providers/<provider>.py
    2. Set display_name, provider_key, default_model class variables
    3. Implement collect() with provider-specific click.prompt calls
    No changes to wizard core are needed.
    """

    display_name: ClassVar[str]
    """Human-readable name shown in the provider selection menu."""

    provider_key: ClassVar[str]
    """Provider key used in LLMFactory (e.g. "anthropic", "openai")."""

    default_model: ClassVar[str]
    """Default model identifier for this provider."""

    @abstractmethod
    def collect(self) -> ProviderConfig:
        """Run interactive prompts and return collected provider config.

        Returns:
            ProviderConfig with provider, model, env_vars, and llm_string.
        """
        ...

    @classmethod
    def all_wizards(cls) -> List["BaseClientWizard"]:
        """Return instances of all registered provider wizard subclasses.

        Returns:
            List of instantiated BaseClientWizard subclasses in registration order.
        """
        return [sub() for sub in cls.__subclasses__()]


class WizardRunner:
    """Orchestrates the full parrot setup wizard pipeline.

    Pipeline:
        1. Display numbered provider menu → user selects provider
        2. Run chosen provider wizard to collect credentials
        3. Ask for target environment (default: "dev")
        4. Check for existing keys in target .env → offer overwrite if found
        5. Write credentials to env file
        6. Optionally scaffold an agent
        7. Optionally bootstrap app.py / run.py
        8. Return WizardResult summary
    """

    def run(self) -> WizardResult:
        """Execute the full setup wizard and return results.

        Returns:
            WizardResult describing everything that was created.
        """
        # Import providers to trigger subclass registration
        import parrot.setup.providers  # noqa: F401

        wizards = BaseClientWizard.all_wizards()
        # ... present menu, collect, write, scaffold, bootstrap
        ...
```

### Existing Key Detection Pattern
```python
# Read existing keys from target .env if it exists
existing_keys = set()
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            existing_keys.add(line.split("=", 1)[0].strip())

# Warn about conflicts and offer per-key overwrite
conflicting = existing_keys & set(env_vars.keys())
for key in conflicting:
    if not click.confirm(f"  {key} already exists. Overwrite?", default=False):
        del env_vars[key]
```

### Key Constraints
- `WizardRunner` must handle `KeyboardInterrupt` gracefully: catch it and print
  `"\nSetup cancelled."` before exiting cleanly (no traceback).
- Provider subclasses are imported lazily inside `run()` to avoid circular imports.
- `parrot/setup/providers/__init__.py` must import all 5 provider modules to
  trigger their `BaseClientWizard` subclass registration.

---

## Acceptance Criteria

- [ ] `BaseClientWizard` ABC exists in `parrot/setup/wizard.py`
- [ ] `BaseClientWizard.all_wizards()` returns all registered subclasses
- [ ] `WizardRunner.run()` presents a numbered provider menu
- [ ] Wizard detects existing env var keys and prompts for overwrite per-key
- [ ] `KeyboardInterrupt` exits cleanly with a message, no traceback
- [ ] Google-style docstrings on all public classes and methods
- [ ] Type hints on all signatures
- [ ] No linting errors: `ruff check parrot/setup/wizard.py`

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/cli-wizard-setup.spec.md` — Sections 2 and 3 Module 1
2. **Check dependencies** — TASK-275 must be done
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** per scope above
5. **Verify** all acceptance criteria
6. **Move this file** to `sdd/tasks/completed/TASK-276-base-client-wizard.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: claude-session
**Date**: 2026-03-10
**Notes**: Extended `parrot/setup/wizard.py` with `BaseClientWizard` ABC (abstract `collect()`,
`all_wizards()` classmethod via `__subclasses__()`) and `WizardRunner` with full pipeline:
provider menu, env path resolution, per-key overwrite detection, scaffolding delegation,
app bootstrap delegation. `WizardRunner` accepts `force` in `__init__` (not `run()`) for
testability. `KeyboardInterrupt` caught in `run()` with clean message then re-raised.
All ruff checks pass.
**Deviations from spec**: `WizardRunner.__init__` also accepts optional `cwd: Path` parameter
for testability (not in spec but consistent with scaffolding design).
