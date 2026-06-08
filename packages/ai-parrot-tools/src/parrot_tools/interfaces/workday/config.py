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

from pydantic import BaseModel, computed_field

from parrot.conf import (
    WORKDAY_CLIENT_ID,
    WORKDAY_CLIENT_SECRET,
    WORKDAY_REFRESH_TOKEN,
    WORKDAY_REPORT_PASSWORD,
    WORKDAY_REPORT_USERNAME,
    WORKDAY_TOKEN_URL,
    WORKDAY_WSDL_ABSENCE_MANAGEMENT,
    WORKDAY_WSDL_CUSTOM_PUNCH_FIELD_REPORT,
    WORKDAY_WSDL_FINANCIAL_MANAGEMENT,
    WORKDAY_WSDL_HUMAN_RESOURCES,
    WORKDAY_WSDL_INTEGRATIONS,
    WORKDAY_WSDL_PATH,
    WORKDAY_WSDL_RECRUITING,
    WORKDAY_WSDL_TIME,
    WORKDAY_WSDL_TIME_BLOCK_REPORT,
)

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
    tenant: str = "nav"
    report_owner: str = "owner@example.com"
    workday_url: str = "https://services1.wd501.myworkday.com"
    timeout: int = 300

    # ------------------------------------------------------------------
    # Resolved computed properties — explicit value wins, conf fallback
    # ------------------------------------------------------------------

    @computed_field  # type: ignore[misc]
    @property
    def resolved_client_id(self) -> str | None:
        """Return the explicit ``client_id`` or fall back to ``WORKDAY_CLIENT_ID``."""
        return self.client_id if self.client_id is not None else WORKDAY_CLIENT_ID

    @computed_field  # type: ignore[misc]
    @property
    def resolved_client_secret(self) -> str | None:
        """Return the explicit ``client_secret`` or fall back to ``WORKDAY_CLIENT_SECRET``."""
        return self.client_secret if self.client_secret is not None else WORKDAY_CLIENT_SECRET

    @computed_field  # type: ignore[misc]
    @property
    def resolved_token_url(self) -> str | None:
        """Return the explicit ``token_url`` or fall back to ``WORKDAY_TOKEN_URL``."""
        return self.token_url if self.token_url is not None else WORKDAY_TOKEN_URL

    @computed_field  # type: ignore[misc]
    @property
    def resolved_refresh_token(self) -> str | None:
        """Return the explicit ``refresh_token`` or fall back to ``WORKDAY_REFRESH_TOKEN``."""
        return self.refresh_token if self.refresh_token is not None else WORKDAY_REFRESH_TOKEN

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
