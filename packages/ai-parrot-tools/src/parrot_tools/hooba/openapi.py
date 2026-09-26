"""Generated Hooba API tools: cookie-authenticated, account-scoped, drafts only (FEAT-602 M4)."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Sequence

from parrot.tools.openapitoolkit import OpenAPIToolkit
from parrot.tools.toolkit import ToolkitTool
from parrot_tools.business_automation.models import OperationKind

from .credentials import HoobaLoginHook
from .settings import HoobaSettings
from .spec import load_pinned_spec

DEFAULT_INCLUDE_TAGS: tuple[str, ...] = (
    "Invoice",
    "InvoiceLine",
    "InvoiceSerie",
    "PurchaseInvoice",
    "PurchaseInvoiceLine",
    "Contact",
    "Tax",
    "IncomeTax",
    "AccountingAccount",
    "PaymentMethod",
    "PaymentTerm",
    "Currency",
    "Document",
    "DocumentType",
    "InboxFile",
    "UnitOfMeasure",
)
READ_PATH_BLOCKLIST: tuple[str, ...] = (r":download", r":export", r":pdf-", r"/avatar$")
DRAFT_OPERATIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/accounts/{accountId}/invoices"),
        ("PATCH", "/accounts/{accountId}/invoices/{invoiceId}"),
        ("POST", "/accounts/{accountId}/invoices/{invoiceId}/invoice-lines"),
        ("PATCH", "/accounts/{accountId}/invoices/{invoiceId}/invoice-lines/{invoiceLineId}"),
        ("POST", "/accounts/{accountId}/invoices/{invoiceId}/invoice-lines:sort"),
        ("POST", "/accounts/{accountId}/purchase-invoices"),
        ("PATCH", "/accounts/{accountId}/purchase-invoices/{purchaseInvoiceId}"),
        ("POST", "/accounts/{accountId}/purchase-invoices/{purchaseInvoiceId}/purchase-invoice-lines"),
        (
            "PATCH",
            "/accounts/{accountId}/purchase-invoices/{purchaseInvoiceId}/purchase-invoice-lines/"
            "{purchaseInvoiceLineId}",
        ),
        ("POST", "/accounts/{accountId}/purchase-invoices/{purchaseInvoiceId}/purchase-invoice-lines:sort"),
        ("POST", "/accounts/{accountId}/purchase-invoices:create-from-inbox-file"),
    }
)
LEGAL_EFFECT_PATTERNS: tuple[str, ...] = (
    r":issue$",
    r":confirm$",
    r":cancel$",
    r":send",
    r":delete$",
    r":bulk-",
    r":schedule$",
    r":unschedule$",
    r":create-corrective$",
    r":collect$",
)
MAX_TOOLS = 80
_READ_BLOCK = [re.compile(pattern) for pattern in READ_PATH_BLOCKLIST]


def is_allowed(method: str, path: str) -> bool:
    """Return whether a raw OpenAPI operation belongs to Hooba's draft-safe surface."""
    normalized_method = method.upper()
    if normalized_method in {"GET", "HEAD"}:
        return not any(pattern.search(path) for pattern in _READ_BLOCK)
    return (normalized_method, path) in DRAFT_OPERATIONS


def classify_operation(method: str, path: str) -> OperationKind:
    """Classify an operation as READ, DRAFT, or default-deny SUBMIT."""
    normalized_method = method.upper()
    if normalized_method in {"GET", "HEAD"}:
        return OperationKind.READ
    if (normalized_method, path) in DRAFT_OPERATIONS:
        return OperationKind.DRAFT
    return OperationKind.SUBMIT


class HoobaOpenAPIToolkit(OpenAPIToolkit):
    """Generated Hooba API tools, cookie-authenticated, account-scoped, drafts only."""

    def __init__(
        self,
        settings: HoobaSettings,
        login_hook: HoobaLoginHook,
        *,
        spec: Optional[Dict[str, Any]] = None,
        include_tags: Optional[Sequence[str]] = None,
        max_tools: int = MAX_TOOLS,
        **kwargs: Any,
    ) -> None:
        self.settings = settings
        super().__init__(
            spec=spec or load_pinned_spec(settings.spec_path),
            service="hooba",
            base_url=settings.base_url,
            auth_type="cookie",
            login_hook=login_hook,
            extra_headers=settings.default_headers(),
            path_defaults={"accountId": settings.account_id},
            include_tags=include_tags or settings.include_tags or DEFAULT_INCLUDE_TAGS,
            exclude_methods=("DELETE", "PUT"),
            exclude_paths=READ_PATH_BLOCKLIST,
            operation_filter=is_allowed,
            max_tools=max_tools,
            **kwargs,
        )

    def _create_tool_from_method(self, name: str, bound_method: Any) -> ToolkitTool:
        """Stamp generated tools with their operation kind and submit confirmation requirement."""
        tool = super()._create_tool_from_method(name, bound_method)
        operation = getattr(bound_method, "_operation", None)
        if operation is not None:
            kind = classify_operation(operation["method"], operation["path"])
            tool.routing_meta["operation_kind"] = kind.value
            if kind is OperationKind.SUBMIT:
                tool.routing_meta["requires_confirmation"] = True
        return tool

    def operation_kinds(self) -> Dict[str, OperationKind]:
        """Map every generated operation method name to its OperationKind."""
        return {
            self._create_method_name(operation): classify_operation(operation["method"], operation["path"])
            for operation in self.operations
        }
