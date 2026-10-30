# TASK-4772: Mermaid source utilities + error codes (M1)

**Feature**: FEAT-753 — A2UI MermaidDiagram (opaque Mermaid-source component in the Parrot catalog)
**Spec**: `sdd/specs/a2ui-mermaid-diagram.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 / goals G2, G4, G6. The pure text layer every other module calls: diagram-type
detection, directive normalization, the statement-aware safety check, the opt-in `GraphSpec` bridge and the
FEAT-755 phrase-bank constants. It lives in `graph/mermaid_source.py` (NOT in the catalog component module)
because `test_lazy_imports.py` forbids `parrot.bots.data` from importing `catalog.parrot` — FEAT-755 will import
the constants from `parrot.outputs.a2ui.graph`.

---

## Scope

- Append four error-code constants to `catalog/base.py` right after `TRANSFORM_REF_UNKNOWN`.
- Create `graph/mermaid_source.py` with `MermaidDiagramType`, `MERMAID_DIAGRAM_TYPES`, `MERMAID_SOURCE_MAX_BYTES`,
  `MERMAID_THEMES`, `_HEADER_TO_TYPE`, `MERMAID_DIAGRAM_ROUTE_KEY`, `MERMAID_DIAGRAM_ROUTE_UTTERANCES`,
  `MermaidSourceIssue`, `iter_statements`, `detect_diagram_type`, `normalize_mermaid_source`,
  `check_mermaid_source`, `graph_spec_from_mermaid_source` (spec §2 Data Models + §3 M1 skeleton, verbatim).
- Re-export the public names from `graph/__init__.py` (`__all__` kept alphabetical).
- Write `tests/outputs/a2ui/graph/test_mermaid_source.py` with the §4 M1 rows and the shared sample constants.

**NOT in scope**: the `MermaidDiagram` catalog component and the `validate_envelope` pass (TASK-4773); the builder (TASK-4774); any change to `graph/mermaid.py` (codec stays byte-unchanged, AC-5).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid_source.py` | CREATE | pure detection / normalization / check / bridge + constants |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py` | MODIFY | append 4 MERMAID_* error codes after TRANSFORM_REF_UNKNOWN |
| `packages/ai-parrot/src/parrot/outputs/a2ui/graph/__init__.py` | MODIFY | re-export the new public names |
| `packages/ai-parrot/tests/outputs/a2ui/graph/test_mermaid_source.py` | CREATE | M1 unit tests + shared samples |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `65144d730` (2026-10-27). Use these exact imports, names and
> signatures. If you need something not listed here, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.outputs.a2ui.graph.mermaid import MermaidCodecError, from_mermaid, to_mermaid  # verified: graph/mermaid.py:67 (__all__), :126, :323, :206
from parrot.outputs.a2ui.graph.models import GraphSpec  # verified: graph/models.py:179
# the four codes below are CREATED by this task in catalog/base.py (after line 96):
from parrot.outputs.a2ui.catalog.base import (
    MERMAID_DIAGRAM_TYPE_MISMATCH, MERMAID_SOURCE_TOO_LARGE, MERMAID_UNSAFE_DIRECTIVE, MERMAID_UNSAFE_INTERACTION,
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py
TRANSFORM_REF_UNKNOWN = "TRANSFORM_REF_UNKNOWN"  # line 96 — append the new codes right after it
# catalog/base.py imports only parrot.outputs.a2ui.models (line 25) — so importing it from graph/ is cycle-free

# packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid.py   (DO NOT MODIFY)
class MermaidCodecError(CatalogValidationError): def __init__(self, line_no: int, line: str, reason: str)  # line 126, 139
def _prepare_lines(text: str) -> list[tuple[int, str]]  # line 174 — raises on "%%{" (line 191)
def to_mermaid(spec: GraphSpec) -> str  # line 206 — headers "flowchart <dir>", "stateDiagram-v2", "sequenceDiagram"
def from_mermaid(text: str) -> GraphSpec  # line 323 — header dispatch lines 344-350
_UNSUPPORTED_PREFIXES = ("classDef", "click", "style", "linkStyle", "loop", "alt", "par", "note", "Note")  # line 77

# packages/ai-parrot/src/parrot/outputs/a2ui/graph/__init__.py
from .mermaid import MermaidCodecError, from_mermaid, to_mermaid  # line 12
__all__ = [  # line 30 — alphabetical list of strings
```

### Does NOT Exist
- ~~`parrot.outputs.a2ui.mermaid`~~ (package) — does not exist; the new module is `parrot.outputs.a2ui.graph.mermaid_source`.
- ~~`detect_diagram_type` / `normalize_mermaid_source` / `check_mermaid_source` / `graph_spec_from_mermaid_source`~~ anywhere — new in this task.
- ~~an `import parrot.outputs.a2ui.catalog`~~ (the package) from `mermaid_source.py` — FORBIDDEN: `catalog/__init__.py` imports this module (TASK-4773), so it would be a cycle. Import only `catalog.base`.
- ~~a Mermaid parser library in Python~~ — none is added; validation is pure string scanning.
- ~~`from_mermaid` returning `kind="dag"`~~ — never (graph/mermaid.py:50-55).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid_source.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/outputs/a2ui/graph/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/outputs/a2ui/graph/test_mermaid_source.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid.py#from_mermaid",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid.py#MermaidCodecError",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/graph/models.py#GraphSpec"
  ]
}
```

---

## Implementation Notes

- **Statement scanner (`iter_statements`)** is the heart of the safety check: split on `\n` AND on `;`
  outside quoted strings (`"…"`, honour `\\"` escapes) and outside label delimiters (`[ ] ( ) { }` nesting depth
  > 0). Keep the 1-based line number where each statement STARTS. Skip blank statements, `%%` comment lines,
  `%%{…}%%` directives (single- and multi-line) and a leading YAML front-matter block (`---` on line 1 … next `---`).
- **Interaction check** matches the FIRST TOKEN of each logical statement exactly: `click`, `link`, `callback`.
  `clickable[Clickable]` and `A["first; click is label text"]` must pass. `javascript:` and `<script` are matched
  anywhere in the raw source, case-insensitively (rejecting a label that contains them is intended).
- **Directive check** is on the RAW source lines (`line.strip().startswith("%%{")`), not on `iter_statements`
  (which skips directives). Front-matter `config:` key → also `MERMAID_UNSAFE_DIRECTIVE`.
- **Byte cap**: `len(source.encode("utf-8"))`; empty string is also `MERMAID_SOURCE_TOO_LARGE` ("empty source").
- Return EVERY issue (never stop at the first) — `test_check_reports_all_issues_not_first`.
- Q2 (32 KiB vs 64 KiB) is open in the spec: keep **32_768** unless the user says otherwise.

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly verbatim, then
> complete every `# FILL IN:` marker. Never change a signature, class name or file path fixed here.

### Steps (in order)
1. Append the 4 codes to `catalog/base.py` — *why*: `mermaid_source.py` imports them; codes live with the other catalog codes.
2. Create `graph/mermaid_source.py` from the block below; implement the FILL IN bodies — *why*: pure functions, no I/O.
3. Add the re-exports to `graph/__init__.py` — *why*: FEAT-755 imports the route constants from `parrot.outputs.a2ui.graph` (AC-9).
4. Write the tests, including a fresh-interpreter import probe of `mermaid_source` (cycle guard, spec §7 Known Risks).
5. Run ruff/black and the Validation Commands.

### `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'TRANSFORM_REF_UNKNOWN = "TRANSFORM_REF_UNKNOWN"' catalog/base.py)
# AFTER — insert below `TRANSFORM_REF_UNKNOWN = "TRANSFORM_REF_UNKNOWN"` (verified: catalog/base.py:96)
# FEAT-753 — MermaidDiagram source gate (graph/mermaid_source.check_mermaid_source).
MERMAID_SOURCE_TOO_LARGE = "MERMAID_SOURCE_TOO_LARGE"
MERMAID_UNSAFE_DIRECTIVE = "MERMAID_UNSAFE_DIRECTIVE"
MERMAID_UNSAFE_INTERACTION = "MERMAID_UNSAFE_INTERACTION"
MERMAID_DIAGRAM_TYPE_MISMATCH = "MERMAID_DIAGRAM_TYPE_MISMATCH"
```
**Why**: spec §2 Data Models fixes the names and the append point; nothing else in `base.py` changes.

### `packages/ai-parrot/src/parrot/outputs/a2ui/graph/mermaid_source.py` (CREATE)
```python
"""Pure Mermaid-source utilities for the ``MermaidDiagram`` component (FEAT-753, Module 1).

Detects the diagram type, strips ``%%{ … }%%`` directives (builder lane), checks a source for the
wire (every origin, called from ``catalog.validate_envelope``) and bridges the flowchart / state /
sequence subset to a typed ``GraphSpec``. Never draws, never does I/O. MUST NOT import the
``parrot.outputs.a2ui.catalog`` package (it imports this module) — only ``catalog.base``.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Final, Literal, TypedDict, get_args

from parrot.outputs.a2ui.catalog.base import (
    MERMAID_DIAGRAM_TYPE_MISMATCH,
    MERMAID_SOURCE_TOO_LARGE,
    MERMAID_UNSAFE_DIRECTIVE,
    MERMAID_UNSAFE_INTERACTION,
)
from parrot.outputs.a2ui.graph.mermaid import MermaidCodecError, from_mermaid
from parrot.outputs.a2ui.graph.models import GraphSpec

__all__ = [
    "MERMAID_DIAGRAM_ROUTE_KEY",
    "MERMAID_DIAGRAM_ROUTE_UTTERANCES",
    "MERMAID_DIAGRAM_TYPES",
    "MERMAID_SOURCE_MAX_BYTES",
    "MERMAID_THEMES",
    "MermaidDiagramType",
    "MermaidSourceIssue",
    "check_mermaid_source",
    "detect_diagram_type",
    "graph_spec_from_mermaid_source",
    "iter_statements",
    "normalize_mermaid_source",
]

MermaidDiagramType = Literal[
    "flowchart", "sequence", "class", "state", "er", "journey", "gantt", "pie",
    "quadrant", "requirement", "gitGraph", "c4", "mindmap", "timeline", "zenuml",
    "sankey", "xychart", "block", "packet", "kanban", "architecture", "radar",
    "treemap", "unknown",
]
MERMAID_DIAGRAM_TYPES: Final[tuple[str, ...]] = get_args(MermaidDiagramType)
MERMAID_SOURCE_MAX_BYTES: Final[int] = 32_768
MERMAID_THEMES: Final[tuple[str, ...]] = ("default", "neutral", "dark", "forest", "base")
MERMAID_DIAGRAM_ROUTE_KEY: Final[str] = "a2ui:MermaidDiagram"
MERMAID_DIAGRAM_ROUTE_UTTERANCES: Final[tuple[str, ...]] = (
    "as a diagram", "draw this as a diagram", "sequence diagram of", "show the flow as a sequence diagram",
    "class diagram of", "ER diagram of the data model", "gantt chart of the plan", "draw a mindmap",
    "diagrama de secuencia de", "muéstralo como diagrama", "diagrama de clases de", "diagrama entidad-relación",
    "haz un diagrama de flujo", "dibuja un mapa mental",
)

#: header keyword (first token of the first statement) -> diagram type
_HEADER_TO_TYPE: Final[dict[str, str]] = {
    # FILL IN: copy the table from spec §2 "Data Models" verbatim (29 keys) — bounded by AC-1/test_detect_diagram_type_table
}
_INTERACTION_KEYWORDS: Final[frozenset[str]] = frozenset({"click", "link", "callback"})
_UNSAFE_ANYWHERE = re.compile(r"javascript:|<script", re.IGNORECASE)


class MermaidSourceIssue(TypedDict):
    """One validation finding: ``code`` (a ``catalog.base`` constant), ``message``, ``line_no`` (1-based or None)."""

    code: str
    message: str
    line_no: int | None


def iter_statements(source: str) -> Iterator[tuple[int, str]]:
    """Yield ``(line_no, stripped_statement)`` for every logical statement.

    Split on newlines and on semicolons outside quoted text and label delimiters; keep the 1-based
    line where each statement starts. Skip blank statements, ``%%`` comments, ``%%{ … }%%``
    directives and a leading YAML front-matter block. Never raises.
    """
    # FILL IN: character scanner tracking (in_quote, escape, bracket_depth) — bounded by
    #   test_statement_boundaries_and_interactions; front-matter only when line 1 is exactly "---"


def detect_diagram_type(source: str) -> str:
    """Return the diagram type from the first token of the first statement (exact, case-sensitive); else ``"unknown"``."""
    for _line_no, statement in iter_statements(source):
        return _HEADER_TO_TYPE.get(statement.split(maxsplit=1)[0], "unknown")
    return "unknown"


def normalize_mermaid_source(source: str) -> tuple[str, str | None]:
    """Strip every ``%%{ … }%%`` directive (single- or multi-line) and front-matter ``config:``; lift ``theme``.

    Returns ``(normalized_source, theme)`` — ``theme`` only when it is one of ``MERMAID_THEMES``.
    Line endings become ``\n`` and exactly one trailing newline is guaranteed. Never raises.
    """
    # FILL IN: directive regex across lines (re.DOTALL on "%%{.*?}%%"), theme via regex on the directive
    #   body (r'"?theme"?\s*:\s*"?(\w+)') — never json.loads (directives are JSON5-ish); drop the
    #   front-matter `config:` key AND its indented value lines, keep title-only front-matter (spec §7).


def check_mermaid_source(source: str, *, declared_type: str | None = None) -> list[MermaidSourceIssue]:
    """Validate ``source`` for the wire; return EVERY issue found (empty list == valid). Pure; never raises.

    Order: size/empty -> surviving directive or front-matter ``config:`` -> interaction statement /
    ``javascript:`` / ``<script`` -> declared type mismatch.
    """
    issues: list[MermaidSourceIssue] = []
    if not source or len(source.encode("utf-8")) > MERMAID_SOURCE_MAX_BYTES:
        issues.append(
            {
                "code": MERMAID_SOURCE_TOO_LARGE,
                "message": "empty source" if not source else f"source exceeds {MERMAID_SOURCE_MAX_BYTES} UTF-8 bytes",
                "line_no": None,
            }
        )
        if not source:
            return issues
    # FILL IN: directive lines (raw scan) + front-matter config -> MERMAID_UNSAFE_DIRECTIVE with line_no
    # FILL IN: iter_statements first token in _INTERACTION_KEYWORDS -> MERMAID_UNSAFE_INTERACTION with line_no;
    #   _UNSAFE_ANYWHERE.finditer over raw lines -> MERMAID_UNSAFE_INTERACTION with line_no
    if declared_type is not None:
        detected = detect_diagram_type(source)
        if declared_type != detected:
            issues.append(
                {
                    "code": MERMAID_DIAGRAM_TYPE_MISMATCH,
                    "message": f"diagramType {declared_type!r} does not match detected {detected!r}",
                    "line_no": None,
                }
            )
    return issues


def graph_spec_from_mermaid_source(source: str) -> GraphSpec:
    """Opt-in bridge: normalize ``source`` and delegate to :func:`from_mermaid`.

    Raises:
        MermaidCodecError: outside the codec's flowchart / stateDiagram-v2 / sequenceDiagram subset.
    """
    normalized, _theme = normalize_mermaid_source(source)
    return from_mermaid(normalized)
```
**Why this shape**: signatures and constants are fixed by spec §2/§3 M1. `MermaidCodecError` is imported (and
listed for documentation) because `graph_spec_from_mermaid_source` re-raises it; keep the import even if ruff
flags it unused by adding it to a `Raises:` usage or `# noqa: F401` — prefer referencing it in the docstring only
and remove the import if ruff complains. Directives are stripped by regex, never parsed as JSON.

### `packages/ai-parrot/src/parrot/outputs/a2ui/graph/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from .mermaid import MermaidCodecError, from_mermaid, to_mermaid' graph/__init__.py) — line 12
# AFTER — insert below that import line:
from .mermaid_source import (
    MERMAID_DIAGRAM_ROUTE_KEY,
    MERMAID_DIAGRAM_ROUTE_UTTERANCES,
    MERMAID_DIAGRAM_TYPES,
    MERMAID_SOURCE_MAX_BYTES,
    check_mermaid_source,
    detect_diagram_type,
    graph_spec_from_mermaid_source,
    normalize_mermaid_source,
)
# occurrences: 1 (verified: grep -c '__all__ = \[' graph/__init__.py) — line 30
# FILL IN: add the 8 names above to __all__ in alphabetical (case-sensitive, as existing) order
```
**Why**: AC-9 — the route constants must be importable from `parrot.outputs.a2ui.graph` without touching `catalog.parrot`.

### `packages/ai-parrot/tests/outputs/a2ui/graph/test_mermaid_source.py` (CREATE)
```python
"""FEAT-753 M1 — pure Mermaid source utilities (spec §4 Unit Tests, M1 rows)."""

from __future__ import annotations

import subprocess
import sys

import pytest

from parrot.outputs.a2ui.catalog.base import (
    MERMAID_DIAGRAM_TYPE_MISMATCH,
    MERMAID_SOURCE_TOO_LARGE,
    MERMAID_UNSAFE_DIRECTIVE,
    MERMAID_UNSAFE_INTERACTION,
)
from parrot.outputs.a2ui.graph import (
    MERMAID_SOURCE_MAX_BYTES,
    GraphSpec,
    MermaidCodecError,
    check_mermaid_source,
    detect_diagram_type,
    graph_spec_from_mermaid_source,
    normalize_mermaid_source,
)
from parrot.outputs.a2ui.graph.mermaid_source import _HEADER_TO_TYPE

SEQUENCE_SRC = "sequenceDiagram\n    participant A as Alice\n    A->>B: hello\n"
CLASS_SRC = "classDiagram\n    class Animal {\n      +String name\n    }\n    Animal <|-- Dog\n"
ER_SRC = "erDiagram\n    CUSTOMER ||--o{ ORDER : places\n"
FRONTMATTER_SRC = "---\ntitle: Checkout\n---\n%% a comment\nflowchart LR\n    a --> b\n"
DIRECTIVE_SRC = '%%{init: {"theme": "dark", "flowchart": {"htmlLabels": true}}}%%\nflowchart TD\n    a --> b\n'
CLICK_SRC = "flowchart TD\n    a --> b\n    click a href \"javascript:alert(1)\"\n"
OVERSIZE_SRC = "flowchart TD\n" + "\n".join(f"n{i} --> n{i+1}" for i in range(6000))


def _codes(issues):
    return [i["code"] for i in issues]


def test_import_is_cycle_free_in_fresh_interpreter() -> None:
    # spec §7 Known Risks — mirrors test_lazy_imports.py:_run_probe
    proc = subprocess.run(
        [sys.executable, "-c", "import parrot.outputs.a2ui.graph.mermaid_source"], capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr


# FILL IN: test_detect_diagram_type_table (parametrize over _HEADER_TO_TYPE items, "graph TD", FRONTMATTER_SRC, "" -> unknown)
# FILL IN: test_normalize_strips_directives_and_lifts_theme (single + multi-line, non-theme directive -> None, remainder byte-identical)
# FILL IN: test_check_rejects_oversize_and_empty (multi-byte chars counted as bytes)
# FILL IN: test_check_rejects_surviving_directive (line_no set); front-matter config: also rejected
# FILL IN: test_check_rejects_click_link_callback_javascript_script (parametrized; "clickable[x]" passes)
# FILL IN: test_statement_boundaries_and_interactions (spec §4 row: semicolon vector, quoted/bracketed labels, escaped quotes, comments, line numbers)
# FILL IN: test_check_reports_all_issues_not_first (3 problems -> 3 issues)
# FILL IN: test_check_type_mismatch
# FILL IN: test_graph_spec_from_mermaid_source_subset_and_rejection (flowchart/state/sequence -> GraphSpec; CLASS_SRC -> MermaidCodecError)
```
**Why**: the sample constants are spec §4 "Test Data / Fixtures" verbatim — TASK-4773/4774 tests copy them.

### FILL IN checklist
- [ ] `_HEADER_TO_TYPE` — copy spec §2 table verbatim; bounded by `test_detect_diagram_type_table`
- [ ] `iter_statements` — quote/escape/bracket-aware split; bounded by `test_statement_boundaries_and_interactions`
- [ ] `normalize_mermaid_source` — regex strip + theme lift + front-matter `config:` removal; bounded by AC-3
- [ ] `check_mermaid_source` directive / interaction branches — bounded by AC-2 (every issue, with `line_no`)
- [ ] `graph/__init__.py` `__all__` entries — alphabetical
- [ ] the 9 test bodies listed in the test file

---

## Acceptance Criteria

- [ ] All §4 M1 rows implemented and passing.
- [ ] `from parrot.outputs.a2ui.graph import MERMAID_DIAGRAM_ROUTE_KEY, MERMAID_DIAGRAM_ROUTE_UTTERANCES` works (AC-9).
- [ ] `graph/mermaid.py` byte-unchanged (`git diff --stat` shows no change to it) — AC-5.
- [ ] `test_lazy_imports.py` and `test_mermaid.py` still green.
- [ ] `ruff check` + `black --check -l 120` clean on touched files (AC-12).

## Validation Commands

- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/outputs/a2ui/graph/test_mermaid_source.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/outputs/a2ui/graph/test_mermaid.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/outputs/a2ui/test_lazy_imports.py -q`

---

## Test Specification

See the test-file block above — the FILL IN list is the §4 M1 row set, one function per row.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug a2ui-mermaid-diagram --feature-id FEAT-753`).
2. **Read the spec** `sdd/specs/a2ui-mermaid-diagram.spec.md` (§2 decisions D1–D7, §6 contract, §7 constraints).
3. **Check dependencies** — every `Depends-on` task must be `done` in `sdd/tasks/index/a2ui-mermaid-diagram.json`.
4. **Verify the Codebase Contract** — re-run the `grep -c` of every MODIFY anchor before editing; a count of 0 is drift: stop and report.
5. **Update status** in the per-spec index → `"in-progress"`.
6. **Implement** the blueprint, then complete every `FILL IN` — touch only the files listed above.
7. **Validate**: `ruff check --fix <files>`, `black -l 120 <files>`, then the Validation Commands with
   `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-visualizations/src`.
8. **Close** with `scripts/sdd/close_task.sh <TASK-ID> a2ui-mermaid-diagram verified` and fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (sequential fallback; parrot-sdd-coder MCP disconnected)
**Date**: 2026-10-27
**Notes**: Implemented `graph/mermaid_source.py`, 4 `MERMAID_*` codes in `catalog/base.py`, re-exports in `graph/__init__.py`, and 50 tests (all green, incl. test_mermaid.py and test_lazy_imports.py). The cycle-probe test derives the src path from `__file__` (a relative PYTHONPATH does not survive pytest's cwd). The bridge tests use `flowchart TB` with declared nodes because the codec accepts only TB/LR/BT/RL and requires declared nodes; `DIRECTIVE_SRC` stays `flowchart TD` for the check/normalize tests. Empty/whitespace-only source normalizes to `""`.

**Deviations from spec**: none
