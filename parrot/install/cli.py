"""CLI commands for installing external tools via Docker."""
import subprocess
import sys
from pathlib import Path
import click
from navconfig.logging import logging


logger = logging.getLogger("parrot.install.cli")

# Default services path: ~/.parrot/services
PARROT_SERVICES_DIR = Path.home() / ".parrot" / "services"


@click.group(invoke_without_command=True)
@click.pass_context
def install(ctx):
    """Install external tools and services (e.g., CloudSploit, Prowler)."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


def _run_command(cmd: str, cwd: Path = None, check: bool = True):
    """Run a shell command."""
    click.echo(f"==> Running: {cmd}")
    try:
        subprocess.run(
            cmd,
            shell=True,
            check=check,
            cwd=cwd,
            stdout=sys.stdout if click.get_current_context().params.get("verbose", False) else subprocess.PIPE,
            stderr=subprocess.STDOUT
        )
    except subprocess.CalledProcessError as e:
        click.secho(f"Error running command: {cmd}", fg="red")
        if e.output:
            click.secho(e.output.decode("utf-8"), fg="red")
        raise click.Abort()


@install.command()
@click.option("--verbose", is_flag=True, help="Enable verbose output")
def cloudsploit(verbose):
    """Install CloudSploit by cloning its repo, patching, and building a Docker image."""
    click.secho("Starting CloudSploit installation...", fg="green")

    # Ensure services directory exists
    PARROT_SERVICES_DIR.mkdir(parents=True, exist_ok=True)
    cloudsploit_dir = PARROT_SERVICES_DIR / "cloudsploit"

    # Git clone
    if not cloudsploit_dir.exists():
        click.echo(f"Cloning CloudSploit to {cloudsploit_dir}...")
        try:
            subprocess.run(
                ["git", "clone", "https://github.com/aquasecurity/cloudsploit.git", str(cloudsploit_dir)],
                check=True,
                stdout=sys.stdout if verbose else subprocess.PIPE,
                stderr=subprocess.STDOUT
            )
        except subprocess.CalledProcessError as e:
            click.secho("Failed to clone CloudSploit repository.", fg="red")
            if e.output:
                click.secho(e.output.decode("utf-8"), fg="red")
            raise click.Abort()
    else:
        click.echo(f"CloudSploit directory already exists at {cloudsploit_dir}. Updating...")
        try:
            subprocess.run(
                ["git", "pull"],
                cwd=cloudsploit_dir,
                check=True,
                stdout=sys.stdout if verbose else subprocess.PIPE,
                stderr=subprocess.STDOUT
            )
        except subprocess.CalledProcessError as e:
            click.secho("Failed to update CloudSploit repository.", fg="red")
            if e.output:
                click.secho(e.output.decode("utf-8"), fg="red")
            raise click.Abort()

    # Patch Dockerfile
    dockerfile_path = cloudsploit_dir / "Dockerfile"
    if dockerfile_path.exists():
        click.echo("Patching Dockerfile...")
        content = dockerfile_path.read_text(encoding="utf-8")
        patched_content = content.replace('ENTRYPOINT ["cloudsploitscan"]', 'ENTRYPOINT ["cloudsploit-scan"]')
        if content != patched_content:
            dockerfile_path.write_text(patched_content, encoding="utf-8")
            click.echo("Dockerfile patched successfully.")
        else:
            click.echo("Dockerfile already patched or ENTRYPOINT not found.")
    else:
        click.secho("Dockerfile not found in CloudSploit repository.", fg="yellow")

    # Patch export.js (comment out codestar lines)
    export_js_path = cloudsploit_dir / "export.js"
    if export_js_path.exists():
        click.echo("Patching export.js...")
        lines = export_js_path.read_text(encoding="utf-8").splitlines()
        patched_lines = []
        patched = False
        for line in lines:
            if "codestarValidRepoProviders" in line or "codestarHasTags" in line:
                if not line.strip().startswith("//"):
                    line = f"// {line}"
                    patched = True
            patched_lines.append(line)
        
        if patched:
            export_js_path.write_text("\n".join(patched_lines) + "\n", encoding="utf-8")
            click.echo("export.js patched successfully.")
        else:
            click.echo("export.js already patched or target lines not found.")
    else:
        click.secho("export.js not found in CloudSploit repository.", fg="yellow")

    # Docker build
    click.echo("Building CloudSploit Docker image (cloudsploit:0.0.1)...")
    try:
        subprocess.run(
            ["docker", "build", ".", "-t", "cloudsploit:0.0.1"],
            cwd=cloudsploit_dir,
            check=True,
            stdout=sys.stdout if verbose else subprocess.PIPE,
            stderr=subprocess.STDOUT
        )
        click.secho("CloudSploit built successfully!", fg="green")
    except subprocess.CalledProcessError as e:
        click.secho("Failed to build CloudSploit Docker image.", fg="red")
        if e.output:
            click.secho(e.output.decode("utf-8"), fg="red")
        raise click.Abort()


@install.command()
@click.option("--verbose", is_flag=True, help="Enable verbose output")
def prowler(verbose):
    """Install Prowler by pulling its latest Docker image."""
    click.secho("Starting Prowler installation...", fg="green")
    
    click.echo("Pulling prowler/prowler:latest Docker image...")
    try:
        subprocess.run(
            ["docker", "pull", "prowler/prowler:latest"],
            check=True,
            stdout=sys.stdout if verbose else subprocess.PIPE,
            stderr=subprocess.STDOUT
        )
        click.secho("Prowler pulled successfully!", fg="green")
    except subprocess.CalledProcessError as e:
        click.secho("Failed to pull Prowler Docker image.", fg="red")
        if e.output:
            click.secho(e.output.decode("utf-8"), fg="red")
        raise click.Abort()


@install.command()
@click.option("--verbose", is_flag=True, help="Enable verbose output")
def scoutsuite(verbose):
    """Install ScoutSuite by running uv pip install."""
    click.secho("Starting ScoutSuite installation...", fg="green")
    
    click.echo("Running `uv pip install scoutsuite`...")
    try:
        subprocess.run(
            ["uv", "pip", "install", "scoutsuite"],
            check=True,
            stdout=sys.stdout if verbose else subprocess.PIPE,
            stderr=subprocess.STDOUT
        )
        click.secho("ScoutSuite installed successfully!", fg="green")
    except subprocess.CalledProcessError as e:
        click.secho("Failed to install ScoutSuite.", fg="red")
        if e.output:
            click.secho(e.output.decode("utf-8"), fg="red")
        raise click.Abort()

