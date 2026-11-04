"""Tests for technical-wiki configuration (FEAT-801)."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
from click.testing import CliRunner

from parrot.cli import cli
from parrot.sdd.config import SddConfig, load_sdd_config
from parrot.sdd.cli import mounted_modules
from parrot.sdd.techwiki.config import TechwikiConfig, TechwikiPackage, load_techwiki_config


class TestTechwikiConfig:
    """Configuration-model and workspace-inventory coverage tests."""

    def test_defaults_and_forbid_extra(self) -> None:
        """TechwikiConfig supplies defaults and rejects unknown keys."""
        cfg = TechwikiConfig()
        assert cfg.source_dir == "wiki"
        with pytest.raises(Exception):
            TechwikiConfig(unknown_key="x")

    def test_sdd_config_techwiki_roundtrip(self, tmp_path: Path) -> None:
        """SddConfig.techwiki loads a valid ``techwiki`` configuration section."""
        (tmp_path / "sdd").mkdir()
        (tmp_path / "sdd" / "config.json").write_text(
            json.dumps(
                {
                    "techwiki": {
                        "source_dir": "technical-wiki",
                        "packages": [{"dist": "demo", "src": "packages/demo/src", "roots": ["demo"]}],
                    }
                }
            ),
            encoding="utf-8",
        )

        cfg = load_sdd_config(tmp_path)

        assert isinstance(cfg, SddConfig)
        assert cfg.techwiki == TechwikiConfig(
            source_dir="technical-wiki",
            packages=[TechwikiPackage(dist="demo", src="packages/demo/src", roots=["demo"])],
        )

    def test_load_techwiki_config_absent(self, tmp_path: Path) -> None:
        """A configuration without ``techwiki`` returns its defaults."""
        (tmp_path / "sdd").mkdir()
        (tmp_path / "sdd" / "config.json").write_text('{"base_branch": "dev"}', encoding="utf-8")

        cfg = load_techwiki_config(tmp_path)

        assert cfg.packages == []

    def test_techwiki_cli_noun_mounts_expected_commands(self) -> None:
        """The technical-wiki noun exposes all four planned subcommands."""
        result = CliRunner().invoke(cli, ["sdd", "techwiki", "--help"])

        assert result.exit_code == 0, result.output
        assert {"techwiki_api", "techwiki_bundle", "techwiki_check"} <= mounted_modules()
        for command in ("api", "bundle", "check", "sidebar"):
            assert command in result.output

    def test_workspace_python_distribution_coverage(self) -> None:
        """Configured distributions cover every workspace member shipping Python sources."""
        root = Path(__file__).resolve().parents[4]
        configured = {(package.dist, package.src) for package in load_techwiki_config(root).packages}
        expected = {
            (
                tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["name"],
                str(pyproject.parent.relative_to(root) / "src"),
            )
            for pyproject in (root / "packages").glob("*/pyproject.toml")
            if any((pyproject.parent / "src").rglob("*.py")) or any((pyproject.parent / "src").rglob("*.pyi"))
        }

        assert configured == expected
