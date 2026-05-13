"""Click command entry point for the AI-Parrot agent REPL.

Provides the ``parrot agent`` subcommand that loads a registered agent
and drops the user into an interactive REPL session.
"""
import click


@click.command("agent")
@click.argument("name", required=False)
@click.option("--list", "list_agents", is_flag=True, help="List all registered agents.")
@click.option("--server", default=None, help="Connect to a running AI-Parrot server URL.")
@click.option("--no-stream", is_flag=True, help="Disable streaming output (batch mode).")
def agent(name: str, list_agents: bool, server: str, no_stream: bool) -> None:
    """Interactive REPL for AI-Parrot agents.

    Args:
        name: Optional agent name to load.
        list_agents: If True, list all registered agents and exit.
        server: Optional server URL for server-mode operation.
        no_stream: If True, disable streaming and use batch mode.
    """
    click.echo("parrot agent: not yet implemented (stub)")
