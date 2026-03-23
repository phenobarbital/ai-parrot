"""Scaffolding utilities for the parrot setup wizard.

Provides all file I/O operations used by the wizard pipeline:

- ``slugify`` / ``class_name_from_slug`` — name transformations
- ``render_template`` — ``string.Template``-based rendering from
  ``parrot/templates/``
- ``write_env_vars`` — safe append to ``.env`` files
- ``scaffold_agent`` — generate an Agent Python file in ``AGENTS_DIR``
- ``bootstrap_app`` — generate ``app.py`` and ``run.py`` in the
  project root
"""
from __future__ import annotations

import re
from pathlib import Path
from string import Template
from typing import Dict

import click

# Resolve the templates directory relative to this file so it works
# regardless of the process working directory.
_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


# ---------------------------------------------------------------------------
# Name transformation helpers
# ---------------------------------------------------------------------------


def slugify(name: str) -> str:
    """Convert a human-readable name to a URL-safe hyphenated slug.

    Strips special characters, collapses whitespace to hyphens, and
    lower-cases the result.

    Args:
        name: Human-readable string (e.g. ``"My Research Agent #1"``).

    Returns:
        Lowercase hyphenated slug (e.g. ``"my-research-agent-1"``).

    Examples:
        >>> slugify("My Agent")
        'my-agent'
        >>> slugify("Agent #1 (Test)")
        'agent-1-test'
    """
    name = name.lower()
    name = re.sub(r"[\s_]+", "-", name)        # spaces and underscores → hyphens
    name = re.sub(r"[^a-z0-9-]", "", name)     # strip everything else
    name = re.sub(r"-+", "-", name).strip("-")
    return name


def class_name_from_slug(slug: str) -> str:
    """Convert a hyphenated slug to a PascalCase class name.

    Args:
        slug: Hyphenated slug (e.g. ``"my-research-agent"``).

    Returns:
        PascalCase class name (e.g. ``"MyResearchAgent"``).

    Examples:
        >>> class_name_from_slug("my-research-agent")
        'MyResearchAgent'
        >>> class_name_from_slug("bot")
        'Bot'
    """
    return "".join(word.capitalize() for word in slug.split("-"))


def module_name_from_slug(slug: str) -> str:
    """Convert a hyphenated slug to a valid Python module name.

    Args:
        slug: Hyphenated slug (e.g. ``"my-research-agent"``).

    Returns:
        Underscored module name (e.g. ``"my_research_agent"``).
    """
    return slug.replace("-", "_")


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------


def render_template(template_name: str, context: Dict[str, str]) -> str:
    """Render a ``string.Template`` file from ``parrot/templates/``.

    Uses ``safe_substitute`` so unrecognised ``$variables`` are left
    intact rather than raising ``KeyError``.

    Args:
        template_name: Filename inside ``parrot/templates/``
            (e.g. ``"agent.py.tpl"``).
        context: Mapping of variable name → replacement string.

    Returns:
        Rendered content with all ``$variables`` substituted.

    Raises:
        FileNotFoundError: If the requested template file does not exist.
    """
    tpl_path = _TEMPLATES_DIR / template_name
    if not tpl_path.exists():
        raise FileNotFoundError(
            f"Template '{template_name}' not found in {_TEMPLATES_DIR}"
        )
    return Template(tpl_path.read_text()).safe_substitute(context)


# ---------------------------------------------------------------------------
# Environment file writer
# ---------------------------------------------------------------------------


def _ensure_base_env(env_path: Path, environment: str) -> None:
    """Ensure the .env file has the base navconfig variables.

    If the file doesn't exist, creates it from navconfig's bundled
    .env.sample template (which includes ENV, CONFIG_FILE, DEBUG, etc.).
    Also ensures ``etc/config.ini`` exists.

    Args:
        env_path: Path to the target ``.env`` file.
        environment: Environment name to set in the ENV variable.
    """
    project_root = env_path.parent
    # Walk up to find the project root (env/.env → root, env/dev/.env → root)
    while project_root.name in ("env",) or project_root.parent.name == "env":
        project_root = project_root.parent

    if not env_path.exists():
        try:
            from navconfig.samples import get_sample_path
            content = get_sample_path(".env.sample").read_text(encoding="utf-8")
            content = content.replace("ENV=dev", f"ENV={environment}")
            content = content.replace("APP_NAME=MyApp", "APP_NAME=Parrot")
            env_path.write_text(content, encoding="utf-8")
        except ImportError:
            # navconfig not installed — write minimal base
            env_path.write_text(
                f"ENV={environment}\n"
                f"CONFIG_FILE=etc/config.ini\n"
                f"DEBUG=true\n"
                f"APP_NAME=Parrot\n"
                f"PRODUCTION=false\n"
                f"LOGLEVEL=DEBUG\n",
                encoding="utf-8",
            )

    # Ensure etc/config.ini exists
    config_file = project_root / "etc" / "config.ini"
    if not config_file.exists():
        config_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            from navconfig.samples import get_sample_path
            content = get_sample_path("config.ini.sample").read_text(encoding="utf-8")
            content = content.replace("APP_NAME = MyApp", "APP_NAME = Parrot")
            config_file.write_text(content, encoding="utf-8")
        except ImportError:
            config_file.write_text(
                "[general]\nDEBUG = true\nAPP_NAME = Parrot\n\n"
                "[logging]\nlogdir = logs\nloglevel = DEBUG\n",
                encoding="utf-8",
            )

    # Ensure logs/ directory exists
    (project_root / "logs").mkdir(parents=True, exist_ok=True)


def write_env_vars(
    env_vars: Dict[str, str],
    env_path: Path,
    environment: str = "default",
) -> None:
    """Write environment variables to a ``.env`` file.

    If the file doesn't exist, it is first seeded from navconfig's
    base template (with ENV, CONFIG_FILE, DEBUG, etc.) so that the
    application can boot correctly. Credentials are then appended.

    Args:
        env_vars: Mapping of ``VAR_NAME`` → value to write.
        env_path: Absolute (or relative) path to the target ``.env`` file.
        environment: Environment name (used when seeding a new file).
    """
    env_path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_base_env(env_path, environment)

    with env_path.open("a") as fh:
        fh.write("\n# -- LLM Credentials (added by parrot setup) --\n")
        for key, value in env_vars.items():
            fh.write(f"{key}={value}\n")


# ---------------------------------------------------------------------------
# Agent scaffolder
# ---------------------------------------------------------------------------


def scaffold_agent(agent_config: object, cwd: Path) -> Path:  # noqa: ARG001
    """Scaffold a new Agent Python file from the ``agent.py.tpl`` template.

    Writes the rendered file to ``AGENTS_DIR/<module_name>.py``,
    creating the directory if necessary.

    Args:
        agent_config: ``AgentConfig`` instance with ``name``,
            ``agent_id``, and ``provider_config.llm_string`` set.
        cwd: Project root (unused directly; ``AGENTS_DIR`` is resolved
            from ``parrot.conf``).

    Returns:
        Absolute ``Path`` of the created agent ``.py`` file.
    """
    from parrot.conf import AGENTS_DIR
    from parrot.setup.wizard import AgentConfig

    config: AgentConfig = agent_config  # type: ignore[assignment]

    slug = config.agent_id
    class_name = class_name_from_slug(slug)
    module_name = module_name_from_slug(slug)

    context: Dict[str, str] = {
        "agent_name": config.name,
        "agent_id": slug,
        "class_name": class_name,
        "llm_string": config.provider_config.llm_string,
        "agent_module": module_name,
    }

    content = render_template("agent.py.tpl", context)

    agents_dir = Path(AGENTS_DIR)
    agents_dir.mkdir(parents=True, exist_ok=True)

    out_path = agents_dir / f"{module_name}.py"
    out_path.write_text(content)
    return out_path


# ---------------------------------------------------------------------------
# App bootstrapper
# ---------------------------------------------------------------------------


def bootstrap_app(agent_config: object, cwd: Path, force: bool = False) -> bool:
    """Generate ``app.py`` and ``run.py`` in the project root.

    Skips generation (and emits a warning) if either file already exists
    and ``force`` is ``False``.

    Args:
        agent_config: ``AgentConfig`` instance used to populate template
            variables for ``app.py``.
        cwd: Project root directory where ``app.py`` and ``run.py`` are
            written.
        force: When ``True``, overwrite existing files without prompting.

    Returns:
        ``True`` if both files were written; ``False`` if skipped due to
        pre-existing files.
    """
    from parrot.setup.wizard import AgentConfig

    config: AgentConfig = agent_config  # type: ignore[assignment]

    slug = config.agent_id
    class_name = class_name_from_slug(slug)
    module_name = module_name_from_slug(slug)

    context: Dict[str, str] = {
        "agent_name": config.name,
        "agent_id": slug,
        "class_name": class_name,
        "agent_module": module_name,
    }

    app_path = cwd / "app.py"
    run_path = cwd / "run.py"

    if not force and (app_path.exists() or run_path.exists()):
        click.secho(
            "  app.py or run.py already exists — skipping. "
            "Use --force to overwrite.",
            fg="yellow",
        )
        return False

    app_path.write_text(render_template("app.py.tpl", context))
    run_path.write_text(render_template("run.py.tpl", context))
    return True
