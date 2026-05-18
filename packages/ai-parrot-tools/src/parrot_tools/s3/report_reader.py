"""S3ReportReaderToolkit — LLM-facing agnostic S3 report reader.

Exposes 8 agent tools (``s3_`` prefix) for reading, filtering, comparing,
and summarizing S3-stored reports.  Operates in dual mode:

- With ``SecurityReportStore``: catalog-backed queries for indexed reports.
- Without ``SecurityReportStore``: raw S3 browsing via ``FileManagerInterface``
  only (catalog-dependent tools return an informative error dict).

Module implements Spec §3 Module 1 (FEAT-184).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from io import BytesIO
from uuid import UUID

from parrot.interfaces.file import FileManagerInterface, FileMetadata
from parrot.storage.security_reports import (
    ReportFilter,
    ReportKind,
    ReportRef,
    SecurityReportStore,
)
from parrot_tools.security.parsers import get_report_parser

from ..toolkit import AbstractToolkit
from .comparator import GenericReportComparator


class S3ReportReaderToolkit(AbstractToolkit):
    """Agnostic read-only toolkit for LLM agents to explore S3-stored reports.

    Mounts 8 tools with the ``s3_`` prefix, preventing collision when
    co-mounted with ``SecurityReportToolkit``.

    Works in two modes:

    - **Full mode** (``report_store`` provided): catalog-backed queries
      available in addition to raw S3 browsing.
    - **File-only mode** (no ``report_store``): only ``s3_list_reports``,
      ``s3_get_report_content``, ``s3_compare_reports``,
      ``s3_summarize_report``, and ``s3_get_report_url`` work.
      Catalog-dependent tools return ``{"error": "...", "hint": "..."}``.

    Args:
        file_manager: Required. Provides raw S3 operations (list, download,
            URL generation).
        report_store: Optional. Provides catalog-backed queries.
        default_prefix: S3 key prefix used when ``prefix`` is omitted from
            ``list_reports``. Defaults to ``"security-reports/"``.
        max_diff_changes: Cap on the ``changes`` list returned by
            ``compare_reports``. Defaults to 50.
        **kwargs: Forwarded to ``AbstractToolkit.__init__``.
    """

    tool_prefix: str = "s3"
    DEFAULT_VISIBILITY_DAYS: int = 30

    def __init__(
        self,
        file_manager: FileManagerInterface,
        report_store: SecurityReportStore | None = None,
        *,
        default_prefix: str = "security-reports/",
        max_diff_changes: int = 50,
        **kwargs,
    ) -> None:
        """Initialize S3ReportReaderToolkit.

        Args:
            file_manager: Required FileManagerInterface for raw S3 access.
            report_store: Optional SecurityReportStore for catalog queries.
            default_prefix: Default S3 prefix for ``list_reports``.
            max_diff_changes: Max changes to include in comparison results.
            **kwargs: Forwarded to AbstractToolkit.
        """
        super().__init__(**kwargs)
        self._fm = file_manager
        self._store = report_store
        self._default_prefix = default_prefix
        self._comparator = GenericReportComparator(max_changes=max_diff_changes)
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Public async methods — auto-discovered as agent tools (s3_ prefix)
    # ------------------------------------------------------------------

    async def list_reports(
        self,
        prefix: str = "",
        pattern: str = "*.json",
        limit: int = 50,
    ) -> list[dict]:
        """List S3 objects under the given prefix. Works without catalog.

        Browses raw S3 objects without using the catalog.  Useful for
        discovering reports that may not be indexed.

        Args:
            prefix: S3 key prefix to list under. Defaults to the toolkit's
                ``default_prefix`` (``"security-reports/"``).
            pattern: Glob pattern to filter results (e.g., ``"*.json"``).
                Defaults to ``"*.json"``.
            limit: Maximum number of results to return. Defaults to 50.

        Returns:
            List of file metadata dicts with keys: ``name``, ``path``,
            ``size``, ``content_type``, ``modified_at``.
        """
        effective_prefix = prefix or self._default_prefix
        files: list[FileMetadata] = await self._fm.list_files(effective_prefix, pattern)
        return [self._serialize_metadata(m) for m in files[:limit]]

    async def get_latest_report(
        self,
        scanner: str | None = None,
        framework: str | None = None,
        report_kind: str = "scan",
    ) -> dict:
        """Requires catalog. Return the most recent report matching the filters.

        Returns the latest ``ReportRef`` metadata from the catalog for the
        given scanner/framework/kind combination.

        Args:
            scanner: Scanner name (e.g., ``"cloudsploit"``, ``"trivy"``).
                ``None`` matches any scanner.
            framework: Compliance framework (e.g., ``"HIPAA"``).
                ``None`` matches any framework.
            report_kind: Report kind — one of ``"scan"``,
                ``"daily_summary"``, ``"weekly_summary"``,
                ``"monthly_summary"``, ``"drift_comparison"``.
                Defaults to ``"scan"``.

        Returns:
            Report metadata dict, or ``{"error": "..."}`` if no catalog
            is configured or no match is found.
        """
        err = self._require_catalog("get_latest_report")
        if err is not None:
            return err

        try:
            kind = ReportKind(report_kind)
        except ValueError:
            kind = ReportKind.SCAN

        refs = await self._store.query(  # type: ignore[union-attr]
            ReportFilter(
                scanner=scanner,
                framework=framework,
                report_kind=kind,
                limit=1,
                order_by="produced_at_desc",
            )
        )
        if not refs:
            return {
                "error": "No report found",
                "hint": "Adjust scanner/framework/report_kind filters or try list_reports.",
            }
        return refs[0].model_dump(mode="json")

    async def get_report_content(
        self,
        report_id_or_path: str,
        section: str = "full",
    ) -> dict:
        """Works without catalog (S3 path) or with catalog (UUID).

        Fetch and return report content.  Accepts either a catalog UUID
        or a raw S3 key path.

        - **UUID** (``"3fa85f64-5717-4562-b3fc-2c963f66afa6"``): fetches
          content via catalog + applies parser for section extraction.
        - **S3 path** (``"security-reports/cloudsploit/scan.json"``):
          downloads via FileManagerInterface.  Scanner is inferred from
          the path convention ``{prefix}{scanner}/{framework}/...``.

        For ``section="full"``, the entire parsed JSON is returned.  For
        other sections, the registered parser's ``extract_section`` is
        called when a scanner is known.  HTML content is always returned
        as-is (no JSON parsing).

        Args:
            report_id_or_path: Catalog UUID string or S3 key path.
            section: Section to extract.  ``"full"`` returns all content.
                Other values (``"summary"``, ``"critical"``, etc.) use
                the scanner's parser. Defaults to ``"full"``.

        Returns:
            Content dict.  Returns ``{"error": "..."}`` if UUID not found.
        """
        try:
            content, scanner, ref = await self._fetch_content(report_id_or_path)
        except Exception as exc:  # noqa: BLE001 — surface fetch errors as structured error dict
            self.logger.warning("get_report_content fetch failed: %s", exc)
            return {"error": str(exc), "hint": "Verify the report path or UUID exists."}

        # HTML content returned as-is
        content_type = ref.content_type if ref else None
        if content_type and "html" in content_type:
            return {
                "content_type": content_type,
                "content": content.decode("utf-8", errors="replace"),
            }

        if section == "full":
            try:
                parsed = json.loads(content)
                return {"content_type": "application/json", "data": parsed}
            except (json.JSONDecodeError, ValueError):
                return {
                    "content_type": "text/plain",
                    "content": content.decode("utf-8", errors="replace"),
                }

        # Section extraction via parser
        if scanner:
            try:
                parser = get_report_parser(scanner)
                return parser.extract_section(content, section)
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(
                    "Parser section extraction failed for scanner %r section %r: %s",
                    scanner,
                    section,
                    exc,
                )

        # Fall back to full content
        try:
            parsed = json.loads(content)
            return {"content_type": "application/json", "data": parsed, "section": "full"}
        except (json.JSONDecodeError, ValueError):
            return {
                "content_type": "text/plain",
                "content": content.decode("utf-8", errors="replace"),
            }

    async def filter_reports(
        self,
        scanner: str | None = None,
        framework: str | None = None,
        provider: str | None = None,
        report_kind: str | None = None,
        since_days: int = 30,
        limit: int = 20,
    ) -> list[dict]:
        """Requires catalog. Query the catalog with multiple filters.

        Returns a list of report metadata records matching all specified
        criteria, ordered by ``produced_at`` descending.

        Args:
            scanner: Filter by scanner name. ``None`` matches all.
            framework: Filter by compliance framework. ``None`` matches all.
            provider: Filter by cloud provider (e.g., ``"aws"``).
                ``None`` matches all.
            report_kind: Report kind filter.  ``None`` matches all kinds.
            since_days: Look back at most this many days. Defaults to 30.
            limit: Maximum results to return (1–500). Defaults to 20.

        Returns:
            List of ``ReportRef`` metadata dicts, or
            ``[{"error": "..."}]`` when no catalog is configured.
        """
        err = self._require_catalog("filter_reports")
        if err is not None:
            return [err]

        since = datetime.now(timezone.utc) - timedelta(days=since_days)
        kind: ReportKind | None = None
        if report_kind is not None:
            try:
                kind = ReportKind(report_kind)
            except ValueError:
                kind = None

        refs = await self._store.query(  # type: ignore[union-attr]
            ReportFilter(
                scanner=scanner,
                framework=framework,
                provider=provider,
                report_kind=kind,
                since=since,
                limit=limit,
                order_by="produced_at_desc",
            )
        )
        return [r.model_dump(mode="json") for r in refs]

    async def compare_reports(
        self,
        report_a: str,
        report_b: str,
    ) -> dict:
        """Works without catalog (S3 paths) or with catalog (UUIDs).

        Diff two report documents and return a structured comparison.

        Both arguments can be catalog UUIDs or S3 key paths.  Attempts
        scanner-aware comparison (e.g., CloudSploit domain diff) when the
        scanner is known; falls back to generic structural JSON diff.

        Args:
            report_a: UUID or S3 path of the baseline (earlier) report.
            report_b: UUID or S3 path of the current (later) report.

        Returns:
            Structured diff dict from ``GenericReportComparator.compare``.
        """
        try:
            content_a, scanner_a, _ = await self._fetch_content(report_a)
            content_b, scanner_b, _ = await self._fetch_content(report_b)
        except Exception as exc:  # noqa: BLE001 — surface fetch errors as structured error dict
            self.logger.warning("compare_reports fetch failed: %s", exc)
            return {"error": str(exc), "hint": "Verify both report paths or UUIDs exist."}
        # Prefer scanner from report_a; fall back to report_b
        scanner = scanner_a or scanner_b
        return self._comparator.compare(content_a, content_b, scanner=scanner)

    async def summarize_report(
        self, report_id_or_path: str,
    ) -> dict:
        """Works without catalog (S3 paths) or with catalog (UUIDs).

        Extract structured metrics from a report — no LLM call.

        Returns severity breakdown, top findings (from catalog when
        available), content type, scanner, framework, and detected
        categories.  The calling agent's LLM should generate narrative
        from this structured output.

        Args:
            report_id_or_path: Catalog UUID string or S3 key path.

        Returns:
            Structured metrics dict.
        """
        try:
            content, scanner, ref = await self._fetch_content(report_id_or_path)
        except Exception as exc:  # noqa: BLE001 — surface fetch errors as structured error dict
            self.logger.warning("summarize_report fetch failed: %s", exc)
            return {"error": str(exc), "hint": "Verify the report path or UUID exists."}

        # Catalog-backed summary
        if ref is not None:
            return {
                "report_id": str(ref.report_id),
                "scanner": ref.scanner,
                "framework": ref.framework,
                "provider": ref.provider,
                "content_type": ref.content_type,
                "produced_at": ref.produced_at.isoformat(),
                "severity_breakdown": ref.severity_summary.model_dump(),
                "top_findings": [f.model_dump() for f in ref.top_findings],
                "report_kind": ref.report_kind.value,
            }

        # Raw S3 summary — parse JSON and extract structural metrics
        content_type = "application/json"
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            return {
                "content_type": "text/html" if b"<html" in content[:200] else "text/plain",
                "size_bytes": len(content),
                "scanner": scanner,
                "framework": None,
            }

        metrics = self._extract_json_metrics(data)

        return {
            "content_type": content_type,
            "size_bytes": len(content),
            "scanner": scanner,
            "framework": None,
            "severity_breakdown": metrics["severity_breakdown"],
            "total_findings": metrics["total_findings"],
            "categories": metrics["categories"],
        }

    async def get_report_url(
        self, report_id_or_path: str, expiry: int = 3600,
    ) -> dict:
        """Works without catalog. Generate a pre-signed URL for a report.

        Resolves the S3 URI (from catalog if UUID is given, or directly
        from the path) and generates a pre-signed URL.

        Args:
            report_id_or_path: Catalog UUID string or S3 key path.
            expiry: URL expiry time in seconds. Defaults to 3600 (1 hour).

        Returns:
            Dict with ``url``, ``path``, and ``expiry_seconds``.
        """
        path: str
        try:
            uid = UUID(report_id_or_path)
            if self._store is not None:
                ref = await self._store.get(uid)
                if ref is not None:
                    path = ref.uri
                else:
                    return {"error": f"Report {report_id_or_path} not found in catalog"}
            else:
                # No catalog — treat as path
                path = report_id_or_path
        except ValueError:
            path = report_id_or_path

        try:
            url = await self._fm.get_file_url(path, expiry)
        except Exception as exc:  # noqa: BLE001 — surface URL generation errors as structured error dict
            self.logger.warning("get_report_url failed for path %r: %s", path, exc)
            return {"error": str(exc), "hint": "Verify the report path exists and file manager is configured."}
        return {"url": url, "path": path, "expiry_seconds": expiry}

    async def list_report_categories(self) -> dict:
        """Requires catalog. List distinct scanners, frameworks, and report kinds.

        Returns the distinct values present in the catalog for each
        categorical dimension.  Useful for discovering what data is
        available before using ``filter_reports``.

        For scanners: deduplicates via a broad query (limit 500) in Python,
        since the store only provides ``query_distinct_frameworks``.

        Returns:
            Dict with ``scanners``, ``frameworks``, and ``report_kinds``,
            or ``{"error": "..."}`` when no catalog is configured.
        """
        err = self._require_catalog("list_report_categories")
        if err is not None:
            return err

        frameworks = await self._store.query_distinct_frameworks()  # type: ignore[union-attr]

        # Deduplicate scanners in Python (no distinct query exists)
        refs = await self._store.query(  # type: ignore[union-attr]
            ReportFilter(limit=500, order_by="produced_at_desc")
        )
        scanners = sorted({r.scanner for r in refs})
        report_kinds = sorted({r.report_kind.value for r in refs})

        return {
            "scanners": scanners,
            "frameworks": sorted(frameworks),
            "report_kinds": report_kinds,
        }

    # ------------------------------------------------------------------
    # Private helpers — excluded from auto-discovery
    # ------------------------------------------------------------------

    def _require_catalog(self, method_name: str) -> dict | None:
        """Return an error dict if ``_store`` is None, else return ``None``.

        Args:
            method_name: Calling tool name for the hint message.

        Returns:
            Error dict if no catalog, ``None`` if catalog is available.
        """
        if self._store is None:
            return {
                "error": "Catalog not available — report_store was not configured.",
                "hint": (
                    f"'{method_name}' requires a SecurityReportStore. "
                    "Use list_reports or get_report_content with an S3 path instead."
                ),
            }
        return None

    async def _fetch_content(
        self,
        report_id_or_path: str,
    ) -> tuple[bytes, str | None, ReportRef | None]:
        """Dual-mode content fetch — UUID via catalog, path via file manager.

        Args:
            report_id_or_path: Catalog UUID string or S3 key path.

        Returns:
            Tuple of ``(content_bytes, scanner_or_None, ref_or_None)``.
            Scanner is inferred from the catalog or from the path.
        """
        try:
            uid = UUID(report_id_or_path)
            # UUID path — use catalog if available
            if self._store is not None:
                ref = await self._store.get(uid)
                if ref is not None:
                    content = await self._store.fetch_content(uid)
                    return content, ref.scanner, ref
            # Catalog unavailable or ref not found — fall through to path
            path = report_id_or_path
        except ValueError:
            path = report_id_or_path

        # Path-based download
        buf = BytesIO()
        await self._fm.download_file(path, buf)
        buf.seek(0)  # defensive: reset position before reading
        content = buf.getvalue()
        scanner = self._infer_scanner(path)
        return content, scanner, None

    def _extract_json_metrics(
        self,
        data: dict,
        max_depth: int = 3,
        sample_size: int = 5,
    ) -> dict:
        """Walk a parsed JSON dict to extract findings and severity metrics.

        Recursively traverses ``data`` up to ``max_depth`` levels deep,
        collecting severity counts and findings array lengths.  To keep
        runtime bounded, only the first ``sample_size`` items of any list
        are sampled.

        Args:
            data: Parsed JSON document to inspect.
            max_depth: Maximum recursion depth (default 3 — avoids deeply
                nested documents blowing the call stack).
            sample_size: Number of list elements sampled at each level
                (default 5 — trades completeness for performance on large
                reports).

        Returns:
            Dict with three keys:
            - ``severity_breakdown``: mapping of severity level name
              (``"critical"``, ``"high"``, etc.) to integer count.
            - ``total_findings``: total number of finding entries found
              across all known container keys.
            - ``categories``: list of distinct container key names that
              held findings arrays (e.g., ``["findings", "results"]``).
        """
        severity_breakdown: dict[str, int] = {}
        total_findings = 0
        categories: list[str] = []

        def _walk(obj: object, depth: int) -> None:
            nonlocal total_findings
            if depth > max_depth:
                return
            if isinstance(obj, dict):
                for key, val in obj.items():
                    key_lower = key.lower()
                    if key_lower in {"critical", "high", "medium", "low", "informational"}:
                        if isinstance(val, int):
                            severity_breakdown[key_lower] = val
                    if key_lower in {"findings", "results", "checks", "issues"}:
                        if isinstance(val, list):
                            total_findings += len(val)
                            if key_lower not in categories:
                                categories.append(key_lower)
                    if isinstance(val, (dict, list)):
                        _walk(val, depth + 1)
            elif isinstance(obj, list):
                for item in obj[:sample_size]:
                    _walk(item, depth + 1)

        _walk(data, 0)
        return {
            "severity_breakdown": severity_breakdown,
            "total_findings": total_findings,
            "categories": categories,
        }

    def _infer_scanner(self, path: str) -> str | None:
        """Infer scanner name from S3 key path convention.

        Parses the convention ``{prefix}{scanner}/{framework}/{date}/{id}.json``
        by stripping the default prefix and taking the first path component.

        Args:
            path: S3 key path string.

        Returns:
            Scanner name string, or ``None`` if inference fails.
        """
        # Strip known prefix
        relative = path
        if path.startswith(self._default_prefix):
            relative = path[len(self._default_prefix):]

        parts = relative.split("/")
        if parts and parts[0]:
            candidate = parts[0]
            # Validate against known scanners to avoid false positives
            known = {"cloudsploit", "trivy", "prowler", "checkov", "aggregator"}
            if candidate in known:
                return candidate
            # Return candidate anyway for unknown scanners
            return candidate if len(candidate) > 1 else None
        return None

    @staticmethod
    def _serialize_metadata(m: FileMetadata) -> dict:
        """Serialize a FileMetadata dataclass to a JSON-compatible dict.

        Args:
            m: FileMetadata instance from FileManagerInterface.

        Returns:
            Dict with ``name``, ``path``, ``size``, ``content_type``,
            ``modified_at``.
        """
        return {
            "name": m.name,
            "path": m.path,
            "size": m.size,
            "content_type": m.content_type,
            "modified_at": str(m.modified_at) if m.modified_at is not None else None,
        }
