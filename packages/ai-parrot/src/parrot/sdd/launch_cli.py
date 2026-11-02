"""`parrot sdd launch worker|brief|fix` — the three interactive entry points of an SDD cycle (FEAT-633, C30 item 5)."""

from __future__ import annotations

import os

import click

_PASSTHROUGH = {"ignore_unknown_options": True, "allow_interspersed_args": False}


@click.group(name="launch")
def launch() -> None:
    """Start an SDD cycle interactively: a sandboxed feature worker, a brief, or a ledger fix session."""


@launch.command("worker", context_settings={"ignore_unknown_options": True})
@click.argument("feature")
@click.option("--tmux", "use_tmux", is_flag=True, default=False)
@click.option("--detach", is_flag=True, default=False)
@click.option("--sandbox", type=click.Choice(["required", "preferred", "off", "legacy"]), default=None)
@click.option("--sandbox-allow-domain", "allowed_domains", multiple=True, metavar="HOST")
@click.option("--no-upstream", is_flag=True, default=False)
@click.argument("claude_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def worker(
    ctx: click.Context,
    feature: str,
    use_tmux: bool,
    detach: bool,
    sandbox: str | None,
    allowed_domains: tuple[str, ...],
    no_upstream: bool,
    claude_args: tuple[str, ...],
) -> None:
    """Prepare FEATURE and launch its sdd-worker console."""
    if detach and not use_tmux:
        raise click.UsageError("--detach requires --tmux")
    # Snapshot BEFORE importing parrot.flows: that import lets navconfig load the project's settings
    # .env (API keys and other secrets) into os.environ, and none of it may reach the worker.
    base_env = dict(os.environ)
    from parrot.flows.dev_loop import feature_launcher  # noqa: PLC0415

    try:
        code = feature_launcher.launch(
            feature,
            tmux=use_tmux,
            detach=detach,
            sandbox=sandbox,
            allowed_domains=allowed_domains,
            no_upstream=no_upstream,
            claude_args=claude_args,
            base_env=base_env,
        )
    except feature_launcher.LaunchError as exc:
        click.echo(f"launch-worker: {exc}", err=True)
        ctx.exit(exc.exit_code)
    ctx.exit(code)


def _session(ctx: click.Context, prompt_words: list[str]) -> None:
    """Exec an interactive Claude session in the primary checkout with the slash command as first prompt."""
    base_env = dict(os.environ)  # snapshot BEFORE importing parrot.flows (navconfig loads .env secrets on import)
    from parrot.flows.dev_loop import feature_launcher  # noqa: PLC0415

    try:
        cwd = feature_launcher.resolve_primary_checkout(feature_launcher._invocation_dir())
    except feature_launcher.LaunchError as exc:
        click.echo(f"launch: {exc}", err=True)
        ctx.exit(exc.exit_code)
    ctx.exit(feature_launcher.launch_session(" ".join(prompt_words), cwd=cwd, base_env=base_env))


@launch.command("brief", context_settings=_PASSTHROUGH, add_help_option=False)
@click.argument("source")
@click.argument("rest", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def brief(ctx: click.Context, source: str, rest: tuple[str, ...]) -> None:
    """Open a Claude session running `/sdd-brief SOURCE [flags...]` in the primary checkout."""
    _session(ctx, ["/sdd-brief", source, *rest])


@launch.command("fix", context_settings=_PASSTHROUGH, add_help_option=False)
@click.argument("rest", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def fix(ctx: click.Context, rest: tuple[str, ...]) -> None:
    """Open a Claude session running `/sdd-fix [issue-id | --top N ...]` in the primary checkout."""
    _session(ctx, ["/sdd-fix", *rest])
