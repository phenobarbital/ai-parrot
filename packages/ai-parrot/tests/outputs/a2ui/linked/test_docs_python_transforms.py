"""FEAT-636 AC12 — docs describe server-side python transformers for linked surfaces."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]


def test_wire_doc_describes_python_transforms() -> None:
    wire = (ROOT / "docs/outputs/a2ui-linked-surfaces.md").read_text()
    for needle in (
        "transform.python",
        "/api/v1/ui/surfaces/{surface_id}/sources/{key}/data",
        "transformer_not_registered",
        "transform_failed",
        "transform_invalid_output",
        "input_alias",
        "terminal",
        "saved data",
    ):
        assert needle in wire, needle


def test_toolkit_doc_mentions_python_member() -> None:
    toolkit = (ROOT / "docs/tools/querysource-toolkit.md").read_text()
    assert "transform.python" in toolkit or '"python"' in toolkit