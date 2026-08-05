"""WorkdayConfig — credential + tenant configuration for WorkdayService.

Each optional credential field falls back to the matching ``WORKDAY_*``
setting from ``parrot.conf`` when left ``None`` (G3/C6).

WSDL routing helper
-------------------
``get_wsdl_path(operation_type)`` maps a Workday operation key to the
correct WSDL file path.  The mapping is lifted verbatim from the two
``wsdl_mapping`` blocks in ``workday.py`` (original source)
(lines 339-360 and 500-517) and unified into a single canonical dict.

Known discrepancy between the two original blocks
--------------------------------------------------
``get_organization``:
  - ``__init__``     (line 345): ``WORKDAY_WSDL_HUMAN_RESOURCES``   ← used here
  - helper method   (line 506): ``WORKDAY_WSDL_PATH``               ← superseded
The ``__init__`` block is the authoritative runtime path (executed on
every component instantiation), so this module uses
``WORKDAY_WSDL_HUMAN_RESOURCES`` for ``get_organization``.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from parrot.conf import (
    WORKDAY_CLIENT_ID,
    WORKDAY_CLIENT_ID_IMPL,
    WORKDAY_CLIENT_SECRET,
    WORKDAY_CLIENT_SECRET_IMPL,
    WORKDAY_DEFAULT_TENANT,
    WORKDAY_ENV,
    WORKDAY_REFRESH_TOKEN,
    WORKDAY_REFRESH_TOKEN_IMPL,
    WORKDAY_REPORT_OWNER,
    WORKDAY_REPORT_PASSWORD,
    WORKDAY_REPORT_USERNAME,
    WORKDAY_TOKEN_URL,
    WORKDAY_TOKEN_URL_IMPL,
    WORKDAY_URL,
    WORKDAY_WSDL_ABSENCE_MANAGEMENT,
    WORKDAY_WSDL_CUSTOM_PUNCH_FIELD_REPORT,
    WORKDAY_WSDL_FINANCIAL_MANAGEMENT,
    WORKDAY_WSDL_HUMAN_RESOURCES,
    WORKDAY_WSDL_INTEGRATIONS,
    WORKDAY_WSDL_PATH,
    WORKDAY_WSDL_PAYROLL,
    WORKDAY_WSDL_RECRUITING,
    WORKDAY_WSDL_TIME,
    WORKDAY_WSDL_TIME_BLOCK_REPORT,
)
from pydantic import BaseModel, computed_field, model_validator

#: ``WORKDAY_ENV`` values that select the sandbox/implementation credential set.
_SANDBOX_ENVS = {"sandbox", "impl", "implementation"}

# ---------------------------------------------------------------------------
# WSDL routing
# ---------------------------------------------------------------------------

#: Canonical operation-type → WSDL path mapping.
#: Lifted from workday.py:339-360 (authoritative ``__init__`` block).
#: ``WORKDAY_WSDL_PATH`` (staffing) is the default for unknown types.
_WSDL_ROUTING: dict[str, Any] = {
    "get_time_blocks": WORKDAY_WSDL_TIME,
    "get_workers": WORKDAY_WSDL_PATH,
    "get_locations": WORKDAY_WSDL_HUMAN_RESOURCES,
    "get_time_requests": WORKDAY_WSDL_TIME,
    "get_organizations": WORKDAY_WSDL_PATH,
    "get_organization": WORKDAY_WSDL_HUMAN_RESOURCES,  # see module docstring
    "get_location_hierarchy_assignments": WORKDAY_WSDL_HUMAN_RESOURCES,
    "get_cost_centers": WORKDAY_WSDL_FINANCIAL_MANAGEMENT,
    "get_applicants": WORKDAY_WSDL_RECRUITING,
    "get_candidates": WORKDAY_WSDL_RECRUITING,
    "get_job_requisitions": WORKDAY_WSDL_RECRUITING,
    "get_job_postings": WORKDAY_WSDL_RECRUITING,
    "get_job_posting_sites": WORKDAY_WSDL_RECRUITING,
    "get_recruiting_agency_users": WORKDAY_WSDL_RECRUITING,
    "get_time_off_balances": WORKDAY_WSDL_ABSENCE_MANAGEMENT,
    "extract_time_blocks_report": WORKDAY_WSDL_TIME_BLOCK_REPORT,
    "custom_punch_field_report": WORKDAY_WSDL_CUSTOM_PUNCH_FIELD_REPORT,
    "get_references": WORKDAY_WSDL_INTEGRATIONS,
    # FEAT-027: write operations — Time Tracking WSDL
    "put_time_clock_events": WORKDAY_WSDL_TIME,
    "import_time_clock_events": WORKDAY_WSDL_TIME,
    "import_reported_time_blocks": WORKDAY_WSDL_TIME,
    # FEAT-230: Absence Management write + eligibility ops
    "request_time_off": WORKDAY_WSDL_ABSENCE_MANAGEMENT,
    "get_time_off_eligibility": WORKDAY_WSDL_ABSENCE_MANAGEMENT,
    # FEAT-232: Payroll read ops
    "get_payroll_balances": WORKDAY_WSDL_PAYROLL,
    "get_payroll_results": WORKDAY_WSDL_PAYROLL,
    "get_company_payment_dates": WORKDAY_WSDL_PAYROLL,
}


def get_wsdl_path(operation_type: str) -> Any:
    """Return the WSDL path for a given Workday operation type.

    Falls back to ``WORKDAY_WSDL_PATH`` (staffing WSDL) for unknown types,
    matching the behaviour of ``workday.py:360`` and ``workday.py:517``.

    Args:
        operation_type: The Workday operation key (e.g. ``"get_workers"``).

    Returns:
        The resolved WSDL path (``str`` or ``pathlib.Path`` depending on
        whether the value was loaded from the config file or the fallback).
    """
    return _WSDL_ROUTING.get(operation_type, WORKDAY_WSDL_PATH)


# ---------------------------------------------------------------------------
# WorkdayConfig
# ---------------------------------------------------------------------------


class WorkdayConfig(BaseModel):
    """Explicit Workday credentials / tenant; each optional field falls back
    to the matching ``WORKDAY_*`` in ``parrot.conf`` when left ``None``.

    Usage::

        # All-defaults — picks up credentials from the environment / conf.
        cfg = WorkdayConfig()

        # Explicit override — useful for multi-tenant scenarios or tests.
        cfg = WorkdayConfig(client_id="my-id", client_secret="my-secret")

    Resolved values are exposed via the ``resolved_*`` computed properties so
    that callers always get a definite value regardless of whether an explicit
    override was provided.
    """

    client_id: str | None = None
    client_secret: str | None = None
    token_url: str | None = None
    refresh_token: str | None = None
    report_username: str | None = None
    report_password: str | None = None
    tenant: str | None = None
    report_owner: str | None = None
    workday_url: str | None = None
    timeout: int = 300
    #: Target environment. ``None`` falls back to ``WORKDAY_ENV`` (default
    #: ``"prod"``). Set to ``"sandbox"`` / ``"impl"`` / ``"implementation"``
    #: to resolve credentials from the ``WORKDAY_*_IMPL`` settings and point
    #: the SOAP endpoint at the implementation host.
    env: str | None = None

    # ------------------------------------------------------------------
    # Environment selector — plain properties, not serialized fields
    # ------------------------------------------------------------------

    @property
    def resolved_env(self) -> str:
        """The effective environment (explicit ``env`` or ``WORKDAY_ENV``)."""
        return (self.env or WORKDAY_ENV or "prod").strip().lower()

    @property
    def resolved_is_sandbox(self) -> bool:
        """``True`` when targeting the sandbox/implementation tenant."""
        return self.resolved_env in _SANDBOX_ENVS

    # ------------------------------------------------------------------
    # Resolved computed properties — explicit value wins, conf fallback.
    # The conf fallback is environment-aware: ``resolved_is_sandbox`` swaps
    # the ``WORKDAY_*`` defaults for their ``WORKDAY_*_IMPL`` counterparts,
    # failing loudly rather than silently falling back to production.
    # ------------------------------------------------------------------

    @computed_field  # type: ignore[misc]
    @property
    def resolved_client_id(self) -> str | None:
        """Explicit ``client_id`` or the env-appropriate ``WORKDAY_CLIENT_ID[_IMPL]``.

        Raises:
            ValueError: sandbox is selected but ``WORKDAY_CLIENT_ID_IMPL`` is unset.
        """
        if self.client_id is not None:
            return self.client_id
        if self.resolved_is_sandbox:
            if not WORKDAY_CLIENT_ID_IMPL:
                raise ValueError(
                    "WorkdayConfig: env='sandbox' selected but WORKDAY_CLIENT_ID_IMPL "
                    "is not set. Refusing to fall back to the production credential."
                )
            return WORKDAY_CLIENT_ID_IMPL
        return WORKDAY_CLIENT_ID

    @computed_field  # type: ignore[misc]
    @property
    def resolved_client_secret(self) -> str | None:
        """Explicit ``client_secret`` or the env-appropriate ``WORKDAY_CLIENT_SECRET[_IMPL]``.

        Raises:
            ValueError: sandbox is selected but ``WORKDAY_CLIENT_SECRET_IMPL`` is unset.
        """
        if self.client_secret is not None:
            return self.client_secret
        if self.resolved_is_sandbox:
            if not WORKDAY_CLIENT_SECRET_IMPL:
                raise ValueError(
                    "WorkdayConfig: env='sandbox' selected but WORKDAY_CLIENT_SECRET_IMPL "
                    "is not set. Refusing to fall back to the production credential."
                )
            return WORKDAY_CLIENT_SECRET_IMPL
        return WORKDAY_CLIENT_SECRET

    @computed_field  # type: ignore[misc]
    @property
    def resolved_token_url(self) -> str | None:
        """Explicit ``token_url`` or the env-appropriate ``WORKDAY_TOKEN_URL[_IMPL]``.

        Raises:
            ValueError: sandbox is selected but ``WORKDAY_TOKEN_URL_IMPL`` is unset.
        """
        if self.token_url is not None:
            return self.token_url
        if self.resolved_is_sandbox:
            if not WORKDAY_TOKEN_URL_IMPL:
                raise ValueError(
                    "WorkdayConfig: env='sandbox' selected but WORKDAY_TOKEN_URL_IMPL "
                    "is not set. Refusing to fall back to the production credential."
                )
            return WORKDAY_TOKEN_URL_IMPL
        return WORKDAY_TOKEN_URL

    @computed_field  # type: ignore[misc]
    @property
    def resolved_refresh_token(self) -> str | None:
        """Explicit ``refresh_token`` or the env-appropriate ``WORKDAY_REFRESH_TOKEN[_IMPL]``.

        Raises:
            ValueError: sandbox is selected but ``WORKDAY_REFRESH_TOKEN_IMPL`` is unset.
        """
        if self.refresh_token is not None:
            return self.refresh_token
        if self.resolved_is_sandbox:
            if not WORKDAY_REFRESH_TOKEN_IMPL:
                raise ValueError(
                    "WorkdayConfig: env='sandbox' selected but WORKDAY_REFRESH_TOKEN_IMPL "
                    "is not set. Refusing to fall back to the production credential."
                )
            return WORKDAY_REFRESH_TOKEN_IMPL
        return WORKDAY_REFRESH_TOKEN

    @model_validator(mode="after")
    def _align_workday_url_to_env(self) -> WorkdayConfig:
        """Point ``workday_url`` at the sandbox host when targeting sandbox.

        The SOAP host (where ``WorkdayService.bind_service`` sends the call)
        must match the tenant we authenticate against. ai-parrot's
        ``workday_url`` defaults to ``None`` (vendor-neutral); when left
        unset and the resolved environment is sandbox, derive the host from
        the resolved (impl) ``token_url`` so sandbox-intended writes never
        reach production. An explicit ``workday_url`` is always respected.
        """
        if self.resolved_is_sandbox and self.workday_url is None:
            turl = self.resolved_token_url
            if turl:
                parts = urlparse(turl)
                if parts.scheme and parts.netloc:
                    self.workday_url = f"{parts.scheme}://{parts.netloc}"
        return self

    @computed_field  # type: ignore[misc]
    @property
    def resolved_report_username(self) -> str | None:
        """Return the explicit ``report_username`` or fall back to ``WORKDAY_REPORT_USERNAME``."""
        return self.report_username if self.report_username is not None else WORKDAY_REPORT_USERNAME

    @computed_field  # type: ignore[misc]
    @property
    def resolved_report_password(self) -> str | None:
        """Return the explicit ``report_password`` or fall back to ``WORKDAY_REPORT_PASSWORD``."""
        return self.report_password if self.report_password is not None else WORKDAY_REPORT_PASSWORD

    @computed_field  # type: ignore[misc]
    @property
    def resolved_tenant(self) -> str | None:
        """Return the explicit ``tenant`` or fall back to ``WORKDAY_DEFAULT_TENANT``."""
        return self.tenant if self.tenant is not None else WORKDAY_DEFAULT_TENANT

    @computed_field  # type: ignore[misc]
    @property
    def resolved_report_owner(self) -> str | None:
        """Return the explicit ``report_owner`` or fall back to ``WORKDAY_REPORT_OWNER``."""
        return self.report_owner if self.report_owner is not None else WORKDAY_REPORT_OWNER

    @computed_field  # type: ignore[misc]
    @property
    def resolved_workday_url(self) -> str | None:
        """Return the explicit ``workday_url`` or fall back to ``WORKDAY_URL``."""
        return self.workday_url if self.workday_url is not None else WORKDAY_URL
