import subprocess
import sys
import click

@click.group()
def conf():
    """Configuration management commands."""
    pass

@conf.command()
def init():
    """Initialize configuration structure (env/ and etc/)."""
    try:
        click.echo("Running kardex create to initialize configuration...")
        result = subprocess.run(["kardex", "create"], check=True)
        if result.returncode == 0:
            click.echo("Configuration initialized successfully.")
    except FileNotFoundError:
        click.secho("Error: 'kardex' command not found. Please ensure kardex is installed.", fg="red", err=True)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        click.secho(f"Error during initialization with kardex: {e}", fg="red", err=True)
        sys.exit(e.returncode)
