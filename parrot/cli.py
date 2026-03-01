"""Top-level CLI entrypoint for Parrot utilities."""
import click
from parrot.mcp.cli import mcp
from parrot.autonomous.cli import autonomous
from parrot.install.cli import install
from parrot.install.conf import conf

@click.group()
def cli():
    """Parrot command-line interface."""
    pass

# Attach subcommands
cli.add_command(mcp, name="mcp")
cli.add_command(autonomous, name="autonomous")
cli.add_command(install, name="install")
cli.add_command(conf, name="conf")

if __name__ == "__main__":
    cli()
