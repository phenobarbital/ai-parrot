"""Control-plane routes for provisioning a tenant.

These sit under ``/control/`` with the rest of the tenant lifecycle, which
means they are **exempt from tenant resolution** — they carry the tenant in
the path and are gated by a platform-staff policy instead. That exemption is
the reason every handler here reads the tenant from the repository by hand and
refuses an unknown one: without the middleware there is nothing else checking
that the slug in the URL is real.

Long operations return **202 with a job id**, never a result. A dedicated
stack takes minutes to build; holding an HTTP request open for it would time
out at whatever proxy sits in front, and the client would have no way to tell
a timeout from a failure. The state machine on ``saas.deployments`` is the
answer to "what happened" — ``GET`` the deployment.

The claim is a conditional write, not a check. Two ``pulumi up`` processes on
one stack corrupt its state file, and this is an HTTP API someone can call
twice in a second.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from aiohttp import web
from navconfig.logging import logging
from navigator.views import BaseView

from ..provisioning.models import DeploymentMode, DeploymentStatus
from ..tenancy.context import TenantContext
from .authz import check_policy
from .tenants import APP_TENANT_REPOSITORY, json_error

#: Key under which ``setup_saas_api`` publishes the deployment repository.
APP_DEPLOYMENT_REPOSITORY = "saas_deployments"

#: Key under which the deployers are published, keyed by tenancy mode.
APP_DEPLOYERS = "saas_deployers"

#: PBAC resource for the control plane, shared with the tenant lifecycle.
PBAC_RESOURCE_NAME = "control"

#: Which transient status each operation moves the deployment into.
_TRANSITIONS = {
    "plan": DeploymentStatus.PLANNING,
    "apply": DeploymentStatus.APPLYING,
    "destroy": DeploymentStatus.DESTROYING,
}

logger = logging.getLogger("parrot_saas.handlers.deployments")


class _DeploymentViewBase(BaseView):
    """Shared plumbing for the provisioning routes."""

    def _tenant_id(self) -> str:
        """Return the tenant slug from the path."""
        return self.request.match_info.get("tenant_id", "")

    def _deployments(self) -> Optional[Any]:
        """Return the deployment repository published on the app."""
        return self.request.app.get(APP_DEPLOYMENT_REPOSITORY)

    def _deployer(self, mode: str) -> Optional[Any]:
        """Return the deployer for a tenancy mode."""
        return (self.request.app.get(APP_DEPLOYERS) or {}).get(mode)

    async def _authorize(self, action: str) -> Optional[web.Response]:
        """Check the platform-staff policy for one action."""
        return await check_policy(
            self.request, action, PBAC_RESOURCE_NAME, subject=self._tenant_id()
        )

    async def _tenant(self) -> tuple[Optional[TenantContext], Optional[web.Response]]:
        """Resolve the tenant named in the path.

        The tenant middleware does not run on control-plane routes, so the
        lifecycle checks it would have made are made here. Provisioning a
        suspended tenant is refused for the same reason ingest refuses it:
        retiring a tenant has to actually stop work being done for them.
        """
        tenant_id = self._tenant_id()
        repository = self.request.app.get(APP_TENANT_REPOSITORY)
        if repository is None:  # pragma: no cover - misconfiguration
            return None, json_error(
                503, "not_configured", "the control plane is not configured"
            )
        record = await repository.get(tenant_id)
        if record is None:
            return None, json_error(
                404, "unknown_tenant", f"no tenant {tenant_id!r}"
            )
        if record.status == "suspended":
            return None, json_error(
                403, "tenant_suspended", f"tenant {tenant_id!r} is suspended"
            )
        return record.to_context(), None


class DeploymentView(_DeploymentViewBase):
    """Read or tear down a tenant's deployment."""

    _logger_name: str = "parrot_saas.DeploymentView"

    async def get(self) -> web.Response:
        """Return the recorded deployment, refreshed from the backend.

        The stored row is the state machine; the deployer is asked what is
        *actually* there. Reporting only the row would keep saying ``ready``
        for a stack someone removed by hand, which is exactly the moment an
        operator most needs the truth.
        """
        denied = await self._authorize("saas:tenant:read")
        if denied is not None:
            return denied
        tenant, error = await self._tenant()
        if error is not None:
            return error
        deployments = self._deployments()
        if deployments is None:  # pragma: no cover - misconfiguration
            return json_error(503, "not_configured", "no deployment repository")

        record = await deployments.get(tenant.tenant_id)
        payload = record.to_json() if record else {
            "tenant_id": tenant.tenant_id,
            "mode": tenant.mode,
            "status": DeploymentStatus.PENDING.value,
        }

        deployer = self._deployer(tenant.mode)
        if deployer is not None and not (record and record.busy):
            # Skipped while an operation is in flight: a status probe during a
            # ``pulumi up`` competes for the same state lock.
            try:
                live = await deployer.status(tenant)
                payload["live"] = live.to_json()
            except Exception as exc:  # noqa: BLE001 - the row is still useful
                logger.warning(
                    "could not read live status for %s: %s", tenant.tenant_id, exc
                )
                payload["live_error"] = str(exc)
        return web.json_response(payload)

    async def delete(self) -> web.Response:
        """Destroy the tenant's infrastructure. Returns 202."""
        return await _start(self, "destroy", "saas:tenant:provision")


class DeploymentPlanView(_DeploymentViewBase):
    """Preview what provisioning would change."""

    _logger_name: str = "parrot_saas.DeploymentPlanView"

    async def post(self) -> web.Response:
        """Start a plan. Returns 202."""
        return await _start(self, "plan", "saas:tenant:provision")


class DeploymentApplyView(_DeploymentViewBase):
    """Provision the tenant."""

    _logger_name: str = "parrot_saas.DeploymentApplyView"

    async def post(self) -> web.Response:
        """Start an apply. Returns 202."""
        return await _start(self, "apply", "saas:tenant:provision")


async def _start(
    view: _DeploymentViewBase, operation: str, action: str
) -> web.Response:
    """Claim the deployment and run one operation in the background.

    Args:
        view: The calling view.
        operation: ``plan`` | ``apply`` | ``destroy``.
        action: The policy action to check.

    Returns:
        202 with the job id, or an error. 409 when something is already in
        flight — which is the one status that must not be a 400: the request
        was perfectly valid, it just conflicts with the deployment's state.
    """
    denied = await view._authorize(action)  # noqa: SLF001 - same module
    if denied is not None:
        return denied
    tenant, error = await view._tenant()  # noqa: SLF001
    if error is not None:
        return error

    deployments = view._deployments()  # noqa: SLF001
    deployer = view._deployer(tenant.mode)  # noqa: SLF001
    if deployments is None or deployer is None:
        return json_error(
            503,
            "not_configured",
            f"no deployer is configured for mode {tenant.mode!r}",
            configured=sorted(view.request.app.get(APP_DEPLOYERS) or {}),
        )

    job_id = str(uuid.uuid4())
    claimed, busy = await deployments.claim(
        tenant.tenant_id,
        status=_TRANSITIONS[operation].value,
        job_id=job_id,
        mode=tenant.mode,
    )
    if claimed is None:
        return json_error(
            409,
            "deployment_busy",
            f"a {busy.status} operation is already in flight for "
            f"{tenant.tenant_id!r}",
            # Not ``status=``: that is ``json_error``'s own first parameter,
            # and passing it here is a TypeError inside the error path — the
            # one place a mistake turns a considered 409 into a bare 500.
            current_status=busy.status,
            job_id=busy.job_id,
        )

    await _dispatch(view.request.app, deployer, deployments, tenant, operation, job_id)
    return web.json_response(
        {
            "job_id": job_id,
            "operation": operation,
            "tenant_id": tenant.tenant_id,
            "status": claimed.status,
        },
        status=202,
    )


async def _dispatch(
    app: web.Application,
    deployer: Any,
    deployments: Any,
    tenant: TenantContext,
    operation: str,
    job_id: str,
) -> None:
    """Run the operation through the job manager, or inline without one."""

    async def _work() -> dict:
        return await run_operation(deployer, deployments, tenant, operation)

    jobs = app.get("job_manager")
    if jobs is None:
        # Inline is the honest fallback for a deployment without the jobs
        # subsystem: the request holds open, which for a shared tenant is
        # milliseconds. A dedicated stack really does want the job manager.
        await _work()
        return

    jobs.create_job(
        job_id=job_id,
        obj_id=f"deploy:{tenant.tenant_id}",
        query={"tenant_id": tenant.tenant_id, "operation": operation},
        session_id=tenant.tenant_id,
        execution_mode="provisioning",
    )
    await jobs.execute_job(job_id, _work)


async def run_operation(
    deployer: Any, deployments: Any, tenant: TenantContext, operation: str
) -> dict:
    """Execute one deployer operation and record its outcome.

    Never raises: this runs on a background worker, where an exception would
    be logged and lost — and would leave the deployment stuck in its transient
    status forever, refusing every later operation because the claim never
    cleared.

    Args:
        deployer: The deployer to drive.
        deployments: Repository to record the outcome in.
        tenant: The tenant being provisioned.
        operation: ``plan`` | ``apply`` | ``destroy``.

    Returns:
        The operation's result as JSON.
    """
    try:
        result = await getattr(deployer, operation)(tenant)
    except Exception as exc:  # noqa: BLE001 - recorded, never propagated
        logger.exception(
            "%s failed for tenant %s", operation, tenant.tenant_id
        )
        await deployments.record(
            tenant.tenant_id,
            status=DeploymentStatus.FAILED.value,
            last_error=f"{type(exc).__name__}: {exc}",
        )
        return {"operation": operation, "success": False, "error": str(exc)}

    # A plan changes nothing, so it must not leave the deployment claiming to
    # be ready. It reverts to whatever it was before, which for a fresh tenant
    # is 'pending'.
    status = result.status
    if operation == "plan":
        status = (
            DeploymentStatus.FAILED.value
            if not result.success
            else DeploymentStatus.PENDING.value
        )

    await deployments.record(
        tenant.tenant_id,
        status=getattr(status, "value", status),
        outputs=result.outputs if result.success else None,
        last_error="" if result.success else result.detail,
        stack=result.stack,
    )
    logger.info(
        "%s for tenant %s finished: %s",
        operation,
        tenant.tenant_id,
        "ok" if result.success else result.detail,
    )
    return result.to_json()


def default_deployers(**deployers: Any) -> dict:
    """Build the mode → deployer mapping.

    Args:
        **deployers: ``shared=...`` and/or ``dedicated=...``.

    Returns:
        The mapping, with absent modes omitted rather than mapped to ``None``
        — the handler's "no deployer for this mode" branch then reports which
        modes *are* configured, which is what makes a wiring mistake
        diagnosable from the response.
    """
    return {
        mode: deployer
        for mode, deployer in deployers.items()
        if deployer is not None and mode in (m.value for m in DeploymentMode)
    }


def setup_deployment_routes(
    app: web.Application, *, base: str = "/api/v1/saas/control/tenants"
) -> None:
    """Register the provisioning routes.

    The two action routes go in before ``{tenant_id}/deployment`` for the
    usual reason — aiohttp resolves resources in registration order — though
    here the paths do not actually collide.

    Args:
        app: The aiohttp application.
        base: Base path for the tenant collection.
    """
    _app = app.get_app() if hasattr(app, "get_app") else app
    _app.router.add_view(f"{base}/{{tenant_id}}/plan", DeploymentPlanView)
    _app.router.add_view(f"{base}/{{tenant_id}}/deploy", DeploymentApplyView)
    _app.router.add_view(f"{base}/{{tenant_id}}/deployment", DeploymentView)


__all__ = (
    "APP_DEPLOYERS",
    "APP_DEPLOYMENT_REPOSITORY",
    "DeploymentApplyView",
    "DeploymentPlanView",
    "DeploymentView",
    "default_deployers",
    "run_operation",
    "setup_deployment_routes",
)
