"""Docker Compose file generator.

Generates valid docker-compose YAML files from Pydantic ComposeServiceDef models.
Implements spec Section 3 — Module 4 (FEAT-033).
"""

import asyncio
import re
from pathlib import Path
from typing import Dict, Optional

import yaml
from navconfig.logging import logging

from parrot.conf import DOCKER_FILE_LOCATION

from .models import ComposeServiceDef


class ComposeGenerator:
    """Generates docker-compose YAML from Pydantic models.

    Converts ComposeServiceDef instances into valid docker-compose v3.8 YAML,
    extracts named volumes into the top-level volumes section, and writes
    to disk at the configured DOCKER_FILE_LOCATION or a user-specified path.

    Example:
        generator = ComposeGenerator()
        services = {
            "redis": ComposeServiceDef(image="redis:alpine", ports=["6379:6379"]),
        }
        compose_dict = generator.to_dict("myproject", services)
        path = await generator.generate("myproject", services)
    """

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)

    def _extract_named_volumes(
        self, services: Dict[str, ComposeServiceDef]
    ) -> Dict[str, Optional[dict]]:
        """Extract named volumes from service definitions.

        Named volumes are those that don't start with '/', './', or '~/'
        and contain a ':' separator (e.g., 'pgdata:/var/lib/postgresql/data').
        Host path mounts like '/data:/app/data' are not extracted.

        Args:
            services: Service definitions to scan for named volumes.

        Returns:
            Dict of volume names to None (external=false, default driver).
        """
        named_volumes: Dict[str, Optional[dict]] = {}
        for svc in services.values():
            for vol in svc.volumes:
                if ":" not in vol:
                    continue
                host_part = vol.split(":")[0]
                # Named volumes don't start with path prefixes
                if not re.match(r"^[/~.]", host_part):
                    named_volumes[host_part] = None
        return named_volumes

    def to_dict(
        self,
        project_name: str,
        services: Dict[str, ComposeServiceDef],
    ) -> dict:
        """Convert service definitions to a compose dict.

        Args:
            project_name: Project name (used for logging/context).
            services: Service definitions keyed by service name.

        Returns:
            A dict representing a valid docker-compose v3.8 structure.
        """
        compose: dict = {
            "version": "3.8",
            "services": {},
        }
        for name, svc in services.items():
            svc_dict: dict = {"image": svc.image}
            if svc.ports:
                svc_dict["ports"] = svc.ports
            if svc.volumes:
                svc_dict["volumes"] = svc.volumes
            if svc.environment:
                svc_dict["environment"] = svc.environment
            if svc.depends_on:
                svc_dict["depends_on"] = svc.depends_on
            svc_dict["restart"] = svc.restart
            if svc.command:
                svc_dict["command"] = svc.command
            if svc.healthcheck:
                svc_dict["healthcheck"] = svc.healthcheck
            compose["services"][name] = svc_dict

        # Extract named volumes to top-level section
        named_volumes = self._extract_named_volumes(services)
        if named_volumes:
            compose["volumes"] = named_volumes

        self.logger.debug(
            "Built compose dict for project '%s' with %d services",
            project_name,
            len(services),
        )
        return compose

    async def generate(
        self,
        project_name: str,
        services: Dict[str, ComposeServiceDef],
        output_path: Optional[str] = None,
    ) -> str:
        """Generate and write a docker-compose.yml file.

        Args:
            project_name: Project name for the compose stack.
            services: Service definitions keyed by service name.
            output_path: Path to write the file. Defaults to
                DOCKER_FILE_LOCATION / docker-compose.yml.

        Returns:
            The absolute path to the written file.
        """
        if output_path is None:
            output_path = str(
                Path(DOCKER_FILE_LOCATION) / "docker-compose.yml"
            )

        # Ensure parent directory exists
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        compose_dict = self.to_dict(project_name, services)

        with open(output_path, "w") as f:
            yaml.dump(
                compose_dict,
                f,
                default_flow_style=False,
                sort_keys=False,
            )

        self.logger.info("Generated compose file: %s", output_path)
        return output_path

    async def validate(self, compose_path: str) -> bool:
        """Validate a docker-compose file using docker compose config.

        Args:
            compose_path: Path to the docker-compose.yml file.

        Returns:
            True if the file is valid, False otherwise.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "compose", "-f", compose_path, "config",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode == 0:
                self.logger.info(
                    "Compose file validated: %s", compose_path
                )
                return True
            self.logger.warning(
                "Compose validation failed for %s: %s",
                compose_path,
                stderr.decode().strip(),
            )
            return False
        except FileNotFoundError:
            self.logger.warning(
                "docker compose not available; skipping validation"
            )
            return False
