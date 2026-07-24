"""``parrot devloop`` — Interactive CLI console for dev-loop flows.

Click command surface registered in ``cli._lazy_commands`` as ``"devloop"``.
All heavy imports (``parrot.conf``, ``parrot.flows.dev_loop.*``) are deferred
into command bodies so ``parrot devloop --help`` stays fast.
"""
from __future__ import annotations

import asyncio

import click


@click.group(invoke_without_command=True)
@click.pass_context
def devloop(ctx: click.Context) -> None:
    """Interactive CLI console for dev-loop flows.

    Run without a subcommand for the full interactive console,
    or use 'run' / 'revise' subcommands for specific modes.
    """
    if ctx.invoked_subcommand is None:
        ctx.invoke(run_cmd)


@devloop.command("run")
@click.option("--brief", "brief_file", type=click.Path(exists=True), default=None,
              help="Path to a YAML/JSON brief file (skips the wizard).")
@click.option("--yes", "skip_wizard", is_flag=True, default=False,
              help="Skip confirmation prompts (requires --brief).")
def run_cmd(brief_file: str | None = None, skip_wizard: bool = False) -> None:
    """Start a new dev-loop run.

    Without --brief, opens the interactive wizard to collect a WorkBrief.
    With --brief and --yes, dispatches non-interactively.
    """
    from parrot.cli.devloop.console import DevLoopConsole  # noqa: PLC0415

    console = DevLoopConsole()
    exit_code = asyncio.run(console.start(brief_file=brief_file))
    raise SystemExit(exit_code)


@devloop.command("revise")
@click.option("--brief", "brief_file", type=click.Path(exists=True), default=None,
              help="Path to a YAML/JSON RevisionBrief file.")
def revise_cmd(brief_file: str | None = None) -> None:
    """Start a revision-mode run.

    Collects a RevisionBrief interactively or from a file, then dispatches
    run_revision() on the dev-loop runner.
    """
    from parrot.cli.devloop.console import DevLoopConsole  # noqa: PLC0415

    console = DevLoopConsole()
    exit_code = asyncio.run(console.start(brief_file=brief_file, revision=True))
    raise SystemExit(exit_code)
