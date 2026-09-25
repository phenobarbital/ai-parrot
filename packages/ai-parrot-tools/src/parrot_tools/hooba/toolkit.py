"""HoobaToolkit — drafts-only Hooba automation for AI-Parrot agents (FEAT-602 M6)."""

from __future__ import annotations

import asyncio
import difflib
import json
import os
import re
import unicodedata
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Literal, Optional

import aiohttp
from parrot.auth.broker import CredentialBroker
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.tools.toolkit import AbstractToolkit
from parrot_tools.business_automation.models import OperationKind
from parrot_tools.business_automation.toolkit import _credential_resolver_from_broker

from .bank import manifest_path_for, parse_bbva_statement, reconcile
from .credentials import make_login_hook, register_hooba_provider
from .importer import BbvaImporter
from .models import (
    ContactMatch,
    DraftReceipt,
    ExpenseDraftBatch,
    HoobaLookupError,
    HoobaStateError,
    InvoiceDraft,
    PurchaseInvoiceDraft,
)
from .openapi import HoobaOpenAPIToolkit
from .rules import RuleEngine
from .settings import HoobaSettings
from .web import HoobaWebAdapter

#: ``IVA<percentage>`` sales/purchase VAT code, e.g. ``IVA21`` -> 21%.
_TAX_CODE_RE = re.compile(r"^IVA(\d+(?:\.\d+)?)$")
#: ``IRPF<percentage>`` income-tax withholding code, e.g. ``IRPF15`` -> 15%.
_INCOME_TAX_CODE_RE = re.compile(r"^IRPF(\d+(?:\.\d+)?)$")
#: Hooba ``EntityUrn`` values (spec §6) for the two draft kinds this toolkit attaches documents to.
_ENTITY_URN = {"invoice": "urn:entity:invoice", "purchase_invoice": "urn:entity:purchase-invoice"}
#: List paths used both by ``hooba_list_drafts`` and the idempotency lookup in ``_find_by_key``.
_LIST_PATH = {
    "invoice": "/accounts/{accountId}/invoices",
    "purchase_invoice": "/accounts/{accountId}/purchase-invoices",
}
#: Output-envelope wrapper key Hooba uses for line records (list AND create responses).
_LINE_WRAPPER = {"invoice": "invoiceLine", "purchase_invoice": "purchaseInvoiceLine"}

_READ_TOOLS = (
    "hooba_whoami",
    "hooba_find_contact",
    "hooba_list_drafts",
    "hooba_download_invoice_pdf",
    "hooba_recover_web_session",
    "hooba_run_web_action",
)
_DRAFT_TOOLS = (
    "hooba_create_invoice_draft",
    "hooba_create_purchase_invoice_draft",
    "hooba_attach_document",
    "hooba_import_bbva_statement",
)


class HoobaToolkit(AbstractToolkit):
    """Create Hooba invoice and expense DRAFTS, never issue or confirm them."""

    auto_open = True
    exclude_tools = ("operation_kinds",)

    def __init__(
        self,
        settings: Optional[HoobaSettings] = None,
        credential_broker: Optional[CredentialBroker] = None,
        *,
        api: Optional[HoobaOpenAPIToolkit] = None,
        web: Optional[HoobaWebAdapter] = None,
        rules_path: Optional[str] = None,
        headless: bool = True,
        **kwargs: Any,
    ) -> None:
        """Initialize the API toolkit and retain a lazy web adapter."""
        super().__init__(**kwargs)
        self.settings = settings or HoobaSettings.from_env()
        if credential_broker is None:
            credential_broker = CredentialBroker()
            register_hooba_provider(credential_broker, self.settings.credential_provider)
        self._broker = credential_broker
        self._api = api or HoobaOpenAPIToolkit(
            self.settings,
            make_login_hook(self.settings, credential_broker),
        )
        self._web = web
        self._rules_path = rules_path
        self._headless = headless

    async def _open(self) -> None:
        """Establish the API session only; the browser remains lazy."""
        await self._api._ensure_session()

    async def _close(self) -> None:
        """Close a started web adapter and release the toolkit lifecycle state."""
        if self._web is not None:
            await self._web.close()
        await super()._close()

    def get_tools(self, permission_context: Any = None, resolver: Any = None) -> list[AbstractTool]:
        """Return composite and generated API tools, rejecting duplicate names."""
        own = super().get_tools(permission_context, resolver)
        api = self._api.get_tools()
        names = [tool.name for tool in own]
        collisions = set(names).intersection(tool.name for tool in api)
        if collisions:
            raise ValueError(f"Hooba tool name collision: {sorted(collisions)}")
        return own + api

    def operation_kinds(self) -> Dict[str, OperationKind]:
        """Map every composite and generated tool name to its operation kind.

        `_READ_TOOLS` and `_DRAFT_TOOLS` (TASK-3743's draft/attach/import
        composite tools) plus the bound API toolkit's own generated tools.
        """
        kinds = dict.fromkeys(_READ_TOOLS, OperationKind.READ)
        kinds.update(dict.fromkeys(_DRAFT_TOOLS, OperationKind.DRAFT))
        kinds.update(self._api.operation_kinds())
        return kinds

    def _web_adapter(self) -> Optional[HoobaWebAdapter]:
        """Build the private web adapter on first web-tool use."""
        if self.settings.catalog_dir is None:
            return None
        if self._web is None:
            resolver = _credential_resolver_from_broker(self._broker, self.settings.credential_user_id)
            self._web = HoobaWebAdapter(
                self.settings.catalog_dir,
                resolver,
                headless=self._headless,
            )
        return self._web

    def _url(self, path: str) -> str:
        """Resolve the account placeholder in a composite API path."""
        return f"{self.settings.base_url.rstrip('/')}/{path.lstrip('/')}".replace(
            "{accountId}", str(self.settings.account_id)
        )

    async def _call(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict] = None,
        data: Optional[dict] = None,
    ) -> Any:
        """Call a JSON endpoint through the API cookie session."""
        request_kwargs: Dict[str, Any] = {
            "url": self._url(path),
            "method": method.upper(),
            "params": params or {},
            "use_json": data is not None,
        }
        if data is not None:
            request_kwargs["data"] = data
        result, error = await self._api._cookie_request(method.upper(), request_kwargs["url"], request_kwargs)
        if error:
            status = error.get("status") if isinstance(error, dict) else getattr(error, "status", error)
            raise RuntimeError(f"Hooba API request failed: HTTP {status}")
        return result

    async def _call_raw(self, method: str, path: str) -> bytes:
        """Download bytes through the API cookie session, refreshing once on 401."""
        await self._api._ensure_session()
        service = self._api.http_service
        url = self._url(path)
        for attempt in range(2):
            response, error = await service._request(
                url=url,
                method=method.upper(),
                headers={**service.headers, **self.settings.default_headers()},
                cookies=self._api.get_cookies(),
                full_response=True,
                use_proxy=False,
                raise_for_status=False,
            )
            if error:
                raise RuntimeError(f"Hooba API request failed: HTTP {error}")
            if response.status_code == 401 and attempt == 0:
                await self._api._ensure_session(force=True)
                continue
            if response.status_code >= 400:
                raise RuntimeError(f"Hooba API request failed: HTTP {response.status_code}")
            return bytes(response.content)
        raise RuntimeError("Hooba API request failed: HTTP 401")

    @staticmethod
    def _ok(result: Any, kind: OperationKind) -> dict:
        """Build a successful agent-facing envelope."""
        return ToolResult(status="success", result=result, metadata={"operation_kind": kind.value}).model_dump()

    @staticmethod
    def _err(message: str, kind: OperationKind, next_tool: Optional[str] = None) -> dict:
        """Build an error envelope without raising into the agent loop."""
        metadata = {"operation_kind": kind.value}
        if next_tool is not None:
            metadata["next_tool"] = next_tool
        return ToolResult(
            success=False,
            status="error",
            result=None,
            error=message,
            metadata=metadata,
        ).model_dump()

    async def hooba_whoami(self) -> dict:
        """Return the authenticated Hooba member summary."""
        try:
            return self._ok(await self._call("GET", "/accounts/{accountId}/member"), OperationKind.READ)
        except Exception as exc:  # noqa: BLE001
            return self._err(str(exc), OperationKind.READ, "hooba_recover_web_session")

    @staticmethod
    def _fold(value: Any) -> str:
        """Normalize text for case- and accent-insensitive matching."""
        text = unicodedata.normalize("NFKD", str(value or ""))
        return "".join(char for char in text if not unicodedata.combining(char)).casefold()

    @staticmethod
    def _contact_name(contact: dict) -> str:
        """Return the best legal display name from a Hooba contact payload."""
        legal_name = contact.get("legalName") or contact.get("legal_name")
        if legal_name:
            return str(legal_name)
        trade_name = contact.get("tradeName") or contact.get("trade_name")
        if trade_name:
            return str(trade_name)
        parts = [contact.get(key) for key in ("firstName", "surname", "surnames", "lastName")]
        return " ".join(str(part) for part in parts if part)

    async def _find_contacts_raw(self, query: str, limit: int = 5) -> list[ContactMatch]:
        """Fuzzy-match contacts by legal/trade/personal name similarity (score >= 0.85).

        Shared by `hooba_find_contact` and the BBVA importer's `ContactFinder`.
        """
        contacts = await self._call("GET", "/accounts/{accountId}/contacts")
        if isinstance(contacts, dict):
            contacts = contacts.get("items", contacts.get("content", contacts.get("data", [])))
        matches: list[ContactMatch] = []
        folded_query = self._fold(query)
        for contact in list(contacts or [])[:500]:
            if not isinstance(contact, dict):
                continue
            candidates = [
                contact.get("legalName"),
                contact.get("tradeName"),
                " ".join(
                    str(contact.get(key))
                    for key in ("firstName", "surname", "surnames", "lastName")
                    if contact.get(key)
                ),
            ]
            score = max(
                (
                    difflib.SequenceMatcher(None, folded_query, self._fold(candidate)).ratio()
                    for candidate in candidates
                ),
                default=0.0,
            )
            if score >= 0.85:
                name = self._contact_name(contact)
                matches.append(
                    ContactMatch(
                        contact_id=int(contact.get("id", contact.get("contactId"))),
                        legal_name=name,
                        score=score,
                    )
                )
        matches.sort(key=lambda match: match.score, reverse=True)
        return matches[: max(0, limit)]

    async def hooba_find_contact(self, query: str, limit: int = 5) -> dict:
        """Find contacts by fuzzy legal, trade, or personal name similarity."""
        try:
            matches = await self._find_contacts_raw(query, limit)
            return self._ok([match.model_dump() for match in matches], OperationKind.READ)
        except Exception as exc:  # noqa: BLE001
            return self._err(str(exc), OperationKind.READ, "hooba_recover_web_session")

    async def hooba_list_drafts(
        self,
        kind: Literal["invoice", "purchase_invoice"],
        limit: int = 50,
    ) -> dict:
        """List the newest Hooba invoice or purchase-invoice drafts."""
        try:
            path = "/accounts/{accountId}/invoices" if kind == "invoice" else "/accounts/{accountId}/purchase-invoices"
            records = await self._call("GET", path)
            if isinstance(records, dict):
                records = records.get("items", records.get("content", records.get("data", [])))
            drafts = [
                record for record in (records or []) if isinstance(record, dict) and record.get("state") == "draft"
            ]
            drafts.sort(key=lambda record: str(record.get("date", record.get("createdAt", ""))), reverse=True)
            return self._ok(drafts[: max(0, limit)], OperationKind.READ)
        except Exception as exc:  # noqa: BLE001
            return self._err(str(exc), OperationKind.READ, "hooba_recover_web_session")

    async def hooba_download_invoice_pdf(self, invoice_id: int, dest_dir: Optional[str] = None) -> dict:
        """Download an invoice PDF into the state directory with owner-only permissions."""
        try:
            content = await self._call_raw("GET", f"/accounts/{{accountId}}/invoices/{invoice_id}:download")

            def resolve_and_write_pdf() -> Path:
                # Path.expanduser() can hit a pwd-database lookup, and mkdir/write_bytes/chmod
                # are real disk I/O — all of it belongs off the event loop (ASYNC240).
                directory = (
                    Path(dest_dir)
                    if dest_dir is not None
                    else Path(os.environ.get("PARROT_STATE_DIR", "~/.parrot_state")).expanduser() / "hooba" / "pdf"
                )
                path = directory.expanduser() / f"invoice-{invoice_id}.pdf"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                path.chmod(0o600)
                return path

            path = await asyncio.to_thread(resolve_and_write_pdf)
            return self._ok({"path": str(path), "size": len(content)}, OperationKind.READ)
        except Exception as exc:  # noqa: BLE001
            return self._err(str(exc), OperationKind.READ, "hooba_recover_web_session")

    async def hooba_recover_web_session(self) -> dict:
        """Recover a browser session and inject its sid cookie into the API jar."""
        adapter = self._web_adapter()
        if adapter is None:
            return self._err("HOOBA_CATALOG_DIR not set", OperationKind.READ)
        try:
            cookies = await adapter.recover_session()
            if not cookies or "sid" not in cookies:
                return self._err("web session recovery failed", OperationKind.READ)
            await self._api.set_cookies(cookies)
            return self._ok({"recovered": True, "cookie_names": sorted(cookies)}, OperationKind.READ)
        except Exception as exc:  # noqa: BLE001
            return self._err(str(exc), OperationKind.READ)

    async def hooba_run_web_action(self, action: str, params: Optional[dict] = None) -> dict:
        """Run a private-catalog navigation action without exposing write actions."""
        adapter = self._web_adapter()
        if adapter is None:
            return self._err("HOOBA_CATALOG_DIR not set", OperationKind.READ)
        try:
            return self._ok(await adapter.run_navigation(action, params), OperationKind.READ)
        except Exception as exc:  # noqa: BLE001
            return self._err(str(exc), OperationKind.READ)

    # -- id resolvers (never guess an id; unresolvable -> HoobaLookupError) --

    async def _resolve_tax(self, code: str, operation_type: Literal["sale", "purchase"]) -> Optional[int]:
        """Resolve a symbolic tax code (``IVA21``, ``EXENTO``) to a Hooba tax id.

        Args:
            code: ``IVA<percentage>`` or the sentinel ``EXENTO``.
            operation_type: ``"sale"`` for invoice lines, ``"purchase"`` for purchase-invoice lines.

        Returns:
            The resolved tax id, or ``None`` for ``EXENTO`` (no tax applies).
        """
        if code == "EXENTO":
            return None
        match = _TAX_CODE_RE.match(code)
        if match is None:
            raise HoobaLookupError(f"Unrecognized tax code: {code!r}")
        percentage = Decimal(match.group(1))
        taxes = await self._call("GET", "/taxes")
        for tax in taxes or []:
            if not isinstance(tax, dict) or tax.get("operationType") != operation_type:
                continue
            if Decimal(str(tax.get("percentage", -1))) == percentage:
                return int(tax["id"])
        raise HoobaLookupError(f"No tax found for code={code!r} operation_type={operation_type!r}")

    async def _resolve_income_tax(self, code: Optional[str]) -> Optional[int]:
        """Resolve a symbolic income-tax withholding code (``IRPF15``) to a Hooba id."""
        if code is None:
            return None
        match = _INCOME_TAX_CODE_RE.match(code)
        if match is None:
            raise HoobaLookupError(f"Unrecognized income tax code: {code!r}")
        percentage = Decimal(match.group(1))
        income_taxes = await self._call("GET", "/income-taxes")
        for item in income_taxes or []:
            if isinstance(item, dict) and Decimal(str(item.get("percentage", -1))) == percentage:
                return int(item["id"])
        raise HoobaLookupError(f"No income tax found for code={code!r}")

    async def _resolve_serie(self, code: Optional[str], simplified: bool) -> int:
        """Resolve an invoice serie code, or the account's default serie for `simplified`."""
        series = [
            serie
            for serie in (await self._call("GET", "/accounts/{accountId}/invoice-series") or [])
            if isinstance(serie, dict)
        ]
        if code:
            for serie in series:
                if serie.get("code") == code:
                    return int(serie["id"])
            raise HoobaLookupError(f"No invoice serie found for code={code!r}")
        default_field = "defaultForSimplified" if simplified else "default"
        for serie in series:
            if serie.get(default_field):
                return int(serie["id"])
        raise HoobaLookupError(f"No default invoice serie for simplified={simplified}")

    async def _resolve_contact(self, contact_id: Optional[int], contact_query: Optional[str]) -> Optional[int]:
        """Resolve a contact selector to an id; both unset (purchase invoices) stays unresolved."""
        if contact_id is not None:
            return int(contact_id)
        if contact_query is None:
            return None
        matches = await self._find_contacts_raw(contact_query, limit=1)
        if not matches:
            raise HoobaLookupError(f"No contact match for query={contact_query!r}")
        return matches[0].contact_id

    async def _resolve_document_type(self, entity: Literal["invoice", "purchase_invoice"]) -> int:
        """Resolve the Hooba document type id whose entity URN matches `entity`."""
        document_types = await self._call("GET", "/accounts/{accountId}/document-types")
        urn = _ENTITY_URN[entity]
        for item in document_types or []:
            if not isinstance(item, dict):
                continue
            entity_info = item.get("entity") or {}
            if entity_info.get("urn") == urn:
                document_type = item.get("documentType") or {}
                document_type_id = document_type.get("id")
                if document_type_id is not None:
                    return int(document_type_id)
        raise HoobaLookupError(f"No document type found for entity={entity!r}")

    # -- idempotency (S11): find a prior draft by its `[parrot:<key>]` notes marker --

    @staticmethod
    def _unwrap(record: Any, wrapper_key: Optional[str]) -> dict:
        """Unwrap a Hooba ``{wrapper_key: {...}}`` output envelope; pass a flat dict through."""
        if isinstance(record, dict) and wrapper_key and isinstance(record.get(wrapper_key), dict):
            return record[wrapper_key]
        return record if isinstance(record, dict) else {}

    async def _find_by_key(self, kind: Literal["invoice", "purchase_invoice"], key: str) -> Optional[dict]:
        """Find a draft header whose ``notes`` carry the ``[parrot:<key>]`` idempotency marker."""
        records = await self._call("GET", _LIST_PATH[kind])
        if isinstance(records, dict):
            records = records.get("items", records.get("content", records.get("data", [])))
        wrapper_key = "purchaseInvoice" if kind == "purchase_invoice" else None
        marker = f"[parrot:{key}]"
        for record in records or []:
            entity = self._unwrap(record, wrapper_key)
            if marker in str(entity.get("notes") or ""):
                return entity
        return None

    @staticmethod
    def _line_signature(name: Any, price: Any) -> tuple[str, str]:
        """Comparable ``(name, price)`` signature used for idempotent line matching."""
        return (str(name), str(Decimal(str(price))))

    @staticmethod
    def _lines_path(kind: Literal["invoice", "purchase_invoice"], entity_id: int) -> str:
        """Build the composite lines-collection path for an invoice or purchase-invoice."""
        entity_segment = "invoices" if kind == "invoice" else "purchase-invoices"
        line_segment = "invoice-lines" if kind == "invoice" else "purchase-invoice-lines"
        return f"/accounts/{{accountId}}/{entity_segment}/{entity_id}/{line_segment}"

    @staticmethod
    def _entity_path(kind: Literal["invoice", "purchase_invoice"], entity_id: int) -> str:
        """Build the composite path for a single invoice or purchase-invoice header."""
        entity_segment = "invoices" if kind == "invoice" else "purchase-invoices"
        return f"/accounts/{{accountId}}/{entity_segment}/{entity_id}"

    @staticmethod
    def _line_body(
        kind: Literal["invoice", "purchase_invoice"], line: Any, tax_id: Optional[int], income_tax_id: Optional[int]
    ) -> dict:
        """Build the ``oneOf`` Product line body (invoices) or the flat purchase-invoice-line body."""
        if kind == "invoice":
            return {
                "type": "product",
                "name": line.name,
                "price": float(line.price),
                "quantity": float(line.quantity),
                "discount": float(line.discount),
                "taxId": tax_id,
                "incomeTaxId": income_tax_id,
            }
        if line.accounting_account_code is not None:
            raise HoobaLookupError(
                f"accounting_account_code resolution is not supported: {line.accounting_account_code!r}"
            )
        return {
            "name": line.name,
            "price": float(line.price),
            "quantity": float(line.quantity),
            "taxId": tax_id,
            "incomeTaxId": income_tax_id,
            "accountingAccountId": None,
            "notes": line.notes or "",
        }

    async def _sync_lines_and_finalize(
        self,
        kind: Literal["invoice", "purchase_invoice"],
        entity_id: int,
        lines: Any,
        operation_type: Literal["sale", "purchase"],
        key: str,
        *,
        reused: bool,
    ) -> DraftReceipt:
        """Verify draft state FIRST (AC-7, S11), then post lines not already present (matched by name+price).

        The state check MUST happen before any line write: on the ``reused=True`` path the matched
        record may have been issued/confirmed by a human since a prior attempt, and writing a new
        line onto an already-finalized document is exactly the class of harm the DRAFT_OPERATIONS
        allowlist exists to prevent, reached via a different path than the generated write surface.
        """
        entity = await self._call("GET", self._entity_path(kind, entity_id))
        entity = entity if isinstance(entity, dict) else {}
        state = entity.get("state")
        if state != "draft":
            raise HoobaStateError(f"{kind} {entity_id} came back in state {state!r}, expected 'draft'")

        wrapper_key = _LINE_WRAPPER[kind]
        existing_raw = await self._call("GET", self._lines_path(kind, entity_id))
        existing = [self._unwrap(item, wrapper_key) for item in (existing_raw or [])]
        existing_signatures = {self._line_signature(item.get("name"), item.get("price", 0)) for item in existing}
        line_ids = [item["id"] for item in existing if item.get("id") is not None]

        for line in lines:
            signature = self._line_signature(line.name, line.price)
            if signature in existing_signatures:
                continue
            tax_id = await self._resolve_tax(line.tax_code, operation_type)
            income_tax_id = await self._resolve_income_tax(line.income_tax_code)
            body = self._line_body(kind, line, tax_id, income_tax_id)
            created = await self._call("POST", self._lines_path(kind, entity_id), data=body)
            created_entity = self._unwrap(created, wrapper_key)
            if created_entity.get("id") is not None:
                line_ids.append(created_entity["id"])
            existing_signatures.add(signature)

        return DraftReceipt(
            kind=kind,
            id=entity_id,
            state=state,
            number=entity.get("number"),
            line_ids=[int(line_id) for line_id in line_ids],
            correlation_key=key,
            reused=reused,
        )

    # -- draft creation (AC-7) --

    async def _create_invoice(self, draft: InvoiceDraft) -> DraftReceipt:
        """Idempotent sales-invoice draft creation (AC-7, S11)."""
        key = draft.correlation_key or uuid.uuid4().hex
        existing = await self._find_by_key("invoice", key)
        if existing is not None:
            return await self._sync_lines_and_finalize(
                "invoice", int(existing["id"]), draft.lines, "sale", key, reused=True
            )

        contact_id = await self._resolve_contact(draft.contact_id, draft.contact_query)
        serie_id = await self._resolve_serie(draft.invoice_serie_code, draft.simplified)
        header_body = {
            "invoiceSerieId": serie_id,
            "simplified": draft.simplified,
            "contactId": contact_id,
            "operationDate": draft.operation_date.isoformat() if draft.operation_date else None,
            "reference": draft.reference,
            "notes": f"{(draft.notes or '').strip()} [parrot:{key}]".strip(),
        }
        header = await self._call("POST", "/accounts/{accountId}/invoices", data=header_body)
        return await self._sync_lines_and_finalize("invoice", int(header["id"]), draft.lines, "sale", key, reused=False)

    async def hooba_create_invoice_draft(self, draft: InvoiceDraft) -> dict:
        """Create a sales invoice in DRAFT state (never issued).

        Args:
            draft: Contact, serie, lines (name, price, quantity, tax code). Exactly one of contact_id / contact_query.

        Returns:
            ToolResult dict whose result is a DraftReceipt (``reused`` True when a partial draft was completed).
        """
        try:
            draft = InvoiceDraft.model_validate(draft)
            receipt = await self._create_invoice(draft)
            return self._ok(receipt.model_dump(), OperationKind.DRAFT)
        except (HoobaLookupError, HoobaStateError) as exc:
            return self._err(str(exc), OperationKind.DRAFT)
        except Exception as exc:  # noqa: BLE001
            return self._err(str(exc), OperationKind.DRAFT, "hooba_recover_web_session")

    async def _create_purchase_invoice(self, draft: PurchaseInvoiceDraft) -> DraftReceipt:
        """Idempotent purchase-invoice draft creation; the BBVA importer's DraftCreator."""
        key = draft.correlation_key or uuid.uuid4().hex
        existing = await self._find_by_key("purchase_invoice", key)
        if existing is not None:
            return await self._sync_lines_and_finalize(
                "purchase_invoice", int(existing["id"]), draft.lines, "purchase", key, reused=True
            )

        contact_id = await self._resolve_contact(draft.contact_id, draft.contact_query)
        header_body = {
            "date": draft.date.isoformat(),
            "number": draft.number,
            "simplified": draft.simplified,
            "contactId": contact_id,
            "taxIncluded": draft.tax_included,
            "subjectToIncomeTax": draft.subject_to_income_tax,
            "notes": f"{(draft.notes or '').strip()} [parrot:{key}]".strip(),
        }
        header = await self._call("POST", "/accounts/{accountId}/purchase-invoices", data=header_body)
        return await self._sync_lines_and_finalize(
            "purchase_invoice", int(header["id"]), draft.lines, "purchase", key, reused=False
        )

    async def hooba_create_purchase_invoice_draft(self, draft: PurchaseInvoiceDraft) -> dict:
        """Declare an expense / purchase as a purchase-invoice DRAFT (never confirmed)."""
        try:
            draft = PurchaseInvoiceDraft.model_validate(draft)
            receipt = await self._create_purchase_invoice(draft)
            return self._ok(receipt.model_dump(), OperationKind.DRAFT)
        except (HoobaLookupError, HoobaStateError) as exc:
            return self._err(str(exc), OperationKind.DRAFT)
        except Exception as exc:  # noqa: BLE001
            return self._err(str(exc), OperationKind.DRAFT, "hooba_recover_web_session")

    async def hooba_attach_document(
        self, entity: Literal["invoice", "purchase_invoice"], entity_id: int, file_path: str
    ) -> dict:
        """Attach a file (receipt, ticket PDF) to an invoice or purchase invoice.

        Args:
            entity: Which draft kind the file attaches to.
            entity_id: The invoice or purchase-invoice id.
            file_path: Local path of the file to upload.

        Returns:
            ToolResult dict whose result is the created Hooba document.
        """
        try:
            document_type_id = await self._resolve_document_type(entity)
            path = Path(file_path)
            content = await asyncio.to_thread(path.read_bytes)
            url = self._url(f"/accounts/{{accountId}}/documents/{document_type_id}/{entity_id}")

            async def _upload() -> tuple[int, Any]:
                form = aiohttp.FormData()
                form.add_field("file", content, filename=path.name)
                form.add_field("data", json.dumps({}))
                cookie_header = "; ".join(f"{name}={value}" for name, value in self._api.get_cookies().items())
                headers = {**self.settings.default_headers(), "cookie": cookie_header}
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, data=form, headers=headers) as response:
                        return response.status, await response.json(content_type=None)

            status, payload = await _upload()
            if status == 401:
                await self._api._ensure_session(force=True)
                status, payload = await _upload()
            if status >= 400:
                raise RuntimeError(f"Hooba document upload failed: HTTP {status}")
            return self._ok(payload, OperationKind.DRAFT)
        except Exception as exc:  # noqa: BLE001
            return self._err(str(exc), OperationKind.DRAFT, "hooba_recover_web_session")

    async def hooba_import_bbva_statement(self, path: str, period: str, dry_run: bool = True) -> dict:
        """Turn a BBVA movements Excel into purchase-invoice drafts (dry run by default).

        Args:
            path: Local path of the BBVA .xlsx export.
            period: Accounting period label, e.g. "2026-09".
            dry_run: When True, plan only — nothing is sent to Hooba.

        Returns:
            ToolResult dict whose result is an ExpenseDraftBatch.
        """
        try:
            statement = await parse_bbva_statement(path)
            engine = RuleEngine.load(self._rules_path)
            importer = BbvaImporter(engine, self._find_contacts_raw, self._create_purchase_invoice)
            planned, manifest, skipped = await importer.plan(statement, period=period)

            created: list[DraftReceipt] = []
            if not dry_run:
                created = await importer.apply(planned, manifest)

            summary = reconcile(manifest, len(planned))
            batch = ExpenseDraftBatch(
                statement_digest=statement.digest,
                period=period,
                dry_run=dry_run,
                planned=len(planned),
                created=created,
                skipped=skipped,
                reconciled=bool(summary["reconciled"]),
                manifest_path=str(manifest_path_for(statement.digest)),
            )
            return self._ok(batch.model_dump(), OperationKind.DRAFT)
        except Exception as exc:  # noqa: BLE001
            return self._err(str(exc), OperationKind.DRAFT, "hooba_recover_web_session")
