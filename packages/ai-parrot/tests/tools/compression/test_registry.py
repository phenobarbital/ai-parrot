"""Unit tests for the TOML compressor manifest schema + CompressorRegistry
(TASK-1948).

The core default manifest (`compressors.toml`) names `json_compact`
(TASK-1949) and, since TASK-1954 added the `dq_execute_database_query`
entry, `columnar` (TASK-1954) too — both must be registered for
`CompressorRegistry.load()` to validate it. Importing
`parrot.tools.compression.codecs` (the real package both codecs live in)
registers them as an import side effect; done here via an autouse fixture
so these tests don't depend on collection order relative to
`test_json_compact.py`/`test_columnar.py`.
"""
import sys
from pathlib import Path

import pytest

from parrot.tools.compression import CompressorRegistry, FilterLevel


@pytest.fixture(autouse=True)
def _ensure_builtin_codecs_registered():
    """Ensure `json_compact`/`columnar` are registered before `load()`
    validates the core manifest. Plain `import` is idempotent (cached in
    `sys.modules`), so this is safe regardless of test order."""
    import parrot.tools.compression.codecs  # noqa: F401


@pytest.fixture
def compressors_toml(tmp_path):
    """Project-level .parrot/compressors.toml with exact/glob/wildcard entries."""
    d = tmp_path / ".parrot"
    d.mkdir()
    (d / "compressors.toml").write_text(
        '[compressor."execute_database_query"]\n'
        'codec = "json_compact"\nlevel = "normal"\ntee = true\n'
        '[compressor."execute_db_*"]\ncodec = "json_compact"\nlevel = "minimal"\n'
        '[compressor."*"]\ncodec = "json_compact"\nlevel = "minimal"\n'
    )
    return tmp_path


class TestCompressorRegistry:
    def test_filterlevel_default_minimal(self, tmp_path):
        """No config anywhere → effective entry level is MINIMAL."""
        reg = CompressorRegistry.load(project_root=tmp_path)
        assert reg.resolve("anything").level is FilterLevel.MINIMAL

    def test_resolution_exact_over_glob_over_wildcard(self, compressors_toml):
        reg = CompressorRegistry.load(project_root=compressors_toml)
        assert reg.resolve("execute_database_query").level is FilterLevel.NORMAL
        assert reg.resolve("execute_db_other").level is FilterLevel.MINIMAL
        assert reg.resolve("unrelated_tool").level is FilterLevel.MINIMAL

    def test_toml_unknown_codec_fails_at_load(self, tmp_path):
        d = tmp_path / ".parrot"
        d.mkdir()
        f = d / "compressors.toml"
        f.write_text('[compressor."x"]\ncodec = "colunmar"\n')
        with pytest.raises(ValueError) as exc:
            CompressorRegistry.load(project_root=tmp_path)
        assert str(f) in str(exc.value) and "colunmar" in str(exc.value)

    def test_malformed_toml_fails_at_load(self, tmp_path):
        d = tmp_path / ".parrot"
        d.mkdir()
        (d / "compressors.toml").write_text("[compressor.\n")
        with pytest.raises(Exception):
            CompressorRegistry.load(project_root=tmp_path)

    def test_shadowing_builtin_warns(self, tmp_path, caplog):
        d = tmp_path / ".parrot"
        d.mkdir()
        (d / "compressors.toml").write_text(
            '[compressor."*"]\ncodec = "json_compact"\nlevel = "normal"\n'
        )
        with caplog.at_level("WARNING"):
            CompressorRegistry.load(project_root=tmp_path)
        assert any("shadow" in r.message.lower() for r in caplog.records)

    def test_registry_immutable_after_load(self, tmp_path):
        reg = CompressorRegistry.load(project_root=tmp_path)
        with pytest.raises(Exception):
            reg.entries["*"] = None

    def test_missing_manifests_not_an_error(self, tmp_path):
        """Absent project/thirdparty manifests are skipped silently; core
        default still resolves."""
        reg = CompressorRegistry.load(
            project_root=tmp_path, thirdparty_sources=("nonexistent_pkg_xyz",)
        )
        assert reg.resolve("anything").codec == "json_compact"


def test_third_party_package_manifest_no_core_edits(tmp_path, monkeypatch):
    """G6: a third-party package declares a compressor via its own TOML,
    with zero edits to any parrot core file."""
    fixture_parent = Path(__file__).parent
    monkeypatch.syspath_prepend(str(fixture_parent))
    sys.modules.pop("fixture_pkg", None)

    reg = CompressorRegistry.load(
        project_root=tmp_path, thirdparty_sources=("fixture_pkg",)
    )
    entry = reg.resolve("fixture_pkg_tool")
    assert entry is not None
    assert entry.codec == "json_compact"
    assert entry.level is FilterLevel.NORMAL
