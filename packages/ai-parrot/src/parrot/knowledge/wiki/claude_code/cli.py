"""``parrot claude`` — install the LLM Wiki as Claude Code infrastructure.

Subcommands:
    install    Wire the repo's wiki into Claude Code (CLAUDE.md
               section, PreToolUse nudge hook, /parrotwiki command,
               git post-commit auto-upsert).
    uninstall  Remove every managed artifact.
    status     Show what is currently installed.
    hook       PreToolUse hook runtime (reads stdin; used internally).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import click

from parrot.knowledge.wiki.claude_code.installer import (
    install_claude_integration,
    integration_status,
    uninstall_claude_integration,
)
from parrot.knowledge.wiki.project import (
    WikiConfigError,
    find_project_root,
    load_project_config,
)




#: Shared `--path` option — every command resolves the repo root the same way.
path_option = click.option(
    "--path", "path_", default=None, help="Repo root (default: auto-detect)."
)

def _resolve_root(path: Optional[str]) -> Path:
    """Resolve the target repository root or abort with guidance."""
    if path:
        root = Path(path).resolve()
        if not root.is_dir():
            raise click.ClickException(f"Not a directory: {root}")
        return root
    found = find_project_root()
    if found is None:
        raise click.ClickException(
            "No repository found upwards from here — run inside a git "
            "repo or pass --path."
        )
    return found


@click.group(name="claude")
def claude() -> None:
    """Claude Code integration for the repository LLM Wiki."""


@claude.command()
@path_option
@click.option(
    "--git-hook/--no-git-hook",
    default=True,
    show_default=True,
    help="Install a git post-commit hook that upserts the wiki.",
)
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
def install(
    path_: Optional[str],
    git_hook: bool,
    gitignore: bool,
    build_now: bool,
) -> None:
    """Install the wiki toolkit as Claude Code infrastructure.

    Writes a small config plus assistant-facing wiring so Claude Code
    consults the knowledge graph for codebase questions — preferring
    scoped `wikitoolkit query "<question>"` calls over grepping raw
    files — and keeps the graph fresh on every git commit.
    """
    root = _resolve_root(path_)
    try:
        config = load_project_config(root)
        actions = install_claude_integration(
            root, config, git_hook=git_hook, gitignore=gitignore
        )
    except (RuntimeError, WikiConfigError) as exc:
        raise click.ClickException(str(exc)) from exc

    for action in actions:
        click.echo(f"  ✓ {action}")

    if build_now and not config.is_built(root):
        click.echo("Building the wiki plane (first run)...")
        from parrot.knowledge.wiki.cli import build as wiki_build

        ctx = click.Context(wiki_build)
        ctx.invoke(wiki_build, path_=str(root), quiet=True)

    click.secho(
        "Claude Code integration installed. Try: "
        "`wikitoolkit query \"<question>\"` or /parrotwiki in Claude Code.",
        fg="green",
    )


@claude.command()
@path_option
def uninstall(path_: Optional[str]) -> None:
    """Remove the Claude Code integration (keeps the wiki plane)."""
    root = _resolve_root(path_)
    for action in uninstall_claude_integration(root):
        click.echo(f"  ✓ {action}")


@claude.command()
@path_option
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
def status(path_: Optional[str], as_json: bool) -> None:
    """Show which integration pieces are installed."""
    root = _resolve_root(path_)
    info = integration_status(root)
    if as_json:
        click.echo(json.dumps(info, indent=2))
        return
    click.echo(f"Repository: {info['root']}")
    labels = {
        "config": ".parrot/wiki.json config",
        "wiki_built": "wiki plane built",
        "claude_md_section": "CLAUDE.md wiki section",
        "pre_tool_use_hook": "PreToolUse nudge hook",
        "slash_command": "/parrotwiki command",
        "git_post_commit_hook": "git post-commit auto-upsert",
    }
    for key, label in labels.items():
        mark = "✓" if info.get(key) else "✗"
        click.echo(f"  {mark} {label}")


@claude.command(hidden=True)
def hook() -> None:
    """PreToolUse hook runtime (reads the payload from stdin)."""
    from parrot.knowledge.wiki.claude_code.hook import run_pre_tool_use_hook

    sys.exit(run_pre_tool_use_hook())
