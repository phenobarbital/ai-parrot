"""Typed helpdesk tools for Softhealer ``sh_all_in_one_helpdesk`` on Odoo 19."""

from __future__ import annotations

import logging
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
from parrot.interfaces.odoointerface import OdooConfig, OdooError
from parrot.tools.decorators import tool_schema
from parrot_tools.odoo.helpdesk_normalize import extra_fields_to_dict, normalize_ticket
from parrot_tools.odoo.models.envelopes import FieldSelectionMetadata, ModelInfo, ModelOperations, ModelsResult
from parrot_tools.odoo.models.helpdesk_entities import HelpdeskMessage, HelpdeskStageInfo, HelpdeskTicket
from parrot_tools.odoo.models.helpdesk_envelopes import (
    HelpdeskReferenceItem,
    HelpdeskReferenceResult,
    TicketExtraFieldsResult,
    TicketHistoryResult,
    TicketListResult,
    TicketMessagesResult,
    TicketResult,
)
from parrot_tools.odoo.models.helpdesk_inputs import (
    GetTicketExtraFieldsInput,
    GetTicketHistoryInput,
    GetTicketInput,
    GetTicketMessagesInput,
    ListMyTicketsInput,
    ListReferenceInput,
    SearchTicketsInput,
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
        """Read one ticket; use ``get_ticket_history`` separately when history is required."""
        _ = include_history
        ticket = await self._load_ticket(ticket_id, include_extra=include_extra_fields)
        return TicketResult(ticket=ticket, url=self._ticket_url(ticket_id))

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
