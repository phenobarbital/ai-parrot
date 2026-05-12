"""SecurityReportStore Protocol + PostgresS3SecurityReportStore implementation.

The store is the catalog's persistence core:
- Postgres holds metadata (queryable, indexed) via asyncdb.AsyncDB.
- S3 holds content (cheap, large blobs) via FileManagerInterface.

Key design invariants:
1. S3 upload FIRST, Postgres INSERT second (S3-wins, Postgres-reconciled).
2. query() NEVER applies an implicit ``since`` filter — visibility window
   is the caller's responsibility (spec §5 hard requirement).
3. ``delete()`` is reserved for explicit GDPR requests; never called by
   automatic retention paths (spec §1 Goals: compliance retention).
4. bootstrap_schema() is idempotent (all DDL uses IF NOT EXISTS).
"""
from __future__ import annotations

import asyncio
import json
import logging
import importlib.resources
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Protocol, runtime_checkable
from uuid import UUID

try:
    from asyncdb import AsyncDB
except ImportError:  # pragma: no cover
    AsyncDB = None  # type: ignore[assignment,misc]

from parrot.interfaces.file import FileManagerInterface
from parrot.storage.security_reports.models import (
    EmbeddedFinding,
    ReportFilter,
    ReportKind,
    ReportRef,
    SeverityBreakdown,
)


@runtime_checkable
class SecurityReportStore(Protocol):
    """Protocol for the security report catalog persistence layer.

    Implementations back this with any combination of metadata store and
    content store. The reference implementation uses Postgres + S3.
    """

    async def save_report(self, ref: ReportRef, content: bytes | Path) -> ReportRef:
        """Upload content and persist metadata. Returns the ref with uri set."""
        ...

    async def index(self, ref: ReportRef) -> None:
        """Index-only path: insert metadata for a ref whose content was
        already uploaded separately. No S3 upload performed."""
        ...

    async def query(self, filter: ReportFilter) -> list[ReportRef]:
        """Query the catalog by filter. Never applies an implicit age filter."""
        ...

    async def get(self, report_id: UUID) -> ReportRef | None:
        """Fetch a single ReportRef by primary key. None if not found."""
        ...

    async def fetch_content(self, report_id: UUID) -> bytes:
        """Download and return the content bytes for a report."""
        ...

    async def delete(self, report_id: UUID) -> None:
        """Hard-delete a report (GDPR-only). Not used by retention logic."""
        ...

    async def query_distinct_frameworks(self) -> list[str]:
        """Return distinct non-null framework values from the catalog."""
        ...

    async def bootstrap_schema(self) -> None:
        """Idempotently apply schema.sql to the Postgres database."""
        ...


# ---------------------------------------------------------------------------
# Postgres + S3 implementation
# ---------------------------------------------------------------------------

_INSERT_SQL = """
INSERT INTO security_reports (
    report_id, report_kind, scanner, framework, provider,
    scope, severity_summary, top_findings, uri, content_type,
    content_bytes, produced_at, produced_by, parser_version, retention_class
) VALUES (
    $1, $2, $3, $4, $5,
    $6::jsonb, $7::jsonb, $8::jsonb, $9, $10,
    $11, $12, $13, $14, $15
)
ON CONFLICT (report_id) DO NOTHING
"""

_SELECT_BY_ID = """
SELECT report_id, report_kind, scanner, framework, provider,
       scope, severity_summary, top_findings, uri, content_type,
       content_bytes, produced_at, produced_by, parser_version,
       retention_class
FROM security_reports
WHERE report_id = $1
"""


def _row_to_ref(row: dict) -> ReportRef:
    """Convert a raw Postgres row dict to a ReportRef."""
    # asyncdb returns asyncpg Record objects; coerce to dict-like access
    scope = row["scope"] if isinstance(row["scope"], dict) else json.loads(row["scope"] or "{}")
    sev_raw = row["severity_summary"]
    if isinstance(sev_raw, str):
        sev_raw = json.loads(sev_raw)
    sev = SeverityBreakdown(**{k: v for k, v in sev_raw.items() if k in ("critical", "high", "medium", "low", "informational")})

    tf_raw = row["top_findings"]
    if isinstance(tf_raw, str):
        tf_raw = json.loads(tf_raw)
    top_findings = [EmbeddedFinding(**f) for f in (tf_raw or [])]

    return ReportRef(
        report_id=row["report_id"],
        report_kind=ReportKind(row["report_kind"]),
        scanner=row["scanner"],
        framework=row["framework"],
        provider=row["provider"],
        scope=scope,
        severity_summary=sev,
        top_findings=top_findings,
        uri=row["uri"],
        content_type=row["content_type"],
        content_bytes=row["content_bytes"],
        produced_at=row["produced_at"],
        produced_by=row["produced_by"],
        parser_version=row["parser_version"],
        retention_class=row["retention_class"],
    )


class PostgresS3SecurityReportStore:
    """Postgres (metadata) + S3/FileManager (content) catalog implementation.

    Constructor:
        dsn: Postgres connection string (asyncdb AsyncDB format).
        file_manager: FileManagerInterface implementation (e.g. S3FileManager).
        s3_prefix: Path prefix for content objects. Defaults to
            'security-reports/' but can be overridden for multi-env isolation.
    """

    def __init__(
        self,
        dsn: str,
        file_manager: FileManagerInterface,
        *,
        s3_prefix: str = "security-reports/",
    ) -> None:
        self._dsn = dsn
        self._fm = file_manager
        self._prefix = s3_prefix
        self.logger = logging.getLogger(__name__)
        if AsyncDB is None:
            raise RuntimeError(
                "asyncdb is not installed. Install it to use PostgresS3SecurityReportStore."
            )
        self._db = AsyncDB("pg", dsn=dsn)
        self._schema_bootstrapped = False
        self._bootstrap_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_key(self, ref: ReportRef) -> str:
        """Deterministic S3 key for human browsing in the AWS console."""
        fw = ref.framework or "security"
        ts = ref.produced_at.strftime("%Y/%m/%d")
        return f"{self._prefix}{ref.scanner}/{fw}/{ts}/{ref.report_id}.json"

    async def _upload_content(self, key: str, content: bytes | Path) -> None:
        """Upload content bytes or Path to the file manager."""
        if isinstance(content, Path):
            await self._fm.upload_file(content, key)
        else:
            await self._fm.create_file(key, content)

    async def _get_connection(self):
        """Return an asyncdb connection context manager."""
        return await self._db.connection()

    async def _ensure_schema(self) -> None:
        """Lazily bootstrap the schema once per store instance.

        First write-side call (``save_report`` / ``index``) triggers
        ``bootstrap_schema``. Subsequent calls fast-path on the
        ``_schema_bootstrapped`` flag. The asyncio.Lock + double-check
        prevents two concurrent first-calls from racing on the same DDL.
        Schema is idempotent (``IF NOT EXISTS``) so this is also safe
        across multiple processes.
        """
        if self._schema_bootstrapped:
            return
        async with self._bootstrap_lock:
            if self._schema_bootstrapped:
                return
            await self.bootstrap_schema()
            self._schema_bootstrapped = True

    # ------------------------------------------------------------------
    # Protocol implementation
    # ------------------------------------------------------------------

    async def save_report(self, ref: ReportRef, content: bytes | Path) -> ReportRef:
        """Upload content to S3 first, then insert metadata into Postgres.

        S3 upload runs first (orphan-tolerant per spec §7 R8). If metadata
        insert fails, the S3 object is orphaned — acceptable for v1.
        Returns the ref with ``uri`` populated.
        """
        await self._ensure_schema()
        key = self._build_key(ref)
        await self._upload_content(key, content)
        self.logger.debug("Uploaded report content to %s", key)

        uri = key  # FileManager handles the full path; store the key
        ref = ref.model_copy(update={"uri": uri})

        try:
            async with await self._get_connection() as conn:
                await conn.execute(
                    _INSERT_SQL,
                    ref.report_id,
                    ref.report_kind.value,
                    ref.scanner,
                    ref.framework,
                    ref.provider,
                    json.dumps(ref.scope),
                    json.dumps(ref.severity_summary.model_dump()),
                    json.dumps([f.model_dump() for f in ref.top_findings]),
                    ref.uri,
                    ref.content_type,
                    ref.content_bytes,
                    ref.produced_at,
                    ref.produced_by,
                    ref.parser_version,
                    ref.retention_class,
                )
        except Exception as exc:
            self.logger.error("Metadata insert failed (S3 object orphaned): %s", exc)
            raise
        return ref

    async def index(self, ref: ReportRef) -> None:
        """Insert metadata only (content was already uploaded externally)."""
        await self._ensure_schema()
        async with await self._get_connection() as conn:
            await conn.execute(
                _INSERT_SQL,
                ref.report_id,
                ref.report_kind.value,
                ref.scanner,
                ref.framework,
                ref.provider,
                json.dumps(ref.scope),
                json.dumps(ref.severity_summary.model_dump()),
                json.dumps([f.model_dump() for f in ref.top_findings]),
                ref.uri,
                ref.content_type,
                ref.content_bytes,
                ref.produced_at,
                ref.produced_by,
                ref.parser_version,
                ref.retention_class,
            )

    async def query(self, filter: ReportFilter) -> list[ReportRef]:
        """Query the catalog.

        CRITICAL: No implicit ``since`` filter is applied — ALL matching
        reports are returned regardless of age. Set ``filter.since`` when
        you need a time window (spec §5 hard requirement).
        """
        clauses: list[str] = []
        params: list = []

        def _add(clause: str, value) -> None:
            params.append(value)
            clauses.append(clause.replace("?", f"${len(params)}"))

        if filter.scanner is not None:
            _add("scanner = ?", filter.scanner)
        if filter.framework is not None:
            _add("framework = ?", filter.framework)
        if filter.provider is not None:
            _add("provider = ?", filter.provider)
        if filter.report_kind is not None:
            _add("report_kind = ?", filter.report_kind.value)
        if filter.since is not None:
            _add("produced_at >= ?", filter.since)
        if filter.until is not None:
            _add("produced_at <= ?", filter.until)
        if filter.scope_match is not None:
            _add("scope @> ?::jsonb", json.dumps(filter.scope_match))

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        direction = "DESC" if filter.order_by == "produced_at_desc" else "ASC"
        sql = f"""
            SELECT report_id, report_kind, scanner, framework, provider,
                   scope, severity_summary, top_findings, uri, content_type,
                   content_bytes, produced_at, produced_by, parser_version,
                   retention_class
            FROM security_reports
            {where}
            ORDER BY produced_at {direction}
            LIMIT ${len(params) + 1}
        """
        params.append(filter.limit)

        async with await self._get_connection() as conn:
            rows = await conn.fetch(sql, *params)

        return [_row_to_ref(dict(row)) for row in (rows or [])]

    async def get(self, report_id: UUID) -> ReportRef | None:
        """Fetch a single ReportRef by primary key."""
        async with await self._get_connection() as conn:
            rows = await conn.fetch(_SELECT_BY_ID, report_id)
        if not rows:
            return None
        return _row_to_ref(dict(rows[0]))

    async def fetch_content(self, report_id: UUID) -> bytes:
        """Download and return the content bytes for a report."""
        ref = await self.get(report_id)
        if ref is None:
            raise KeyError(f"Report {report_id} not found")
        buf = BytesIO()
        await self._fm.download_file(ref.uri, buf)
        return buf.getvalue()

    async def delete(self, report_id: UUID) -> None:
        """Hard-delete a report (GDPR-only). Removes both Postgres row and S3 content."""
        ref = await self.get(report_id)
        if ref is None:
            self.logger.warning("delete() called on non-existent report_id=%s", report_id)
            return
        # Delete S3 content first, then metadata row
        await self._fm.delete_file(ref.uri)
        async with await self._get_connection() as conn:
            await conn.execute(
                "DELETE FROM security_reports WHERE report_id = $1", report_id
            )

    async def query_distinct_frameworks(self) -> list[str]:
        """Return distinct non-null framework values via SQL DISTINCT query."""
        sql = (
            "SELECT DISTINCT framework FROM security_reports "
            "WHERE framework IS NOT NULL ORDER BY framework"
        )
        async with await self._get_connection() as conn:
            rows = await conn.fetch(sql)
        return [row["framework"] for row in (rows or [])]

    async def bootstrap_schema(self) -> None:
        """Idempotently apply schema.sql to the connected database.

        Uses importlib.resources so the .sql file is always located relative
        to this package regardless of CWD.
        """
        try:
            # Python 3.9+ importlib.resources API
            pkg_files = importlib.resources.files("parrot.storage.security_reports")
            schema_path = pkg_files.joinpath("schema.sql")
            schema_sql = schema_path.read_text()
        except Exception:
            # Fallback: resolve relative to this file
            schema_path = Path(__file__).parent / "schema.sql"
            schema_sql = schema_path.read_text()

        async with await self._get_connection() as conn:
            for stmt in schema_sql.split(";"):
                stmt = stmt.strip()
                if stmt:
                    await conn.execute(stmt)
        self.logger.info("Security reports schema bootstrapped.")
