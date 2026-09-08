"""``parrot codex`` — install WikiToolkit as Codex infrastructure."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import click
from parrot.knowledge.wiki.codex.installer import (
    install_codex_integration,
    integration_status,
    uninstall_codex_integration,
)
from parrot.knowledge.wiki.project import WikiConfigError, find_project_root, load_effective_config

path_option = click.option(
    "--path",
    "path_",
    default=None,
    help="Repo root (default: auto-detect).",
)


def _resolve_root(path: Optional[str]) -> Path:
    if path:
        root = Path(path).resolve()
        if not root.is_dir():
            raise click.ClickException(f"Not a directory: {root}")
        return root
    found = find_project_root()
    if found is None:
        raise click.ClickException("No repository found upwards from here — run inside a git repo or pass --path.")
    return found


@click.group(name="codex")
def codex() -> None:
    """Codex integration for the repository LLM Wiki and Bookstore."""


@codex.command()
@path_option
@click.option(
    "--gitignore/--no-gitignore",
    default=True,
    show_default=True,
    help="Add .parrot/ to .gitignore.",
)
@click.option(
    "--build/--no-build",
    "build_now",
    default=True,
    show_default=True,
    help="Build the wiki plane now if it does not exist yet.",
)
@click.option(
    "--bookstore/--no-bookstore",
    default=True,
    show_default=True,
    help="Install Bookstore MCP and skill when an indexed library exists (no indexing).",
)
def install(path_: Optional[str], gitignore: bool, build_now: bool, bookstore: bool) -> None:
    """Install WikiToolkit and Bookstore MCP servers and skills for Codex."""
    root = _resolve_root(path_)
    try:
        config = load_effective_config(root).config
        actions = install_codex_integration(root, config, gitignore=gitignore, bookstore=bookstore)
    except (RuntimeError, WikiConfigError) as exc:
        raise click.ClickException(str(exc)) from exc

    for action in actions:
        click.echo(f"  ✓ {action}")

    if build_now and not config.is_built(root):
        click.echo("Building the wiki plane (first run)...")
        from parrot.knowledge.wiki.cli import build as wiki_build

        context = click.Context(wiki_build)
        context.invoke(wiki_build, path_=str(root), quiet=True)

    click.secho(
        "Codex integration installed. Restart Codex in this trusted repository "
        "to load its MCP servers, skills, and permission rules.",
        fg="green",
    )


@codex.command()
@path_option
def uninstall(path_: Optional[str]) -> None:
    """Remove the Codex integration while retaining the wiki plane."""
    root = _resolve_root(path_)
    try:
        actions = uninstall_codex_integration(root)
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc
    for action in actions:
        click.echo(f"  ✓ {action}")


@codex.command()
@path_option
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
def status(path_: Optional[str], as_json: bool) -> None:
    """Show which Codex integration pieces are installed."""
    root = _resolve_root(path_)
    try:
        info = integration_status(root)
    except (RuntimeError, WikiConfigError) as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        click.echo(json.dumps(info, indent=2))
        return
    click.echo(f"Repository: {info['root']}")
    labels = {
        "config": ".parrot/wiki.json config",
        "wiki_built": "wiki plane built",
        "agents_md_section": "AGENTS.md wiki section",
        "skill": "parrot-wiki Codex skill",
        "mcp": "wikitoolkit MCP with automatic approval",
        "permissions": "wikitoolkit command permissions",
        "bookstore_mcp": "bookstore PageIndex MCP",
        "bookstore_skill": "bookstore research skill",
    }
    for key, label in labels.items():
        mark = "✓" if info.get(key) else "✗"
        click.echo(f"  {mark} {label}")
