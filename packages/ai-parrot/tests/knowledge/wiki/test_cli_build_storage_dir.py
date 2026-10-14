"""Hermetic behavioral tests for FEAT-672."""

import sys
import types
from pathlib import Path

from click.testing import CliRunner

if "parrot.utils.types" not in sys.modules:
    _utils_types_stub = types.ModuleType("parrot.utils.types")
    _utils_types_stub.SafeDict = dict
    sys.modules["parrot.utils.types"] = _utils_types_stub
if "parrot.utils.parsers.toml" not in sys.modules:
    _toml_stub = types.ModuleType("parrot.utils.parsers.toml")
    _toml_stub.TOMLParser = object
    sys.modules["parrot.utils.parsers.toml"] = _toml_stub

from parrot.knowledge.wiki.cli import wiki  # noqa: E402
from parrot.knowledge.wiki.project import load_project_config, save_project_config  # noqa: E402


def _write_source(root: Path) -> None:
    """Create the smallest source fixture accepted by the repository scanner."""
    root.mkdir()
    (root / "module.py").write_text('"""Fixture module."""\n\nVALUE = 1\n', encoding="utf-8")


def _build(root: Path, *options: str) -> object:
    """Build a fixture repository with optional storage configuration."""
    return CliRunner().invoke(
        wiki,
        ["build", "--path", str(root), "--no-git", "--no-export", "--no-graph", "--quiet", *options],
    )


def test_build_storage_dir_overrides_plane_location(tmp_path: Path) -> None:
    """`--storage-dir` places the plane at the absolute path, not `<root>/.parrot/wiki`."""
    root = tmp_path / "repo"
    storage_dir = tmp_path / "external-plane"
    _write_source(root)

    result = _build(root, "--storage-dir", str(storage_dir))

    assert result.exit_code == 0, result.output
    assert (storage_dir / "wiki.db").exists()
    assert not (root / ".parrot" / "wiki").exists()


def test_build_storage_dir_does_not_persist_config(tmp_path: Path) -> None:
    """An override leaves an existing config byte-for-byte unchanged and creates no overlay."""
    root = tmp_path / "repo"
    storage_dir = tmp_path / "external-plane"
    _write_source(root)
    config = load_project_config(root)
    config.wiki_name = "configured"
    save_project_config(root, config)
    config_path = root / ".parrot" / "wiki.json"
    original_config = config_path.read_bytes()

    result = _build(root, "--storage-dir", str(storage_dir))

    assert result.exit_code == 0, result.output
    assert config_path.read_bytes() == original_config
    assert not (root / ".parrot" / "wiki.local.json").exists()


def test_build_storage_dir_rejects_relative_path(tmp_path: Path) -> None:
    """A relative value raises `ClickException`."""
    root = tmp_path / "repo"
    _write_source(root)

    result = _build(root, "--storage-dir", "relative-plane")

    assert result.exit_code != 0
    assert "--storage-dir must be an absolute path" in result.output
    assert not (root / ".parrot").exists()


def test_build_without_storage_dir_unchanged(tmp_path: Path) -> None:
    """Omitting the flag keeps today's persistence behaviour."""
    root = tmp_path / "repo"
    _write_source(root)

    result = _build(root)

    assert result.exit_code == 0, result.output
    assert (root / ".parrot" / "wiki.json").exists()
    assert (root / ".parrot" / "wiki.local.json").exists()
    assert (root / ".parrot" / "wiki" / "wiki.db").exists()
