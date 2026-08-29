"""What a deployment is, and what an operation on one returned."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field


class DeploymentMode(str, Enum):
    """How a tenant is served.

    Mirrors ``TenantMode``: the deployment records what was actually built,
    which can lag the tenant's requested mode while provisioning is in flight.
    """

    SHARED = "shared"
    DEDICATED = "dedicated"


class DeploymentStatus(str, Enum):
    """Where a tenant's infrastructure is.

    The transient states exist because provisioning a dedicated stack takes
    minutes, not milliseconds: a control plane that could only say "ready" or
    "failed" would show "failed" for the whole time a stack was coming up.

    ``DESTROYED`` is terminal but not a deletion. The row stays so a tenant
    that is torn down and rebuilt has one history rather than two, and so an
    operator can see that a stack once existed.
    """

    PENDING = "pending"
    PLANNING = "planning"
    APPLYING = "applying"
    READY = "ready"
    FAILED = "failed"
    DESTROYING = "destroying"
    DESTROYED = "destroyed"


#: States from which a new operation may start. Refusing to start one while
#: another is in flight is what keeps two ``pulumi up`` processes off the same
#: stack, which is a corrupted state file rather than a queued second run.
IDLE_STATUSES = frozenset(
    {
        DeploymentStatus.PENDING.value,
        DeploymentStatus.READY.value,
        DeploymentStatus.FAILED.value,
        DeploymentStatus.DESTROYED.value,
    }
)


class Deployment(BaseModel):
    """The infrastructure serving one tenant.

    Attributes:
        tenant_id: Owning tenant, and the primary key — a tenant has exactly
            one deployment.
        mode: What was actually built.
        status: Where it is.
        stack: Pulumi stack name, empty for a shared tenant.
        outputs: Non-secret stack outputs. **Never a connection string**: the
            DSN goes to the secret store and this keeps the reference.
        last_error: Why the last operation failed, empty otherwise.
        job_id: The background job currently working on it, if any.
        created_at: Row creation time.
        updated_at: Last transition.
    """

    model_config = ConfigDict(use_enum_values=True, validate_default=True)

    tenant_id: str = ""
    mode: DeploymentMode = DeploymentMode.SHARED
    status: DeploymentStatus = DeploymentStatus.PENDING
    stack: str = ""
    outputs: dict[str, Any] = Field(default_factory=dict)
    last_error: str = ""
    job_id: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Deployment":
        """Build a deployment from a database row."""
        import json

        data = dict(row)
        outputs = data.get("outputs")
        if isinstance(outputs, str):
            try:
                outputs = json.loads(outputs)
            except ValueError:
                outputs = {}
        data["outputs"] = outputs or {}
        return cls(**data)

    def to_json(self) -> dict[str, Any]:
        """Render for the wire."""
        return {
            "tenant_id": self.tenant_id,
            "mode": self.mode,
            "status": self.status,
            "stack": self.stack,
            "outputs": self.outputs,
            "last_error": self.last_error,
            "job_id": self.job_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @property
    def busy(self) -> bool:
        """Whether an operation is currently in flight."""
        return self.status not in IDLE_STATUSES


class DeploymentResult(BaseModel):
    """What one deployer operation produced.

    Deliberately not an exception-based interface. Provisioning fails for
    ordinary reasons — a port already bound, a stale state lock, a daemon that
    is not running — and every one of those has to reach the control plane as
    a status and a message rather than as a traceback in a worker log.

    Attributes:
        tenant_id: The tenant operated on.
        operation: ``plan`` | ``apply`` | ``destroy`` | ``status``.
        success: Whether it did what was asked.
        status: The deployment's status afterwards.
        outputs: Non-secret outputs.
        summary: Resource counts, when the backend reports them.
        detail: Human-readable explanation, success or failure.
        stack: Stack operated on, empty for shared.
        secret_refs: Names under which secret outputs were stored, so a
            caller can find them without ever seeing a value.
    """

    model_config = ConfigDict(use_enum_values=True, validate_default=True)

    tenant_id: str = ""
    operation: str = ""
    success: bool = False
    status: DeploymentStatus = DeploymentStatus.PENDING
    outputs: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, int] = Field(default_factory=dict)
    detail: str = ""
    stack: str = ""
    secret_refs: list[str] = Field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        """Render for the wire."""
        return {
            "tenant_id": self.tenant_id,
            "operation": self.operation,
            "success": self.success,
            "status": self.status,
            "outputs": self.outputs,
            "summary": self.summary,
            "detail": self.detail,
            "stack": self.stack,
            "secret_refs": self.secret_refs,
        }


__all__ = (
    "IDLE_STATUSES",
    "Deployment",
    "DeploymentMode",
    "DeploymentResult",
    "DeploymentStatus",
)
