"""CLI entry point for the parrot setup wizard."""
import click

from parrot.setup.wizard import WizardRunner


@click.command()
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Overwrite existing app.py and run.py if they exist.",
)
def setup(force: bool) -> None:
    """Interactive first-time setup wizard for AI-Parrot.

    Guides you through:

    \b
      - Selecting an LLM provider and entering credentials
      - Writing credentials to the correct .env file
      - Optionally creating an Agent in AGENTS_DIR
      - Optionally generating app.py and run.py bootstrap files

    Run 'parrot setup --force' to overwrite existing app.py / run.py.
    """
    click.echo(click.style("\nWelcome to AI-Parrot Setup", bold=True))
    click.echo("Press Ctrl+C at any time to cancel.\n")

    runner = WizardRunner(force=force)
    try:
        result = runner.run()
    except KeyboardInterrupt:
        click.echo("\nSetup cancelled.")
        return

    # Summary
    click.echo()
    click.secho("Setup complete!", fg="green", bold=True)
    click.echo(f"  Provider  : {result.provider_config.llm_string}")
    click.echo(f"  Env file  : {result.env_file_path}")
    if result.agent_config:
        click.echo(f"  Agent     : {result.agent_config.file_path}")
    if result.app_bootstrapped:
        click.echo("  Generated : app.py, run.py")
    click.echo("\nNext steps:")
    click.echo("  1. Review the .env file and verify your credentials")
    if result.agent_config:
        click.echo(f"  2. Customize {result.agent_config.file_path}")
    click.echo("  3. Run: python run.py")
