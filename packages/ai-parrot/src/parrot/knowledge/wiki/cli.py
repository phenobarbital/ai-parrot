"""Click commands for installing the LLM Wiki into coding agents."""

from pathlib import Path

import click

from parrot.knowledge.wiki import coding_agents


@click.group()
def wiki() -> None:
    """Manage the repository LLM Wiki and agent integrations."""


def _agent(name: str) -> None:
    @wiki.command(name)
    @click.option("--path", type=click.Path(file_okay=False, path_type=Path), default=Path.cwd)
    @click.argument("action", type=click.Choice(["install", "hook"]))
    def command(path: Path, action: str) -> None:
        """Install integration or run its lifecycle hook."""
        if action == "hook":
            raise click.exceptions.Exit(coding_agents.hook(name))
        for item in coding_agents.install(name, path):
            click.echo(f"  ✓ {item}")


for _name in ("codex", "claude", "gemini"):
    _agent(_name)
