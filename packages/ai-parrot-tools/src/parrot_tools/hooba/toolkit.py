"""HoobaToolkit — drafts-only Hooba automation for AI-Parrot agents (FEAT-602 M6)."""

from __future__ import annotations

import asyncio
import difflib
import os
import unicodedata
from pathlib import Path
from typing import Any, Dict, Literal, Optional

from parrot.auth.broker import CredentialBroker
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.tools.toolkit import AbstractToolkit
from parrot_tools.business_automation.models import OperationKind
from parrot_tools.business_automation.toolkit import _credential_resolver_from_broker

from .credentials import make_login_hook, register_hooba_provider
from .models import ContactMatch
from .openapi import HoobaOpenAPIToolkit
from .settings import HoobaSettings
from .web import HoobaWebAdapter

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

        Only the tools this task actually generates (`_READ_TOOLS` plus the
        bound API toolkit's own tools). `_DRAFT_TOOLS` names TASK-3743's
        not-yet-implemented composite tools and is intentionally excluded
        here -- TASK-3743 extends this method when it adds those methods.
        """
        kinds = dict.fromkeys(_READ_TOOLS, OperationKind.READ)
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

    async def hooba_find_contact(self, query: str, limit: int = 5) -> dict:
        """Find contacts by fuzzy legal, trade, or personal name similarity."""
        try:
            contacts = await self._call("GET", "/accounts/{accountId}/contacts")
            if isinstance(contacts, dict):
                contacts = contacts.get("items", contacts.get("content", contacts.get("data", [])))
            matches = []
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
            return self._ok([match.model_dump() for match in matches[: max(0, limit)]], OperationKind.READ)
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
            directory = (
                Path(dest_dir)
                if dest_dir is not None
                else Path(os.environ.get("PARROT_STATE_DIR", "~/.parrot_state")).expanduser() / "hooba" / "pdf"
            )
            path = directory.expanduser() / f"invoice-{invoice_id}.pdf"

            def write_pdf() -> None:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                path.chmod(0o600)

            await asyncio.to_thread(write_pdf)
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
