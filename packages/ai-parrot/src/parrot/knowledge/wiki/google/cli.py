"""``parrot google`` — install WikiToolkit as Google Antigravity / Gemini CLI infrastructure."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import click
from parrot.knowledge.wiki.google.installer import (
    install_google_integration,
    integration_status,
    uninstall_google_integration,
)
from parrot.knowledge.wiki.project import WikiConfigError, load_effective_config
from parrot.launcher import LinkedWorktreeError, install_root, require_primary_checkout

path_option = click.option(
    "--path",
    "path_",
    default=None,
    help="Repo root (default: auto-detect; required to install into a linked worktree on purpose).",
)


def _resolve_root(path: Optional[str], *, write: bool = True) -> Path:
    """Resolve the install target, rejecting implicit worktree writes before side effects.

    Args:
        path: Explicit ``--path`` value, or ``None`` to resolve the checkout containing the cwd.
        write: Whether the verb writes; an implicit linked-worktree target is then refused.

    Returns:
        The install target (host assets are written here).

    Raises:
        click.ClickException: ``--path`` is not a directory, or an implicit write target is a
            linked worktree (the message names the primary checkout and the ``--path`` escape hatch).
    """
    explicit: Optional[Path] = None
    if path:
        explicit = Path(path).resolve()
        if not explicit.is_dir():
            raise click.ClickException(f"Not a directory: {explicit}")
    try:
        resolved = install_root(Path.cwd(), explicit=explicit)
        if write:
            require_primary_checkout(resolved)
    except LinkedWorktreeError as exc:
        raise click.ClickException(str(exc)) from exc
    return resolved.root


@click.group(name="google")
def google() -> None:
    """Google Antigravity / Gemini CLI integration for LLM Wiki and Bookstore."""


@google.command()
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
@click.option(
    "--portable/--no-portable",
    default=None,
    help="Emit bare launcher commands with no absolute paths or cwd — required for a multi-repo-safe "
    "~/.gemini/config/mcp_config.json. Default: keep the current form (baked on a fresh install).",
)
def install(
    path_: Optional[str],
    gitignore: bool,
    build_now: bool,
    bookstore: bool,
    portable: Optional[bool],
) -> None:
    """Install WikiToolkit and Bookstore MCP servers and skills for Google Antigravity."""
    root = _resolve_root(path_)
    # Wiki state lives at the shared root (the primary checkout of a linked worktree): load it there so
    # worktree defaults never overwrite the primary configuration; host assets still go to `root`.
    state_root = install_root(root, explicit=root).shared_root
    try:
        config = load_effective_config(state_root).config
        actions = install_google_integration(
            root, config, gitignore=gitignore, bookstore=bookstore, portable=portable
        )
    except (RuntimeError, WikiConfigError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc

    for action in actions:
        click.echo(f"  ✓ {action}")

    if build_now and not config.is_built(state_root):
        click.echo("Building the wiki plane (first run)...")
        from parrot.knowledge.wiki.cli import build as wiki_build

        context = click.Context(wiki_build)
        context.invoke(wiki_build, path_=str(state_root), quiet=True)

    click.secho(
        "Google Antigravity integration installed. Restart Antigravity CLI in this trusted repository "
        "to load its MCP servers, skills, and instructions.",
        fg="green",
    )


@google.command()
@path_option
def uninstall(path_: Optional[str]) -> None:
    """Remove the Google Antigravity integration while retaining the wiki plane."""
    root = _resolve_root(path_)
    try:
        actions = uninstall_google_integration(root)
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc
    for action in actions:
        click.echo(f"  ✓ {action}")


@google.command()
@path_option
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
def status(path_: Optional[str], as_json: bool) -> None:
    """Show which Google Antigravity integration pieces are installed."""
    root = _resolve_root(path_, write=False)
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
        "gemini_md_section": "GEMINI.md wiki section",
        "skill": "parrot-wiki Antigravity skill",
        "mcp": "wikitoolkit MCP server",
        "plugin": "parrot Antigravity plugin",
        "bookstore_mcp": "bookstore PageIndex MCP",
        "bookstore_skill": "bookstore research skill",
    }
    for key, label in labels.items():
        mark = "✓" if info.get(key) else "✗"
        click.echo(f"  {mark} {label}")


# Alias for invocation as `parrot gemini`
gemini = google
