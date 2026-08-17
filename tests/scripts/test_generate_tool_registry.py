"""Regression tests for scripts/generate_tool_registry.py.

Covers the ast.AnnAssign blindspot fixed in FEAT-427: TOOL_REGISTRY /
LOADER_REGISTRY are declared as annotated assignments
(``NAME: dict[str, str] = {...}``), which the AST represents as
``ast.AnnAssign``, not ``ast.Assign``. These tests exercise both the
unannotated (regression-proof) and annotated (bug-fix-proof) forms,
plus the "bare annotation, no value" edge case.
"""
import subprocess
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import generate_tool_registry as gtr


ANNASSIGN_SOURCE = textwrap.dedent('''
    """Docstring."""

    TOOL_REGISTRY: dict[str, str] = {
        "foo": "pkg.mod.Foo",
    }
    ''')

PLAIN_ASSIGN_SOURCE = textwrap.dedent('''
    """Docstring."""

    TOOL_REGISTRY = {
        "foo": "pkg.mod.Foo",
    }
    ''')

BARE_ANNOTATION_SOURCE = textwrap.dedent('''
    """Docstring."""

    TOOL_REGISTRY: dict[str, str]
    ''')


def test_read_existing_registry_annassign(tmp_path):
    init_file = tmp_path / "__init__.py"
    init_file.write_text(ANNASSIGN_SOURCE)
    result = gtr.read_existing_registry(init_file, "TOOL_REGISTRY")
    assert result == {"foo": "pkg.mod.Foo"}


def test_read_existing_registry_plain_assign_unchanged(tmp_path):
    init_file = tmp_path / "__init__.py"
    init_file.write_text(PLAIN_ASSIGN_SOURCE)
    result = gtr.read_existing_registry(init_file, "TOOL_REGISTRY")
    assert result == {"foo": "pkg.mod.Foo"}


def test_read_existing_registry_bare_annotation_no_value(tmp_path):
    init_file = tmp_path / "__init__.py"
    init_file.write_text(BARE_ANNOTATION_SOURCE)
    result = gtr.read_existing_registry(init_file, "TOOL_REGISTRY")
    assert result is None


def test_update_init_file_rewrites_annassign_in_place(tmp_path):
    init_file = tmp_path / "__init__.py"
    init_file.write_text(ANNASSIGN_SOURCE)
    new_registry = {"foo": "pkg.mod.Foo", "bar": "pkg.mod.Bar"}
    changed, _diff = gtr.update_init_file(init_file, "TOOL_REGISTRY", new_registry)
    assert changed is True
    new_content = init_file.read_text()
    assert "TOOL_REGISTRY: dict[str, str] = {" in new_content
    assert '"bar": "pkg.mod.Bar"' in new_content


def test_scan_exports_annassign(tmp_path):
    pkg_dir = tmp_path / "pkg"
    pkg_dir.mkdir()
    (pkg_dir / "mod.py").write_text(
        'LOADER_MAPPING: dict[str, str] = {"x": "y"}\n'
    )
    result = gtr.scan_exports(pkg_dir, "pkg", ["LOADER_MAPPING"])
    assert result == {"LOADER_MAPPING": "pkg.mod.LOADER_MAPPING"}


def test_check_mode_clean_on_current_repo_files():
    tools_scanned = gtr.scan_classes(
        gtr.TOOLS_PKG_DIR, gtr.TOOL_SUFFIXES, gtr.TOOL_BASE_CLASSES, "parrot_tools"
    )
    changed, _diff = gtr.update_init_file(
        gtr.TOOLS_INIT, "TOOL_REGISTRY", tools_scanned, dry_run=True
    )
    assert changed is False

    loaders_scanned = gtr.scan_classes(
        gtr.LOADERS_PKG_DIR, gtr.LOADER_SUFFIXES, gtr.LOADER_BASE_CLASSES, "parrot_loaders"
    )
    factory_exports = gtr.scan_exports(
        gtr.LOADERS_PKG_DIR, "parrot_loaders", ["get_loader_class", "LOADER_MAPPING"]
    )
    loaders_scanned.update(factory_exports)
    changed, _diff = gtr.update_init_file(
        gtr.LOADERS_INIT, "LOADER_REGISTRY", loaders_scanned, dry_run=True
    )
    assert changed is False


def test_check_cli_exits_zero_on_repo():
    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "generate_tool_registry.py"), "--check"],
        capture_output=True,
        text=True,
        cwd=repo_root,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
