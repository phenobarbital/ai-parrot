"""Docker-backed remote tool executor.

Runs the envelope inside a Docker container using the async Docker
Engine API (``aiodocker``). Two lifecycle modes:

* ``"warm"`` (default) — a single long-lived container is created
  lazily and each envelope runs inside it via the Docker exec API.
  An idle TTL tears the container down after a period of inactivity
  so hosts don't accumulate stale sandboxes. Best latency.
* ``"ephemeral"`` — a fresh container is created per call and
  force-removed afterwards. Strongest isolation (no state shared
  between calls) at the cost of container start latency.

The envelope is uploaded into the container filesystem via the Engine's
``put_archive`` API and the worker is invoked as
``python -m parrot.cli.tool_worker --envelope <path>`` — the same
worker entrypoint (and the same sentinel-delimited stdout protocol)
used by :class:`K8sToolExecutor`, so results parse identically across
runtimes. A file upload is used instead of an attached stdin stream
because the Engine's exec/attach websocket has no reliable stdin
half-close, and the payload never appears in ``docker inspect`` or
``ps`` output.

Containers run with hardened defaults: all capabilities dropped,
``no-new-privileges``, memory/CPU/pids limits, and a configurable
network mode (``"none"`` gives a fully offline sandbox).

This module's heavy dependency (``aiodocker``) is only imported when
an executor instance is constructed, so projects that never use the
Docker executor are not forced to install the client.

Note: Docker Sandboxes (the ``sbx`` microVM CLI) is a planned sibling
executor behind the same interface once it grows a scriptable API; the
policy registry reserves the ``"docker-sandbox"`` name for it.
"""
from __future__ import annotations

import asyncio
import io
import logging
import re
import tarfile
import uuid
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from .abstract import AbstractToolExecutor, ToolExecutionEnvelope
from .runner import parse_sentinel_output

if TYPE_CHECKING:
    from ..abstract import ToolResult

logger = logging.getLogger(__name__)

_MEM_SUFFIXES = {"b": 1, "k": 1024, "m": 1024**2, "g": 1024**3}
_MEM_RE = re.compile(r"^(\d+)\s*([bkmg]?)$", re.IGNORECASE)

# Directory inside the container where envelopes are uploaded. /tmp is
# writable in effectively every image, including read-only-rootfs
# setups that mount a tmpfs there.
_ENVELOPE_DIR = "/tmp"


def _mem_bytes(value: Union[int, str]) -> int:
    """Parse a memory limit like ``512m`` / ``"1g"`` / ``1073741824`` into bytes."""
    if isinstance(value, int):
        return value
    match = _MEM_RE.match(value.strip())
    if not match:
        raise ValueError(
            f"Invalid memory limit {value!r}: expected e.g. '512m', '1g' "
            "or an integer byte count."
        )
    number, suffix = match.groups()
    return int(number) * _MEM_SUFFIXES[(suffix or "b").lower()]


class DockerToolExecutor(AbstractToolExecutor):
    """Runs the envelope inside a Docker container.

    Args:
        image: Container image that ships ``parrot.cli.tool_worker``.
            Defaults to :data:`parrot.conf.DOCKER_TOOL_IMAGE` (the same
            worker image the K8s executor uses).
        docker_host: Docker Engine endpoint (e.g.
            ``unix:///var/run/docker.sock`` or ``tcp://host:2375``).
            Defaults to :data:`parrot.conf.DOCKER_HOST`; when empty the
            client auto-detects from the ``DOCKER_HOST`` environment
            variable or the default unix socket.
        mode: ``"warm"`` reuses one long-lived container across calls
            (torn down after *idle_ttl_seconds* of inactivity);
            ``"ephemeral"`` creates and removes a container per call.
            Defaults to :data:`parrot.conf.DOCKER_EXECUTOR_MODE`.
        idle_ttl_seconds: Idle time after which the warm container is
            removed. Defaults to :data:`parrot.conf.DOCKER_IDLE_TTL_SECONDS`.
        network_mode: Docker network mode for the container. Defaults
            to :data:`parrot.conf.DOCKER_NETWORK_MODE` (``bridge``).
            Use ``"none"`` for tools that must run fully offline.
        mem_limit: Memory limit (``"512m"`` default) as a string with
            b/k/m/g suffix or an integer byte count.
        nano_cpus: CPU quota in units of 1e-9 CPUs. Defaults to half a
            CPU (``500_000_000``).
        pids_limit: Maximum number of processes in the container.
        cap_drop: Linux capabilities to drop. Defaults to ``["ALL"]``.
        security_opt: Docker security options. Defaults to
            ``["no-new-privileges"]``.
        env: Extra environment variables injected into the container
            (e.g. LLM API keys when dispatching Agents-as-Tools).
        volumes: Bind mounts in ``"host:container[:mode]"`` form.
        labels: Extra labels stamped on the container (merged with the
            executor's standard ``parrot-executor=true`` label).
        pull_policy: ``"missing"`` pulls the image only when absent
            locally, ``"always"`` pulls before every container
            creation, ``"never"`` never pulls.
    """

    def __init__(
        self,
        image: Optional[str] = None,
        docker_host: Optional[str] = None,
        mode: Optional[str] = None,
        idle_ttl_seconds: Optional[int] = None,
        network_mode: Optional[str] = None,
        mem_limit: Union[int, str] = "512m",
        nano_cpus: int = 500_000_000,
        pids_limit: int = 256,
        cap_drop: Optional[List[str]] = None,
        security_opt: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        volumes: Optional[List[str]] = None,
        labels: Optional[Dict[str, str]] = None,
        pull_policy: str = "missing",
    ) -> None:
        # Lazy-import the docker client so projects without the
        # ``remote-tools`` extra don't pay an import-time cost.
        try:
            import aiodocker  # noqa: F401
        except ImportError as exc:  # pragma: no cover - exercised by users
            raise ImportError(
                "aiodocker is required for DockerToolExecutor. "
                "Install with: uv pip install ai-parrot[remote-tools]"
            ) from exc

        from ...conf import (  # local to avoid heavy import cost
            DOCKER_EXECUTOR_MODE,
            DOCKER_HOST,
            DOCKER_IDLE_TTL_SECONDS,
            DOCKER_NETWORK_MODE,
            DOCKER_TOOL_IMAGE,
        )

        self.image = image or DOCKER_TOOL_IMAGE
        self.docker_host = docker_host or DOCKER_HOST or None
        self.mode = (mode or DOCKER_EXECUTOR_MODE or "warm").lower()
        if self.mode not in ("warm", "ephemeral"):
            raise ValueError(
                f"Invalid mode {self.mode!r}: expected 'warm' or 'ephemeral'."
            )
        self.idle_ttl_seconds = (
            idle_ttl_seconds
            if idle_ttl_seconds is not None
            else DOCKER_IDLE_TTL_SECONDS
        )
        self.network_mode = network_mode or DOCKER_NETWORK_MODE
        self.mem_limit_bytes = _mem_bytes(mem_limit)
        self.nano_cpus = int(nano_cpus)
        self.pids_limit = int(pids_limit)
        self.cap_drop = list(cap_drop) if cap_drop is not None else ["ALL"]
        self.security_opt = (
            list(security_opt)
            if security_opt is not None
            else ["no-new-privileges"]
        )
        self.env = dict(env or {})
        self.volumes = list(volumes or [])
        self.labels = {"parrot-executor": "true", **(labels or {})}
        if pull_policy not in ("missing", "always", "never"):
            raise ValueError(
                f"Invalid pull_policy {pull_policy!r}: expected "
                "'missing', 'always' or 'never'."
            )
        self.pull_policy = pull_policy

        self._docker: Any = None  # aiodocker.Docker
        self._warm_container: Any = None  # aiodocker container
        self._warm_lock = asyncio.Lock()
        self._inflight = 0
        self._last_used = 0.0
        self._reaper_task: Optional[asyncio.Task] = None
        self._closed = False
        self.logger = logger.getChild(self.__class__.__name__)

    # ------------------------------------------------------------------
    # Client / image plumbing
    # ------------------------------------------------------------------

    async def _ensure_client(self):
        if self._docker is not None:
            return self._docker
        import aiodocker

        self._docker = (
            aiodocker.Docker(url=self.docker_host)
            if self.docker_host
            else aiodocker.Docker()
        )
        return self._docker

    async def _ensure_image(self) -> None:
        """Pull the worker image according to ``pull_policy``."""
        if self.pull_policy == "never":
            return
        docker = await self._ensure_client()
        if self.pull_policy == "always":
            await docker.images.pull(self.image)
            return
        # "missing": inspect first, pull only on absence.
        try:
            await docker.images.inspect(self.image)
        except Exception:
            self.logger.info("Pulling worker image %s", self.image)
            await docker.images.pull(self.image)

    def _host_config(self) -> Dict[str, Any]:
        host_config: Dict[str, Any] = {
            "NetworkMode": self.network_mode,
            "Memory": self.mem_limit_bytes,
            "NanoCpus": self.nano_cpus,
            "PidsLimit": self.pids_limit,
            "CapDrop": self.cap_drop,
            "SecurityOpt": self.security_opt,
        }
        if self.volumes:
            host_config["Binds"] = list(self.volumes)
        return host_config

    def _container_config(self, cmd: List[str]) -> Dict[str, Any]:
        return {
            "Image": self.image,
            "Cmd": cmd,
            "Env": [f"{k}={v}" for k, v in self.env.items()],
            "Labels": dict(self.labels),
            "HostConfig": self._host_config(),
        }

    @staticmethod
    def _envelope_tar(envelope_json: str, filename: str) -> bytes:
        """Pack the envelope JSON into an in-memory tar for ``put_archive``."""
        buf = io.BytesIO()
        data = envelope_json.encode("utf-8")
        with tarfile.open(fileobj=buf, mode="w") as tar:
            info = tarfile.TarInfo(name=filename)
            info.size = len(data)
            info.mode = 0o600
            tar.addfile(info, io.BytesIO(data))
        return buf.getvalue()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(
        self, envelope: ToolExecutionEnvelope
    ) -> "ToolResult":
        from ..abstract import ToolResult

        if self._closed:
            return ToolResult(
                success=False,
                status="error",
                result=None,
                error="DockerToolExecutor is closed.",
                metadata={"executor": "docker", "mode": self.mode},
            )

        self._inflight += 1
        try:
            runner = (
                self._execute_warm
                if self.mode == "warm"
                else self._execute_ephemeral
            )
            return await asyncio.wait_for(
                runner(envelope), timeout=envelope.timeout_seconds
            )
        except asyncio.TimeoutError:
            if self.mode == "warm":
                # A stuck worker would keep burning the warm container's
                # resources; reset it so the next call starts clean.
                await self._teardown_warm()
            return ToolResult(
                success=False,
                status="error",
                result=None,
                error=(
                    f"Docker tool execution did not finish within "
                    f"{envelope.timeout_seconds}s"
                ),
                metadata={"executor": "docker", "mode": self.mode},
            )
        except Exception as exc:
            return ToolResult(
                success=False,
                status="error",
                result=None,
                error=f"Docker executor failed: {exc}",
                metadata={"executor": "docker", "mode": self.mode},
            )
        finally:
            self._inflight -= 1
            self._last_used = asyncio.get_event_loop().time()

    async def close(self) -> None:
        self._closed = True
        if self._reaper_task is not None:
            self._reaper_task.cancel()
            self._reaper_task = None
        await self._teardown_warm()
        if self._docker is not None:
            try:
                await self._docker.close()
            except Exception:
                pass
            self._docker = None

    # ------------------------------------------------------------------
    # Warm mode
    # ------------------------------------------------------------------

    async def _ensure_warm_container(self):
        async with self._warm_lock:
            if self._warm_container is not None:
                return self._warm_container
            docker = await self._ensure_client()
            await self._ensure_image()
            name = f"parrot-tool-warm-{uuid.uuid4().hex[:12]}"
            # The warm container just sleeps; work happens via exec.
            config = self._container_config(["sleep", "infinity"])
            self.logger.info(
                "Creating warm Docker container %s image=%s", name, self.image
            )
            container = await docker.containers.create(config=config, name=name)
            await container.start()
            self._warm_container = container
            self._last_used = asyncio.get_event_loop().time()
            if self._reaper_task is None:
                self._reaper_task = asyncio.get_event_loop().create_task(
                    self._reaper_loop()
                )
            return container

    async def _execute_warm(
        self, envelope: ToolExecutionEnvelope
    ) -> "ToolResult":
        container = await self._ensure_warm_container()
        envelope_name = f"parrot-envelope-{uuid.uuid4().hex}.json"
        envelope_path = f"{_ENVELOPE_DIR}/{envelope_name}"
        await container.put_archive(
            _ENVELOPE_DIR,
            self._envelope_tar(envelope.model_dump_json(), envelope_name),
        )
        # One shell round-trip runs the worker AND removes the envelope
        # file so secrets don't linger in the warm container between
        # calls. The path is executor-generated (uuid hex) — no quoting
        # hazards.
        cmd = [
            "sh",
            "-c",
            (
                f"python -m parrot.cli.tool_worker --envelope {envelope_path}; "
                f"s=$?; rm -f {envelope_path}; exit $s"
            ),
        ]
        exec_ = await container.exec(cmd=cmd, stdout=True, stderr=True)
        output = await self._collect_exec_output(exec_)
        container_id = getattr(container, "id", None)
        return parse_sentinel_output(
            output,
            metadata={
                "executor": "docker",
                "mode": "warm",
                "container_id": container_id,
                "exec_id": getattr(exec_, "id", None),
            },
        )

    @staticmethod
    async def _collect_exec_output(exec_: Any) -> str:
        """Drain an exec's multiplexed stdout/stderr stream to a string."""
        chunks: List[bytes] = []
        async with exec_.start(detach=False) as stream:
            while True:
                message = await stream.read_out()
                if message is None:
                    break
                chunks.append(message.data)
        return b"".join(chunks).decode("utf-8", errors="replace")

    async def _teardown_warm(self) -> None:
        async with self._warm_lock:
            container, self._warm_container = self._warm_container, None
        if container is None:
            return
        try:
            await container.delete(force=True)
        except Exception as exc:
            self.logger.warning(
                "Failed to remove warm Docker container: %s", exc
            )

    async def _maybe_reap(self) -> bool:
        """Tear the warm container down if it has been idle past the TTL.

        Returns True when the container was reaped.
        """
        if self._warm_container is None or self._inflight > 0:
            return False
        idle = asyncio.get_event_loop().time() - self._last_used
        if idle < self.idle_ttl_seconds:
            return False
        self.logger.info(
            "Reaping warm Docker container after %.0fs idle", idle
        )
        await self._teardown_warm()
        return True

    async def _reaper_loop(self) -> None:
        """Periodically check the warm container against ``idle_ttl_seconds``."""
        interval = max(self.idle_ttl_seconds / 4.0, 1.0)
        try:
            while True:
                await asyncio.sleep(interval)
                await self._maybe_reap()
        except asyncio.CancelledError:  # close() cancels us
            pass

    # ------------------------------------------------------------------
    # Ephemeral mode
    # ------------------------------------------------------------------

    async def _execute_ephemeral(
        self, envelope: ToolExecutionEnvelope
    ) -> "ToolResult":
        docker = await self._ensure_client()
        await self._ensure_image()
        name = f"parrot-tool-{uuid.uuid4().hex[:12]}"
        envelope_name = f"parrot-envelope-{uuid.uuid4().hex}.json"
        envelope_path = f"{_ENVELOPE_DIR}/{envelope_name}"
        config = self._container_config(
            [
                "python",
                "-m",
                "parrot.cli.tool_worker",
                "--envelope",
                envelope_path,
            ]
        )
        self.logger.info(
            "Creating ephemeral Docker container %s image=%s tool=%s",
            name,
            self.image,
            envelope.tool_import_path,
        )
        container = await docker.containers.create(config=config, name=name)
        try:
            # Upload the envelope before starting — put_archive works on
            # created (not yet running) containers.
            await container.put_archive(
                _ENVELOPE_DIR,
                self._envelope_tar(envelope.model_dump_json(), envelope_name),
            )
            await container.start()
            await container.wait()
            logs = await container.log(stdout=True, stderr=True)
            output = "".join(logs) if isinstance(logs, list) else str(logs)
            return parse_sentinel_output(
                output,
                metadata={
                    "executor": "docker",
                    "mode": "ephemeral",
                    "container_id": getattr(container, "id", None),
                    "container_name": name,
                },
            )
        finally:
            try:
                await container.delete(force=True)
            except Exception as cleanup_exc:
                self.logger.warning(
                    "Failed to remove Docker container %s: %s",
                    name,
                    cleanup_exc,
                )
