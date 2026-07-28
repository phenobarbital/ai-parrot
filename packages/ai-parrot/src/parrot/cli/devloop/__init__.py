"""``parrot devloop`` — Interactive CLI console for dev-loop flows.

Click command surface registered in ``cli._lazy_commands`` as ``"devloop"``.
All heavy imports (``parrot.conf``, ``parrot.flows.dev_loop.*``) are deferred
into command bodies so ``parrot devloop --help`` stays fast.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids a heavy runtime import
    from parrot.flows.dev_loop.models import DevAgentSpec


def _parse_dev_agent_flag(value: str) -> DevAgentSpec:
    """Parse a repeatable ``--dev-agent backend[:model[:count]]`` flag (FEAT-388 G2).

    Args:
        value: Raw flag value, e.g. ``"codex:gpt-5.5:2"`` or bare ``"agy"``.

    Returns:
        The validated ``DevAgentSpec``.

    Raises:
        click.BadParameter: Unknown backend (lists catalog ids) or a
            non-positive/invalid ``count``.
    """
    from parrot.flows.dev_loop import catalog  # noqa: PLC0415
    from parrot.flows.dev_loop.models import DevAgentSpec  # noqa: PLC0415

    parts = value.split(":", 2)
    backend_id = parts[0]
    model = parts[1] if len(parts) > 1 else ""
    count_raw = parts[2] if len(parts) > 2 else ""

    if catalog.get_backend(backend_id) is None:
        valid = ", ".join(b.id for b in catalog.BACKENDS)
        raise click.BadParameter(
            f"Unknown backend {backend_id!r}. Valid backends: {valid}"
        )

    count = 1
    if count_raw:
        try:
            count = int(count_raw)
        except ValueError as exc:
            raise click.BadParameter(
                f"count must be a positive integer, got {count_raw!r}"
            ) from exc
        if count < 1:
            raise click.BadParameter(
                f"count must be a positive integer, got {count_raw!r}"
            )

    return DevAgentSpec(agent=backend_id, model=model, count=count)


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
              help="Path to a YAML/JSON brief file (skips the wizard). "
                   "'kind: feature' routes to feature-mode (FEAT-378); "
                   "everything else (or no 'kind') loads as a bug/enhancement/"
                   "new_feature WorkBrief.")
@click.option("--yes", "skip_wizard", is_flag=True, default=False,
              help="Skip confirmation prompts (requires --brief, or use with "
                   "--text to skip the intake accept/edit/redo/cancel loop).")
@click.option("--dev-agent", "dev_agent_flags", multiple=True, default=(),
              help="Repeatable dev-agent pool row: backend[:model[:count]] "
                   "(e.g. codex:gpt-5.5:2). Merges into the built brief; "
                   "a --brief file's own dev_agents (if set) wins.")
@click.option("--text", "intake_text", default=None,
              help="Non-interactive free-text feature intake (FEAT-388 G4) — "
                   "skips the kind picker. Combine with --yes to also skip "
                   "the accept/edit/redo/cancel confirm loop (G5).")
def run_cmd(
    brief_file: str | None = None,
    skip_wizard: bool = False,
    dev_agent_flags: tuple[str, ...] = (),
    intake_text: str | None = None,
) -> None:
    """Start a new dev-loop run.

    Without --brief, opens the interactive console: a kind picker
    (bug/enhancement/feature) routes bug/enhancement to the WorkBrief
    wizard (byte-identical to before) and feature to the free-text
    intake path (FEAT-388). With --brief and --yes, dispatches
    non-interactively. The brief file's 'kind' field selects the topology:
    'kind: feature' dispatches a FeatureBrief through the feature-mode
    flow (document-driven planning, judge-panel QA, draft PR handoff);
    any other/absent 'kind' dispatches the existing bug/enhancement/
    new_feature WorkBrief path, unchanged.
    """
    from parrot.cli.devloop.console import DevLoopConsole  # noqa: PLC0415

    dev_agents = [_parse_dev_agent_flag(raw) for raw in dev_agent_flags] or None

    console = DevLoopConsole()
    exit_code = asyncio.run(
        console.start(
            brief_file=brief_file,
            dev_agents=dev_agents,
            intake_text=intake_text,
            skip_confirm=skip_wizard,
        )
    )
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
