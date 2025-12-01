"""Top-level CLI entrypoint for Parrot utilities."""
import click
from parrot.mcp.cli import mcp


@click.group()
def cli():
    """Parrot command-line interface."""
    pass


# Attach subcommands
cli.add_command(mcp, name="mcp")


if __name__ == "__main__":
    cli()
