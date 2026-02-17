"""Top-level CLI entrypoint for Parrot utilities."""
import click
from parrot.mcp.cli import mcp
from parrot.autonomous.cli import autonomous


@click.group()
def cli():
    """Parrot command-line interface."""
    pass


# Attach subcommands
cli.add_command(mcp, name="mcp")
cli.add_command(autonomous, name="autonomous")


if __name__ == "__main__":
    cli()
