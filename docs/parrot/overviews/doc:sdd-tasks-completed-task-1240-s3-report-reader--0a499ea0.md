---
type: Wiki Overview
title: 'TASK-1240: S3ReportReaderToolkit + Package Registry'
id: doc:sdd-tasks-completed-task-1240-s3-report-reader-toolkit-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task implements Spec Module 1 (S3 Report Reader Toolkit) and the
relates_to:
- concept: mod:parrot.interfaces.file
  rel: mentions
- concept: mod:parrot.storage.security_reports
  rel: mentions
- concept: mod:parrot_tools.cloudsploit.toolkit
  rel: mentions
- concept: mod:parrot_tools.s3
  rel: mentions
- concept: mod:parrot_tools.s3.report_reader
  rel: mentions
- concept: mod:parrot_tools.security.parsers
  rel: mentions
---

# TASK-1240: S3ReportReaderToolkit + Package Registry

**Feature**: FEAT-184 — Agnostic S3 Report Reader Toolkit
**Spec**: `sdd/specs/agenttool-s3-readreports.spec.md`
**Status**: [x] done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1239
**Assigned-to**: unassigned

---

## Context

This task implements Spec Module 1 (S3 Report Reader Toolkit) and the
registry entry from Module 3. It creates the LLM-facing toolkit with 8
public async methods that auto-discover as agent tools, all namespaced
with `tool_prefix="s3_"`.

The toolkit operates in **dual mode**:
- `FileManagerInterface` (required) for raw S3 operations.
- `SecurityReportStore` (optional) for catalog-backed queries.

When `report_store is None`, catalog-dependent tools return
`{"error": "...", "hint": "..."}` instead of raising.

---

## Scope

- Create `packages/ai-parrot-tools/src/parrot_tools/s3/report_reader.py`
  with `S3ReportReaderToolkit(AbstractToolkit)`.
- Update `packages/ai-parrot-tools/src/parrot_tools/s3/__init__.py` to
  export `S3ReportReaderToolkit`.
- Update `packages/ai-parrot-tools/src/parrot_tools/__init__.py` to add
  `"s3_report_reader"` entry in `TOOL_REGISTRY`.

**S3ReportReaderToolkit** must implement these 8 public async methods
(each auto-discovered as an agent tool with `s3_` prefix):

1. **`list_reports(prefix, pattern, limit)`** — Browse S3 objects.
   - Call `self._fm.list_files(prefix or self._default_prefix, pattern)`.
   - Serialize `FileMetadata` → `{name, path, size, content_type, modified_at}`.
   - Cap at `limit`. No catalog needed.

2. **`get_latest_report(scanner, framework, report_kind)`** — Most recent catalog report.
   - Requires catalog. Build `ReportFilter(scanner=..., framework=..., report_kind=ReportKind(report_kind), limit=1, order_by="produced_at_desc")`.
   - Call `self._store.query(filter)`. Return `ref.model_dump(mode="json")` or error.

3. **`get_report_content(report_id_or_path, section)`** — Download + parse.
   - Dual-mode: if `report_id_or_path` is a valid UUID, fetch via `self._store.fetch_content(uuid)` and get scanner from `self._store.get(uuid)`.
   - Otherwise: treat as S3 path, download via `self._fm.download_file(path, BytesIO())`. Infer scanner from path via `_infer_scanner(path)`.
   - For `section="full"`: return parsed JSON content (or raw HTML string).
   - For other sections: dispatch to `get_report_parser(scanner).extract_section(content, section)` if scanner is known. Fall back to full content if no parser.

4. **`filter_reports(scanner, framework, provider, report_kind, since_days, limit)`** — Catalog query.
   - Requires catalog. Build `ReportFilter` with provided params + `since` from `since_days`.
   - Return list of `ReportRef` dicts.

5. **`compare_reports(report_a, report_b)`** — Diff two reports.
   - Fetch content for both (dual-mode: UUID or path).
   - Determine scanner (from catalog or path inference).
   - Delegate to `GenericReportComparator.compare(content_a, content_b, scanner=scanner)`.

6. **`summarize_report(report_id_or_path)`** — Structured metrics extraction.
   - Fetch content (dual-mode).
   - If catalog-backed: return `ref.severity_summary`, `ref.top_findings`, `ref.scanner`, `ref.framework`, `ref.content_type`.
   - If raw S3: parse JSON content, extract top-level keys, count findings arrays, detect severity fields. Return structured dict with `{content_type, size_bytes, scanner, framework, severity_breakdown, top_findings, categories}`.

7. **`get_report_url(report_id_or_path, expiry)`** — Pre-signed URL.
   - If UUID: look up `ref.uri` from catalog, then `self._fm.get_file_url(uri, expiry)`.
   - If path: `self._fm.get_file_url(path, expiry)` directly.
   - Return `{url, path, expiry_seconds}`.

8. **`list_report_categories()`** — Distinct scanners, frameworks, kinds.
   - Requires catalog. Call `self._store.query_distinct_frameworks()`.
   - For scanners: run `self._store.query(ReportFilter(limit=500))` and deduplicate `ref.scanner` in Python.
   - Return `{scanners: [...], frameworks: [...], report_kinds: [...]}`.

**Internal helpers** (prefixed with `_`, excluded from auto-discovery):

- `_require_catalog(method_name: str) -> dict | None` — returns error dict if `self._store is None`.
- `_fetch_content(report_id_or_path: str) -> tuple[bytes, str | None, ReportRef | None]` — dual-mode content fetch. Returns `(content_bytes, scanner, ref_or_none)`.
- `_infer_scanner(path: str) -> str | None` — parse S3 key convention `{prefix}{scanner}/{framework}/...` to extract scanner name.

**NOT in scope**:
- The comparator (TASK-1239).
- Tests (TASK-1241).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/s3/report_reader.py` | CREATE | `S3ReportReaderToolkit` implementation |
| `packages/ai-parrot-tools/src/parrot_tools/s3/__init__.py` | MODIFY | Add `S3ReportReaderToolkit` export |
| `packages/ai-parrot-tools/src/parrot_tools/__init__.py` | MODIFY | Add `"s3_report_reader"` to `TOOL_REGISTRY` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# AbstractToolkit (via parrot_tools re-export shim)
from ..toolkit import AbstractToolkit  # verified: parrot_tools/toolkit.py:2

# FileManagerInterface + FileMetadata
from parrot.interfaces.file import FileManagerInterface, FileMetadata
# verified: packages/ai-parrot/src/parrot/interfaces/file/__init__.py:18-22

# SecurityReportStore Protocol + models
from parrot.storage.security_reports import (
    SecurityReportStore,    # verified: store.py:43
    ReportFilter,           # verified: models.py:108
    ReportKind,             # verified: models.py:25
    ReportRef,              # verified: models.py:69
)

# Parser registry
from parrot_tools.security.parsers import get_report_parser
# verified: parsers/__init__.py:31

# GenericReportComparator (from TASK-1239)
from .comparator import GenericReportComparator
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):  # line 191
    exclude_tools: tuple[str, ...] = ()  # line 228
    tool_prefix: Optional[str] = None    # line 242
    def __init__(self, **kwargs):         # line 247

# packages/ai-parrot/src/parrot/storage/security_reports/store.py
class SecurityReportStore(Protocol):  # line 43
    async def query(self, filter: ReportFilter) -> list[ReportRef]:  # line 59
    async def get(self, report_id: UUID) -> ReportRef | None:        # line 63
    async def fetch_content(self, report_id: UUID) -> bytes:          # line 67
    async def query_distinct_frameworks(self) -> list[str]:           # line 75

# navigator.utils.file.abstract (re-exported via parrot.interfaces.file)
class FileManagerInterface:  # navigator line 36
    async def list_files(self, path: str = "", pattern: str = "*") -> List[FileMetadata]:  # line 52
    async def download_file(self, source: str, destination: Union[Path, BinaryIO]) -> Path:  # line 93
    async def get_file_url(self, path: str, expiry: int = 3600) -> str:  # line 67
    async def exists(self, path: str) -> bool:  # line 130

class FileMetadata:  # navigator line 15 (dataclass)
    name: str
    path: str
    size: int
    content_type: Optional[str]
    modified_at: Optional[datetime]
    url: Optional[str]

# packages/ai-parrot/src/parrot/storage/security_reports/models.py
class ReportKind(str, Enum):  # line 25
    SCAN = "scan"
    DAILY_SUMMARY = "daily_summary"
    WEEKLY_SUMMARY = "weekly_summary"
    MONTHLY_SUMMARY = "monthly_summary"
    DRIFT_COMPARISON = "drift_comparison"

class ReportRef(BaseModel):  # line 69
    report_id: UUID
    report_kind: ReportKind
    scanner: str
    framework: str | None = None
    provider: str
    scope: dict
    severity_summary: SeverityBreakdown
    top_findings: list[EmbeddedFinding]
    uri: str
    content_type: str = "application/json"
    produced_at: datetime
    produced_by: str
    parser_version: str

class ReportFilter(BaseModel):  # line 108
    scanner: str | None = None
    framework: str | None = None
    provider: str | None = None
    report_kind: ReportKind | None = None
    since: datetime | None = None
    until: datetime | None = None
    scope_match: dict | None = None
    limit: int = Field(default=50, ge=1, le=500)
    order_by: Literal["produced_at_desc", "produced_at_asc"] = "produced_at_desc"

# TOOL_REGISTRY pattern in parrot_tools/__init__.py (line 12-136):
TOOL_REGISTRY: dict[str, str] = {
    "cloudsploit": "parrot_tools.cloudsploit.toolkit.CloudSploitToolkit",  # line 64
    # Add: "s3_report_reader": "parrot_tools.s3.report_reader.S3ReportReaderToolkit"
}
```

### Does NOT Exist

- ~~`FileManagerInterface.list_objects()`~~ — the method is `list_files()`.
- ~~`FileManagerInterface.upload()` / `.download()` / `.get_url()`~~ — correct names: `upload_file()`, `download_file()`, `get_file_url()`.
- ~~`SecurityReportStore.query_distinct_scanners()`~~ — only `query_distinct_frameworks()` exists. Deduplicate scanners in Python.
- ~~`ReportRef.content`~~ — `ReportRef` is metadata only; content fetched via `store.fetch_content(report_id)`.
- ~~`AbstractToolkit.register_tool()`~~ — tools are auto-discovered from public async methods.
- ~~`ReportPersistenceMixin`~~ — write-side mixin; NOT used by this read-only toolkit.

---

## Implementation Notes

### Pattern to Follow

```python
# Follow SecurityReportToolkit pattern (report_toolkit.py:27-249):
class S3ReportReaderToolkit(AbstractToolkit):
    tool_prefix: str = "s3_"
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
        super().__init__(**kwargs)
        self._fm = file_manager
        self._store = report_store
        self._default_prefix = default_prefix
        self._comparator = GenericReportComparator(max_changes=max_diff_changes)
        self.logger = logging.getLogger(__name__)
```

### Key Constraints

- All public async methods become tools — write clear, LLM-friendly docstrings.
- Private helper methods (prefixed with `_`) are excluded from auto-discovery.
- Use `try: UUID(value)` to distinguish UUIDs from S3 paths in dual-mode parameters.
- Serialize `FileMetadata` to dict manually (`dataclasses.asdict` works but stringify `modified_at`).
- Download to `BytesIO()` for in-memory content access.
- `tool_prefix = "s3_"` is a class attribute, not a constructor arg.
- Docstrings: first line should state if the tool requires catalog, e.g., `"Requires catalog."` or `"Works without catalog."`.

### References in Codebase

- `parrot_tools/security/report_toolkit.py` — pattern for constructor, dual-mode fetch, UUID parsing
- `parrot_tools/cloudsploit/toolkit.py` — pattern for composing services in a toolkit
- `parrot_tools/aws/s3.py` — pattern for S3-related toolkit (different scope but same base class)

---

## Acceptance Criteria

- [ ] `S3ReportReaderToolkit` inherits `AbstractToolkit` with `tool_prefix = "s3_"`
- [ ] Constructor accepts `file_manager` (required) + `report_store` (optional, `None` default)
- [ ] All 8 public async methods auto-discover as tools with `s3_` prefix
- [ ] `list_reports` works without catalog
- [ ] `get_report_url` works without catalog
- [ ] Catalog-dependent tools return `{"error": "..."}` when `report_store is None`
- [ ] `get_report_content` resolves both UUIDs and S3 paths
- [ ] `compare_reports` delegates to `GenericReportComparator`
- [ ] `summarize_report` returns structured metrics (no LLM call)
- [ ] Scanner inference from S3 path works for `{prefix}{scanner}/{framework}/...`
- [ ] HTML content returned as-is (not parsed as JSON)
- [ ] `TOOL_REGISTRY["s3_report_reader"]` points to `"parrot_tools.s3.report_reader.S3ReportReaderToolkit"`
- [ ] No linting errors: `ruff check packages/ai-parrot-tools/src/parrot_tools/s3/`
- [ ] Import works: `from parrot_tools.s3 import S3ReportReaderToolkit`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-19
**Notes**: Implemented S3ReportReaderToolkit with 8 public async tools (s3_ prefix), dual-mode operation (catalog+FileManager), _fetch_content, _infer_scanner, _require_catalog helpers. TOOL_REGISTRY updated. All acceptance criteria met.

**Deviations from spec**: none
