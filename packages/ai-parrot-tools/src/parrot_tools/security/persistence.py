"""ReportPersistenceMixin — catalog write-side mixin for producer toolkits.

Scanner toolkits (CloudSploit, ComplianceReport, ContainerSecurity) compose
this mixin to gain automatic report cataloging without coupling to the store
internals.

Construction protocol
---------------------
Producer toolkits that inherit from both this mixin and ``AbstractToolkit``
MUST pop ``file_manager`` and ``report_store`` from ``**kwargs`` before
calling ``super().__init__(**kwargs)``, otherwise ``AbstractToolkit``
receives unknown keyword arguments.

Example::

    class MyToolkit(ReportPersistenceMixin, AbstractToolkit):
        def __init__(self, *, config, **kwargs):
            self.file_manager, self.report_store = pop_persistence_kwargs(kwargs)
            super().__init__(**kwargs)
            self.config = config
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from parrot.interfaces.file import FileManagerInterface
from parrot.storage.security_reports import (
    EmbeddedFinding,
    ReportKind,
    ReportRef,
    SecurityReportStore,
    SeverityBreakdown,
)
from parrot_tools.security.parsers import get_report_parser


def pop_persistence_kwargs(
    kwargs: dict[str, Any],
) -> tuple[FileManagerInterface | None, SecurityReportStore | None]:
    """Pop ``file_manager`` and ``report_store`` from a toolkit's ``**kwargs``.

    Call this BEFORE ``super().__init__(**kwargs)`` in producer toolkit
    constructors to prevent unknown-kwarg errors in ``AbstractToolkit``.

    Args:
        kwargs: The ``**kwargs`` dict from the toolkit constructor.  Modified
            in place — both keys are removed if present.

    Returns:
        A ``(file_manager, report_store)`` tuple; either may be ``None`` if
        not present in ``kwargs``.
    """
    fm = kwargs.pop("file_manager", None)
    store = kwargs.pop("report_store", None)
    return fm, store


class ReportPersistenceMixin:
    """Mixin that gives producer toolkits catalog write capability.

    When ``file_manager`` AND ``report_store`` are both non-``None``,
    ``_persist_report`` uploads content to S3 and indexes metadata in
    Postgres via the store. When either dependency is ``None``, the method
    is a **no-op** (returns ``None`` silently) — existing callers that do
    not inject persistence deps continue working unchanged.

    Class attributes (set per-instance in the constructor):
        file_manager: Active ``FileManagerInterface`` or ``None``.
        report_store: Active ``SecurityReportStore`` or ``None``.
        parser_version: Version string forwarded to ``ReportRef.parser_version``.
    """

    file_manager: FileManagerInterface | None = None
    report_store: SecurityReportStore | None = None
    parser_version: str = "1.0.0"

    async def _persist_report(
        self,
        *,
        scanner: str,
        framework: str | None,
        provider: str,
        scope: dict,
        content: bytes | Path,
        content_type: str = "application/json",
        report_kind: ReportKind = ReportKind.SCAN,
        produced_by: str | None = None,
        severity_summary: SeverityBreakdown | None = None,
        top_findings: list[EmbeddedFinding] | None = None,
    ) -> ReportRef | None:
        """Persist a scanner report to the catalog.

        1. No-op if ``file_manager`` or ``report_store`` is ``None``.
        2. If ``severity_summary`` or ``top_findings`` is ``None``, the
           registered parser for ``scanner`` is called to derive the missing
           values from ``content``.
        3. Builds a ``ReportRef`` and delegates to
           ``report_store.save_report(ref, content)``.

        Args:
            scanner: Scanner name (``"trivy"``, ``"cloudsploit"``, etc.).
            framework: Compliance framework or ``None`` (e.g. ``"HIPAA"``).
            provider: Cloud / infrastructure provider (e.g. ``"aws"``).
            scope: Arbitrary scope dict stored verbatim in the catalog
                (e.g. ``{"account_id": "123", "region": "us-east-1"}``).
            content: Raw scanner JSON as bytes or a ``Path`` to the file.
            content_type: MIME type for the content blob.
            report_kind: One of ``ReportKind.SCAN``, ``WEEKLY_SUMMARY``, etc.
            produced_by: Free-form provenance string. Defaults to
                ``"toolkit:<ClassName>"``.
            severity_summary: Pre-computed breakdown; if ``None`` the parser
                derives it from ``content``.
            top_findings: Pre-selected top findings; if ``None`` the parser
                provides them (capped at 10).

        Returns:
            Persisted ``ReportRef`` with ``uri`` populated, or ``None`` when
            persistence deps are not configured.
        """
        if self.file_manager is None or self.report_store is None:
            return None

        if severity_summary is None or top_findings is None:
            parser = get_report_parser(scanner)
            parsed = parser.parse(content)
            if severity_summary is None:
                severity_summary = parsed.severity_summary
            if top_findings is None:
                top_findings = parsed.top_findings[:10]

        ref = ReportRef(
            report_kind=report_kind,
            scanner=scanner,
            framework=framework,
            provider=provider,
            scope=scope,
            severity_summary=severity_summary,
            top_findings=top_findings[:10],
            uri="",  # store populates this
            content_type=content_type,
            produced_at=datetime.now(timezone.utc),
            produced_by=produced_by or f"toolkit:{type(self).__name__}",
            parser_version=self.parser_version,
        )
        return await self.report_store.save_report(ref, content)

    async def _mirror_rendered_report(
        self,
        *,
        local_path: str | Path,
        scanner: str,
        framework: str | None,
        timestamp: datetime,
        extension: str,
    ) -> str | None:
        """Best-effort S3 mirror for a rendered (HTML/PDF) report.

        Renders are derived presentations of the canonical scan JSON; this
        helper drops them in the same S3 prefix used by the catalog so an
        operator browsing the bucket sees JSON + HTML/PDF side-by-side for
        each scan. The render itself is NOT inserted into the Postgres
        catalog — it has no parseable severity summary on its own.

        Args:
            local_path: Path to the rendered file on the host.
            scanner: Scanner identifier (``"cloudsploit"``, ``"compliance"``,
                ``"trivy"``).
            framework: Compliance framework, or ``None`` for unrestricted.
            timestamp: Timestamp to derive the S3 prefix and filename from
                (use ``scan_timestamp`` or ``generated_at`` from the result).
            extension: File extension without leading dot (``"html"``, ``"pdf"``).

        Returns:
            The S3 key when the upload succeeded, or ``None`` when no
            ``file_manager`` is wired or the upload failed. Never raises —
            this path is best-effort and must not block scan completion.
        """
        if self.file_manager is None:
            return None
        fw = framework or "none"
        date_prefix = timestamp.strftime("%Y/%m/%d")
        ts = timestamp.strftime("%Y%m%d_%H%M%S")
        s3_key = (
            f"security-reports/{scanner}/{fw}/{date_prefix}/"
            f"report_{ts}.{extension}"
        )
        log = getattr(self, "logger", None) or logging.getLogger(__name__)
        try:
            await self.file_manager.upload_file(Path(local_path), s3_key)
            log.info("Uploaded %s report to s3://.../%s", extension, s3_key)
            return s3_key
        except Exception as exc:  # pragma: no cover — best-effort mirror
            log.warning(
                "Failed to upload %s report to S3: %s", extension, exc,
            )
            return None
