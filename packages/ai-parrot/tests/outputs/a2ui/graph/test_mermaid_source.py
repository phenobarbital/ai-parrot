"""FEAT-753 M1 — pure Mermaid source utilities (spec §4 Unit Tests, M1 rows)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from parrot.outputs.a2ui.catalog.base import (
    MERMAID_DIAGRAM_TYPE_MISMATCH,
    MERMAID_SOURCE_TOO_LARGE,
    MERMAID_UNSAFE_DIRECTIVE,
    MERMAID_UNSAFE_INTERACTION,
)
from parrot.outputs.a2ui.graph import (
    MERMAID_DIAGRAM_ROUTE_KEY,
    MERMAID_DIAGRAM_ROUTE_UTTERANCES,
    MERMAID_SOURCE_MAX_BYTES,
    GraphSpec,
    MermaidCodecError,
    check_mermaid_source,
    detect_diagram_type,
    graph_spec_from_mermaid_source,
    normalize_mermaid_source,
)
from parrot.outputs.a2ui.graph.mermaid_source import _HEADER_TO_TYPE, iter_statements

SEQUENCE_SRC = "sequenceDiagram\n    participant A as Alice\n    A->>B: hello\n"
CLASS_SRC = "classDiagram\n    class Animal {\n      +String name\n    }\n    Animal <|-- Dog\n"
ER_SRC = "erDiagram\n    CUSTOMER ||--o{ ORDER : places\n"
FRONTMATTER_SRC = "---\ntitle: Checkout\n---\n%% a comment\nflowchart LR\n    a --> b\n"
DIRECTIVE_SRC = '%%{init: {"theme": "dark", "flowchart": {"htmlLabels": true}}}%%\nflowchart TD\n    a --> b\n'
CLICK_SRC = 'flowchart TD\n    a --> b\n    click a href "javascript:alert(1)"\n'
OVERSIZE_SRC = "flowchart TD\n" + "\n".join(f"n{i} --> n{i + 1}" for i in range(6000))


def _codes(issues):
    return [i["code"] for i in issues]


def test_import_is_cycle_free_in_fresh_interpreter() -> None:
    # spec §7 Known Risks — mirrors test_lazy_imports.py:_run_probe (this tree's src first on sys.path)
    src = Path(__file__).resolve().parents[4] / "src"
    probe = f"import sys\nsys.path.insert(0, {str(src)!r})\nimport parrot.outputs.a2ui.graph.mermaid_source"
    proc = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr


def test_route_constants_exported() -> None:
    assert MERMAID_DIAGRAM_ROUTE_KEY == "a2ui:MermaidDiagram"
    assert "as a diagram" in MERMAID_DIAGRAM_ROUTE_UTTERANCES


@pytest.mark.parametrize(("header", "expected"), list(_HEADER_TO_TYPE.items()))
def test_detect_diagram_type_table(header: str, expected: str) -> None:
    assert detect_diagram_type(f"{header}\n  a --> b\n") == expected


def test_detect_diagram_type_edge_cases() -> None:
    assert detect_diagram_type("graph TD\n a-->b") == "flowchart"
    assert detect_diagram_type(FRONTMATTER_SRC) == "flowchart"
    assert detect_diagram_type(DIRECTIVE_SRC) == "flowchart"
    assert detect_diagram_type(SEQUENCE_SRC) == "sequence"
    assert detect_diagram_type(CLASS_SRC) == "class"
    assert detect_diagram_type(ER_SRC) == "er"
    assert detect_diagram_type("") == "unknown"
    assert detect_diagram_type("Flowchart TD") == "unknown"  # case-sensitive
    assert detect_diagram_type("nonsense") == "unknown"


def test_normalize_strips_directives_and_lifts_theme() -> None:
    normalized, theme = normalize_mermaid_source(DIRECTIVE_SRC)
    assert theme == "dark"
    assert normalized == "flowchart TD\n    a --> b\n"

    multi = '%%{\n  init: {\n    "theme": "forest"\n  }\n}%%\nflowchart TD\n  a --> b'
    normalized, theme = normalize_mermaid_source(multi)
    assert theme == "forest"
    assert normalized == "flowchart TD\n  a --> b\n"

    normalized, theme = normalize_mermaid_source(
        '%%{init: {"flowchart": {"curve": "basis"}}}%%\nflowchart TD\n a-->b\n'
    )
    assert theme is None
    assert "%%{" not in normalized

    normalized, theme = normalize_mermaid_source('%%{init: {"theme": "bogus"}}%%\nflowchart TD\n a-->b\n')
    assert theme is None

    plain = "flowchart TD\n    a --> b\n"
    assert normalize_mermaid_source(plain) == (plain, None)
    assert normalize_mermaid_source("flowchart TD\r\n a-->b\r\n\r\n")[0] == "flowchart TD\n a-->b\n"


def test_normalize_front_matter_config_removed_title_kept() -> None:
    src = "---\ntitle: T\nconfig:\n  theme: dark\n  flowchart:\n    curve: basis\n---\nflowchart TD\n a-->b\n"
    normalized, _ = normalize_mermaid_source(src)
    assert "config:" not in normalized
    assert "curve" not in normalized
    assert "title: T" in normalized
    assert check_mermaid_source(normalized) == []
    assert normalize_mermaid_source(FRONTMATTER_SRC)[0] == FRONTMATTER_SRC


def test_check_accepts_valid_sources() -> None:
    for src in (FRONTMATTER_SRC, SEQUENCE_SRC, CLASS_SRC, ER_SRC, "flowchart TD\n    clickable[Clickable] --> b\n"):
        assert check_mermaid_source(src) == [], src


def test_check_rejects_oversize_and_empty() -> None:
    issues = check_mermaid_source(OVERSIZE_SRC)
    assert MERMAID_SOURCE_TOO_LARGE in _codes(issues)
    # multi-byte chars count as bytes, not characters
    multibyte = "flowchart TD\n a[" + "é" * (MERMAID_SOURCE_MAX_BYTES // 2 + 1) + "]\n"
    assert len(multibyte) < MERMAID_SOURCE_MAX_BYTES < len(multibyte.encode())
    assert MERMAID_SOURCE_TOO_LARGE in _codes(check_mermaid_source(multibyte))
    assert _codes(check_mermaid_source("")) == [MERMAID_SOURCE_TOO_LARGE]


def test_check_rejects_surviving_directive() -> None:
    issues = check_mermaid_source(DIRECTIVE_SRC)
    assert [(i["code"], i["line_no"]) for i in issues] == [(MERMAID_UNSAFE_DIRECTIVE, 1)]
    cfg = "---\nconfig:\n  theme: dark\n---\nflowchart TD\n a-->b\n"
    issues = check_mermaid_source(cfg)
    assert [(i["code"], i["line_no"]) for i in issues] == [(MERMAID_UNSAFE_DIRECTIVE, 2)]


@pytest.mark.parametrize(
    "line",
    [
        'click a href "https://example.com"',
        "link a https://example.com",
        "callback a myFn",
        "a --> b; click a call fn()",
        "  click   a",
    ],
)
def test_check_rejects_click_link_callback(line: str) -> None:
    issues = check_mermaid_source(f"flowchart TD\n    a --> b\n    {line}\n")
    assert MERMAID_UNSAFE_INTERACTION in _codes(issues)


@pytest.mark.parametrize(
    "src",
    [
        'flowchart TD\n a["see javascript:alert(1)"]\n',
        "flowchart TD\n a[<SCRIPT>x</SCRIPT>]\n",
        "flowchart TD\n a[JaVaScRiPt:void(0)]\n",
    ],
)
def test_check_rejects_javascript_and_script(src: str) -> None:
    assert MERMAID_UNSAFE_INTERACTION in _codes(check_mermaid_source(src))


def test_statement_boundaries_and_interactions() -> None:
    # semicolon vector
    assert MERMAID_UNSAFE_INTERACTION in _codes(check_mermaid_source("flowchart TD\n a-->b; click a href x\n"))
    # quoted / bracketed labels containing "; click" are NOT interactions
    assert check_mermaid_source('flowchart TD\n A["first; click is label text"]\n') == []
    assert check_mermaid_source("flowchart TD\n A[first; click is label] --> B\n") == []
    # escaped quote does not end the string
    assert check_mermaid_source('flowchart TD\n A["say \\"hi; click\\" now"]\n') == []
    # commented-out interaction ignored; a word that merely starts with click passes
    assert check_mermaid_source("flowchart TD\n %% click a href x\n clickable[Clickable]\n") == []
    # line numbers are where the statement starts
    issues = check_mermaid_source("flowchart TD\n a-->b\n\n b-->c; link c x\n")
    assert [(i["code"], i["line_no"]) for i in issues] == [(MERMAID_UNSAFE_INTERACTION, 4)]
    # iter_statements: skips directives / comments / front-matter
    stmts = list(iter_statements(FRONTMATTER_SRC))
    assert stmts == [(5, "flowchart LR"), (6, "a --> b")]
    assert list(iter_statements("a;b;;c")) == [(1, "a"), (1, "b"), (1, "c")]
    assert list(iter_statements("")) == []


def test_check_reports_all_issues_not_first() -> None:
    src = '%%{init: {"theme": "dark"}}%%\nflowchart TD\n a-->b\n click a href "x"\n'
    codes = _codes(check_mermaid_source(src, declared_type="sequence"))
    assert MERMAID_UNSAFE_DIRECTIVE in codes
    assert MERMAID_UNSAFE_INTERACTION in codes
    assert MERMAID_DIAGRAM_TYPE_MISMATCH in codes
    assert len(codes) == 3


def test_check_type_mismatch() -> None:
    assert check_mermaid_source(SEQUENCE_SRC, declared_type="sequence") == []
    issues = check_mermaid_source(SEQUENCE_SRC, declared_type="flowchart")
    assert _codes(issues) == [MERMAID_DIAGRAM_TYPE_MISMATCH]
    assert check_mermaid_source(SEQUENCE_SRC) == []


def test_graph_spec_from_mermaid_source_subset_and_rejection() -> None:
    # the codec needs declared nodes/participants and TB|LR|BT|RL directions
    flow = '%%{init: {"theme": "dark"}}%%\nflowchart TB\n a[A]\n b[B]\n a --> b\n'
    spec = graph_spec_from_mermaid_source(flow)
    assert isinstance(spec, GraphSpec)
    assert {n.id for n in spec.nodes} == {"a", "b"}
    seq = "sequenceDiagram\n    participant A as Alice\n    participant B as Bob\n    A->>B: hello\n"
    assert isinstance(graph_spec_from_mermaid_source(seq), GraphSpec)
    assert isinstance(graph_spec_from_mermaid_source("stateDiagram-v2\n[*] --> idle\nidle --> done\n"), GraphSpec)
    with pytest.raises(MermaidCodecError):
        graph_spec_from_mermaid_source(CLASS_SRC)
