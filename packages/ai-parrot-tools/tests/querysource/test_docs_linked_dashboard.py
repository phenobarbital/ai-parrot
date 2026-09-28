"""FEAT-610 AC12 — the wire doc and toolkit doc describe the new behaviour."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def test_docs_linked_dashboard() -> None:
    """Wire doc lists routes/cap/refreshSource; toolkit doc lists the dashboard tool and JSONB ops."""
    wire = (ROOT / "docs/outputs/a2ui-linked-surfaces.md").read_text()
    for route in (
        "/api/v3/queries/{slug}",
        "/api/v1/{tenant}/queries/{slug}",
        "/api/v1/queries/{schema}/{slug}",
        "/api/v2/services/queries/{slug}",
        "5000",
        "refreshSource",
    ):
        assert route in wire
    toolkit = (ROOT / "docs/tools/querysource-toolkit.md").read_text()
    assert "qs_build_linked_dashboard" in toolkit
    assert "@>" in toolkit
