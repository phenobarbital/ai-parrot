"""Tests for the static techwiki API reference generator."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from parrot.sdd.scripts.techwiki_api import main
from parrot.sdd.techwiki.api import GriffeUnavailable, generate
from parrot.sdd.techwiki.config import TechwikiConfig, TechwikiPackage


def _require_griffe() -> None:
    """Skip static-rendering tests only when the declared optional extra is absent."""
    if importlib.util.find_spec("griffe") is None:
        pytest.skip("griffe extra is not installed")


@pytest.fixture
def techwiki_repo(tmp_path: Path) -> tuple[Path, TechwikiConfig]:
    """Build a minimal repository containing the static sample package."""
    fixture = Path(__file__).parent / "fixtures" / "techwiki_pkg"
    destination = tmp_path / "packages" / "sample" / "src"
    destination.mkdir(parents=True)
    for source in fixture.rglob("*.py"):
        target = destination / source.relative_to(fixture)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path, TechwikiConfig(
        packages=[TechwikiPackage(dist="sample", src="packages/sample/src", roots=["samplepkg"])]
    )


class TestGenerate:
    """Static generator behaviour."""

    def test_generate_static_no_import(self, techwiki_repo: tuple[Path, TechwikiConfig]) -> None:
        """Fixture package renders without import side effects."""
        _require_griffe()
        root, cfg = techwiki_repo
        before = set(sys.modules)
        pages, skipped = generate(cfg, root)
        assert not skipped
        assert pages
        assert not ({name for name in sys.modules if name.startswith("samplepkg")} - before)

    def test_generate_is_deterministic(self, techwiki_repo: tuple[Path, TechwikiConfig]) -> None:
        """Two runs return byte-identical output."""
        _require_griffe()
        root, cfg = techwiki_repo
        first, _ = generate(cfg, root)
        second, _ = generate(cfg, root)
        assert [(page.module, page.body) for page in first] == [(page.module, page.body) for page in second]

    def test_generate_satellite_coverage(self) -> None:
        """A configured satellite distribution can be rendered statically."""
        _require_griffe()
        root = Path(__file__).parents[3]
        cfg = TechwikiConfig(
            packages=[
                TechwikiPackage(dist="ai-parrot", src="packages/ai-parrot/src", roots=["parrot"]),
                TechwikiPackage(dist="ai-parrot-tools", src="packages/ai-parrot-tools/src", roots=["parrot_tools"]),
            ]
        )
        pages, _ = generate(cfg, root)
        assert any(page.module.startswith("parrot_tools") for page in pages)


class TestCli:
    """CLI dependency and strict exit paths."""

    def test_griffe_unavailable_exit_3(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Unavailable griffe returns the documented dependency exit code."""
        def unavailable(*args: object, **kwargs: object) -> tuple[list[object], list[dict[str, str]]]:
            raise GriffeUnavailable("griffe is not installed. Install with: pip install ai-parrot[techwiki]")

        monkeypatch.setattr("parrot.sdd.techwiki.api.generate", unavailable)
        assert main(["--out", str(tmp_path), "--root", str(tmp_path)]) == 3

    def test_generate_matches_golden(self, techwiki_repo: tuple[Path, TechwikiConfig]) -> None:
        """Core module output contains the stable golden documentation headings."""
        _require_griffe()
        root, cfg = techwiki_repo
        pages, _ = generate(cfg, root)
        core = next(page for page in pages if page.module == "samplepkg.core")
        golden = Path(__file__).parent / "fixtures" / "techwiki_golden" / "samplepkg.core.md"
        for line in golden.read_text(encoding="utf-8").splitlines():
            assert line in core.body

    def test_strict_fails_on_skipped_module(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Strict mode returns four when generation reports a skipped module."""
        monkeypatch.setattr(
            "parrot.sdd.techwiki.api.generate",
            lambda *args, **kwargs: ([], [{"module": "broken", "reason": "syntax error"}]),
        )
        (tmp_path / "sdd").mkdir()
        (tmp_path / "sdd" / "config.json").write_text('{"techwiki": {}}', encoding="utf-8")
        assert main(["--out", str(tmp_path / "out"), "--root", str(tmp_path), "--strict"]) == 4


class TestRenderingRules:
    """Public API filtering rules."""

    def test_all_honoured_and_private_excluded(self, techwiki_repo: tuple[Path, TechwikiConfig]) -> None:
        """The fixture's explicit exports exclude private and imported names."""
        _require_griffe()
        root, cfg = techwiki_repo
        pages, _ = generate(cfg, root)
        core = next(page for page in pages if page.module == "samplepkg.core")
        assert "_private" not in core.body
        assert "PublicModel" in core.body
        assert "format_value" in core.body
