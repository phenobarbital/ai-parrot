"""Typed helpdesk tools for Softhealer ``sh_all_in_one_helpdesk`` on Odoo 19."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Optional

from parrot.conf import (
    ODOO_HELPDESK_APIKEY,
    ODOO_HELPDESK_DATABASE,
    ODOO_HELPDESK_PASSWORD,
    ODOO_HELPDESK_TIMEOUT,
    ODOO_HELPDESK_URL,
    ODOO_HELPDESK_USER,
    ODOO_HELPDESK_VERIFY_SSL,
)
from parrot.interfaces.odoointerface import OdooConfig, OdooError, OdooRPCError
from parrot.tools.decorators import requires_permission, tool_schema
from parrot_tools.odoo.helpdesk_normalize import extra_fields_to_dict, normalize_stats_groups, normalize_ticket
from parrot_tools.odoo.models.envelopes import (
    BinaryFieldResult,
    FieldSelectionMetadata,
    ModelInfo,
    ModelOperations,
    ModelsResult,
)
from parrot_tools.odoo.models.helpdesk_entities import (
    HelpdeskMessage,
    HelpdeskSla,
    HelpdeskSlaStatus,
    HelpdeskStageInfo,
    HelpdeskTicket,
    HelpdeskTicketAlarm,
)
from parrot_tools.odoo.models.helpdesk_envelopes import (
    HelpdeskReferenceItem,
    HelpdeskReferenceResult,
    SlaPolicyListResult,
    SlaPolicyResult,
    SlaStatusResult,
    TicketExtraFieldsResult,
    TicketHistoryResult,
    TicketAlarmListResult,
    TicketAssignmentResult,
    TicketCommentResult,
    TicketListResult,
    TicketMessagesResult,
    TicketResult,
    TicketStatsResult,
    TicketTimerResult,
    TicketTransitionResult,
    WizardResult,
)
from parrot_tools.odoo.models.helpdesk_inputs import (
    ApproveTicketInput,
    CancelTicketInput,
    CloseTicketInput,
    MoveTicketToStageInput,
    ReopenTicketInput,
    ResolveTicketInput,
    AddTicketCommentInput,
    AssignTicketInput,
    AttachToTicketInput,
    CreateTicketInput,
    GetTicketExtraFieldsInput,
    GetTicketHistoryInput,
    GetTicketInput,
    GetTicketMessagesInput,
    GetTicketSlaStatusInput,
    ListMyTicketsInput,
    ListReferenceInput,
    ListSlaPoliciesInput,
    ListTicketAlarmsInput,
    MassUpdateTicketsInput,
    MergeTicketsInput,
    SearchTicketsInput,
    ReassignTicketInput,
    TakeTicketInput,
    UpdateTicketInput,
    CreateSlaPolicyInput,
    UpdateSlaPolicyInput,
    StartTicketTimerInput,
    StopTicketTimerInput,
    TicketStatsInput,
)
from parrot_tools.odoo.toolkit import OdooToolkit, _DEFAULT_KNOWN_MODELS
from parrot_tools.odoo.transport.base import AbstractOdooTransport
from parrot_tools.odoo.transport.detect import Protocol

TICKET_MODEL = "sh.helpdesk.ticket"

_HELPDESK_KNOWN_MODELS: tuple[tuple[str, str], ...] = (
    ("sh.helpdesk.ticket", "Helpdesk Ticket"),
    ("sh.helpdesk.team", "Helpdesk Team"),
    ("helpdesk.stages", "Helpdesk Stage"),
    ("helpdesk.category", "Helpdesk Category"),
    ("helpdesk.subcategory", "Helpdesk Subcategory"),
    ("helpdesk.priority", "Helpdesk Priority"),
    ("helpdesk.sub.type", "Helpdesk Subject"),
    ("helpdesk.tags", "Helpdesk Tag"),
    ("sh.helpdesk.ticket.type", "Helpdesk Ticket Type"),
    ("sh.helpdesk.sla", "Helpdesk SLA Policy"),
    ("sh.helpdesk.sla.status", "Helpdesk SLA Status"),
    ("sh.helpdesk.ticket.stage.info", "Helpdesk Stage History"),
    ("sh.ticket.alarm", "Helpdesk Ticket Alarm"),
)

_STAGE_ROLE_FIELDS = (
    "new_stage_id",
    "reopen_stage_id",
    "done_stage_id",
    "cancel_stage_id",
    "close_stage_id",
    "sh_staff_replied_stage_id",
    "sh_customer_replied_stage_id",
)


class OdooHelpdeskToolkit(OdooToolkit):
    """Helpdesk tools for Softhealer ``sh_all_in_one_helpdesk`` on top of :class:`OdooToolkit`."""

    confirming_tools: frozenset = OdooToolkit.confirming_tools | frozenset(
        {"cancel_ticket", "merge_tickets", "mass_update_tickets"}
    )

    _TICKET_LIST_FIELDS = [
        "id",
        "name",
        "email_subject",
        "stage_id",
        "state",
        "priority",
        "team_id",
        "user_id",
        "sh_user_ids",
        "category_id",
        "sub_category_id",
        "ticket_type",
        "partner_id",
        "create_date",
        "close_date",
        "sh_sla_deadline",
    ]
    _TICKET_DEFAULT_FIELDS = [
        "id",
        "name",
        "description",
        "comment",
        "customer_comment",
        "email",
        "email_cc",
        "email_subject",
        "mobile_no",
        "person_name",
        "partner_id",
        "stage_id",
        "team_id",
        "team_head",
        "user_id",
        "category_id",
        "sub_category_id",
        "ticket_type",
        "subject_id",
        "priority",
        "company_id",
        "sh_user_ids",
        "tag_ids",
        "sh_sla_policy_ids",
        "sh_sla_status_ids",
        "sh_ticket_alarm_ids",
        "attachment_ids",
        "timehseet_ids",
        "priority_new",
        "state",
        "open_boolean",
        "done_stage_boolean",
        "closed_stage_boolean",
        "cancel_stage_boolean",
        "reopen_stage_boolean",
        "done_button_boolean",
        "cancel_button_boolean",
        "close_date",
        "close_by",
        "cancel_date",
        "cancel_by",
        "cancel_reason",
        "replied_date",
        "sh_due_date",
        "sh_sla_deadline",
        "sh_status",
        "create_date",
        "write_date",
        "ticket_from_portal",
        "ticket_from_website",
        "ticket_running",
        "dynamic_form_submission_id",
    ]
    _REF_MODELS: dict[str, tuple[str, str]] = {
        "stage": ("helpdesk.stages", "name"),
        "team": ("sh.helpdesk.team", "name"),
        "category": ("helpdesk.category", "name"),
        "sub_category": ("helpdesk.subcategory", "name"),
        "priority": ("helpdesk.priority", "name"),
        "ticket_type": ("sh.helpdesk.ticket.type", "name"),
        "tag": ("helpdesk.tags", "name"),
        "user": ("res.users", "name"),
        "sla": ("sh.helpdesk.sla", "name"),
    }

    def __init__(
        self,
        url: str | None = None,
        database: str | None = None,
        username: str | None = None,
        password: str | None = None,
        timeout: int | None = None,
        verify_ssl: bool | None = None,
        protocol: Protocol = "auto",
        transport: AbstractOdooTransport | None = None,
        **kwargs: Any,
    ) -> None:
        """Resolve values from arguments or dedicated ``ODOO_HELPDESK_*`` configuration."""
        resolved = OdooConfig(
            url=url if url is not None else (ODOO_HELPDESK_URL or ""),
            database=database if database is not None else (ODOO_HELPDESK_DATABASE or ""),
            username=username if username is not None else (ODOO_HELPDESK_USER or ""),
            password=password if password is not None else (ODOO_HELPDESK_APIKEY or ODOO_HELPDESK_PASSWORD or ""),
            timeout=timeout if timeout is not None else ODOO_HELPDESK_TIMEOUT,
            verify_ssl=verify_ssl if verify_ssl is not None else ODOO_HELPDESK_VERIFY_SSL,
        )
        super().__init__(
            url=resolved.url,
            database=resolved.database,
            username=resolved.username,
            password=resolved.password,
            timeout=resolved.timeout,
            verify_ssl=resolved.verify_ssl,
            protocol=protocol,
            transport=transport,
            **kwargs,
        )
        self.config = resolved
        self._ref_cache: dict[tuple[str, str], int] = {}
        self._stages_cache: dict[int, dict[str, Any]] | None = None
        self._stage_roles: dict[str, int | None] | None = None
        self.logger = logging.getLogger(__name__)

    async def _resolve_ref(self, kind: str, value: int | str) -> int:
        """Resolve an integer id or one unambiguous named reference."""
        if isinstance(value, int):
            return value
        if kind not in self._REF_MODELS:
            raise ValueError(f"unknown ref kind {kind!r}")
        model, field = self._REF_MODELS[kind]
        key = (model, value)
        if key in self._ref_cache:
            return self._ref_cache[key]
        domains = [[("login", "=", value)]] if kind == "user" else []
        domains.extend([[(field, "=", value)], [(field, "ilike", value)]])
        for domain in domains:
            rows = await self._execute(model, "search_read", [domain], {"fields": ["id", field], "limit": 5}) or []
            if len(rows) == 1:
                result = int(rows[0]["id"])
                self._ref_cache[key] = result
                return result
            if len(rows) > 1:
                candidates = ", ".join(f"{row.get(field, '')} ({row['id']})" for row in rows)
                raise ValueError(f"Ambiguous {kind} named {value!r}: {candidates}")
        raise ValueError(f"No {kind} named {value!r}")

    async def _resolve_refs(self, kind: str, values: list[int | str]) -> list[int]:
        """Resolve each named or numeric reference in order."""
        return [await self._resolve_ref(kind, value) for value in values]

    async def _stage_map(self) -> dict[int, dict[str, Any]]:
        """Return cached helpdesk stages keyed by id."""
        if self._stages_cache is None:
            rows = await self._execute(
                "helpdesk.stages",
                "search_read",
                [[]],
                {
                    "fields": [
                        "name",
                        "sequence",
                        "sh_next_stage",
                        "is_done_button_visible",
                        "is_cancel_button_visible",
                    ],
                    "order": "sequence, id",
                },
            )
            self._stages_cache = {int(row["id"]): row for row in rows or []}
        return self._stages_cache

    async def _company_stage_config(self) -> dict[str, int | None]:
        """Return cached company stage role ids for the connected user."""
        if self._stage_roles is None:
            transport = await self._ensure_transport()
            users = await self._execute("res.users", "read", [[transport.uid]], {"fields": ["company_id"]}) or []
            company_id = (users[0].get("company_id") or [1])[0] if users else 1
            companies = (
                await self._execute("res.company", "read", [[company_id]], {"fields": list(_STAGE_ROLE_FIELDS)}) or []
            )
            company = companies[0] if companies else {}
            names = {
                "new_stage_id": "new",
                "reopen_stage_id": "reopen",
                "done_stage_id": "done",
                "cancel_stage_id": "cancel",
                "close_stage_id": "close",
                "sh_staff_replied_stage_id": "staff_replied",
                "sh_customer_replied_stage_id": "customer_replied",
            }
            self._stage_roles = {
                short: int(value[0]) if isinstance(value := company.get(field), (list, tuple)) and value else None
                for field, short in names.items()
            }
        return self._stage_roles

    async def _closed_stage_ids(self) -> list[int]:
        """Return close and cancel stage ids, with terminal-stage fallback."""
        roles = await self._company_stage_config()
        ids = [stage_id for stage_id in (roles.get("close"), roles.get("cancel")) if stage_id]
        if ids:
            return ids
        return [stage_id for stage_id, row in (await self._stage_map()).items() if not row.get("sh_next_stage")]

    async def _extra_rows(self, ticket_id: int) -> list[dict[str, Any]]:
        """Fetch TROC extra-field rows for a ticket."""
        return (
            await self._execute(
                "sh.helpdesk.ticket.extra_fields",
                "search_read",
                [[("ticket_id", "=", ticket_id)]],
                {"fields": ["field_name", "name", "value"], "limit": 500},
            )
            or []
        )

    async def _load_ticket(self, ticket_id: int, include_extra: bool = True) -> HelpdeskTicket:
        """Read and normalize one ticket, including optional TROC extra fields."""
        record = await self._read_one(TICKET_MODEL, ticket_id, self._TICKET_DEFAULT_FIELDS)
        if not record:
            raise ValueError(f"Ticket {ticket_id} not found")
        extra = await self._extra_rows(ticket_id) if include_extra else None
        return normalize_ticket(record, extra, await self._stage_map(), await self._company_stage_config())

    def _ticket_url(self, ticket_id: int) -> str:
        """Build the Odoo form URL for a ticket."""
        return self._record_url(self.config.url, TICKET_MODEL, ticket_id)

    async def list_models(self) -> ModelsResult:
        """List helpdesk and core models with the connected user's ACLs."""
        models: list[ModelInfo] = []
        for technical_name, label in _HELPDESK_KNOWN_MODELS + _DEFAULT_KNOWN_MODELS:
            operations = ModelOperations()
            for operation in ("read", "write", "create", "unlink"):
                try:
                    allowed = await self._execute(
                        technical_name, "check_access_rights", [operation], {"raise_exception": False}
                    )
                except OdooError:
                    allowed = False
                setattr(operations, operation, bool(allowed))
            models.append(ModelInfo(model=technical_name, name=label, operations=operations))
        return ModelsResult(models=models, total=len(models))

    async def _reference(self, model: str, fields: list[str], limit: int, order: str = "id") -> HelpdeskReferenceResult:
        """Fetch named reference records and preserve requested fields in ``extra``."""
        rows = (
            await self._execute(
                model, "search_read", [[]], {"fields": ["id", "name", *fields], "limit": limit, "order": order}
            )
            or []
        )
        items = [
            HelpdeskReferenceItem(
                id=int(row["id"]), name=str(row.get("name") or ""), extra={key: row.get(key) for key in fields}
            )
            for row in rows
        ]
        return HelpdeskReferenceResult(kind=model, items=items, total=len(items))

    @tool_schema(ListReferenceInput)
    async def list_helpdesk_stages(self, limit: int = 100) -> HelpdeskReferenceResult:
        """List helpdesk stages ordered by sequence with transition flags."""
        return await self._reference(
            "helpdesk.stages",
            ["sequence", "sh_next_stage", "is_done_button_visible", "is_cancel_button_visible"],
            limit,
            "sequence, id",
        )

    @tool_schema(ListReferenceInput)
    async def list_helpdesk_teams(self, limit: int = 100) -> HelpdeskReferenceResult:
        """List helpdesk teams with their head and members."""
        return await self._reference("sh.helpdesk.team", ["team_head", "team_members"], limit)

    @tool_schema(ListReferenceInput)
    async def list_helpdesk_categories(self, limit: int = 100) -> HelpdeskReferenceResult:
        """List categories with their team and child subcategories."""
        result = await self._reference("helpdesk.category", ["team_id"], limit)
        rows = (
            await self._execute(
                "helpdesk.subcategory",
                "search_read",
                [[]],
                {"fields": ["id", "name", "parent_category_id"], "limit": 500},
            )
            or []
        )
        children: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            parent = row.get("parent_category_id")
            if isinstance(parent, (list, tuple)) and parent:
                children.setdefault(int(parent[0]), []).append(
                    {"id": int(row["id"]), "name": str(row.get("name") or "")}
                )
        for item in result.items:
            item.extra["subcategories"] = children.get(item.id, [])
        return result

    @tool_schema(ListReferenceInput)
    async def list_helpdesk_priorities(self, limit: int = 100) -> HelpdeskReferenceResult:
        """List helpdesk priorities ordered by sequence."""
        return await self._reference("helpdesk.priority", ["sequence", "color"], limit, "sequence, id")

    @tool_schema(ListReferenceInput)
    async def list_ticket_types(self, limit: int = 100) -> HelpdeskReferenceResult:
        """List helpdesk ticket types and their SLA counts."""
        return await self._reference("sh.helpdesk.ticket.type", ["sla_count"], limit)

    @tool_schema(ListReferenceInput)
    async def list_helpdesk_tags(self, limit: int = 100) -> HelpdeskReferenceResult:
        """List helpdesk tags with their display color."""
        return await self._reference("helpdesk.tags", ["color"], limit)

    @tool_schema(GetTicketInput)
    async def get_ticket(
        self, ticket_id: int, include_extra_fields: bool = True, include_history: bool = False
    ) -> TicketResult:
        """Read one ticket; with ``include_history`` its stage-history lines are returned in ``history``."""
        ticket = await self._load_ticket(ticket_id, include_extra=include_extra_fields)
        history = (await self.get_ticket_history(ticket_id)).lines if include_history else []
        return TicketResult(ticket=ticket, url=self._ticket_url(ticket_id), history=history)

    async def _ticket_list(
        self, clauses: list[Any], fields: list[str], limit: int, offset: int, order: str
    ) -> TicketListResult:
        """Run the shared ticket list/count/normalization sequence."""
        records = (
            await self._execute(
                TICKET_MODEL,
                "search_read",
                [clauses],
                {"fields": fields, "limit": limit, "offset": offset, "order": order},
            )
            or []
        )
        total = int(await self._execute(TICKET_MODEL, "search_count", [clauses]) or 0)
        stages, roles = await self._stage_map(), await self._company_stage_config()
        return TicketListResult(
            tickets=[normalize_ticket(record, None, stages, roles) for record in records],
            total=total,
            limit=limit,
            offset=offset,
            fields=fields,
            metadata=FieldSelectionMetadata(fields_returned=len(fields), field_selection_method="requested"),
        )

    @tool_schema(SearchTicketsInput)
    async def search_tickets(
        self,
        query: Optional[str] = None,
        stage: Optional[int | str] = None,
        team: Optional[int | str] = None,
        assignee: Optional[int | str] = None,
        category: Optional[int | str] = None,
        priority: Optional[int | str] = None,
        ticket_type: Optional[int | str] = None,
        partner_id: Optional[int] = None,
        created_after: Optional[str] = None,
        created_before: Optional[str] = None,
        only_open: bool = False,
        domain: Optional[list[Any]] = None,
        fields: Optional[list[str]] = None,
        limit: int = 50,
        offset: int = 0,
        order: str = "id desc",
    ) -> TicketListResult:
        """Search tickets by text, references, dates, and open/closed lifecycle state."""
        clauses: list[Any] = []
        if query:
            clauses.extend(
                ["|", "|", ("name", "ilike", query), ("email_subject", "ilike", query), ("email", "ilike", query)]
            )
        for field, kind, value in (
            ("stage_id", "stage", stage),
            ("team_id", "team", team),
            ("user_id", "user", assignee),
            ("category_id", "category", category),
            ("priority", "priority", priority),
            ("ticket_type", "ticket_type", ticket_type),
        ):
            if value is not None:
                clauses.append((field, "=", await self._resolve_ref(kind, value)))
        if partner_id is not None:
            clauses.append(("partner_id", "=", partner_id))
        if created_after is not None:
            clauses.append(("create_date", ">=", created_after))
        if created_before is not None:
            clauses.append(("create_date", "<=", created_before))
        if only_open:
            clauses.append(("stage_id", "not in", await self._closed_stage_ids()))
        if domain:
            clauses.extend(domain)
        use_fields = fields or self._TICKET_LIST_FIELDS
        result = await self._ticket_list(clauses, use_fields, limit, offset, order)
        result.metadata = FieldSelectionMetadata(
            fields_returned=len(use_fields), field_selection_method="requested" if fields else "auto"
        )
        return result

    @tool_schema(ListMyTicketsInput)
    async def list_my_tickets(self, only_open: bool = True, limit: int = 50) -> TicketListResult:
        """List tickets assigned to, or additionally shared with, the connected user."""
        transport = await self._ensure_transport()
        clauses: list[Any] = ["|", ("user_id", "=", transport.uid), ("sh_user_ids", "in", [transport.uid])]
        if only_open:
            clauses.append(("stage_id", "not in", await self._closed_stage_ids()))
        result = await self._ticket_list(clauses, self._TICKET_LIST_FIELDS, limit, 0, "id desc")
        result.metadata = FieldSelectionMetadata(
            fields_returned=len(self._TICKET_LIST_FIELDS), field_selection_method="auto"
        )
        return result

    @tool_schema(GetTicketHistoryInput)
    async def get_ticket_history(self, ticket_id: int) -> TicketHistoryResult:
        """List ticket stage-history records ordered chronologically."""
        rows = (
            await self._execute(
                "sh.helpdesk.ticket.stage.info",
                "search_read",
                [[("stage_task_id", "=", ticket_id)]],
                {
                    "fields": [
                        "stage_task_id",
                        "stage_name",
                        "date_in",
                        "date_out",
                        "date_in_by",
                        "date_out_by",
                        "day_diff",
                        "time_diff",
                        "total_time_diff",
                    ],
                    "order": "date_in, id",
                },
            )
            or []
        )
        return TicketHistoryResult(
            ticket_id=ticket_id, lines=[HelpdeskStageInfo.model_validate(row) for row in rows], total=len(rows)
        )

    @tool_schema(GetTicketMessagesInput)
    async def get_ticket_messages(
        self, ticket_id: int, limit: int = 20, include_notifications: bool = False
    ) -> TicketMessagesResult:
        """List messages on a ticket, optionally including notification-only messages."""
        domain: list[Any] = [("model", "=", TICKET_MODEL), ("res_id", "=", ticket_id)]
        if not include_notifications:
            domain.append(("message_type", "!=", "notification"))
        rows = (
            await self._execute(
                "mail.message",
                "search_read",
                [domain],
                {
                    "fields": ["message_type", "subtype_id", "date", "author_id", "body"],
                    "limit": limit,
                    "order": "id desc",
                },
            )
            or []
        )
        messages = [
            HelpdeskMessage(
                id=int(row["id"]),
                date=row.get("date"),
                author_id=row.get("author_id"),
                message_type=row.get("message_type"),
                subtype=(row.get("subtype_id") or [None, None])[1],
                body=str(row.get("body") or ""),
                is_internal=(row.get("subtype_id") or [None, None])[1] == "Note",
            )
            for row in rows
        ]
        return TicketMessagesResult(ticket_id=ticket_id, messages=messages, total=len(messages))

    @tool_schema(GetTicketExtraFieldsInput)
    async def get_ticket_extra_fields(self, ticket_id: int) -> TicketExtraFieldsResult:
        """Return TROC extra-field values and labels for a ticket."""
        fields, labels = extra_fields_to_dict(await self._extra_rows(ticket_id))
        return TicketExtraFieldsResult(ticket_id=ticket_id, fields=fields, labels=labels, count=len(fields))

    # ── Ticket writes, comments, attachments (FEAT-616 M6) ─────────────────
    async def _find_or_create_partner(self, partner_id: int | None, email: str | None, name: str | None) -> int:
        """Resolve a customer by id, email, name, or create one."""
        if partner_id:
            return partner_id
        if not email and not name:
            raise ValueError("A customer needs partner_id, partner_email or partner_name")
        domain = [("email", "=ilike", email)] if email else [("name", "=", name)]
        rows = await self._execute("res.partner", "search_read", [domain], {"fields": ["id"], "limit": 1}) or []
        if rows:
            return int(rows[0]["id"])
        created = await self._execute("res.partner", "create", [{"name": name or email, "email": email}])
        return int(created[0] if isinstance(created, list) else created)

    @requires_permission("odoo.write")
    @tool_schema(CreateTicketInput)
    async def create_ticket(
        self,
        subject: str,
        partner_id: Optional[int] = None,
        partner_email: Optional[str] = None,
        partner_name: Optional[str] = None,
        description: Optional[str] = None,
        category: Optional[int | str] = None,
        sub_category: Optional[int | str] = None,
        priority: Optional[int | str] = None,
        team: Optional[int | str] = None,
        ticket_type: Optional[int | str] = None,
        tags: Optional[list[int | str]] = None,
        assignee: Optional[int | str] = None,
        email: Optional[str] = None,
        mobile_no: Optional[str] = None,
        person_name: Optional[str] = None,
        due_date: Optional[str] = None,
        replied_status: str = "customer_replied",
    ) -> TicketResult:
        """Create a helpdesk ticket with resolved references."""
        values: dict[str, Any] = {
            "partner_id": await self._find_or_create_partner(partner_id, partner_email, partner_name),
            "state": replied_status,
            "email_subject": subject,
        }
        if description:
            values["description"] = description if "<" in description else f"<p>{description}</p>"
        for kind, field, value in (
            ("category", "category_id", category),
            ("sub_category", "sub_category_id", sub_category),
            ("priority", "priority", priority),
            ("team", "team_id", team),
            ("ticket_type", "ticket_type", ticket_type),
            ("user", "user_id", assignee),
        ):
            if value is not None:
                values[field] = await self._resolve_ref(kind, value)
        if tags is not None:
            values["tag_ids"] = [[6, 0, await self._resolve_refs("tag", tags)]]
        for field, value in (
            ("email", email),
            ("mobile_no", mobile_no),
            ("person_name", person_name),
            ("sh_due_date", due_date),
        ):
            if value is not None:
                values[field] = value
        new_id = await self._execute(TICKET_MODEL, "create", [values])
        ticket_id = int(new_id[0] if isinstance(new_id, list) else new_id)
        self.logger.info("create_ticket: created %s #%s", TICKET_MODEL, ticket_id)
        return TicketResult(ticket=await self._load_ticket(ticket_id), url=self._ticket_url(ticket_id))

    @requires_permission("odoo.write")
    @tool_schema(UpdateTicketInput)
    async def update_ticket(
        self,
        ticket_id: int,
        subject: Optional[str] = None,
        description: Optional[str] = None,
        comment: Optional[str] = None,
        customer_comment: Optional[str] = None,
        email: Optional[str] = None,
        email_cc: Optional[str] = None,
        mobile_no: Optional[str] = None,
        person_name: Optional[str] = None,
        due_date: Optional[str] = None,
        category: Optional[int | str] = None,
        sub_category: Optional[int | str] = None,
        priority: Optional[int | str] = None,
        team: Optional[int | str] = None,
        ticket_type: Optional[int | str] = None,
        tags: Optional[list[int | str]] = None,
    ) -> TicketResult:
        """Patch descriptive ticket fields without lifecycle or assignment changes."""
        patch: dict[str, Any] = {}
        for field, value in (
            ("email_subject", subject),
            ("description", description),
            ("comment", comment),
            ("customer_comment", customer_comment),
            ("email", email),
            ("email_cc", email_cc),
            ("mobile_no", mobile_no),
            ("person_name", person_name),
            ("sh_due_date", due_date),
        ):
            if value is not None:
                patch[field] = value
        for kind, field, value in (
            ("category", "category_id", category),
            ("sub_category", "sub_category_id", sub_category),
            ("priority", "priority", priority),
            ("team", "team_id", team),
            ("ticket_type", "ticket_type", ticket_type),
        ):
            if value is not None:
                patch[field] = await self._resolve_ref(kind, value)
        if tags is not None:
            patch["tag_ids"] = [[6, 0, await self._resolve_refs("tag", tags)]]
        if not patch:
            raise ValueError("nothing to update")
        await self._execute(TICKET_MODEL, "write", [[ticket_id], patch])
        return TicketResult(ticket=await self._load_ticket(ticket_id), url=self._ticket_url(ticket_id))

    @requires_permission("odoo.write")
    @tool_schema(AddTicketCommentInput)
    async def add_ticket_comment(
        self, ticket_id: int, body: str, internal: bool = True, attachment_ids: Optional[list[int]] = None
    ) -> TicketCommentResult:
        """Post an internal note or public comment and report whether it reopened the ticket."""
        before = await self._read_one(TICKET_MODEL, ticket_id, ["stage_id"])
        kwargs: dict[str, Any] = {
            "body": body,
            "message_type": "comment",
            "subtype_xmlid": "mail.mt_note" if internal else "mail.mt_comment",
        }
        if attachment_ids:
            kwargs["attachment_ids"] = attachment_ids
        message_id = await self._execute(TICKET_MODEL, "message_post", [[ticket_id]], kwargs)
        after = await self._read_one(TICKET_MODEL, ticket_id, ["stage_id"])
        stage_after = (after.get("stage_id") or [None, None])[1]
        return TicketCommentResult(
            ticket_id=ticket_id,
            message_id=int(message_id[0] if isinstance(message_id, list) else message_id),
            internal=internal,
            reopened=(not internal) and before.get("stage_id") != after.get("stage_id"),
            stage_after=stage_after,
        )

    @requires_permission("odoo.write")
    @tool_schema(AttachToTicketInput)
    async def attach_to_ticket(
        self,
        ticket_id: int,
        name: str,
        source: str,
        mimetype: Optional[str] = None,
        description: Optional[str] = None,
    ) -> BinaryFieldResult:
        """Attach a URL or base64 file to a ticket as ``ir.attachment``."""
        return await self.attach_document(
            res_model=TICKET_MODEL,
            res_id=ticket_id,
            name=name,
            source=source,
            mimetype=mimetype,
            description=description,
        )

    # ── Assignment ──────────────────────────────────────────────────────────
    async def _assignment_result(self, ticket_id: int, method_used: str) -> TicketAssignmentResult:
        """Return an assignment result after loading the updated ticket."""
        ticket = await self._load_ticket(ticket_id, include_extra=False)
        return TicketAssignmentResult(
            ticket_id=ticket_id,
            assignee=ticket.user_id,
            additional_assignees=list(ticket.sh_user_ids or []),
            method_used=method_used,
            ticket=ticket,
        )

    @requires_permission("odoo.write")
    @tool_schema(AssignTicketInput)
    async def assign_ticket(
        self, ticket_id: int, assignee: int | str, additional_assignees: Optional[list[int | str]] = None
    ) -> TicketAssignmentResult:
        """Assign a primary user and optionally replace additional assignees."""
        values: dict[str, Any] = {"user_id": await self._resolve_ref("user", assignee)}
        if additional_assignees is not None:
            values["sh_user_ids"] = [[6, 0, await self._resolve_refs("user", additional_assignees)]]
        await self._execute(TICKET_MODEL, "write", [[ticket_id], values])
        return await self._assignment_result(ticket_id, "write")

    @requires_permission("odoo.write")
    @tool_schema(TakeTicketInput)
    async def take_ticket(self, ticket_id: int) -> TicketAssignmentResult:
        """Assign the ticket to the connected user through ``action_take_ticket``."""
        await self._execute(TICKET_MODEL, "action_take_ticket", [[ticket_id]])
        return await self._assignment_result(ticket_id, "action_take_ticket")

    @requires_permission("odoo.write")
    @tool_schema(ReassignTicketInput)
    async def reassign_ticket(self, ticket_id: int, new_assignee: int | str) -> TicketAssignmentResult:
        """Reassign a ticket through the Softhealer transient wizard."""
        new_user = await self._resolve_ref("user", new_assignee)
        wizard = await self._execute(
            "sh.helpdesk.reassign.wizard", "create", [{"ticket_id": ticket_id, "new_user_id": new_user}]
        )
        wizard_id = int(wizard[0] if isinstance(wizard, list) else wizard)
        await self._execute("sh.helpdesk.reassign.wizard", "action_confirm", [[wizard_id]])
        return await self._assignment_result(ticket_id, "reassign_wizard")

    # ── Transitions (FEAT-616 M7): action first, post-condition verified ───
    async def _transition(
        self,
        ticket_id: int,
        action: str,
        *,
        expected_stage: int | None = None,
        fallback_stage: int | None = None,
        pre_write: dict[str, Any] | None = None,
    ) -> TicketTransitionResult:
        """Run ``action`` on the ticket, re-read it and report whether anything changed.

        ``fallback_stage`` (only reopen/move use it) is written ONLY when the action changed nothing and is
        reported as ``method_used="stage_write"`` with a warning, never silently.
        """
        before = await self._read_one(TICKET_MODEL, ticket_id, ["stage_id", "close_date"])
        from_id = before["stage_id"][0] if before.get("stage_id") else None
        if expected_stage is not None and from_id != expected_stage:
            raise ValueError(f"Ticket {ticket_id} is in stage {before.get('stage_id')!r}, expected id {expected_stage}")
        warnings: list[str] = []
        if pre_write:
            await self._execute(TICKET_MODEL, "write", [[ticket_id], pre_write])
        method_used = "none"
        if action:
            result = await self._execute(TICKET_MODEL, action, [[ticket_id]])
            if isinstance(result, dict) and result.get("type") == "ir.actions.act_window":
                warnings.append(f"{action} opened a wizard ({result.get('res_model')}); not applied")
        after = await self._read_one(TICKET_MODEL, ticket_id, ["stage_id", "close_date"])
        applied = after.get("stage_id") != before.get("stage_id") or (
            action == "action_closed" and bool(after.get("close_date")) and not before.get("close_date")
        )
        if applied:
            method_used = "action"
        elif action:
            warnings.append(f"{action} produced no change on this instance (company stage role not configured?)")
        if not applied and fallback_stage is not None:
            await self._execute(TICKET_MODEL, "write", [[ticket_id], {"stage_id": fallback_stage}])
            after = await self._read_one(TICKET_MODEL, ticket_id, ["stage_id", "close_date"])
            applied = after.get("stage_id") != before.get("stage_id")
            method_used = "stage_write"
            if action:  # an explicit move_ticket_to_stage (no action) is the intended path, not a fallback
                warnings.append("stage written directly")
        ticket = await self._load_ticket(ticket_id, include_extra=False)
        return TicketTransitionResult(
            ticket_id=ticket_id,
            action=action or "write",
            applied=applied,
            method_used=method_used,
            from_stage=before["stage_id"][1] if before.get("stage_id") else None,
            to_stage=after["stage_id"][1] if after.get("stage_id") else None,
            warnings=warnings,
            ticket=ticket,
        )

    @requires_permission("odoo.write")
    @tool_schema(CloseTicketInput)
    async def close_ticket(self, ticket_id: int, comment: Optional[str] = None) -> TicketTransitionResult:
        """Close a ticket (Softhealer ``action_closed``: sets close_date/close_by, moves to the company close stage).

        An optional internal note is posted first.
        """
        if comment:
            await self.add_ticket_comment(ticket_id, comment, internal=True)
        return await self._transition(ticket_id, "action_closed")

    @requires_permission("odoo.write")
    @tool_schema(ReopenTicketInput)
    async def reopen_ticket(self, ticket_id: int, to_stage: Optional[int | str] = None) -> TicketTransitionResult:
        """Reopen: ``action_open`` first; if it changes nothing, the stage is written directly (reported as stage_write)."""
        if to_stage is not None:
            target = await self._resolve_ref("stage", to_stage)
        else:
            roles = await self._company_stage_config()
            target = roles.get("reopen") or await self._resolve_ref("stage", "Open")
        return await self._transition(ticket_id, "action_open", fallback_stage=target)

    @requires_permission("odoo.write")
    @tool_schema(ResolveTicketInput)
    async def resolve_ticket(self, ticket_id: int) -> TicketTransitionResult:
        """Mark resolved (Softhealer ``action_done``). No fallback: without a company done stage, applied=False."""
        result = await self._transition(ticket_id, "action_done")
        if (await self._company_stage_config()).get("done") is None:
            result.warnings.append("done stage not configured on company; action_done cannot apply")
        return result

    @requires_permission("odoo.write")
    @tool_schema(ApproveTicketInput)
    async def approve_ticket(self, ticket_id: int) -> TicketTransitionResult:
        """Approve a ticket (Softhealer ``action_approve``). No fallback: the result reports whether it applied."""
        return await self._transition(ticket_id, "action_approve")

    @requires_permission("odoo.write")
    @tool_schema(CancelTicketInput)
    async def cancel_ticket(self, ticket_id: int, reason: str) -> TicketTransitionResult:
        """Cancel a ticket: write ``cancel_reason`` then call ``action_cancel``. No stage fallback.

        ``cancel_reason`` is written before the action, so it stays on the ticket even when ``action_cancel``
        changes nothing (``applied=False``).
        """
        result = await self._transition(ticket_id, "action_cancel", pre_write={"cancel_reason": reason})
        if (await self._company_stage_config()).get("cancel") is None:
            result.warnings.append("cancel stage not configured on company; action_cancel cannot apply")
        return result

    @requires_permission("odoo.write")
    @tool_schema(MoveTicketToStageInput)
    async def move_ticket_to_stage(
        self,
        ticket_id: int,
        stage: int | str,
        expected_current_stage: Optional[int | str] = None,
    ) -> TicketTransitionResult:
        """Move a ticket to a stage by writing ``stage_id``, optionally guarded by the expected current stage."""
        target = await self._resolve_ref("stage", stage)
        expected = (
            await self._resolve_ref("stage", expected_current_stage) if expected_current_stage is not None else None
        )
        return await self._transition(ticket_id, "", expected_stage=expected, fallback_stage=target)

    # ── SLA policies, status, alarms (FEAT-616 M8) ─────────────────────────
    _SLA_FIELDS = [
        "id",
        "display_name",
        "name",
        "sh_team_id",
        "sh_days",
        "sh_hours",
        "sh_minutes",
        "sh_sla_target_type",
        "sh_stage_id",
        "sh_ticket_type_id",
        "company_id",
        "sla_ticket_count",
    ]
    _SLA_STATUS_FIELDS = [
        "id",
        "sh_ticket_id",
        "sh_sla_id",
        "sh_sla_stage_id",
        "sh_deadline",
        "sh_done_sla_date",
        "sh_exceeded_hours",
        "sh_status",
        "sh_create_date",
    ]

    @tool_schema(ListSlaPoliciesInput)
    async def list_sla_policies(
        self, team: Optional[int | str] = None, ticket_type: Optional[int | str] = None, limit: int = 50
    ) -> SlaPolicyListResult:
        """List SLA policies (``sh.helpdesk.sla``), optionally filtered by team and ticket type (id or name)."""
        domain: list[Any] = []
        if team is not None:
            domain.append(("sh_team_id", "=", await self._resolve_ref("team", team)))
        if ticket_type is not None:
            domain.append(("sh_ticket_type_id", "=", await self._resolve_ref("ticket_type", ticket_type)))
        rows = (
            await self._execute(
                "sh.helpdesk.sla", "search_read", [domain], {"fields": self._SLA_FIELDS, "limit": limit, "order": "id"}
            )
            or []
        )
        return SlaPolicyListResult(policies=[HelpdeskSla.model_validate(row) for row in rows], total=len(rows))

    @requires_permission("odoo.write")
    @tool_schema(CreateSlaPolicyInput)
    async def create_sla_policy(
        self,
        name: str,
        team: int | str,
        days: int = 0,
        hours: int = 0,
        minutes: int = 0,
        target_type: str = "reaching_stage",
        stage: Optional[int | str] = None,
        ticket_type: Optional[int | str] = None,
    ) -> SlaPolicyResult:
        """Define an SLA policy for a team to reach a stage or receive assignment within a duration."""
        values: dict[str, Any] = {
            "name": name,
            "sh_team_id": await self._resolve_ref("team", team),
            "sh_days": days,
            "sh_hours": hours,
            "sh_minutes": minutes,
            "sh_sla_target_type": target_type,
        }
        if stage is not None:
            values["sh_stage_id"] = await self._resolve_ref("stage", stage)
        if ticket_type is not None:
            values["sh_ticket_type_id"] = await self._resolve_ref("ticket_type", ticket_type)
        new_id = await self._execute("sh.helpdesk.sla", "create", [values])
        sla_id = int(new_id[0] if isinstance(new_id, list) else new_id)
        self.logger.info("create_sla_policy: created sh.helpdesk.sla #%s", sla_id)
        record = await self._read_one("sh.helpdesk.sla", sla_id, self._SLA_FIELDS)
        return SlaPolicyResult(
            policy=HelpdeskSla.model_validate(record),
            url=self._record_url(self.config.url, "sh.helpdesk.sla", sla_id),
        )

    @requires_permission("odoo.write")
    @tool_schema(UpdateSlaPolicyInput)
    async def update_sla_policy(
        self,
        sla_id: int,
        name: Optional[str] = None,
        days: Optional[int] = None,
        hours: Optional[int] = None,
        minutes: Optional[int] = None,
        target_type: Optional[str] = None,
        stage: Optional[int | str] = None,
        ticket_type: Optional[int | str] = None,
    ) -> SlaPolicyResult:
        """Update the supplied fields of an SLA policy and return the refreshed record."""
        values: dict[str, Any] = {}
        for field, value in {
            "name": name,
            "sh_days": days,
            "sh_hours": hours,
            "sh_minutes": minutes,
            "sh_sla_target_type": target_type,
        }.items():
            if value is not None:
                values[field] = value
        if stage is not None:
            values["sh_stage_id"] = await self._resolve_ref("stage", stage)
        if ticket_type is not None:
            values["sh_ticket_type_id"] = await self._resolve_ref("ticket_type", ticket_type)
        if not values:
            raise ValueError("nothing to update")
        await self._execute("sh.helpdesk.sla", "write", [[sla_id], values])
        record = await self._read_one("sh.helpdesk.sla", sla_id, self._SLA_FIELDS)
        return SlaPolicyResult(
            policy=HelpdeskSla.model_validate(record),
            url=self._record_url(self.config.url, "sh.helpdesk.sla", sla_id),
        )

    @tool_schema(GetTicketSlaStatusInput)
    async def get_ticket_sla_status(self, ticket_id: int) -> SlaStatusResult:
        """Return a ticket's overall SLA status, deadline, and per-policy status rows."""
        ticket = await self._read_one(TICKET_MODEL, ticket_id, ["sh_status", "sh_sla_deadline", "sh_sla_policy_ids"])
        rows = (
            await self._execute(
                "sh.helpdesk.sla.status",
                "search_read",
                [[("sh_ticket_id", "=", ticket_id)]],
                {"fields": self._SLA_STATUS_FIELDS},
            )
            or []
        )
        return SlaStatusResult(
            ticket_id=ticket_id,
            overall_status=ticket.get("sh_status") or None,
            deadline=ticket.get("sh_sla_deadline") or None,
            statuses=[HelpdeskSlaStatus.model_validate(row) for row in rows],
        )

    @tool_schema(ListTicketAlarmsInput)
    async def list_ticket_alarms(self, limit: int = 50) -> TicketAlarmListResult:
        """List ticket alarm configurations from ``sh.ticket.alarm``."""
        rows = (
            await self._execute(
                "sh.ticket.alarm",
                "search_read",
                [[]],
                {"fields": ["id", "name", "type", "sh_remind_before", "sh_reminder_unit"], "limit": limit},
            )
            or []
        )
        return TicketAlarmListResult(alarms=[HelpdeskTicketAlarm.model_validate(row) for row in rows], total=len(rows))

    # ── Stats, wizards, timer (FEAT-616 M9) ─────────────────────────────────

    @tool_schema(TicketStatsInput)
    async def ticket_stats(
        self,
        group_by: str = "stage_id",
        only_open: bool = False,
        domain: Optional[list[Any]] = None,
        created_after: Optional[str] = None,
        created_before: Optional[str] = None,
    ) -> TicketStatsResult:
        """Count tickets grouped by a supported field across Odoo versions."""
        clauses: list[Any] = list(domain or [])
        if created_after is not None:
            clauses.append(("create_date", ">=", created_after))
        if created_before is not None:
            clauses.append(("create_date", "<=", created_before))
        if only_open:
            clauses.append(("stage_id", "not in", await self._closed_stage_ids()))

        version = await self._get_odoo_major_version()
        try:
            if version is not None and version >= 19:
                rows = await self._execute(
                    TICKET_MODEL,
                    "formatted_read_group",
                    [clauses],
                    {"groupby": [group_by], "aggregates": ["__count"]},
                )
                source = "formatted_read_group"
            else:
                rows = await self._execute(
                    TICKET_MODEL,
                    "read_group",
                    [clauses],
                    {"groupby": [group_by], "fields": ["id:count"], "lazy": False},
                )
                source = "read_group"
        except OdooRPCError as exc:
            if group_by != "stage_id":
                raise
            self.logger.warning("ticket_stats: aggregation failed (%s); falling back to per-stage search_count", exc)
            rows = []
            for stage_id, stage in (await self._stage_map()).items():
                count = await self._execute(TICKET_MODEL, "search_count", [clauses + [("stage_id", "=", stage_id)]])
                rows.append({"stage_id": [stage_id, stage["name"]], "__count": count})
            source = "search_count"

        groups = normalize_stats_groups(rows or [], group_by, source)
        return TicketStatsResult(
            group_by=group_by,
            groups=groups,
            total=sum(group.count for group in groups),
            source_method=source,
        )

    @requires_permission("odoo.write")
    @tool_schema(MergeTicketsInput)
    async def merge_tickets(
        self,
        ticket_ids: list[int],
        into_ticket_id: Optional[int] = None,
        merged_action: str = "close",
        merge_history: bool = True,
    ) -> WizardResult:
        """Merge tickets into an existing target or a new ticket through the Softhealer wizard."""
        target = into_ticket_id or ticket_ids[0]
        partner = await self._read_one(TICKET_MODEL, target, ["partner_id"])
        values: dict[str, Any] = {
            "sh_helpdesk_ticket_ids": [[6, 0, ticket_ids]],
            "sh_select_type": "existing" if into_ticket_id else "new",
            "sh_select_merge_type": merged_action,
            "sh_merge_history": merge_history,
            "sh_partner_id": partner["partner_id"][0] if partner.get("partner_id") else False,
        }
        if into_ticket_id:
            values["sh_existing_ticket"] = into_ticket_id
        wizard_model = "sh.helpdesk.ticket.merge.ticket.wizard"
        wizard = await self._execute(wizard_model, "create", [values])
        wizard_id = int(wizard[0] if isinstance(wizard, list) else wizard)
        await self._execute(wizard_model, "action_merge_tickets", [[wizard_id]])

        if into_ticket_id:
            record = await self._read_one(TICKET_MODEL, target, ["sh_merge_ticket_count"])
            applied = int(record.get("sh_merge_ticket_count") or 0) >= len(set(ticket_ids) - {target})
            result_ticket_id: Optional[int] = target
        else:
            rows = await self._execute(
                TICKET_MODEL,
                "search_read",
                [[("sh_merge_ticket_ids", "in", ticket_ids)]],
                {"fields": ["id"], "order": "id desc", "limit": 1},
            )
            result_ticket_id = int(rows[0]["id"]) if rows else None
            applied = result_ticket_id is not None
        return WizardResult(
            wizard_model=wizard_model,
            wizard_id=wizard_id,
            ticket_ids=ticket_ids,
            applied=applied,
            result_ticket_id=result_ticket_id,
            message="tickets merged" if applied else "merge wizard completed but no merged ticket was found",
        )

    @requires_permission("odoo.write")
    @tool_schema(MassUpdateTicketsInput)
    async def mass_update_tickets(
        self,
        ticket_ids: list[int],
        stage: Optional[int | str] = None,
        assignee: Optional[int | str] = None,
        team: Optional[int | str] = None,
        add_followers: Optional[list[int]] = None,
        remove_followers: Optional[list[int]] = None,
    ) -> WizardResult:
        """Apply a staged, assignment, team, or follower update through the Softhealer wizard."""
        if add_followers and remove_followers:
            raise ValueError("add_followers and remove_followers cannot be applied by one mass-update wizard")
        values: dict[str, Any] = {"helpdesks_ticket_ids": [[6, 0, ticket_ids]]}
        if stage is not None:
            values.update({"check_helpdesks_state": True, "helpdesk_stages": await self._resolve_ref("stage", stage)})
        if assignee is not None:
            values.update({"check_assign_to": True, "assign_to": await self._resolve_ref("user", assignee)})
        if team is not None:
            values.update({"check_team_id": True, "team_id": await self._resolve_ref("team", team)})
        if add_followers:
            values.update(
                {
                    "check_add_remove": True,
                    "followers": [[6, 0, add_followers]],
                    "ticket_follower_update_type": "add",
                }
            )
        elif remove_followers:
            values.update(
                {
                    "check_add_remove": True,
                    "followers": [[6, 0, remove_followers]],
                    "ticket_follower_update_type": "remove",
                }
            )
        wizard_model = "sh.helpdesk.ticket.mass.update.wizard"
        wizard = await self._execute(wizard_model, "create", [values])
        wizard_id = int(wizard[0] if isinstance(wizard, list) else wizard)
        await self._execute(wizard_model, "update_record", [[wizard_id]])
        expected: dict[str, int] = {}
        if stage is not None:
            expected["stage_id"] = values["helpdesk_stages"]
        if assignee is not None:
            expected["user_id"] = values["assign_to"]
        if team is not None:
            expected["team_id"] = values["team_id"]
        if not expected:
            return WizardResult(
                wizard_model=wizard_model,
                wizard_id=wizard_id,
                ticket_ids=ticket_ids,
                applied=True,
                message="follower update submitted (followers are not verified)",
            )
        rows = (
            await self._execute(
                TICKET_MODEL, "search_read", [[("id", "in", ticket_ids)]], {"fields": ["id", *expected]}
            )
            or []
        )
        by_id = {int(row["id"]): row for row in rows}
        mismatched = [
            tid
            for tid in ticket_ids
            if tid not in by_id
            or any((by_id[tid].get(field) or [None])[0] != value for field, value in expected.items())
        ]
        return WizardResult(
            wizard_model=wizard_model,
            wizard_id=wizard_id,
            ticket_ids=ticket_ids,
            applied=not mismatched,
            message=(
                "tickets updated"
                if not mismatched
                else f"wizard ran but tickets {mismatched} do not show the requested values"
            ),
        )

    @requires_permission("odoo.write")
    @tool_schema(StartTicketTimerInput)
    async def start_ticket_timer(self, ticket_id: int) -> TicketTimerResult:
        """Start a ticket timer and surface tenant configuration errors as warnings."""
        try:
            await self._execute(TICKET_MODEL, "action_ticket_start", [[ticket_id]])
            ticket = await self._read_one(TICKET_MODEL, ticket_id, ["ticket_running", "start_time"])
        except OdooRPCError as exc:
            return TicketTimerResult(ticket_id=ticket_id, running=False, warnings=[str(exc)])
        return TicketTimerResult(
            ticket_id=ticket_id,
            running=bool(ticket.get("ticket_running")),
            started_at=ticket.get("start_time") or None,
        )

    @requires_permission("odoo.write")
    @tool_schema(StopTicketTimerInput)
    async def stop_ticket_timer(self, ticket_id: int, description: Optional[str] = None) -> TicketTimerResult:
        """Stop a ticket timer by recording and ending its time-account entry."""
        try:
            ticket = await self._read_one(TICKET_MODEL, ticket_id, ["start_time"])
            action = await self._execute(TICKET_MODEL, "action_ticket_end", [[ticket_id]])
            context = action.get("context") if isinstance(action, dict) else {}
            values: dict[str, Any] = {
                "name": description or f"Ticket {ticket_id}",
                "start_date": ticket.get("start_time"),
                "end_date": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
            }
            if isinstance(context, dict) and context.get("default_project_id"):
                values["project_id"] = context["default_project_id"]
            line = await self._execute("ticket.time.account.line", "create", [values])
            line_id = int(line[0] if isinstance(line, list) else line)
            await self._execute("ticket.time.account.line", "end_ticket", [[line_id]])
            record = await self._read_one("ticket.time.account.line", line_id, ["duration"])
        except OdooRPCError as exc:
            return TicketTimerResult(ticket_id=ticket_id, running=False, warnings=[str(exc)])
        return TicketTimerResult(ticket_id=ticket_id, running=False, duration_hours=record.get("duration"))
