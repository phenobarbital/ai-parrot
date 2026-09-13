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
from parrot.mcp.toolkit_seed import available_templates
from parrot.knowledge.wiki.project import (
    WikiConfigError,
    find_project_root,
    load_effective_config,
)

#: Shared `--path` option — every command resolves the repo root the same way.
path_option = click.option("--path", "path_", default=None, help="Repo root (default: auto-detect).")


def _resolve_root(path: Optional[str]) -> Path:
    """Resolve the target repository root or abort with guidance."""
    if path:
        root = Path(path).resolve()
        if not root.is_dir():
            raise click.ClickException(f"Not a directory: {root}")
        return root
    found = find_project_root()
    if found is None:
        raise click.ClickException("No repository found upwards from here — run inside a git " "repo or pass --path.")
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
@click.option(
    "--bookstore/--no-bookstore",
    default=True,
    show_default=True,
    help="Install Bookstore MCP and skill when an indexed library exists (no indexing).",
)
@click.option(
    "--tool-guards/--no-tool-guards",
    default=False,
    show_default=True,
    help="Install the opt-in PreToolUse read guard (FEAT-543) that denies unbounded reads of large files.",
)
@click.option(
    "--toolkits",
    "toolkits_",
    default="",
    help="Comma-separated toolkit sections to seed into .parrot/mcp-toolkits.yaml (e.g. sdd-coder,bounded-source).",
)
@click.option(
    "--all-toolkits",
    "all_toolkits",
    is_flag=True,
    default=False,
    help="Seed every toolkit template shipped with this release.",
)
@click.option(
    "--approve-mcp/--no-approve-mcp",
    default=True,
    show_default=True,
    help="Authorize the managed MCP servers in .claude/settings.local.json.",
)
def install(
    path_: Optional[str],
    git_hook: bool,
    gitignore: bool,
    build_now: bool,
    bookstore: bool,
    tool_guards: bool,
    toolkits_: str,
    all_toolkits: bool,
    approve_mcp: bool,
) -> None:
    """Install the wiki toolkit as Claude Code infrastructure.

    Writes a small config plus assistant-facing wiring so Claude Code
    consults the knowledge graph for codebase questions — preferring
    scoped `wikitoolkit query "<question>"` calls over grepping raw
    files — and keeps the graph fresh on every git commit.
    """
    root = _resolve_root(path_)
    names = sorted(
        {n.strip() for n in toolkits_.split(",") if n.strip()} | (set(available_templates()) if all_toolkits else set())
    )
    try:
        config = load_effective_config(root).config
        actions = install_claude_integration(
            root,
            config,
            git_hook=git_hook,
            gitignore=gitignore,
            bookstore=bookstore,
            toolkits=names,
            approve_mcp=approve_mcp,
        )
    except (RuntimeError, WikiConfigError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc

    for action in actions:
        click.echo(f"  ✓ {action}")

    if not names:
        templates = available_templates()
        if templates:
            click.echo(
                f"  ℹ Use --toolkits=<name,...> or --all-toolkits to seed MCP toolkit servers. "
                f"Available: {', '.join(templates)}"
            )

    if names or approve_mcp:
        click.echo("  ℹ Start a new Claude Code session for the MCP servers to appear.")

    if tool_guards:
        # Lazy import: core must not hard-depend on ai-parrot-tools.
        try:
            from parrot_tools.tool_optimizations.installation import install_guards
        except ImportError as exc:  # pragma: no cover - exercised via monkeypatch
            raise click.ClickException("tool guards require ai-parrot-tools: uv pip install ai-parrot-tools") from exc
        try:
            for action in install_guards(root, "claude"):
                click.echo(f"  ✓ {action}")
        except RuntimeError as exc:
            raise click.ClickException(str(exc)) from exc

    if build_now and not config.is_built(root):
        click.echo("Building the wiki plane (first run)...")
        from parrot.knowledge.wiki.cli import build as wiki_build

        ctx = click.Context(wiki_build)
        ctx.invoke(wiki_build, path_=str(root), quiet=True)

    click.secho(
        "Claude Code integration installed. Try: " '`wikitoolkit query "<question>"` or /parrotwiki in Claude Code.',
        fg="green",
    )


@claude.command()
@path_option
def uninstall(path_: Optional[str]) -> None:
    """Remove the Claude Code integration (keeps the wiki plane)."""
    root = _resolve_root(path_)
    for action in uninstall_claude_integration(root):
        click.echo(f"  ✓ {action}")

    try:
        from parrot_tools.tool_optimizations.installation import uninstall_guards
    except ImportError:
        pass
    else:
        try:
            for action in uninstall_guards(root, "claude"):
                click.echo(f"  ✓ {action}")
        except RuntimeError as exc:
            raise click.ClickException(str(exc)) from exc


@claude.command()
@path_option
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
def status(path_: Optional[str], as_json: bool) -> None:
    """Show which integration pieces are installed."""
    root = _resolve_root(path_)
    info = integration_status(root)

    try:
        from parrot_tools.tool_optimizations.installation import guard_status
    except ImportError:
        pass
    else:
        info["tool_guards"] = guard_status(root, "claude")
    if as_json:
        click.echo(json.dumps(info, indent=2))
        return
    click.echo(f"Repository: {info['root']}")
    labels = {
        "config": ".parrot/wiki.json config",
        "wiki_built": "wiki plane built",
        "claude_md_section": "CLAUDE.md wiki section",
        "pre_tool_use_hook": "PreToolUse nudge hook",
        "permissions": "wikitoolkit permissions (settings.local.json)",
        "slash_command": "/parrotwiki command",
        "git_post_commit_hook": "git post-commit auto-upsert",
        "bookstore_mcp": "bookstore MCP (.mcp.json)",
        "bookstore_skill": "bookstore research skill",
    }
    for key, label in labels.items():
        mark = "✓" if info.get(key) else "✗"
        click.echo(f"  {mark} {label}")


@claude.command(hidden=True)
def hook() -> None:
    """PreToolUse hook runtime (reads the payload from stdin)."""
    from parrot.knowledge.wiki.claude_code.hook import run_pre_tool_use_hook

    sys.exit(run_pre_tool_use_hook())
