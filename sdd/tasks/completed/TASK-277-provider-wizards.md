# TASK-277: Provider Wizard Implementations (5 providers)

**Feature**: CLI Wizard Setup (FEAT-041)
**Spec**: `sdd/specs/cli-wizard-setup.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-276
**Assigned-to**: unassigned

---

## Context

> Implements the five concrete `BaseClientWizard` subclasses — one per supported
> cloud LLM provider. Each wizard collects the provider-specific credentials and
> model selection via interactive click prompts.
> Implements spec Section 3 — Module 2.

---

## Scope

Create the providers package and all five provider wizard files:

| File | Class | Provider key | Default model | Env vars |
|---|---|---|---|---|
| `parrot/setup/providers/__init__.py` | — | — | — | imports all 5 modules |
| `parrot/setup/providers/anthropic.py` | `AnthropicWizard` | `anthropic` | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` |
| `parrot/setup/providers/google.py` | `GoogleWizard` | `google` | `gemini-2.5-flash` | `GOOGLE_API_KEY` |
| `parrot/setup/providers/openai.py` | `OpenAIWizard` | `openai` | `gpt-4o` | `OPENAI_API_KEY`, `OPENAI_BASE_URL` |
| `parrot/setup/providers/xai.py` | `XAIWizard` | `xai` | `grok-3` | `XAI_API_KEY` |
| `parrot/setup/providers/openrouter.py` | `OpenRouterWizard` | `openrouter` | `anthropic/claude-sonnet-4-6` | `OPENROUTER_API_KEY` |

**NOT in scope**: `BaseClientWizard` (TASK-276), scaffolding (TASK-278), CLI
command (TASK-280), tests (TASK-281).

---

## Files to Create

| File | Action |
|---|---|
| `parrot/setup/providers/__init__.py` | CREATE |
| `parrot/setup/providers/anthropic.py` | CREATE |
| `parrot/setup/providers/google.py` | CREATE |
| `parrot/setup/providers/openai.py` | CREATE |
| `parrot/setup/providers/xai.py` | CREATE |
| `parrot/setup/providers/openrouter.py` | CREATE |

---

## Implementation Notes

### `__init__.py` — triggers subclass registration
```python
# parrot/setup/providers/__init__.py
"""Provider wizard implementations — imported to register BaseClientWizard subclasses."""
from parrot.setup.providers.anthropic import AnthropicWizard  # noqa: F401
from parrot.setup.providers.google import GoogleWizard  # noqa: F401
from parrot.setup.providers.openai import OpenAIWizard  # noqa: F401
from parrot.setup.providers.xai import XAIWizard  # noqa: F401
from parrot.setup.providers.openrouter import OpenRouterWizard  # noqa: F401

__all__ = [
    "AnthropicWizard",
    "GoogleWizard",
    "OpenAIWizard",
    "XAIWizard",
    "OpenRouterWizard",
]
```

### Pattern for each wizard
```python
# parrot/setup/providers/anthropic.py
import click
from parrot.setup.wizard import BaseClientWizard, ProviderConfig


class AnthropicWizard(BaseClientWizard):
    """Wizard for Anthropic (Claude) credential collection."""

    display_name: str = "Anthropic (Claude)"
    provider_key: str = "anthropic"
    default_model: str = "claude-sonnet-4-6"

    def collect(self) -> ProviderConfig:
        """Collect Anthropic credentials interactively.

        Returns:
            ProviderConfig with ANTHROPIC_API_KEY and selected model.
        """
        click.echo(f"\nConfiguring {self.display_name}")
        model = click.prompt("Model", default=self.default_model)
        api_key = click.prompt("ANTHROPIC_API_KEY", hide_input=True)
        return ProviderConfig(
            provider=self.provider_key,
            model=model,
            env_vars={"ANTHROPIC_API_KEY": api_key},
            llm_string=f"{self.provider_key}:{model}",
        )
```

### OpenAI wizard — also asks for base_url
```python
# parrot/setup/providers/openai.py
OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"

class OpenAIWizard(BaseClientWizard):
    display_name: str = "OpenAI"
    provider_key: str = "openai"
    default_model: str = "gpt-4o"

    def collect(self) -> ProviderConfig:
        click.echo(f"\nConfiguring {self.display_name}")
        model = click.prompt("Model", default=self.default_model)
        base_url = click.prompt("Base URL", default=OPENAI_DEFAULT_BASE_URL)
        api_key = click.prompt("OPENAI_API_KEY", hide_input=True)
        return ProviderConfig(
            provider=self.provider_key,
            model=model,
            env_vars={
                "OPENAI_API_KEY": api_key,
                "OPENAI_BASE_URL": base_url,
            },
            llm_string=f"{self.provider_key}:{model}",
        )
```

### Key Constraints
- All API key prompts MUST use `hide_input=True`.
- `display_name`, `provider_key`, `default_model` must be plain class attributes
  (not `ClassVar` annotations only — assign actual string values).
- `collect()` must return a `ProviderConfig` with a non-empty `llm_string`.

---

## Acceptance Criteria

- [ ] `parrot/setup/providers/` package exists with `__init__.py`
- [ ] All 5 provider wizard files exist
- [ ] Each wizard has `display_name`, `provider_key`, `default_model` set
- [ ] Each wizard's `collect()` uses `hide_input=True` for API key prompts
- [ ] `OpenAIWizard.collect()` prompts for `OPENAI_BASE_URL` with correct default
- [ ] `BaseClientWizard.all_wizards()` returns all 5 when providers package is imported
- [ ] Google-style docstrings on all classes and `collect()` methods
- [ ] Type hints on all signatures
- [ ] No linting errors: `ruff check parrot/setup/providers/`

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/cli-wizard-setup.spec.md` — Section 3 Module 2
2. **Check dependencies** — TASK-276 must be done
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** per scope above (all 6 files)
5. **Verify** all acceptance criteria
6. **Move this file** to `sdd/tasks/completed/TASK-277-provider-wizards.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-03-10
**Notes**: Created all 5 provider wizard files plus `__init__.py`. All wizards register via `__subclasses__()` and `all_wizards()` returns all 5. Ruff linting passes clean. All API key prompts use `hide_input=True`. OpenAI wizard includes `OPENAI_BASE_URL` with correct default.
**Deviations from spec**: None.
