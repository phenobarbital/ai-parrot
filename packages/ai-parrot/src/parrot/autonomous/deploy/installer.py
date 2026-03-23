"""Generates deployment configs for AutonomousOrchestrator agents."""
from __future__ import annotations

import getpass
import multiprocessing
import os
import sys
from pathlib import Path
from typing import Optional

from navconfig.logging import logging

from .templates import (
    GUNICORN_CONFIG_TEMPLATE,
    SAMPLE_AGENT_TEMPLATE,
    SUPERVISORD_CONFIG_TEMPLATE,
    SYSTEMD_SERVICE_TEMPLATE,
)

logger = logging.getLogger("parrot.autonomous.deploy")


def _default_workers() -> int:
    """Return a sensible default worker count: (2 × CPUs) + 1, capped at 9."""
    return min((2 * multiprocessing.cpu_count()) + 1, 9)


def _resolve_venv() -> str:
    """Return the path to the current virtual-env, or fall back to sys.prefix."""
    return os.environ.get("VIRTUAL_ENV", sys.prefix)


def _module_path_from_file(agent_path: Path) -> str:
    """Derive a dotted module path from a Python file.

    Given ``/opt/agents/my_agent.py`` returns ``my_agent`` (just the stem),
    which is what gunicorn expects for a file-based load.
    """
    return agent_path.stem


class AgentInstaller:
    """Generates gunicorn, supervisord, and systemd configs for an agent."""

    def __init__(
        self,
        agent_path: Path,
        *,
        name: Optional[str] = None,
        bind: str = "0.0.0.0:8080",
        workers: Optional[int] = None,
        venv_path: Optional[str] = None,
        user: Optional[str] = None,
    ) -> None:
        self.agent_path = agent_path.resolve()
        self.name = name or self.agent_path.stem
        self.bind = bind
        self.workers = workers or _default_workers()
        self.venv_path = venv_path or _resolve_venv()
        self.user = user or getpass.getuser()
        self.working_dir = str(self.agent_path.parent)
        self.module_path = _module_path_from_file(self.agent_path)

    # ------------------------------------------------------------------
    # Individual generators
    # ------------------------------------------------------------------

    def generate_gunicorn_config(self) -> Path:
        """Write a ``<name>_gunicorn.py`` file next to the agent script."""
        config_filename = f"{self.name}_gunicorn.py"
        out = self.agent_path.parent / config_filename

        content = GUNICORN_CONFIG_TEMPLATE.format(
            agent_name=self.name,
            config_filename=config_filename,
            module_path=self.module_path,
            bind=self.bind,
            workers=self.workers,
        )
        out.write_text(content, encoding="utf-8")
        logger.info("Gunicorn config written to %s", out)
        return out

    def generate_supervisord_config(self) -> Path:
        """Write a ``<name>.supervisor.conf`` file next to the agent script."""
        config_filename = f"{self.name}.supervisor.conf"
        gunicorn_config = self.agent_path.parent / f"{self.name}_gunicorn.py"
        out = self.agent_path.parent / config_filename

        content = SUPERVISORD_CONFIG_TEMPLATE.format(
            agent_name=self.name,
            config_filename=config_filename,
            venv_path=self.venv_path,
            gunicorn_config_path=str(gunicorn_config),
            module_path=self.module_path,
            working_dir=self.working_dir,
            user=self.user,
        )
        out.write_text(content, encoding="utf-8")
        logger.info("Supervisord config written to %s", out)
        return out

    def generate_systemd_service(self) -> Path:
        """Write a ``<name>.service`` file next to the agent script."""
        service_filename = f"{self.name}.service"
        gunicorn_config = self.agent_path.parent / f"{self.name}_gunicorn.py"
        out = self.agent_path.parent / service_filename

        content = SYSTEMD_SERVICE_TEMPLATE.format(
            agent_name=self.name,
            service_filename=service_filename,
            venv_path=self.venv_path,
            gunicorn_config_path=str(gunicorn_config),
            module_path=self.module_path,
            working_dir=self.working_dir,
            user=self.user,
        )
        out.write_text(content, encoding="utf-8")
        logger.info("Systemd service written to %s", out)
        return out

    # ------------------------------------------------------------------
    # All-in-one
    # ------------------------------------------------------------------

    def install(self) -> dict[str, Path]:
        """Generate all deployment artifacts.

        Returns a dict mapping config type to output path.
        """
        results: dict[str, Path] = {
            "gunicorn": self.generate_gunicorn_config(),
            "supervisord": self.generate_supervisord_config(),
            "systemd": self.generate_systemd_service(),
        }
        return results


def create_sample_agent(output_path: Path) -> Path:
    """Write a sample AutonomousOrchestrator agent script to *output_path*."""
    content = SAMPLE_AGENT_TEMPLATE.format(
        filename=output_path.name,
        filename_stem=output_path.stem,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    logger.info("Sample agent script written to %s", output_path)
    return output_path
