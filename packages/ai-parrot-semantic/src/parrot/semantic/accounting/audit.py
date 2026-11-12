"""Accounting audit entries on the shared SemanticAuditLedger (FEAT-713 M7)."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal, Mapping

from pydantic import BaseModel, TypeAdapter

from parrot.semantic.audit import SemanticAuditLedger
from parrot.semantic.errors import SemanticExecutionError

from .compiler import canonical_request, compile_assertion, compile_metric
from .errors import AccountingAuditError, AccountingError
from .models import AccountingModel, AccountingRequest, AssertionRequest, CompiledMetricQuery, Lineage

if TYPE_CHECKING:
    from parrot.auth.permission import PermissionContext

AuditMode = Literal["required", "best_effort"]
_REQUEST = TypeAdapter(AccountingRequest)


class AccountingAuditEntry(BaseModel):
    """Signed by the shared ledger; satisfies SignableAuditEntry."""

    schema_version: Literal[1] = 1
    entry_id: str
    created_at: datetime
    user_id: str
    tenant_id: str
    subject_digest: str
    model: str
    version: str
    model_hash: str
    snapshot_hash: str
    sql_hash: str
    plan_hash: str
    dialect: str
    target: Literal["database", "duckdb"]
    tool: str
    request_canonical: str
    lineage_ref: str
    assertion_status: Literal["passed", "failed", "skipped", "none"]
    outcome: Literal["ok", "execution_error"]
    row_count: int | None
    duration_ms: int | None
    signature: str = ""

    def canonical_bytes(self) -> bytes:
        """Sorted-key compact JSON without ``signature``."""
        data = self.model_dump(mode="json", exclude={"signature"})
        return json.dumps(data, sort_keys=True, separators=(",", ":")).encode()


def audit_mode_from_env(env: Mapping[str, str] | None = None) -> AuditMode:
    """FINANCE_AUDIT_MODE, default 'required'; unknown values raise ValueError."""
    source = os.environ if env is None else env
    value = source.get("FINANCE_AUDIT_MODE", "required").strip().lower() or "required"
    if value not in ("required", "best_effort"):
        raise ValueError(f"FINANCE_AUDIT_MODE must be 'required' or 'best_effort', got {value!r}")
    return value  # type: ignore[return-value]


def subject_digest(context: "PermissionContext | None") -> str:
    """sha256 of (user_id, tenant_id), or of 'anonymous' when there is no context."""
    if context is None:
        raw = "anonymous"
    else:
        raw = f"{context.user_id}\x1f{context.tenant_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_entry(
    *,
    context: "PermissionContext | None",
    tenant: str,
    model: AccountingModel,
    compiled: CompiledMetricQuery,
    target: Literal["database", "duckdb"],
    tool: str,
    outcome: str,
    assertion_status: str,
    row_count: int | None,
    duration_ms: int | None,
) -> AccountingAuditEntry:
    """Assemble an unsigned entry; lineage_ref = model_hash:plan_hash:sql_hash."""
    return AccountingAuditEntry(
        entry_id=str(uuid.uuid4()),
        created_at=datetime.now(timezone.utc),
        user_id="anonymous" if context is None else str(context.user_id),
        tenant_id=tenant,  # the QUERIED tenant; the caller is identified by user_id and subject_digest
        subject_digest=subject_digest(context),
        model=model.spec.model,
        version=model.spec.version,
        model_hash=compiled.model_hash,
        snapshot_hash=model.snapshot_hash,
        sql_hash=compiled.sql_hash,
        plan_hash=compiled.plan_hash,
        dialect=compiled.dialect,
        target=target,
        tool=tool,
        request_canonical=canonical_request(compiled.request),
        lineage_ref=f"{compiled.model_hash}:{compiled.plan_hash}:{compiled.sql_hash}",
        assertion_status=assertion_status,  # type: ignore[arg-type]
        outcome=outcome,  # type: ignore[arg-type]
        row_count=row_count,
        duration_ms=duration_ms,
    )


async def append_entry(
    ledger: SemanticAuditLedger, entry: AccountingAuditEntry, *, mode: AuditMode
) -> AccountingAuditEntry:
    """ledger.append(entry, required=(mode == 'required')); AccountingAuditError when the sink is missing or fails."""
    try:
        return await ledger.append(entry, required=(mode == "required"))
    except SemanticExecutionError as exc:
        raise AccountingAuditError(str(exc)) from exc


def rebuild_lineage(entry: AccountingAuditEntry, model: AccountingModel) -> Lineage:
    """Recompile from request_canonical; verify model, plan and SQL hashes and lineage_ref before returning.

    Raises:
        AccountingError: on any mismatch or when the request cannot be replayed.
    """
    request = _REQUEST.validate_python(json.loads(entry.request_canonical))
    try:
        if isinstance(request, AssertionRequest):
            compiled = compile_assertion(model, request, entry.dialect)
        else:
            compiled = compile_metric(model, request, entry.dialect)
    except AccountingError:
        raise
    except Exception as exc:  # noqa: BLE001 - replay failures surface as accounting errors
        raise AccountingError(f"audit replay could not recompile the request: {exc}") from exc
    expected = {
        "model_hash": compiled.model_hash,
        "plan_hash": compiled.plan_hash,
        "sql_hash": compiled.sql_hash,
        "lineage_ref": f"{compiled.model_hash}:{compiled.plan_hash}:{compiled.sql_hash}",
    }
    for field, value in expected.items():
        if getattr(entry, field) != value:
            raise AccountingError(f"audit replay mismatch on {field}")
    return compiled.lineage
