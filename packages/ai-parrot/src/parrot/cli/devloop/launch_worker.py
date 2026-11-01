"""Click command for preparing and launching an SDD feature worker."""

from __future__ import annotations

import click


@click.command("launch-worker", context_settings={"ignore_unknown_options": True})
@click.argument("feature")
@click.option("--tmux", "use_tmux", is_flag=True, default=False)
@click.option("--detach", is_flag=True, default=False)
@click.option("--sandbox", type=click.Choice(["required", "preferred", "off", "legacy"]), default=None)
@click.option("--sandbox-allow-domain", "allowed_domains", multiple=True, metavar="HOST")
@click.option("--no-upstream", is_flag=True, default=False)
@click.argument("claude_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def launch_worker_cmd(
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
        )
    except feature_launcher.LaunchError as exc:
        click.echo(f"launch-worker: {exc}", err=True)
        ctx.exit(exc.exit_code)
    ctx.exit(code)
