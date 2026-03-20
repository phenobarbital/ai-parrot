# Feature Specification: CLI Wizard Setup

**Feature ID**: FEAT-041
**Date**: 2026-03-10
**Author**: Jesus Lara
**Status**: approved
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement
New users of AI-Parrot face a steep onboarding curve: they must manually configure
environment files, understand `LLMFactory` provider strings, write boilerplate agent
code, and wire up `app.py` / `run.py` before they can run their first agent. There is
no guided, interactive path from zero to a running agent. This creates friction that
discourages adoption and leads to misconfigured deployments.

### Goals
- Provide a `parrot setup` CLI command that walks new users through first-time
  configuration interactively via a terminal wizard
- Support the five primary cloud LLM providers: **Google**, **OpenAI**, **Anthropic**,
  **xAI (Grok)**, and **OpenRouter** — each with provider-specific credential prompts
- Write collected credentials to the correct environment file (`env/.env` or
  `env/{env}/.env`) without exposing them in terminal history
- Optionally scaffold a new Agent file in `AGENTS_DIR` using a Jinja2/string template,
  populated with user selections
- Generate a minimal `app.py` and `run.py` in the project root so users can
  immediately run `python run.py`
- Make the wizard extensible: adding a new provider requires only a new
  `BaseClientWizard` subclass — no changes to the wizard core

### Non-Goals (explicitly out of scope)
- Setting up local/self-hosted LLM servers (Ollama, vLLM, llama.cpp) — too many
  environment variables; covered by `localllm-client` spec (FEAT-006)
- Database or Redis configuration
- Deployment or containerization (Docker, Pulumi, etc.)
- Editing existing credentials — wizard is for first-time setup; re-run overwrites
- GUI or web-based wizard

---

## 2. Architectural Design

### Overview
The wizard is a new Click command (`setup`) attached to the existing `parrot` CLI group
in `parrot/cli.py`. The wizard is implemented as a pipeline of steps:

1. **Provider selection** — user picks an LLM provider from a numbered menu
2. **Provider wizard** — a `BaseClientWizard` subclass collects provider-specific
   credentials and model selection using `click.prompt` with hidden input where appropriate
3. **Environment writing** — credentials are appended to the correct `.env` file,
   creating parent directories as needed
4. **Agent scaffolding** (optional) — user names an agent; the wizard generates a
   `.py` file in `AGENTS_DIR` from a template
5. **App bootstrap** (optional) — wizard generates `app.py` and `run.py` in the
   project root from templates

Each provider wizard is a class implementing the `BaseClientWizard` protocol. The
wizard runner discovers all registered subclasses and presents them as choices,
making it trivially extensible.

### Component Diagram
```
parrot/cli.py
    └── cli.add_command(setup)
            │
            ▼
parrot/setup/
    ├── __init__.py
    ├── cli.py                  ← @click.command "setup", orchestrates pipeline
    ├── wizard.py               ← BaseClientWizard + wizard runner
    ├── providers/
    │   ├── __init__.py
    │   ├── anthropic.py        ← AnthropicWizard
    │   ├── google.py           ← GoogleWizard
    │   ├── openai.py           ← OpenAIWizard
    │   ├── xai.py              ← XAIWizard
    │   └── openrouter.py       ← OpenRouterWizard
    └── scaffolding.py          ← env writer, agent scaffolder, app bootstrapper

parrot/templates/
    ├── agent.py.tpl            ← Agent class template
    ├── app.py.tpl              ← Minimal app.py template
    └── run.py.tpl              ← Minimal run.py template
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/cli.py` | adds command | `cli.add_command(setup)` |
| `LLMFactory` (factory.py) | references | For provider/model validation and default models |
| `parrot/conf.py` → `AGENTS_DIR` | reads | Destination for generated agent files |
| `click` (already installed) | uses | All interactive prompts, menus, echo |
| `parrot/install/conf.py` | coexists | `parrot conf init` remains unchanged |

### Data Models
```python
from dataclasses import dataclass, field
from typing import Dict, Optional

@dataclass
class ProviderConfig:
    """Collected configuration for a single LLM provider."""
    provider: str                     # e.g. "anthropic"
    model: str                        # e.g. "claude-opus-4-6"
    env_vars: Dict[str, str]          # e.g. {"ANTHROPIC_API_KEY": "sk-..."}
    llm_string: str                   # e.g. "anthropic:claude-opus-4-6"

@dataclass
class AgentConfig:
    """Collected configuration for agent scaffolding."""
    name: str                         # e.g. "My Research Agent"
    agent_id: str                     # slug: e.g. "my-research-agent"
    provider_config: ProviderConfig
    file_path: str                    # absolute path to generated .py file

@dataclass
class WizardResult:
    """Full result of the setup wizard run."""
    provider_config: ProviderConfig
    environment: str                  # e.g. "dev", "prod"
    env_file_path: str                # where credentials were written
    agent_config: Optional[AgentConfig] = None
    app_bootstrapped: bool = False
```

### New Public Interfaces
```python
# parrot/setup/wizard.py

from abc import ABC, abstractmethod
from typing import ClassVar, List
from parrot.setup.wizard import ProviderConfig

class BaseClientWizard(ABC):
    """Base class for provider-specific credential wizards.

    Subclass this to add support for a new LLM provider. The class is
    auto-discovered by the wizard runner via __subclasses__().
    """

    #: Human-readable name shown in the provider selection menu.
    display_name: ClassVar[str]

    #: Provider key used in LLMFactory (e.g. "anthropic", "openai").
    provider_key: ClassVar[str]

    #: Default model identifier for this provider.
    default_model: ClassVar[str]

    @abstractmethod
    def collect(self) -> ProviderConfig:
        """Run interactive prompts and return collected config.

        Returns:
            ProviderConfig with provider, model, and env_vars populated.
        """
        ...

    @classmethod
    def all_wizards(cls) -> List["BaseClientWizard"]:
        """Return instances of all registered provider wizards."""
        return [sub() for sub in cls.__subclasses__()]
```

---

## 3. Module Breakdown

### Module 1: `parrot/setup/wizard.py`
- **Path**: `parrot/setup/wizard.py`
- **Responsibility**: `BaseClientWizard` ABC; `WizardRunner` that presents the
  provider menu, calls the chosen wizard, and orchestrates the pipeline steps
- **Depends on**: `click`, dataclasses from this module, `parrot.setup.providers.*`

### Module 2: Provider wizards (`parrot/setup/providers/`)
- **Path**: `parrot/setup/providers/{anthropic,google,openai,xai,openrouter}.py`
- **Responsibility**: One `BaseClientWizard` subclass per file; each implements
  `collect()` with provider-specific `click.prompt` calls (hidden for secrets)
- **Depends on**: Module 1 (`BaseClientWizard`)

| File | Class | `display_name` | `provider_key` | `default_model` | Env vars prompted |
|---|---|---|---|---|---|
| `anthropic.py` | `AnthropicWizard` | `Anthropic (Claude)` | `anthropic` | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` |
| `google.py` | `GoogleWizard` | `Google (Gemini)` | `google` | `gemini-2.5-flash` | `GOOGLE_API_KEY` |
| `openai.py` | `OpenAIWizard` | `OpenAI` | `openai` | `gpt-4o` | `OPENAI_API_KEY`, `OPENAI_BASE_URL` (default: `https://api.openai.com/v1`) |
| `xai.py` | `XAIWizard` | `xAI (Grok)` | `xai` | `grok-3` | `XAI_API_KEY` |
| `openrouter.py` | `OpenRouterWizard` | `OpenRouter` | `openrouter` | `anthropic/claude-sonnet-4-6` | `OPENROUTER_API_KEY` |

### Module 3: `parrot/setup/scaffolding.py`
- **Path**: `parrot/setup/scaffolding.py`
- **Responsibility**:
  - `write_env_vars(env_vars, env_file_path)` — append/create `.env` file safely
  - `scaffold_agent(agent_config)` — render `agent.py.tpl`, write to `AGENTS_DIR`
  - `bootstrap_app()` — render `app.py.tpl` and `run.py.tpl` to project root
  - `slugify(name)` — convert "My Agent Name" → `"my-agent-name"`
- **Depends on**: `parrot/conf.py` (AGENTS_DIR), `parrot/templates/` (template files),
  Python's `string.Template` or `pathlib`

### Module 4: `parrot/setup/cli.py`
- **Path**: `parrot/setup/cli.py`
- **Responsibility**: Click command `setup`; imports `WizardRunner`, calls pipeline,
  prints summary of what was created
- **Depends on**: Modules 1, 2, 3

### Module 5: CLI Registration
- **Path**: `parrot/cli.py` (modify)
- **Responsibility**: Import and register `setup` command in the root `cli` group
- **Depends on**: Module 4

### Module 6: Templates (`parrot/templates/`)
- **Path**: `parrot/templates/agent.py.tpl`, `app.py.tpl`, `run.py.tpl`
- **Responsibility**: Python string templates (using `string.Template` `$variable`
  syntax) for generated code artifacts
- **Depends on**: None

### Module 7: Unit Tests
- **Path**: `tests/test_setup_wizard.py`
- **Responsibility**: Unit tests for wizard pipeline, provider wizards, scaffolding
- **Depends on**: Modules 1–5

---

## 4. Template Specifications

### `parrot/templates/agent.py.tpl`
```python
"""$agent_name agent."""
import logging
from parrot.bots import Agent


logger = logging.getLogger(__name__)


class $class_name(Agent):
    """$agent_name — generated by parrot setup."""

    agent_id: str = "$agent_id"
    agent_name: str = "$agent_name"

    def __init__(self, **kwargs):
        super().__init__(
            name="$agent_name",
            agent_id="$agent_id",
            llm="$llm_string",
            **kwargs,
        )
```

### `parrot/templates/app.py.tpl`
```python
"""Application entry point — generated by parrot setup."""
from parrot.manager import BotManager
from parrot.conf import STATIC_DIR
from parrot.handlers import AppHandler
from $agent_module import $class_name


class Main(AppHandler):
    """Main application handler."""

    app_name: str = "Parrot"
    enable_static: bool = True
    staticdir: str = STATIC_DIR

    def configure(self):
        self.bot_manager = BotManager()
        self.bot_manager.register($class_name())
        self.bot_manager.setup(self.app)
```

### `parrot/templates/run.py.tpl`
```python
#!/usr/bin/env python3
"""Run script — generated by parrot setup."""
from navigator import Application
from app import Main

app = Application(Main, enable_jinja2=True)

if __name__ == "__main__":
    app.run()
```

---

## 5. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_all_wizards_discovered` | Module 1 | `BaseClientWizard.all_wizards()` returns 5 wizards |
| `test_anthropic_wizard_collects` | Module 2 | Mocked prompt returns correct `ProviderConfig` |
| `test_openai_wizard_default_base_url` | Module 2 | `OPENAI_BASE_URL` defaults to official URL |
| `test_openai_wizard_custom_base_url` | Module 2 | Custom base URL accepted and stored |
| `test_google_wizard_collects` | Module 2 | Correct env vars for Google |
| `test_xai_wizard_collects` | Module 2 | Correct env vars for xAI |
| `test_openrouter_wizard_collects` | Module 2 | Correct env vars for OpenRouter |
| `test_slugify_simple` | Module 3 | `"My Agent"` → `"my-agent"` |
| `test_slugify_special_chars` | Module 3 | `"Agent #1 (Test)"` → `"agent-1-test"` |
| `test_write_env_vars_creates_file` | Module 3 | Creates `env/.env` with correct content |
| `test_write_env_vars_appends` | Module 3 | Appends to existing `.env` without duplicating |
| `test_write_env_vars_dev_env` | Module 3 | Writes to `env/dev/.env` when env=`dev` |
| `test_scaffold_agent_creates_file` | Module 3 | Agent `.py` exists in `AGENTS_DIR` |
| `test_scaffold_agent_template_vars` | Module 3 | Template variables correctly substituted |
| `test_bootstrap_app_creates_files` | Module 3 | `app.py` and `run.py` created in cwd |
| `test_setup_command_no_agent` | Module 4 | Full wizard run without agent scaffolding |
| `test_setup_command_with_agent` | Module 4 | Full wizard run with agent scaffolding |

### Integration Tests
| Test | Description |
|---|---|
| `test_setup_cli_invocation` | `click.testing.CliRunner` invokes `parrot setup` end-to-end |
| `test_generated_agent_importable` | Scaffolded agent file is syntactically valid Python |
| `test_env_file_not_in_git` | Verify `env/` directory is git-ignored |

### Test Data / Fixtures
```python
import pytest
from click.testing import CliRunner
from parrot.setup.cli import setup

@pytest.fixture
def runner():
    return CliRunner()

@pytest.fixture
def anthropic_inputs():
    """Simulated user input for Anthropic wizard."""
    return "\n".join([
        "3",          # provider choice: Anthropic
        "",           # accept default model
        "sk-ant-test-key",  # API key
        "dev",        # environment
        "y",          # create agent?
        "Test Agent", # agent name
        "",           # accept default LLM
        "n",          # skip app bootstrap
    ])
```

---

## 6. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `parrot setup` command is registered and accessible via the CLI
- [ ] Provider menu shows all 5 providers with numbered selection
- [ ] Each provider wizard collects correct, provider-specific credentials
- [ ] API keys are collected with `hide_input=True` (not echoed to terminal)
- [ ] Credentials are written to `env/.env` (default) or `env/{env}/.env`
- [ ] Parent directories of the env file are created if missing
- [ ] Existing env file content is preserved; new vars are appended
- [ ] Agent scaffolding creates a valid, importable `.py` file in `AGENTS_DIR`
- [ ] Agent slug is derived from name: spaces → hyphens, lowercase, no special chars
- [ ] `app.py` and `run.py` templates are rendered and written to project root
- [ ] All three templates exist in `parrot/templates/`
- [ ] `BaseClientWizard` subclass discovery works via `__subclasses__()`
- [ ] Adding a new provider requires only a new subclass — no core changes
- [ ] All unit tests pass: `pytest tests/test_setup_wizard.py -v`
- [ ] Wizard exits cleanly with `Ctrl+C` (no traceback)
- [ ] Google-style docstrings on all public classes and methods
- [ ] Type hints on all function signatures

---

## 7. Implementation Notes & Constraints

### Click Patterns to Follow
```python
import click

# Numbered menu selection
PROVIDER_CHOICES = ["google", "openai", "anthropic", "xai", "openrouter"]

def prompt_provider() -> str:
    click.echo("\nSelect LLM provider:")
    for i, name in enumerate(PROVIDER_CHOICES, 1):
        click.echo(f"  {i}. {name}")
    choice = click.prompt("Enter number", type=click.IntRange(1, len(PROVIDER_CHOICES)))
    return PROVIDER_CHOICES[choice - 1]

# Hidden credential prompt
api_key = click.prompt("ANTHROPIC_API_KEY", hide_input=True)

# Optional with default
model = click.prompt("Model", default="claude-sonnet-4-6")

# Yes/no confirmation
if click.confirm("Create an Agent?", default=True):
    ...
```

### Env File Writing
```python
# Safe append — avoids overwriting existing content
env_path = Path(f"env/{environment}/.env") if environment != "prod" else Path("env/.env")
env_path.parent.mkdir(parents=True, exist_ok=True)
with env_path.open("a") as f:
    for key, value in env_vars.items():
        f.write(f"{key}={value}\n")
```

### Template Rendering
Use Python's built-in `string.Template` to avoid an extra dependency:
```python
from string import Template
from pathlib import Path

def render_template(template_name: str, context: dict) -> str:
    tpl_path = Path(__file__).parent.parent / "templates" / template_name
    return Template(tpl_path.read_text()).safe_substitute(context)
```

### Slugify Implementation
```python
import re

def slugify(name: str) -> str:
    name = name.lower()
    name = re.sub(r"[^a-z0-9\s-]", "", name)
    name = re.sub(r"[\s_]+", "-", name)
    name = re.sub(r"-+", "-", name).strip("-")
    return name
```

### Known Risks / Gotchas
- **`.env` file format**: Some entries may already exist. The wizard appends without
  deduplication; a future improvement could check for existing keys.
- **`app.py` collision**: If `app.py` already exists in the project root (it does in
  the current repo), the wizard must confirm before overwriting. Default: skip and warn.
- **`AGENTS_DIR` not on sys.path at wizard time**: `parrot/conf.py` adds it, so as
  long as the wizard imports from `parrot`, `AGENTS_DIR` is available.
- **Template variable conflicts**: `string.Template` uses `$var` syntax; generated
  Python code must escape literal `$` as `$$` in templates.
- **Class name from slug**: Convert `"my-research-agent"` → `"MyResearchAgent"` using
  `"".join(w.capitalize() for w in slug.split("-"))`.

### External Dependencies
| Package | Already installed | Reason |
|---|---|---|
| `click` | Yes (8.1.7+) | All interactive prompts and CLI structure |
| `string.Template` | Yes (stdlib) | Template rendering — no Jinja2 needed |
| `pathlib` | Yes (stdlib) | File path handling |

No new dependencies required.

---

## 8. Open Questions

- [ ] Should the wizard support re-running and updating existing credentials (i.e.,
      detect existing keys and offer to overwrite)? — *Owner: engineer*: Yes, will be very useful.
- [ ] Should `app.py` overwrite detection be a `--force` flag on `parrot setup`? — *Owner: engineer*: Yes, only overwrite if "--force" is added to the CLI.
- [ ] Should the wizard validate the API key by making a test request before writing? — *Owner: engineer*: I don't think is necessary.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-03-10 | Claude | Initial draft |
