"""Provision a tenant its own stack, driving the Pulumi CLI.

Same port as :class:`~parrot_saas.provisioning.shared.SharedDeployer`, so the
control plane calls the same four methods whichever plane a tenant is on. What
differs is everything underneath: this one shells out to ``pulumi`` against a
program directory and a local Docker daemon.

## Three gaps in ``PulumiExecutor`` this routes around

Each is worked around here rather than patched upstream — the upstream fix is
its own proposal (``sdd/proposals/pulumi-executor-gaps.brainstorm.md``) and
belongs in ``ai-parrot-tools``, where it benefits every consumer.

1. **``config_values`` is accepted and discarded.** ``preview()`` and ``up()``
   both take the argument and never forward it to ``_execute_in_project``;
   their docstrings say "not yet implemented". Passing a tenant's slug through
   it would produce a stack built with the *previous* tenant's config, or none
   at all. This deployer writes ``Pulumi.<stack>.yaml`` itself before running,
   which is what the CLI reads anyway.
2. **``PulumiConfig.state_backend`` is a dead field.** Nothing reads it, and
   there is no ``pulumi login`` anywhere, so a default install would try to
   reach Pulumi Cloud. ``PULUMI_BACKEND_URL`` is exported into the process
   environment instead — which works because ``_build_process_env`` starts
   from ``os.environ.copy()``.
3. **Docker mode cannot drive the Docker provider.**
   ``_build_docker_command`` mounts the project directory and nothing else,
   never ``/var/run/docker.sock``, so Pulumi in a container has no daemon to
   talk to. ``use_docker`` is forced to ``False`` and the host CLI is used.

A fourth, smaller one is worth naming because it looks like a bug in this
file: ``expected_exit_codes`` is ``[0, 1]``, but that list only suppresses a
warning log — ``_parse_pulumi_output`` still sets ``success`` from
``exit_code == 0``. So ``result.success`` is the honest signal and the two
disagree by design; nothing here should consult the exit code itself.

## The connection string never becomes a public output

The stack exports its DSN as a Pulumi secret, so it is encrypted in the state
file. This deployer moves it into the tenant secret store under
``deployment:<stack>:dsn`` and records only that *name* in the control plane's
``outputs`` column — a jsonb column the control plane reads freely and every
backup copies.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Optional

from navconfig.logging import logging

from .. import conf
from ..tenancy.context import TenantContext
from .base import TenantDeployer
from .models import DeploymentResult, DeploymentStatus

logger = logging.getLogger("parrot_saas.provisioning.pulumi")

#: Directory holding the local Docker program.
DEFAULT_PROGRAM_DIR = Path(__file__).resolve().parent / "programs" / "docker"

#: Stack outputs that must never be recorded in the control plane.
SECRET_OUTPUTS = ("dsn",)

#: Secret name a stack's connection string is stored under.
DSN_SECRET_TEMPLATE = "deployment:{stack}:dsn"


def stack_name(tenant_id: str) -> str:
    """Return the Pulumi stack name for a tenant.

    Args:
        tenant_id: The tenant slug, already validated as
            ``^[a-z][a-z0-9-]{1,62}$`` by :class:`TenantContext`.

    Returns:
        The stack name.
    """
    return f"tenant-{tenant_id}"


class PulumiDeployer(TenantDeployer):
    """Builds and tears down a tenant's own stack.

    Args:
        program_dir: Pulumi program to run. **The seam for other providers**:
            an AWS or GCP stack is a sibling directory exporting the same
            output names, and nothing else about this class changes.
        secret_store: Where the stack's connection string is put. Without one
            the DSN is dropped rather than recorded — losing it is recoverable
            (``pulumi stack output``), writing it to a plain column is not.
        executor: Pre-built ``PulumiExecutor``, for tests. Normally built from
            :func:`build_executor`.
        image: Container image for the tenant worker.
        port_allocator: ``(tenant) -> int`` choosing the published host port.
            Defaults to a deterministic hash over the configured range, so a
            re-provision reuses the tenant's port instead of moving it.
        state_dir: Local Pulumi state directory.
        passphrase: Passphrase for the local secrets provider.
        timeout: Seconds allowed for one Pulumi operation.
    """

    name = "pulumi-docker"

    def __init__(
        self,
        *,
        program_dir: Optional[Path] = None,
        secret_store: Optional[Any] = None,
        executor: Optional[Any] = None,
        image: str = conf.SAAS_TENANT_IMAGE,
        port_allocator: Optional[Any] = None,
        state_dir: Path = conf.SAAS_PULUMI_STATE_DIR,
        passphrase: str = conf.SAAS_PULUMI_PASSPHRASE,
        timeout: int = conf.SAAS_PULUMI_TIMEOUT,
    ) -> None:
        self._program_dir = Path(program_dir or DEFAULT_PROGRAM_DIR)
        self._secret_store = secret_store
        self._executor = executor
        self._image = image
        self._allocate_port = port_allocator or default_port
        self._state_dir = Path(state_dir)
        self._passphrase = passphrase
        self._timeout = timeout

    # -- the port ----------------------------------------------------------

    async def plan(self, tenant: TenantContext) -> DeploymentResult:
        """Preview the tenant's stack without building anything."""
        stack = stack_name(tenant.tenant_id)
        ready, problem = self._preflight()
        if not ready:
            return self._blocked(tenant, "plan", stack, problem)

        self._write_stack_config(tenant, stack)
        result = await self._executor_or_build().preview(
            str(self._program_dir), stack=stack
        )
        return DeploymentResult(
            tenant_id=tenant.tenant_id,
            operation="plan",
            success=result.success,
            # A plan builds nothing, so it never reports READY — that would
            # make a preview look like a provisioned tenant.
            status=(
                DeploymentStatus.PENDING
                if result.success
                else DeploymentStatus.FAILED
            ),
            stack=stack,
            summary=result.summary,
            outputs={"plane": "dedicated", "program": str(self._program_dir)},
            detail=result.error or "preview complete",
        )

    async def apply(self, tenant: TenantContext) -> DeploymentResult:
        """Build or update the tenant's stack."""
        stack = stack_name(tenant.tenant_id)
        ready, problem = self._preflight()
        if not ready:
            return self._blocked(tenant, "apply", stack, problem)

        self._write_stack_config(tenant, stack)
        executor = self._executor_or_build()
        result = await executor.up(str(self._program_dir), stack=stack)
        if not result.success:
            return DeploymentResult(
                tenant_id=tenant.tenant_id,
                operation="apply",
                success=False,
                status=DeploymentStatus.FAILED,
                stack=stack,
                summary=result.summary,
                detail=result.error or "pulumi up failed",
            )

        # `up --json` does not always carry the stack's outputs, so they are
        # read back rather than assumed. A stack that came up but whose outputs
        # cannot be read is still a successful apply — the containers exist —
        # so this does not turn one into a failure.
        outputs = dict(result.outputs or {})
        try:
            state = await executor.stack_output(str(self._program_dir), stack=stack)
            outputs.update(state.outputs or {})
        except Exception as exc:  # noqa: BLE001 - the stack is up regardless
            logger.warning("could not read outputs for stack %s: %s", stack, exc)

        public, refs = await self._store_secrets(tenant, stack, outputs)
        return DeploymentResult(
            tenant_id=tenant.tenant_id,
            operation="apply",
            success=True,
            status=DeploymentStatus.READY,
            stack=stack,
            summary=result.summary,
            outputs=public,
            secret_refs=refs,
            detail="stack is up",
        )

    async def destroy(self, tenant: TenantContext) -> DeploymentResult:
        """Tear the tenant's stack down."""
        stack = stack_name(tenant.tenant_id)
        ready, problem = self._preflight()
        if not ready:
            return self._blocked(tenant, "destroy", stack, problem)

        result = await self._executor_or_build().destroy(
            str(self._program_dir), stack=stack
        )
        if result.success:
            await self._forget_secrets(tenant, stack)
        return DeploymentResult(
            tenant_id=tenant.tenant_id,
            operation="destroy",
            success=result.success,
            status=(
                DeploymentStatus.DESTROYED
                if result.success
                else DeploymentStatus.FAILED
            ),
            stack=stack,
            summary=result.summary,
            detail=result.error or "stack destroyed",
        )

    async def status(self, tenant: TenantContext) -> DeploymentResult:
        """Read what the stack currently reports."""
        stack = stack_name(tenant.tenant_id)
        ready, problem = self._preflight()
        if not ready:
            return self._blocked(tenant, "status", stack, problem)

        result = await self._executor_or_build().stack_output(
            str(self._program_dir), stack=stack
        )
        outputs = {
            key: value
            for key, value in (result.outputs or {}).items()
            if key not in SECRET_OUTPUTS
        }
        # An empty output set means the stack exists but has never been
        # applied — `stack output` on a fresh stack succeeds and returns {}.
        deployed = bool(outputs)
        return DeploymentResult(
            tenant_id=tenant.tenant_id,
            operation="status",
            success=result.success,
            status=(
                DeploymentStatus.READY
                if result.success and deployed
                else DeploymentStatus.PENDING
                if result.success
                else DeploymentStatus.FAILED
            ),
            stack=stack,
            outputs=outputs,
            detail=result.error or ("stack is up" if deployed else "stack is empty"),
        )

    # -- machinery ---------------------------------------------------------

    def _executor_or_build(self) -> Any:
        """Return the executor, building one on first use."""
        if self._executor is None:
            self._executor = build_executor(
                state_dir=self._state_dir,
                passphrase=self._passphrase,
                timeout=self._timeout,
            )
        return self._executor

    def _preflight(self) -> tuple[bool, str]:
        """Check that this deployer can run at all.

        Checked before every operation rather than at construction: a
        deployment wires the deployer at start-up and may install the CLI
        afterwards, and refusing to boot the whole API because ``pulumi`` is
        absent would be the wrong trade. The message names the missing thing,
        because "provisioning failed" with no reason is the most common way an
        operator loses an afternoon.

        Returns:
            ``(ok, problem)``.
        """
        if not self._program_dir.is_dir():
            return False, f"the Pulumi program directory {self._program_dir} is missing"
        if not (self._program_dir / "Pulumi.yaml").is_file():
            return False, f"{self._program_dir} contains no Pulumi.yaml"
        cli = conf.SAAS_PULUMI_CLI
        if shutil.which(cli) is None:
            return False, (
                f"the {cli!r} CLI is not on PATH; a dedicated tenant needs it "
                "installed on the host (the toolkit's Docker mode cannot drive "
                "the Docker provider — it never mounts the Docker socket)"
            )
        return True, ""

    def _blocked(
        self, tenant: TenantContext, operation: str, stack: str, problem: str
    ) -> DeploymentResult:
        """Report a precondition failure as a result rather than an exception."""
        logger.error(
            "cannot %s the stack for tenant %s: %s", operation, tenant.tenant_id, problem
        )
        return DeploymentResult(
            tenant_id=tenant.tenant_id,
            operation=operation,
            success=False,
            status=DeploymentStatus.FAILED,
            stack=stack,
            detail=problem,
        )

    def _write_stack_config(self, tenant: TenantContext, stack: str) -> Path:
        """Write ``Pulumi.<stack>.yaml`` beside the program.

        This exists because ``config_values`` is discarded by the executor
        (gap 1 above). Writing the file is not a workaround for a missing
        feature so much as using the mechanism the CLI actually reads.

        Written on every operation, so a tenant whose image or port changed in
        its settings gets the new value on the next apply rather than silently
        keeping the one from the first.

        Args:
            tenant: The tenant being provisioned.
            stack: The stack name.

        Returns:
            The path written.
        """
        settings = tenant.settings or {}
        values = {
            "tenantId": tenant.tenant_id,
            "image": str(settings.get("worker_image") or self._image),
            "hostPort": int(settings.get("host_port") or self._allocate_port(tenant)),
        }
        lines = ["config:"]
        for key, value in values.items():
            lines.append(f"  parrot-saas-tenant:{key}: {value}")
        path = self._program_dir / f"Pulumi.{stack}.yaml"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        logger.debug("wrote %s", path)
        return path

    async def _store_secrets(
        self, tenant: TenantContext, stack: str, outputs: dict
    ) -> tuple[dict, list[str]]:
        """Split the stack's outputs into public and secret.

        Args:
            tenant: The tenant.
            stack: The stack name.
            outputs: Everything the stack exported.

        Returns:
            ``(public_outputs, secret_refs)``. The public half carries a
            ``secret_refs`` entry naming where the rest went, so the control
            plane can point at a credential without holding one.
        """
        public = {k: v for k, v in outputs.items() if k not in SECRET_OUTPUTS}
        refs: list[str] = []
        for key in SECRET_OUTPUTS:
            value = outputs.get(key)
            if not value:
                continue
            ref = DSN_SECRET_TEMPLATE.format(stack=stack)
            if self._secret_store is None:
                logger.warning(
                    "no secret store configured; the %s for stack %s was not "
                    "stored (recover it with `pulumi stack output %s "
                    "--show-secrets`)",
                    key,
                    stack,
                    key,
                )
                continue
            try:
                await self._secret_store.put(tenant.tenant_id, ref, str(value))
            except Exception as exc:  # noqa: BLE001 - never log the value
                logger.error(
                    "could not store the %s for stack %s: %s", key, stack, exc
                )
                continue
            refs.append(ref)
        if refs:
            public["secret_refs"] = refs
        return public, refs

    async def _forget_secrets(self, tenant: TenantContext, stack: str) -> None:
        """Remove a destroyed stack's stored credentials.

        A DSN for a database that no longer exists is not dangerous so much as
        misleading: it is the kind of thing someone later finds and tries.
        """
        if self._secret_store is None:
            return
        ref = DSN_SECRET_TEMPLATE.format(stack=stack)
        try:
            await self._secret_store.delete(tenant.tenant_id, ref)
        except Exception as exc:  # noqa: BLE001 - the stack is already gone
            logger.warning("could not remove %s: %s", ref, exc)


def default_port(tenant: TenantContext) -> int:
    """Choose a stable host port for a tenant.

    Hashed rather than allocated from a counter so that re-provisioning a
    tenant reuses its port. A tenant whose port moved on every apply would
    break every URL and firewall rule pointing at it.

    Collisions across tenants are possible and are *not* silently resolved:
    Docker refuses to bind an occupied port, the apply fails with that
    message, and an operator sets ``settings["host_port"]`` explicitly. A
    deployment with many dedicated tenants wants a real allocator, which is
    what the ``port_allocator`` argument is for.

    Args:
        tenant: The tenant.

    Returns:
        A port inside the configured range.
    """
    import zlib

    span = max(1, conf.SAAS_TENANT_PORT_MAX - conf.SAAS_TENANT_PORT_MIN + 1)
    digest = zlib.crc32(tenant.tenant_id.encode("utf-8"))
    return conf.SAAS_TENANT_PORT_MIN + (digest % span)


def build_executor(
    *,
    state_dir: Path,
    passphrase: str,
    timeout: int,
) -> Any:
    """Build a ``PulumiExecutor`` configured for local, host-CLI operation.

    Args:
        state_dir: Directory backing the local state file.
        passphrase: Passphrase for the local secrets provider.
        timeout: Seconds allowed for one operation.

    Returns:
        The executor.
    """
    from parrot_tools.pulumi.config import PulumiConfig
    from parrot_tools.pulumi.executor import PulumiExecutor

    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)

    # `state_backend` is a dead field (gap 2), so the backend is set through
    # the environment, which `_build_process_env` picks up because it starts
    # from `os.environ.copy()`. Set on this process rather than passed per
    # call because the executor exposes no hook for extra env vars.
    os.environ.setdefault("PULUMI_BACKEND_URL", f"file://{state_dir}")

    return PulumiExecutor(
        PulumiConfig(
            # Not negotiable (gap 3): the toolkit's Docker mode never mounts
            # /var/run/docker.sock, so Pulumi in a container cannot reach the
            # daemon it is supposed to drive.
            use_docker=False,
            cli_path=conf.SAAS_PULUMI_CLI,
            config_passphrase=passphrase,
            auto_create_stack=True,
            timeout=timeout,
        )
    )


__all__ = (
    "DEFAULT_PROGRAM_DIR",
    "DSN_SECRET_TEMPLATE",
    "SECRET_OUTPUTS",
    "PulumiDeployer",
    "build_executor",
    "default_port",
    "stack_name",
)
