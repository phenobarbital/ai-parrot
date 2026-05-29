"""CLI commands for AutonomousOrchestrator deployment.

Provides:
    parrot autonomous create --agent <path>
    parrot autonomous install --agent <path> [--name ...] [--bind ...] [--workers ...]
"""
import sys
from pathlib import Path

import click


@click.group()
def autonomous() -> None:
    """Manage AutonomousOrchestrator agents."""


@autonomous.command()
@click.option(
    "--agent",
    required=True,
    type=click.Path(dir_okay=False, writable=True),
    help="Output path for the generated agent script (e.g. my_agent.py).",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Overwrite the file if it already exists.",
)
def create(agent: str, force: bool) -> None:
    """Generate a sample AutonomousOrchestrator agent script.

    Example:

        parrot autonomous create --agent ./my_agent.py
    """
    from .deploy.installer import create_sample_agent

    output = Path(agent)
    if output.exists() and not force:
        click.confirm(
            f"{output} already exists. Overwrite?",
            abort=True,
        )

    result = create_sample_agent(output)
    click.echo(f"✅ Sample agent created at {result}")
    click.echo(
        f"\nNext step — generate deployment configs:\n"
        f"  parrot autonomous install --agent {result}"
    )


@autonomous.command()
@click.option(
    "--agent",
    required=True,
    type=click.Path(exists=True, dir_okay=False, readable=True),
    help="Path to the agent Python script.",
)
@click.option(
    "--name",
    default=None,
    help="Service name (defaults to script filename stem).",
)
@click.option(
    "--bind",
    default="0.0.0.0:8080",
    show_default=True,
    help="Host:port for gunicorn to bind to.",
)
@click.option(
    "--workers",
    default=None,
    type=int,
    help="Number of gunicorn workers (default: (2×CPUs)+1).",
)
@click.option(
    "--venv",
    default=None,
    type=click.Path(exists=True, file_okay=False),
    help="Path to the virtualenv (auto-detected if omitted).",
)
@click.option(
    "--enable-service",
    is_flag=True,
    default=False,
    help="Copy systemd unit to /etc/systemd/system/ and enable it (requires sudo).",
)
def install(
    agent: str,
    name: str | None,
    bind: str,
    workers: int | None,
    venv: str | None,
    enable_service: bool,
) -> None:
    """Generate gunicorn, supervisord, and systemd configs for an agent.

    Example:

        parrot autonomous install --agent ./my_agent.py --bind 0.0.0.0:8080

    With service registration:

        parrot autonomous install --agent ./my_agent.py --enable-service
    """
    import shutil
    import subprocess

    from .deploy.installer import AgentInstaller

    agent_path = Path(agent)

    installer = AgentInstaller(
        agent_path,
        name=name,
        bind=bind,
        workers=workers,
        venv_path=venv,
    )

    results = installer.install()

    click.echo("✅ Deployment configs generated:")
    for config_type, path in results.items():
        click.echo(f"   {config_type:12s} → {path}")

    # Optional: register as systemd service
    if enable_service:
        service_path = results["systemd"]
        dest = Path(f"/etc/systemd/system/{service_path.name}")

        click.echo(f"\n📋 Installing systemd service to {dest} …")
        try:
            shutil.copy2(service_path, dest)
            subprocess.run(
                ["systemctl", "daemon-reload"],
                check=True,
            )
            subprocess.run(
                ["systemctl", "enable", service_path.stem],
                check=True,
            )
            click.echo(f"✅ Service '{service_path.stem}' enabled.")
            click.echo(f"   Start it with: sudo systemctl start {service_path.stem}")
        except PermissionError:
            click.echo(
                "❌ Permission denied. Re-run with sudo:\n"
                f"   sudo parrot autonomous install --agent {agent} --enable-service",
                err=True,
            )
            sys.exit(1)
        except subprocess.CalledProcessError as exc:
            click.echo(f"❌ systemctl failed: {exc}", err=True)
            sys.exit(1)
    else:
        svc = results["systemd"]
        sup = results["supervisord"]
        click.echo(
            f"\n📋 To register as a system service:\n"
            f"   Systemd:     sudo cp {svc} /etc/systemd/system/ && "
            f"sudo systemctl daemon-reload && sudo systemctl enable {svc.stem}\n"
            f"   Supervisord: sudo cp {sup} /etc/supervisor/conf.d/ && "
            f"sudo supervisorctl reread && sudo supervisorctl update"
        )
