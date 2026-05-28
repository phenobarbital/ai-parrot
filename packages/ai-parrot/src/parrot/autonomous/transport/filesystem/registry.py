"""AgentRegistry — presence management via filesystem JSON files."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiofiles

from .config import FilesystemTransportConfig

logger = logging.getLogger(__name__)


class AgentRegistry:
    """Agent presence registry using JSON files on the filesystem.

    Each agent is represented by a ``<agent_id>.json`` file in the registry
    directory. Liveness is determined by PID checking (``os.kill(pid, 0)``),
    providing instant detection of crashed agents without waiting for
    heartbeat timeouts.

    All writes use the write-then-rename pattern for POSIX atomicity.

    Args:
        registry_dir: Path to the registry directory.
        config: Transport configuration.
    """

    def __init__(self, registry_dir: Path, config: FilesystemTransportConfig) -> None:
        self._dir = registry_dir
        self._config = config

    async def join(
        self,
        agent_id: str,
        name: str,
        pid: int,
        hostname: str,
        cwd: str,
        role: str,
        *,
        status: str = "idle",
        message: str = "",
    ) -> None:
        """Register an agent in the registry.

        Args:
            agent_id: Unique agent identifier.
            name: Human-readable agent name.
            pid: Process ID of the agent.
            hostname: Host where the agent runs.
            cwd: Working directory of the agent.
            role: Agent role (e.g. "agent", "coordinator").
            status: Initial status string.
            message: Optional status message.
        """
        self._dir.mkdir(parents=True, exist_ok=True)
        now = time.time()
        data = {
            "agent_id": agent_id,
            "name": name,
            "pid": pid,
            "hostname": hostname,
            "cwd": cwd,
            "role": role,
            "status": status,
            "message": message,
            "joined_at": now,
            "last_seen": now,
        }
        await self._write(agent_id, data)
        logger.info("Agent %s (%s) joined registry", name, agent_id)

    async def leave(self, agent_id: str) -> None:
        """Deregister an agent from the registry.

        Args:
            agent_id: The agent to remove.
        """
        path = self._dir / f"{agent_id}.json"
        try:
            path.unlink()
            logger.info("Agent %s left registry", agent_id)
        except FileNotFoundError:
            logger.debug("Agent %s not found in registry (already removed)", agent_id)

    async def heartbeat(
        self,
        agent_id: str,
        *,
        status: Optional[str] = None,
        message: Optional[str] = None,
    ) -> None:
        """Update an agent's heartbeat timestamp and optional fields.

        Args:
            agent_id: The agent to update.
            status: Optional new status.
            message: Optional new status message.
        """
        data = await self._read(agent_id)
        if data is None:
            logger.warning("Heartbeat for unknown agent %s", agent_id)
            return
        data["last_seen"] = time.time()
        if status is not None:
            data["status"] = status
        if message is not None:
            data["message"] = message
        await self._write(agent_id, data)

    async def list_active(self) -> List[Dict[str, Any]]:
        """List all agents with live PIDs.

        Returns:
            List of agent data dicts for agents whose PIDs are alive.
        """
        if not self._dir.exists():
            return []
        agents: List[Dict[str, Any]] = []
        for path in self._dir.iterdir():
            if path.name.startswith(".") or path.suffix != ".json":
                continue
            data = await self._read_path(path)
            if data is None:
                continue
            if not self._is_alive(data.get("pid", -1)):
                continue
            if self._config.scope_to_cwd:
                if data.get("cwd") != os.getcwd():
                    continue
            agents.append(data)
        return agents

    async def resolve(self, name_or_id: str) -> Optional[Dict[str, Any]]:
        """Resolve an agent by agent_id (exact) or name (case-insensitive).

        Args:
            name_or_id: Agent ID or name to search for.

        Returns:
            Agent data dict if found, None otherwise.
        """
        agents = await self.list_active()
        # Exact match on agent_id first.
        for agent in agents:
            if agent.get("agent_id") == name_or_id:
                return agent
        # Case-insensitive match on name.
        lower = name_or_id.lower()
        for agent in agents:
            if agent.get("name", "").lower() == lower:
                return agent
        return None

    async def gc_stale(self) -> List[str]:
        """Remove registry entries for agents with dead PIDs.

        Returns:
            List of agent_ids that were removed.
        """
        if not self._dir.exists():
            return []
        removed: List[str] = []
        for path in self._dir.iterdir():
            if path.name.startswith(".") or path.suffix != ".json":
                continue
            data = await self._read_path(path)
            if data is None:
                continue
            if not self._is_alive(data.get("pid", -1)):
                agent_id = data.get("agent_id", path.stem)
                try:
                    path.unlink()
                    removed.append(agent_id)
                    logger.info("GC removed stale agent %s", agent_id)
                except FileNotFoundError:
                    pass
        return removed

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _write(self, agent_id: str, data: Dict[str, Any]) -> None:
        """Write agent data using write-then-rename for atomicity."""
        self._dir.mkdir(parents=True, exist_ok=True)
        tmp_path = self._dir / f".tmp-{agent_id}.json"
        target = self._dir / f"{agent_id}.json"
        async with aiofiles.open(tmp_path, "w") as f:
            await f.write(json.dumps(data, indent=2))
        tmp_path.rename(target)

    async def _read(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Read agent data by agent_id."""
        return await self._read_path(self._dir / f"{agent_id}.json")

    async def _read_path(self, path: Path) -> Optional[Dict[str, Any]]:
        """Read and parse a registry JSON file."""
        try:
            async with aiofiles.open(path, "r") as f:
                content = await f.read()
            return json.loads(content)
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            logger.debug("Failed to read registry file %s: %s", path, exc)
            return None

    @staticmethod
    def _is_alive(pid: int) -> bool:
        """Check if a process with the given PID is alive.

        Uses ``os.kill(pid, 0)`` which does not send a signal but checks
        for process existence.

        Returns:
            True if the process exists, False otherwise.
        """
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            # Process exists but owned by another user.
            return True
        except OSError:
            return False
