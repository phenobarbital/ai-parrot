---
type: Wiki Overview
title: 'Feature Specification: Agnostic S3 Report Reader Toolkit'
id: doc:sdd-specs-agenttool-s3-readreports-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The `SecurityAgent` runs a suite of scanners (CloudSploit, Prowler, Trivy,
relates_to:
- concept: mod:parrot.interfaces.file
  rel: mentions
- concept: mod:parrot.storage.security_reports
  rel: mentions
- concept: mod:parrot_tools.cloudsploit.comparator
  rel: mentions
- concept: mod:parrot_tools.cloudsploit.models
  rel: mentions
- concept: mod:parrot_tools.cloudsploit.parser
  rel: mentions
- concept: mod:parrot_tools.s3
  rel: mentions
- concept: mod:parrot_tools.s3.report_reader
  rel: mentions
- concept: mod:parrot_tools.security.parsers
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: Agnostic S3 Report Reader Toolkit

**Feature ID**: FEAT-184
**Date**: 2026-05-19
**Author**: Jesus Lara
**Status**: approved
**Target version**: v1

---

## 1. Motivation & Business Requirements

### Problem Statement

The `SecurityAgent` runs a suite of scanners (CloudSploit, Prowler, Trivy,
Checkov) that persist findings into an S3 bucket via
`PostgresS3SecurityReportStore` (FEAT-162). The existing
`SecurityReportToolkit` provides basic catalog queries
(`find_security_report`, `read_security_report`, `search_findings`,
`list_available_frameworks`) but is tightly coupled to security-report models
and lacks three capabilities:

1. **Report comparison** — no tool lets the LLM diff two reports to see what
   changed (new findings, resolved findings, severity shifts).
2. **Structured summarization** — no tool extracts key metrics (severity
   counts, categories, top findings) into a structured dict the LLM can
   reason over.
3. **Direct S3 browsing** — no tool lets the LLM browse raw S3 objects
   (list files by prefix/pattern, download HTML or arbitrary JSON) without
   going through the catalog.

A new, **agnostic** toolkit is needed that any agent — not just the
SecurityAgent — can mount to read, filter, compare, and summarize documents
stored in S3.

### Goals

- Expose an agnostic, read-only tool surface for S3-stored reports to any
  LLM agent.
- Operate in **dual mode**: catalog-backed queries when a
  `SecurityReportStore` is injected; raw S3 browsing via
  `FileManagerInterface` when it is not.
- Support both `application/json` and `text/html` content types.
- Provide generic JSON structural diff with optional parser-dispatch for
  richer, scanner-aware comparison.
- Return structured data (not LLM narratives) for summarization — the
  calling agent's LLM generates the narrative.
- Namespace all tools with `tool_prefix="s3"` to prevent collision when
  mounted alongside `SecurityReportToolkit`.
  (Note: `AbstractToolkit` appends `prefix_separator="_"` automatically, so
  `tool_prefix = "s3"` produces the `s3_` prefix on all tool names.)

### Non-Goals (explicitly out of scope)

- Replacing `SecurityReportToolkit` — it stays as the SecurityAgent-specific
  convenience layer (FEAT-162).
- Modifying `PostgresS3SecurityReportStore` or its schema.
- Write/upload capabilities — this is a reader toolkit.
- LLM-powered narrative summaries — the toolkit returns structured metrics.
- New parsers — the existing parser registry is consumed as-is.
- Modifying `ScanComparator` — it stays CloudSploit-specific; reused via dispatch.
- Schema changes to the `security_reports` table.

---

## 2. Architectural Design

### Overview

`S3ReportReaderToolkit` inherits from `AbstractToolkit` and composes two
dependencies via constructor injection:

- **`FileManagerInterface`** (required) — provides raw S3 operations:
  `list_files`, `find_files`, `download_file`, `get_file_url`,
  `get_file_metadata`, `exists`.
- **`SecurityReportStore`** (optional, `None` by default) — provides
  catalog-backed queries: `query`, `get`, `fetch_content`,
  `query_distinct_frameworks`.

When `report_store is None`, catalog-dependent tools return an informative
`{"error": "catalog not available"}` dict. Tools that only need
`FileManagerInterface` always work.

A companion `GenericReportComparator` class provides structural JSON diff.
When a scanner name is known (from catalog metadata or S3 key inference),
it dispatches to the scanner-specific comparator (e.g., `ScanComparator`
for CloudSploit) for richer output. Falls back to generic diff for unknown
formats or HTML.

### Component Diagram

```
                  Agent (any)
                      │
                      ▼
          ┌──────────────────────┐
          │ S3ReportReaderToolkit │  (tool_prefix="s3_")
          │   (AbstractToolkit)  │
          └────┬──────────┬──────┘
               │          │
     ┌─────────▼──┐  ┌────▼──────────────────┐
     │FileManager  │  │SecurityReportStore     │
     │Interface    │  │(optional — Protocol)   │
     │ (required)  │  │                        │
     │             │  │ PostgresS3Security-    │
     │ S3FileMgr   │  │ ReportStore            │
     └─────────────┘  └────────────────────────┘
               │
     ┌─────────▼──────────────┐
     │ GenericReportComparator │
     │  ├─ structural diff    │
     │  └─ parser dispatch    │
     │      ├─ ScanComparator │
     │      └─ (fallback)     │
     └────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractToolkit` | inherits | Auto-discovers public async methods as tools |
| `FileManagerInterface` | composes (required) | Raw S3 list/download/URL operations |
| `SecurityReportStore` (Protocol) | composes (optional) | Catalog queries when available |
| `get_report_parser` | calls | Parser dispatch for section extraction and scanner-aware comparison |
| `ScanComparator` | delegates (via dispatch) | CloudSploit-specific diff when scanner is `cloudsploit` |
| `TOOL_REGISTRY` | registers | Lazy import path in `parrot_tools/__init__.py` |

### Data Models

No new Pydantic models are introduced. The toolkit reuses:

```python
# parrot/storage/security_reports/models.py
ReportRef       # line 69 — full report metadata
ReportFilter    # line 108 — query filter
ReportKind      # line 25 — fractal kind enum
SeverityBreakdown  # line 35 — severity counts
EmbeddedFinding    # line 54 — top-N findings per report

# navigator.utils.file.abstract (via parrot.interfaces.file)
FileMetadata    # name, path, size, content_type, modified_at, url
```

The `GenericReportComparator` returns a plain `dict` (not a Pydantic model) to
stay agnostic:

```python
{
    "baseline_path": str,
    "current_path": str,
    "scanner": str | None,
    "comparison_mode": "generic" | "parser_dispatch",
    "summary": {
        "keys_added": int,
        "keys_removed": int,
        "keys_changed": int,
        "findings_new": int,        # only with parser dispatch
        "findings_resolved": int,   # only with parser dispatch
        "severity_changes": int,    # only with parser dispatch
    },
    "changes": list[dict],  # top-N changes capped for LLM consumption
}
```

### New Public Interfaces

```python
# parrot_tools/s3/report_reader.py

class S3ReportReaderToolkit(AbstractToolkit):
    tool_prefix: str = "s3"  # AbstractToolkit appends separator "_" automatically

    def __init__(
        self,
        file_manager: FileManagerInterface,
        report_store: SecurityReportStore | None = None,
        *,
        default_prefix: str = "security-reports/",
        max_diff_changes: int = 50,
        **kwargs,
    ) -> None: ...

    # --- Tools (auto-discovered) ---

    async def list_reports(
        self, prefix: str = "", pattern: str = "*.json", limit: int = 50,
    ) -> list[dict]: ...

    async def get_latest_report(
        self,
        scanner: str | None = None,
        framework: str | None = None,
        report_kind: str = "scan",
    ) -> dict: ...

    async def get_report_content(
        self,
        report_id_or_path: str,
        section: str = "full",
    ) -> dict: ...

    async def filter_reports(
        self,
        scanner: str | None = None,
        framework: str | None = None,
        provider: str | None = None,
        report_kind: str | None = None,
        since_days: int = 30,
        limit: int = 20,
    ) -> list[dict]: ...

    async def compare_reports(
        self,
        report_a: str,
        report_b: str,
    ) -> dict: ...

    async def summarize_report(
        self, report_id_or_path: str,
    ) -> dict: ...

    async def get_report_url(
        self, report_id_or_path: str, expiry: int = 3600,
    ) -> dict: ...

    async def list_report_categories(self) -> dict: ...
```

```python
# parrot_tools/s3/comparator.py

class GenericReportComparator:
    def __init__(self, max_changes: int = 50) -> None: ...

    def compare(
        self,
        baseline: dict | bytes,
        current: dict | bytes,
        *,
        scanner: str | None = None,
    ) -> dict: ...

    def _structural_diff(self, baseline: dict, current: dict) -> dict: ...
    def _dispatch_to_parser(self, baseline: bytes, current: bytes, scanner: str) -> dict | None: ...
```

---

## 3. Module Breakdown

### Module 1: S3 Report Reader Toolkit

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/s3/report_reader.py`
- **Responsibility**: LLM-facing toolkit with 8 tools for reading, filtering,
  comparing, and summarizing S3-stored reports.
- **Depends on**: `AbstractToolkit`, `FileManagerInterface`,
  `SecurityReportStore` (optional), `GenericReportComparator` (Module 2),
  parser registry.

**Tool implementations**:

1. **`list_reports(prefix, pattern, limit)`** — calls
   `file_manager.list_files(prefix, pattern)`, serializes `FileMetadata`
   objects, caps at `limit`. Always works (no catalog needed).

2. **`get_latest_report(scanner, framework, report_kind)`** — requires
   catalog. Calls `report_store.query(ReportFilter(scanner=..., limit=1))`,
   returns the most recent `ReportRef` as dict. Returns error if no catalog.

3. **`get_report_content(report_id_or_path, section)`** — dual-mode:
   - If `report_id_or_path` is a valid UUID: fetch via
     `report_store.fetch_content(uuid)` + parser dispatch for section.
   - Otherwise: treat as S3 key path, download via
     `file_manager.download_file()`. Infer scanner from path for parser
     dispatch. Section extraction works for JSON; HTML returns raw content.

4. **`filter_reports(scanner, framework, provider, report_kind, since_days, limit)`**
   — requires catalog. Builds `ReportFilter`, calls `report_store.query()`.
   Returns list of `ReportRef` dicts.

5. **`compare_reports(report_a, report_b)`** — dual-mode content fetch
   (UUID or path), then delegates to `GenericReportComparator.compare()`.

6. **`summarize_report(report_id_or_path)`** — fetches content (dual-mode),
   extracts structured metrics: severity breakdown, top findings, content
   type, scanner, framework, total findings count, categories. No LLM call.

7. **`get_report_url(report_id_or_path, expiry)`** — resolves URI
   (catalog lookup or direct path), calls
   `file_manager.get_file_url(uri, expiry)`. Returns `{url, expiry}`.

8. **`list_report_categories()`** — requires catalog. Calls
   `report_store.query_distinct_frameworks()` and a distinct scanners query.
   Returns `{scanners: [...], frameworks: [...], report_kinds: [...]}`.

### Module 2: Generic Report Comparator

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/s3/comparator.py`
- **Responsibility**: Compare two report documents, producing a structured
  diff. Supports two modes: generic structural JSON diff (always available)
  and parser-dispatch (when scanner is known).
- **Depends on**: `get_report_parser` (for dispatch), `ScanComparator`
  (for CloudSploit dispatch).

**Implementation**:

- `compare(baseline, current, *, scanner=None) → dict`
  1. If both inputs are `bytes`, decode as JSON.
  2. If `scanner` is known and a parser is registered: attempt
     parser-specific comparison. For `cloudsploit`, instantiate
     `ScanComparator`, parse both into `ScanResult`, call
     `comparator.compare()`, and convert `ComparisonReport` to dict.
  3. Fall back to `_structural_diff()` for generic comparison.
  4. Cap `changes` list at `max_changes`.

- `_structural_diff(baseline, current) → dict`
  - Walk both dicts recursively.
  - Track: keys added, keys removed, keys changed (with old/new values).
  - For arrays: count elements added/removed (by index, not identity).

### Module 3: Package Init + Registry

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/s3/__init__.py`
- **Responsibility**: Package init with public exports.
- **Depends on**: Module 1.

```python
from .report_reader import S3ReportReaderToolkit

__all__ = ("S3ReportReaderToolkit",)
```

Also update `TOOL_REGISTRY` in `parrot_tools/__init__.py`:
```python
"s3_report_reader": "parrot_tools.s3.report_reader.S3ReportReaderToolkit",
```

### Module 4: Tests

- **Path**: `packages/ai-parrot-tools/tests/s3/test_report_reader.py`
- **Responsibility**: Unit tests for the toolkit and comparator.
- **Depends on**: Modules 1, 2, 3.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_list_reports_no_catalog` | 1 | `list_reports` works with only `FileManagerInterface` |
| `test_list_reports_with_pattern` | 1 | `list_reports` filters by glob pattern |
| `test_list_reports_limit` | 1 | `list_reports` caps results at limit |
| `test_get_latest_report_with_catalog` | 1 | Returns most recent report from catalog |
| `test_get_latest_report_no_catalog` | 1 | Returns error dict when no catalog |
| `test_get_report_content_by_uuid` | 1 | Fetches via catalog + parser dispatch |
| `test_get_report_content_by_path` | 1 | Fetches via FileManagerInterface |
| `test_get_report_content_html` | 1 | Returns raw HTML content (no JSON parsing) |
| `test_get_report_content_section` | 1 | Extracts specific section via parser |
| `test_filter_reports` | 1 | Catalog query with multiple filters |
| `test_filter_reports_no_catalog` | 1 | Returns error dict when no catalog |
| `test_compare_reports_generic` | 2 | Structural JSON diff on two dicts |
| `test_compare_reports_parser_dispatch` | 2 | CloudSploit-aware diff via ScanComparator |
| `test_compare_reports_unknown_scanner` | 2 | Falls back to generic diff for unknown scanner |
| `test_compare_reports_html` | 2 | Returns text diff for HTML content |
| `test_compare_reports_capped` | 2 | Changes list capped at max_changes |
| `test_summarize_report_json` | 1 | Extracts severity counts, top findings, categories |
| `test_summarize_report_html` | 1 | Returns content_type and size for HTML |
| `test_get_report_url` | 1 | Generates pre-signed URL with expiry |
| `test_get_report_url_by_uuid` | 1 | Resolves URI from catalog, then generates URL |
| `test_list_report_categories` | 1 | Returns scanners, frameworks, report_kinds |
| `test_list_report_categories_no_catalog` | 1 | Returns error dict when no catalog |
| `test_tool_prefix_applied` | 1 | All tools have `s3_` prefix |
| `test_structural_diff_nested` | 2 | Handles nested dicts/arrays |
| `test_structural_diff_array_changes` | 2 | Detects added/removed array elements |

### Test Data / Fixtures

```python
@pytest.fixture
def mock_file_manager():
    """Mock FileManagerInterface with list/download/url capabilities."""
    ...

@pytest.fixture
def mock_report_store():
    """Mock SecurityReportStore with query/get/fetch_content."""
    ...

@pytest.fixture
def sample_cloudsploit_report() -> bytes:
    """Minimal CloudSploit JSON scan result for comparison tests."""
    ...

@pytest.fixture
def sample_html_report() -> bytes:
    """Minimal HTML report content."""
    ...

@pytest.fixture
def toolkit_with_catalog(mock_file_manager, mock_report_store):
    """S3ReportReaderToolkit with both deps."""
    return S3ReportReaderToolkit(
        file_manager=mock_file_manager,
        report_store=mock_report_store,
    )

@pytest.fixture
def toolkit_no_catalog(mock_file_manager):
    """S3ReportReaderToolkit without catalog."""
    return S3ReportReaderToolkit(file_manager=mock_file_manager)
```

---

## 5. Acceptance Criteria

- [ ] `S3ReportReaderToolkit` inherits from `AbstractToolkit` with
      `tool_prefix = "s3"` (separator appended automatically by `AbstractToolkit`).
- [ ] Constructor accepts `file_manager: FileManagerInterface` (required) and
      `report_store: SecurityReportStore | None = None` (optional).
- [ ] All 8 public async methods auto-discover as tools with `s3_` prefix.
- [ ] `list_reports` works with `FileManagerInterface` alone (no catalog).
- [ ] `get_report_url` works with `FileManagerInterface` alone.
- [ ] Catalog-dependent tools (`get_latest_report`, `filter_reports`,
      `list_report_categories`) return `{"error": "..."}` when `report_store`
      is `None`.
- [ ] `get_report_content` resolves both UUIDs (via catalog) and S3 key paths
      (via file manager).
- [ ] `compare_reports` uses `GenericReportComparator` with structural JSON
      diff as baseline.
- [ ] `compare_reports` dispatches to `ScanComparator` when scanner is
      `cloudsploit`.
- [ ] `summarize_report` returns structured metrics dict (severity counts,
      top findings, categories) — no LLM call.
- [ ] `GenericReportComparator` caps `changes` list at `max_changes`.
- [ ] Scanner inference from S3 key path works for the convention
      `{prefix}{scanner}/{framework}/{date}/{id}.json`.
- [ ] HTML content is returned as-is (not parsed as JSON).
- [ ] `S3ReportReaderToolkit` is registered in `TOOL_REGISTRY` as
      `"s3_report_reader"`.
- [ ] All unit tests pass: `pytest packages/ai-parrot-tools/tests/s3/ -v`
- [ ] No breaking changes to `SecurityReportToolkit` or
      `PostgresS3SecurityReportStore`.
- [ ] No new external dependencies — only existing `parrot` and
      `parrot_tools` internals.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
# AbstractToolkit (via parrot_tools re-export shim)
from ..toolkit import AbstractToolkit  # verified: parrot_tools/toolkit.py:2

# FileManagerInterface + FileMetadata
from parrot.interfaces.file import FileManagerInterface, FileMetadata
# verified: packages/ai-parrot/src/parrot/interfaces/file/__init__.py:18-22

# SecurityReportStore Protocol + models
from parrot.storage.security_reports import (
    SecurityReportStore,    # verified: store.py:42-43
    ReportFilter,           # verified: models.py:108
    ReportKind,             # verified: models.py:25
    ReportRef,              # verified: models.py:69
    SeverityBreakdown,      # verified: models.py:35
    EmbeddedFinding,        # verified: models.py:54
)

# Parser registry
from parrot_tools.security.parsers import get_report_parser
# verified: parsers/__init__.py:31

# CloudSploit comparator (for dispatch)
from parrot_tools.cloudsploit.comparator import ScanComparator
# verified: comparator.py:5

# CloudSploit parser (for dispatch)
from parrot_tools.cloudsploit.parser import ScanResultParser
# verified: parser.py:16

# CloudSploit models (for dispatch)
from parrot_tools.cloudsploit.models import ScanResult, ComparisonReport
# verified: models.py:70, 216
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):                              # line 191
    exclude_tools: tuple[str, ...] = ()                  # line 228
    tool_prefix: Optional[str] = None                    # line 242
    prefix_separator: str = "_"                          # line 243
    def __init__(self, **kwargs):                         # line 247
    def _resolve_tool_name(self, method_name: str) -> str:  # line 347
    def _generate_tools(self) -> None:                   # line 368

# packages/ai-parrot/src/parrot/storage/security_reports/store.py
@runtime_checkable
class SecurityReportStore(Protocol):                     # line 42-43
    async def save_report(self, ref: ReportRef, content: bytes | Path) -> ReportRef:  # line 50
    async def index(self, ref: ReportRef) -> None:       # line 54
    async def query(self, filter: ReportFilter) -> list[ReportRef]:  # line 59
    async def get(self, report_id: UUID) -> ReportRef | None:  # line 63
    async def fetch_content(self, report_id: UUID) -> bytes:   # line 67
    async def delete(self, report_id: UUID) -> None:           # line 71
    async def query_distinct_frameworks(self) -> list[str]:    # line 75
    async def bootstrap_schema(self) -> None:                  # line 79

# navigator.utils.file.abstract (re-exported via parrot.interfaces.file)
@dataclass
class FileMetadata:                                      # navigator line 15
    name: str
    path: str
    size: int
    content_type: Optional[str]
    modified_at: Optional[datetime]
    url: Optional[str]

class FileManagerInterface:                              # navigator line 36
    async def list_files(self, path: str = "", pattern: str = "*") -> List[FileMetadata]:  # line 52
    async def find_files(self, keywords=None, extension=None, prefix=None) -> List[FileMetadata]:  # line 265
    async def download_file(self, source: str, destination: Union[Path, BinaryIO]) -> Path:  # line 93
    async def get_file_url(self, path: str, expiry: int = 3600) -> str:  # line 67
    async def get_file_metadata(self, path: str) -> FileMetadata:  # line 141
    async def exists(self, path: str) -> bool:           # line 130

# packages/ai-parrot-tools/src/parrot_tools/security/parsers/__init__.py
_REGISTRY: dict[str, ReportParser] = {                   # line 22
    "trivy": TrivyParser(),
    "cloudsploit": CloudSploitParser(),
    "prowler": ProwlerParser(),
    "checkov": CheckovParser(),
    "aggregator": AggregatorParser(),
}
def get_report_parser(scanner: str) -> ReportParser:     # line 31

# packages/ai-parrot-tools/src/parrot_tools/cloudsploit/comparator.py
class ScanComparator:                                    # line 5
    def compare(self, baseline: ScanResult, current: ScanResult) -> ComparisonReport:  # line 8

# packages/ai-parrot-tools/src/parrot_tools/security/report_toolkit.py
class SecurityReportToolkit(AbstractToolkit):             # line 27
    def __init__(self, report_store: SecurityReportStore, file_manager: FileManagerInterface, **kwargs):  # line 44
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `S3ReportReaderToolkit` | `AbstractToolkit` | inheritance | `toolkit.py:191` |
| `S3ReportReaderToolkit` | `FileManagerInterface` | constructor injection | `file/__init__.py:18` |
| `S3ReportReaderToolkit` | `SecurityReportStore` | constructor injection (optional) | `store.py:42` |
| `S3ReportReaderToolkit` | `get_report_parser` | function call | `parsers/__init__.py:31` |
| `GenericReportComparator` | `ScanComparator` | delegation (cloudsploit dispatch) | `comparator.py:5` |
| `GenericReportComparator` | `ScanResultParser` | delegation (parse before compare) | `parser.py:16` |
| `TOOL_REGISTRY` | `S3ReportReaderToolkit` | lazy import string | `__init__.py:12-136` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot_tools.s3`~~ — package does not exist yet; FEAT-184 creates it.
- ~~`FileManagerInterface.list_objects()`~~ — the method is `list_files()`.
- ~~`FileManagerInterface.upload()` / `.download()` / `.get_url()`~~ — correct
  method names are `upload_file()`, `download_file()`, `get_file_url()`.
- ~~`SecurityReportStore.query_distinct_scanners()`~~ — only
  `query_distinct_frameworks()` exists. To get distinct scanners, query with
  broad filter and deduplicate in Python.
- ~~`ReportRef.content`~~ — `ReportRef` is metadata only; content is fetched
  separately via `store.fetch_content(report_id)`.
- ~~`AbstractToolkit.register_tool()`~~ — tools are auto-discovered from
  public async methods; there is no manual registration method.
- ~~`ReportPersistenceMixin`~~ — write-side mixin; NOT used by this toolkit
  (it is read-only).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **`AbstractToolkit` auto-discovery**: every public async method is a tool.
  Docstrings become tool descriptions for the LLM — write them clearly.
  *Ref*: `toolkit.py:368-403`.
- **`tool_prefix` namespacing**: set `tool_prefix = "s3"` on the class to
  namespace all tools (e.g., `s3_list_reports`, `s3_compare_reports`).
  `AbstractToolkit` appends `prefix_separator="_"` automatically, so the
  resulting tool names carry the correct `s3_` prefix.
  *Ref*: `toolkit.py:242, 347-366`.
- **Constructor composition**: compose deps via `__init__` injection, same
  pattern as `SecurityReportToolkit.__init__()`.
  *Ref*: `report_toolkit.py:44-60`.

…(truncated)…
