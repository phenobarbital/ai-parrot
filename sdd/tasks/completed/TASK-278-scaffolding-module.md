# TASK-278: Scaffolding Module

**Feature**: CLI Wizard Setup (FEAT-041)
**Spec**: `sdd/specs/cli-wizard-setup.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-275, TASK-279
**Assigned-to**: claude-session

---

## Context

> Implements all file I/O operations for the wizard: writing `.env` files, rendering
> templates, scaffolding agent files, and bootstrapping app.py / run.py.
> Implements spec Section 3 — Module 3 and the open-question answers
> (existing key detection and `--force` for app.py overwrite).

---

## Scope

Create `parrot/setup/scaffolding.py` with the following public functions:

1. `slugify(name: str) -> str` — convert human name to URL-safe slug
2. `class_name_from_slug(slug: str) -> str` — `"my-agent"` → `"MyAgent"`
3. `render_template(template_name: str, context: dict) -> str` — render a `.tpl` file
4. `write_env_vars(env_vars: dict, env_path: Path) -> None` — append to `.env`
5. `scaffold_agent(agent_config: AgentConfig, cwd: Path) -> Path` — create agent .py
6. `bootstrap_app(agent_config: AgentConfig, cwd: Path, force: bool = False) -> bool`
   — create `app.py` and `run.py`; returns True if files were written

**NOT in scope**: `BaseClientWizard` (TASK-276), provider wizards (TASK-277),
templates themselves (TASK-279), CLI command (TASK-280).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/setup/scaffolding.py` | CREATE | All scaffolding functions |

---

## Implementation Notes

### `slugify` + `class_name_from_slug`
```python
import re

def slugify(name: str) -> str:
    """Convert a human-readable name to a URL-safe slug.

    Args:
        name: Human-readable name (e.g. "My Research Agent #1").

    Returns:
        Lowercase hyphenated slug (e.g. "my-research-agent-1").
    """
    name = name.lower()
    name = re.sub(r"[^a-z0-9\s-]", "", name)
    name = re.sub(r"[\s_]+", "-", name)
    name = re.sub(r"-+", "-", name).strip("-")
    return name


def class_name_from_slug(slug: str) -> str:
    """Convert a slug to a PascalCase class name.

    Args:
        slug: Hyphenated slug (e.g. "my-research-agent").

    Returns:
        PascalCase class name (e.g. "MyResearchAgent").
    """
    return "".join(word.capitalize() for word in slug.split("-"))
```

### `render_template`
```python
from pathlib import Path
from string import Template

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def render_template(template_name: str, context: dict) -> str:
    """Render a string template from parrot/templates/.

    Args:
        template_name: Filename inside parrot/templates/ (e.g. "agent.py.tpl").
        context: Variable substitutions (uses string.Template safe_substitute).

    Returns:
        Rendered string with all $variables substituted.

    Raises:
        FileNotFoundError: If the template file does not exist.
    """
    tpl_path = _TEMPLATES_DIR / template_name
    return Template(tpl_path.read_text()).safe_substitute(context)
```

### `write_env_vars`
```python
def write_env_vars(env_vars: Dict[str, str], env_path: Path) -> None:
    """Append environment variables to a .env file.

    Creates parent directories if they do not exist.
    Caller is responsible for filtering out keys the user chose not to overwrite.

    Args:
        env_vars: Mapping of VAR_NAME → value to write.
        env_path: Absolute path to the target .env file.
    """
    env_path.parent.mkdir(parents=True, exist_ok=True)
    with env_path.open("a") as f:
        for key, value in env_vars.items():
            f.write(f"{key}={value}\n")
```

### `scaffold_agent`
```python
def scaffold_agent(agent_config: AgentConfig, cwd: Path) -> Path:
    """Scaffold a new Agent Python file from the agent template.

    Args:
        agent_config: Agent name, id, and LLM config.
        cwd: Project root (used to resolve AGENTS_DIR).

    Returns:
        Absolute path of the created agent .py file.
    """
    from parrot.conf import AGENTS_DIR
    slug = agent_config.agent_id
    class_name = class_name_from_slug(slug)
    agent_module = slug.replace("-", "_")  # Python module name

    context = {
        "agent_name": agent_config.name,
        "agent_id": slug,
        "class_name": class_name,
        "llm_string": agent_config.provider_config.llm_string,
        "agent_module": agent_module,
    }
    content = render_template("agent.py.tpl", context)
    out_path = Path(AGENTS_DIR) / f"{agent_module}.py"
    out_path.write_text(content)
    return out_path
```

### `bootstrap_app`
```python
def bootstrap_app(agent_config: AgentConfig, cwd: Path, force: bool = False) -> bool:
    """Generate app.py and run.py in the project root.

    Skips generation and warns if files already exist and force=False.

    Args:
        agent_config: Used to populate app.py template variables.
        cwd: Project root directory where app.py / run.py are written.
        force: If True, overwrite existing files without prompting.

    Returns:
        True if both files were written, False if skipped.
    """
    slug = agent_config.agent_id
    class_name = class_name_from_slug(slug)
    agent_module = slug.replace("-", "_")

    context = {
        "agent_name": agent_config.name,
        "agent_id": slug,
        "class_name": class_name,
        "agent_module": agent_module,
    }

    app_path = cwd / "app.py"
    run_path = cwd / "run.py"

    if not force and (app_path.exists() or run_path.exists()):
        import click
        click.secho(
            "  app.py or run.py already exists. Use --force to overwrite.",
            fg="yellow",
        )
        return False

    app_path.write_text(render_template("app.py.tpl", context))
    run_path.write_text(render_template("run.py.tpl", context))
    return True
```

### Key Constraints
- `write_env_vars` only appends — deduplication/overwrite decisions happen in
  `WizardRunner` (TASK-276) before calling this function.
- Templates directory must be resolved relative to this file using `__file__`, not
  a hardcoded path, so it works regardless of working directory.
- `bootstrap_app` checks BOTH `app.py` and `run.py` for existence.

---

## Acceptance Criteria

- [ ] `slugify("My Agent #1")` → `"my-agent-1"`
- [ ] `class_name_from_slug("my-research-agent")` → `"MyResearchAgent"`
- [ ] `render_template` reads from `parrot/templates/` and substitutes `$variables`
- [ ] `write_env_vars` creates parent directories and appends correctly
- [ ] `scaffold_agent` creates a `.py` file in `AGENTS_DIR` with correct content
- [ ] `bootstrap_app` skips existing files and warns unless `force=True`
- [ ] `bootstrap_app` writes both `app.py` and `run.py` when force or clean slate
- [ ] Google-style docstrings on all functions
- [ ] Type hints on all signatures
- [ ] No linting errors: `ruff check parrot/setup/scaffolding.py`

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/cli-wizard-setup.spec.md` — Sections 3 Module 3 and 7
2. **Check dependencies** — TASK-275 (data models) and TASK-279 (templates) must be done
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** per scope above
5. **Verify** all acceptance criteria
6. **Move this file** to `sdd/tasks/completed/TASK-278-scaffolding-module.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: claude-session
**Date**: 2026-03-10
**Notes**: Created `parrot/setup/scaffolding.py` with all 6 public functions: `slugify`,
`class_name_from_slug`, `module_name_from_slug` (bonus helper), `render_template`,
`write_env_vars`, `scaffold_agent`, `bootstrap_app`. Templates resolved relative to `__file__`
for portability. `scaffold_agent` monkeypatches `AGENTS_DIR` in tests. All ruff clean.
All acceptance criteria verified including `ast.parse()` check on generated agent file.
**Deviations from spec**: Added `module_name_from_slug` (not explicitly specified but needed
by both `scaffold_agent` and `bootstrap_app`). Used `object` type hint for `agent_config`
parameter in `scaffold_agent`/`bootstrap_app` to avoid circular import at module level;
cast internally after lazy import.
