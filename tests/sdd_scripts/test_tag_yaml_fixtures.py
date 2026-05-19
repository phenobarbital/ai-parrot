"""Unit tests for scripts/sdd/tag_yaml_fixtures.py (TASK-1241 / FEAT-183).

Verifies the tagger script's idempotency, fixture detection, and CLI entry point.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.sdd.tag_yaml_fixtures import main, tag_file


# ---------------------------------------------------------------------------
# tag_file() unit tests
# ---------------------------------------------------------------------------


def test_tags_untagged_form_fixture(tmp_path: Path) -> None:
    """An untagged form YAML gains tenant: navigator after form_id: line."""
    f = tmp_path / "form.yaml"
    f.write_text("form_id: my-form\nversion: '1.0'\nsections: []\n")

    result = tag_file(f)
    assert result == "tagged"

    content = f.read_text()
    assert "tenant: navigator" in content

    # Inserted right after form_id: line.
    lines = content.splitlines()
    form_id_idx = next(i for i, l in enumerate(lines) if l.startswith("form_id:"))
    tenant_idx = next(i for i, l in enumerate(lines) if l.startswith("tenant:"))
    assert tenant_idx == form_id_idx + 1, (
        "tenant: should appear immediately after form_id:"
    )


def test_skips_already_tagged(tmp_path: Path) -> None:
    """A file that already has tenant: is left byte-identical."""
    f = tmp_path / "form.yaml"
    original = "form_id: my-form\ntenant: epson\nversion: '1.0'\nsections: []\n"
    f.write_text(original)

    result = tag_file(f)

    assert result == "already"
    assert f.read_text() == original


def test_skips_non_form_files(tmp_path: Path) -> None:
    """Files without form_id at root are not form fixtures and are skipped."""
    f = tmp_path / "not_a_form.yaml"
    f.write_text("some_other_key: value\n")

    result = tag_file(f)
    assert result == "not-a-fixture"
    assert f.read_text() == "some_other_key: value\n"


def test_handles_parse_error(tmp_path: Path) -> None:
    """Malformed YAML returns 'parse-error' without crashing."""
    f = tmp_path / "bad.yaml"
    f.write_text("key: [\nunclosed bracket\n")

    result = tag_file(f)
    assert result == "parse-error"


def test_idempotent(tmp_path: Path) -> None:
    """Running tag_file twice on the same file produces no diff on the second run."""
    f = tmp_path / "form.yaml"
    f.write_text("form_id: my-form\nversion: '1.0'\nsections: []\n")

    tag_file(f)
    first = f.read_text()

    result_second = tag_file(f)
    second = f.read_text()

    assert result_second == "already"
    assert first == second


def test_dry_run_does_not_write(tmp_path: Path) -> None:
    """--dry-run reports 'tagged' but does not modify the file."""
    f = tmp_path / "form.yaml"
    original = "form_id: my-form\nversion: '1.0'\nsections: []\n"
    f.write_text(original)

    result = tag_file(f, dry_run=True)

    assert result == "tagged"
    assert f.read_text() == original  # file unchanged


def test_indented_form_id_preserves_indent(tmp_path: Path) -> None:
    """If form_id: is indented, tenant: is inserted at the same indentation."""
    f = tmp_path / "form.yaml"
    f.write_text("  form_id: indented-form\n  sections: []\n")

    tag_file(f)
    content = f.read_text()
    lines = content.splitlines()
    tenant_line = next((l for l in lines if "tenant" in l), None)
    assert tenant_line is not None
    assert tenant_line.startswith("  tenant:")


# ---------------------------------------------------------------------------
# main() / CLI tests
# ---------------------------------------------------------------------------


def test_main_returns_zero(tmp_path: Path) -> None:
    """CLI entry point returns 0 on success."""
    f = tmp_path / "form.yaml"
    f.write_text("form_id: m\nversion: '1.0'\nsections: []\n")

    rc = main(["--roots", str(tmp_path)])

    assert rc == 0
    assert "tenant: navigator" in f.read_text()


def test_main_dry_run_returns_zero(tmp_path: Path) -> None:
    """--dry-run returns 0 and does not modify files."""
    f = tmp_path / "form.yaml"
    original = "form_id: m\nversion: '1.0'\nsections: []\n"
    f.write_text(original)

    rc = main(["--dry-run", "--roots", str(tmp_path)])

    assert rc == 0
    assert f.read_text() == original


def test_main_skips_missing_roots(tmp_path: Path) -> None:
    """Passing a non-existent root does not crash."""
    rc = main(["--roots", str(tmp_path / "does-not-exist")])
    assert rc == 0


def test_main_idempotent_on_second_run(tmp_path: Path) -> None:
    """Running main twice leaves the file byte-identical on the second run."""
    f = tmp_path / "form.yaml"
    f.write_text("form_id: m\nversion: '1.0'\nsections: []\n")

    main(["--roots", str(tmp_path)])
    after_first = f.read_text()

    main(["--roots", str(tmp_path)])
    after_second = f.read_text()

    assert after_first == after_second
    assert "tenant: navigator" in after_first
