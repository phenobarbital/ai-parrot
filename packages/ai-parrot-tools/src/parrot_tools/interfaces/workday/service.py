"""WorkdayService — self-contained Workday operational interface.

Usable without any ``FlowComponent`` (G2). Implements the operational core:
OAuth/Basic-auth lifecycle (via SOAPClient), WSDL routing, eager handler
registry, and the four public data methods.

Public API
----------
- ``fetch(operation_type, **params) -> pd.DataFrame``   — dispatch to handler
- ``fetch_models(operation_type, **params) -> list``    — typed Pydantic (C7)
- ``get_custom_report(report_name, ...) -> pd.DataFrame`` — RaaS custom report
- ``call_operation(operation, **kwargs)``               — raw SOAP (for handlers)
- ``start() / close()``                                 — lifecycle (from SOAPClient)

Auth branching
--------------
Reproduces ``workday.py:362-445`` exactly:
- REST custom report (``custom_report``, ``custom_punch_field_report_rest``,
  ``extract_*``) → Basic Auth (report_username / report_password).
- SOAP custom report (anything ending in ``_report`` that is not a REST
  custom report) → OAuth + Proxy_User_Name in SOAP body.
- Everything else → OAuth only.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
from zeep.helpers import serialize_object as zeep_serialize

from parrot.interfaces.soap import SOAPClient
from parrot_tools.interfaces.workday.config import WorkdayConfig, get_wsdl_path

# ---------------------------------------------------------------------------
# Handler imports (moved to interfaces/workday/handlers/ in TASK-104)
# ---------------------------------------------------------------------------
from parrot_tools.interfaces.workday.handlers import (
    ApplicantType,
    CandidateType,
    CostCenterType,
    CustomPunchFieldReportType,
    CustomPunchFieldReportRestType,
    CustomReportType,
    ImportReportedTimeBlocksType,
    ImportTimeClockEventsType,
    JobPostingSiteType,
    JobPostingType,
    JobRequisitionType,
    LocationType,
    OrganizationType,
    PutTimeClockEventsType,
    RecruitingAgencyUsersType,
    ReferencesType,
    RequestTimeOffType,
    TimeBlockReportType,
    TimeBlockType,
    TimeOffBalanceType,
    TimeOffEligibilityType,
    TimeRequestType,
    WorkerType,
)
from parrot_tools.interfaces.workday.handlers.location_hierarchy_assignments import (
    LocationHierarchyAssignmentsType,
)
from parrot_tools.interfaces.workday.handlers.organization_single import GetOrganization

# Model classes used by fetch_models() (operation_type → model class mapping).
from parrot_tools.interfaces.workday.models.clock_event import (
    ClockEvent,
    ReportedTimeBlock,
)
from parrot_tools.interfaces.workday.models.applicant import Applicant
from parrot_tools.interfaces.workday.models.candidate import Candidate
from parrot_tools.interfaces.workday.models.cost_center import CostCenter
from parrot_tools.interfaces.workday.models.job_posting import JobPosting
from parrot_tools.interfaces.workday.models.job_posting_site import JobPostingSite
from parrot_tools.interfaces.workday.models.job_requisition import JobRequisition
from parrot_tools.interfaces.workday.models.location import Location
from parrot_tools.interfaces.workday.models.organizations import Organization
from parrot_tools.interfaces.workday.models.reference import WorkdayReference
from parrot_tools.interfaces.workday.models.time_block import TimeBlock
from parrot_tools.interfaces.workday.models.time_off_balance import TimeOffBalance
from parrot_tools.interfaces.workday.models.time_off_eligibility import TimeOffEligibility
from parrot_tools.interfaces.workday.models.time_request import TimeRequest
from parrot_tools.interfaces.workday.models.worker import Worker

# ---------------------------------------------------------------------------
# Operation-type → Pydantic model class (for fetch_models typed path, C7)
# ---------------------------------------------------------------------------

_OPERATION_MODEL_MAP: dict[str, type] = {
    "get_workers": Worker,
    "get_time_blocks": TimeBlock,
    "get_locations": Location,
    "get_time_requests": TimeRequest,
    "get_organizations": Organization,
    "get_organization": Organization,
    "get_cost_centers": CostCenter,
    "get_applicants": Applicant,
    "get_candidates": Candidate,
    "get_job_requisitions": JobRequisition,
    "get_job_postings": JobPosting,
    "get_job_posting_sites": JobPostingSite,
    "get_time_off_balances": TimeOffBalance,
    "get_time_off_eligibility": TimeOffEligibility,
    "get_references": WorkdayReference,
}

# REST custom report types that require Basic Auth (workday.py:364)
_REST_REPORT_TYPES: tuple[str, ...] = ("custom_report", "custom_punch_field_report_rest")


class WorkdayService(SOAPClient):
    """Workday operational interface — composable without a FlowComponent.

    Args:
        config: Explicit credentials / tenant.  ``None`` → falls back to the
            ``WORKDAY_*`` settings in ``parrot.conf`` (G3).
        operation_type: Determines the WSDL to load.  Defaults to
            ``"get_workers"`` (staffing WSDL).
        **kwargs: Forwarded to ``SOAPClient.__init__`` (e.g. ``redis_url``).

    Example::

        async with WorkdayService(config=WorkdayConfig()) as svc:
            df = await svc.fetch("get_workers")
    """

    def __init__(
        self,
        *,
        config: WorkdayConfig | None = None,
        operation_type: str = "get_workers",
        **kwargs: Any,
    ) -> None:
        """Build credentials dict from WorkdayConfig and initialise SOAPClient.

        Reproduces the auth-branching logic of workday.py:362-445 verbatim.
        """
        config = config or WorkdayConfig()

        self._operation_type: str = operation_type

        # 1. WSDL routing (lifted from workday.py:339-360 via TASK-101)
        wsdl_path = get_wsdl_path(operation_type)

        # 2. Auth branching — identical to workday.py:362-368
        is_rest_custom_report: bool = (
            operation_type in _REST_REPORT_TYPES
            or operation_type.startswith("extract_")
        )
        is_soap_custom_report: bool = (
            operation_type.endswith("_report") and not is_rest_custom_report
        )

        # 3. Build creds dict — workday.py:371-377
        creds: dict[str, Any] = {
            "client_id": config.resolved_client_id,
            "client_secret": config.resolved_client_secret,
            "token_url": config.resolved_token_url,
            "wsdl_path": str(wsdl_path),
            "refresh_token": config.resolved_refresh_token,
        }

        # 4. REST custom-report: add Basic-auth creds — workday.py:383-403
        _using_basic_auth: bool = False
        _missing_report_creds: bool = False
        if is_rest_custom_report:
            report_username = config.resolved_report_username
            report_password = config.resolved_report_password
            if report_username and report_password:
                creds["report_username"] = report_username
                creds["report_password"] = report_password
                _using_basic_auth = True
            else:
                _missing_report_creds = True

        # 5. Initialise SOAPClient (handles OAuth/Basic internally)
        super().__init__(
            credentials=creds,
            timeout=config.timeout,
            **kwargs,
        )

        # 6. Logger + instance state
        self._logger = logging.getLogger("parrot_tools.interfaces.workday")
        self._config: WorkdayConfig = config
        self._is_rest_custom_report: bool = is_rest_custom_report
        self._is_soap_custom_report: bool = is_soap_custom_report

        # Tenant / report config for custom-report URL building — workday.py:428-430
        self.tenant: str = config.resolved_tenant
        self.report_owner: str = config.resolved_report_owner
        self.workday_url: str = config.resolved_workday_url

        # Log WSDL choice and auth method — workday.py:432-445
        self._logger.info(
            "WorkdayService: WSDL=%s  operation_type=%s", wsdl_path, operation_type
        )
        if is_soap_custom_report:
            self._logger.info(
                "Using OAuth + Proxy_User_Name for SOAP custom report: %s", operation_type
            )
        elif _using_basic_auth:
            self._logger.info(
                "Using Basic auth for REST custom report: %s", operation_type
            )
        elif _missing_report_creds and is_rest_custom_report:
            self._logger.warning(
                "REST custom report '%s' detected but no credentials provided. "
                "Set WORKDAY_REPORT_USERNAME / WORKDAY_REPORT_PASSWORD or pass "
                "report_username/report_password explicitly.",
                operation_type,
            )

        # 7. Eager handler registry (workday.py:454-476).
        # Handlers currently accept ``component`` — passing ``self`` works because
        # WorkdayService inherits SOAPClient which has ``run()``.
        # TASK-104 rebases handlers to use self.service.call_operation() instead.
        self._type_handlers: dict[str, Any] = {
            "get_workers": WorkerType(self),
            "get_time_blocks": TimeBlockType(self),
            "get_locations": LocationType(self),
            "get_time_requests": TimeRequestType(self),
            "get_organizations": OrganizationType(self),
            "get_organization": GetOrganization(self),
            "get_location_hierarchy_assignments": LocationHierarchyAssignmentsType(self),
            "get_cost_centers": CostCenterType(self),
            "get_applicants": ApplicantType(self),
            "get_candidates": CandidateType(self),
            "get_job_requisitions": JobRequisitionType(self),
            "get_job_postings": JobPostingType(self),
            "get_job_posting_sites": JobPostingSiteType(self),
            "get_recruiting_agency_users": RecruitingAgencyUsersType(self),
            "get_time_off_balances": TimeOffBalanceType(self),
            "extract_time_blocks_report": TimeBlockReportType(self),
            "custom_report": CustomReportType(self),
            "custom_punch_field_report": CustomPunchFieldReportType(self),
            "custom_punch_field_report_rest": CustomPunchFieldReportRestType(self),
            "get_references": ReferencesType(self),
            # FEAT-027: write handlers (Time Tracking)
            "put_time_clock_events": PutTimeClockEventsType(self),
            "import_time_clock_events": ImportTimeClockEventsType(self),
            "import_reported_time_blocks": ImportReportedTimeBlocksType(self),
            # FEAT-230: Absence Management handlers
            "request_time_off": RequestTimeOffType(self),
            "get_time_off_eligibility": TimeOffEligibilityType(self),
        }

        self.metrics: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Public data methods
    # ------------------------------------------------------------------

    async def call_operation(self, operation: str, **kwargs: Any) -> Any:
        """Raw SOAP invoke — the single choke point for all handlers (G4).

        Delegates directly to ``SOAPClient.run`` without any dispatch logic.
        Handlers will call this after TASK-104 rebase.

        Args:
            operation: Zeep operation name (e.g. ``"Get_Workers"``).
            **kwargs: SOAP request body fields forwarded to Zeep.

        Returns:
            The raw Zeep response object.
        """
        return await super().run(operation=operation, **kwargs)

    async def fetch(self, operation_type: str, **params: Any) -> pd.DataFrame:
        """Dispatch to the registered handler and return a DataFrame.

        Equivalent to the component's dispatch path in ``run()`` (workday.py:858).
        Does NOT inject flow-specific kwargs (masks, storage, dates from YAML
        attributes); those belong in the thin component (TASK-105).

        Args:
            operation_type: One of the 20 registered operation keys.
            **params: Passed directly to ``handler.execute()``.

        Returns:
            A ``pandas.DataFrame`` with the parsed results.

        Raises:
            ValueError: If the operation_type is not registered.
        """
        handler = self._type_handlers.get(operation_type)
        if handler is None:
            raise ValueError(
                f"Unknown Workday operation type: '{operation_type}'. "
                f"Available: {list(self._type_handlers)}"
            )
        return await handler.execute(**params)

    async def fetch_models(self, operation_type: str, **params: Any) -> list:
        """Typed path returning the underlying Pydantic models (C7).

        Fetches via ``fetch()`` and reconstructs model instances from the
        resulting DataFrame rows.  After TASK-104 the handlers will expose
        the internally-built ``parsed`` list directly — this implementation
        is the correct in-spec stand-in for TASK-103.

        Args:
            operation_type: One of the registered operation keys that has a
                model class in ``_OPERATION_MODEL_MAP``.
            **params: Forwarded to ``fetch()``.

        Returns:
            ``list[<ModelClass>]`` (e.g. ``list[Worker]``) or an empty list
            for operation types with no mapped model class.
        """
        model_class = _OPERATION_MODEL_MAP.get(operation_type)
        if model_class is None:
            self._logger.warning(
                "fetch_models: no Pydantic model registered for operation_type '%s'. "
                "Returning empty list.",
                operation_type,
            )
            return []

        df = await self.fetch(operation_type, **params)
        models = []
        for record in df.to_dict(orient="records"):
            try:
                models.append(model_class(**record))
            except Exception as exc:  # noqa: BLE001
                self._logger.warning(
                    "fetch_models: could not reconstruct %s from row: %s",
                    model_class.__name__,
                    exc,
                )
        return models

    async def get_custom_report(
        self,
        report_name: str,
        report_owner: str | None = None,
        **query_params: Any,
    ) -> pd.DataFrame:
        """Execute any Workday RaaS (Reports as a Service) custom report.

        Mirrors ``workday.py:896-957`` on the service layer.

        Args:
            report_name: Name of the report in Workday (required).
                Example: ``"Extract_Time_Blocks_-_Navigator"``
            report_owner: Email/ID of the report owner (optional).
                Defaults to ``config.report_owner``.
            **query_params: Any report-specific query parameters
                (e.g. ``Start_Date``, ``End_Date``, ``Worker``).

        Returns:
            DataFrame with automatic column detection from the JSON response.
        """
        handler = self._type_handlers.get("custom_report")
        if handler is None:
            raise ValueError("'custom_report' handler not registered in WorkdayService")
        return await handler.execute(
            report_name=report_name,
            report_owner=report_owner or self.report_owner,
            **query_params,
        )

    # ------------------------------------------------------------------
    # FEAT-027: Write methods + read wrapper (G2 / G3)
    # ------------------------------------------------------------------

    async def put_time_clock_events(
        self,
        events: "list[ClockEvent]",
        *,
        auto_submit: bool | None = None,
    ) -> pd.DataFrame:
        """Submit clock events via Put_Time_Clock_Events; return per-event status.

        Usable standalone without any FlowComponent (G8).

        Args:
            events: Validated list of ClockEvent models.
            auto_submit: Optional service-level override for all events' auto_submit
                flag.  When set, every event's ``auto_submit`` is replaced with this
                value before submission.

        Returns:
            DataFrame with columns ``submitted``, ``event_id``, ``error`` —
            one row per input event.  ``event_id`` echoes the client-assigned
            ``Time_Clock_Event_ID`` (Workday returns no per-event WID).
        """
        if auto_submit is not None:
            # Apply service-level override to a shallow copy of each event
            events = [
                ev.model_copy(update={"auto_submit": auto_submit}) for ev in events
            ]
        handler = self._type_handlers["put_time_clock_events"]
        return await handler.execute(events=events)

    async def import_time_clock_events(
        self,
        events: "list[ClockEvent]",
        *,
        batch_id: str | None = None,
    ) -> pd.DataFrame:
        """Batch-import clock events via Import_Time_Clock_Events.

        The response is an async ``Import_Process_Reference`` (Workday processes
        it in the background).  No terminal-status polling is performed (Non-Goal).

        Args:
            events: Validated list of ClockEvent models.
            batch_id: Optional batch identifier forwarded to the SOAP operation.

        Returns:
            DataFrame with ``submitted``/``event_id``/``error``; ``event_id`` is
            the same ``Import_Process_Reference`` on every row.
        """
        handler = self._type_handlers["import_time_clock_events"]
        return await handler.execute(events=events, batch_id=batch_id)

    async def import_reported_time_blocks(
        self,
        blocks: "list[ReportedTimeBlock]",
    ) -> pd.DataFrame:
        """Import reported time blocks via Import_Reported_Time_Blocks.

        Args:
            blocks: Validated list of ReportedTimeBlock models.

        Returns:
            DataFrame with ``submitted``/``event_id``/``error``; ``event_id`` is
            the same ``Import_Process_Reference`` on every row.
        """
        handler = self._type_handlers["import_reported_time_blocks"]
        return await handler.execute(blocks=blocks)

    async def get_calculated_time_blocks(self, **criteria: Any) -> pd.DataFrame:
        """Typed wrapper over the existing get_time_blocks handler (G3, read-only).

        Delegates to the unchanged ``TimeBlockType`` handler — no behaviour
        change to the existing operation.

        Args:
            **criteria: Same keyword arguments as
                ``fetch("get_time_blocks", **criteria)`` (e.g. ``worker_id``,
                ``start_date``, ``end_date``).

        Returns:
            DataFrame of calculated time blocks.
        """
        return await self.fetch("get_time_blocks", **criteria)

    # ------------------------------------------------------------------
    # Lifecycle overrides
    # ------------------------------------------------------------------

    async def start(self, **_kwargs: Any) -> None:
        """Initialise Redis, OAuth token, and Zeep transport/client."""
        await super().start()

    async def close(self) -> None:
        """Release transport, Redis, and Zeep client."""
        await super().close()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def serialize_object(self, obj: Any) -> Any:
        """Custom serialiser that preserves Zeep ID objects.

        Verbatim from ``workday.py:523-536``.  Parser output depends on this
        to keep the ``type`` / ``_value_1`` structure intact.

        Args:
            obj: Any Zeep-serialised value.

        Returns:
            A JSON-friendly structure with Zeep ID objects preserved as
            ``{"type": ..., "_value_1": ...}`` dicts.
        """

        def _serialize(o: Any) -> Any:
            if isinstance(o, list):
                return [_serialize(i) for i in o]
            if isinstance(o, dict):
                return {k: _serialize(v) for k, v in o.items()}
            # Zeep ID object: has .type and ._value_1
            if hasattr(o, "type") and hasattr(o, "_value_1"):
                return {
                    "type": getattr(o, "type", None),
                    "_value_1": getattr(o, "_value_1", None),
                }
            return o

        raw = zeep_serialize(obj, target_cls=dict)
        return _serialize(raw)

    def split_parts(self, task_list: list, num_parts: int = 5) -> list:
        """Divide ``task_list`` into ``num_parts`` roughly equal sublists.

        Verbatim from ``parrot_tools.interfaces.workday``.
        Called by workers/applicants/job_requisitions handlers for batch processing.

        Args:
            task_list: The sequence to partition.
            num_parts: Number of sublists to produce.

        Returns:
            A list of ``num_parts`` sublists.
        """
        part_size, remainder = divmod(len(task_list), num_parts)
        parts: list = []
        start = 0
        for i in range(num_parts):
            end = start + part_size + (1 if i < remainder else 0)
            parts.append(task_list[start:end])
            start = end
        return parts

    def add_metric(self, key: str, value: Any) -> None:
        """Store a named metric.  Called by handlers to record counts.

        Args:
            key: Metric name (e.g. ``"NUM_WORKERS"``).
            value: Metric value.
        """
        self.metrics[key] = value
