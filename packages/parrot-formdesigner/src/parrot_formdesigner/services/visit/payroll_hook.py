"""PayrollHook interface and NullPayrollHook no-op implementation (FEAT-303).

Decision (spec §8): the concrete Workday / claims implementation lives in
``ai-parrot`` (FEAT-026/027) and the staging path is documented in FEAT-321.
This package only defines:

- ``PayrollHook`` — abstract base class with ``on_checkout()``.
- ``NullPayrollHook`` — no-op implementation used in tests and as the
  default when no concrete hook is registered.

Registration pattern (spec §8): callers register their concrete hook via
``services/callback_registry.py`` under the name ``"payroll_hook"``::

    from parrot_formdesigner.services.callback_registry import register_form_callback
    from parrot_formdesigner.services.visit import NullPayrollHook

    hook = NullPayrollHook()

    @register_form_callback("payroll_hook")
    async def _on_checkout(visit, *, hours, tenant):
        await hook.on_checkout(visit, hours=hours, tenant=tenant)

``VisitService.checkout()`` resolves the hook via ``_CALLBACK_REGISTRY``
at checkout time — it does **not** accept the hook as a constructor argument.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Visit


class PayrollHook(ABC):
    """Abstract interface for payroll / claims notification on checkout.

    Called by ``VisitService.checkout()`` after a GPS-validated checkout.
    Implementations MUST NOT write directly to ``troc.worked_hours`` —
    the downstream write-path goes through the staging table
    (``time_capture_staging`` → consolidation → ``worked_hours`` →
    attestation → approval → Workday sync — see FEAT-321).

    All methods are async.
    """

    @abstractmethod
    async def on_checkout(
        self,
        visit: "Visit",
        *,
        hours: float,
        tenant: str,
    ) -> None:
        """Called after a successful GPS-validated checkout.

        Args:
            visit: The completed ``Visit`` record (with ``submission_id`` set).
            hours: GPS-validated worked hours (check_in → check_out delta).
            tenant: The tenant slug for this visit.
        """
        ...


class NullPayrollHook(PayrollHook):
    """No-op PayrollHook implementation.

    Used in unit tests and as the default when no concrete hook is
    registered.  Logs the call at DEBUG level and returns immediately.
    """

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)

    async def on_checkout(
        self,
        visit: "Visit",
        *,
        hours: float,
        tenant: str,
    ) -> None:
        """No-op: log the call and return immediately.

        Args:
            visit: The completed ``Visit`` record.
            hours: GPS-validated worked hours.
            tenant: The tenant slug.
        """
        self.logger.debug(
            "NullPayrollHook.on_checkout: visit=%s, hours=%.4f, tenant=%r (no-op)",
            visit.visit_id,
            hours,
            tenant,
        )
