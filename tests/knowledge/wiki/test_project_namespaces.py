"""Unit tests for FEAT-450 namespace declaration (project.py, Module 1)."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from parrot.knowledge.wiki.project import (
    GlobalWikiRegistry,
    WikiConfigError,
    WikiNamespaceConfig,
    WikiProjectConfig,
    global_registry_path,
    load_global_registry,
    merge_namespaces,
    parrot_home,
    resolve_entry_base,
    save_global_registry,
    validate_namespace_name,
)
from pydantic import ValidationError


@pytest.fixture
def parrot_home_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect PARROT_HOME at a temp dir for registry tests."""
    home = tmp_path / "home"
    monkeypatch.setenv("PARROT_HOME", str(home))
    return home


# --------------------------------------------------------------------------
# WikiNamespaceConfig
# --------------------------------------------------------------------------


def test_namespace_config_exactly_one_source() -> None:
    assert WikiNamespaceConfig(path="../asyncdb").kind == "path"
    with pytest.raises(ValidationError):
        WikiNamespaceConfig()
    with pytest.raises(ValidationError):
        WikiNamespaceConfig(path="a", vault="b")
    with pytest.raises(ValidationError):
        WikiNamespaceConfig(store="s", database="d")


def test_namespace_config_kind_and_target() -> None:
    assert WikiNamespaceConfig(store="/s").kind == "store"
    assert WikiNamespaceConfig(vault="/v").kind == "vault"
    assert WikiNamespaceConfig(vault="/v").target == "/v"


def test_database_forces_arangodb() -> None:
    cfg = WikiNamespaceConfig(database="wiki_legal")
    assert cfg.kind == "database"
    assert cfg.backend == "arangodb"


def test_namespace_config_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        WikiNamespaceConfig(vaults="/v")  # type: ignore[call-arg]


def test_namespace_weight_bounds() -> None:
    assert WikiNamespaceConfig(path="p", weight=0.0).weight == 0.0
    with pytest.raises(ValidationError):
        WikiNamespaceConfig(path="p", weight=1.5)


# --------------------------------------------------------------------------
# Name validation
# --------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["all", "local", "a::b", "", "-x", "a b", "_x"])
def test_namespace_name_validation_rejects(bad: str) -> None:
    with pytest.raises(ValueError):
        validate_namespace_name(bad)


@pytest.mark.parametrize("good", ["asyncdb", "legal:civil", "n1", "a.b-c_d"])
def test_namespace_name_validation_accepts(good: str) -> None:
    assert validate_namespace_name(good) == good


def test_project_config_rejects_reserved_key() -> None:
    with pytest.raises(ValidationError):
        WikiProjectConfig.model_validate(
            {"namespaces": {"all": {"path": "/x"}}}
        )


def test_registry_rejects_reserved_key() -> None:
    with pytest.raises(ValidationError):
        GlobalWikiRegistry.model_validate(
            {"namespaces": {"local": {"path": "/x"}}}
        )


# --------------------------------------------------------------------------
# WikiProjectConfig compatibility
# --------------------------------------------------------------------------


def test_wiki_project_config_defaults_keep_hook_compat() -> None:
    cfg = WikiProjectConfig.model_validate({"wiki_name": "x"})
    assert cfg.namespaces == {}


def test_legacy_config_file_without_namespaces_loads(tmp_path: Path) -> None:
    from parrot.knowledge.wiki.project import (
        config_path,
        load_project_config,
        save_project_config,
    )

    root = tmp_path / "repo"
    (root / ".parrot").mkdir(parents=True)
    config_path(root).write_text(
        json.dumps({"wiki_name": "legacy", "storage_dir": ".parrot/wiki"}),
        encoding="utf-8",
    )
    cfg = load_project_config(root)
    assert cfg.namespaces == {}

    cfg.namespaces["other"] = WikiNamespaceConfig(path="../other")
    save_project_config(root, cfg)
    reloaded = load_project_config(root)
    assert reloaded.namespaces["other"].path == "../other"
    assert reloaded.namespaces["other"].kind == "path"


# --------------------------------------------------------------------------
# Global registry
# --------------------------------------------------------------------------


def test_global_registry_roundtrip_and_missing(parrot_home_dir: Path) -> None:
    assert global_registry_path() == parrot_home_dir / "wikis.json"
    assert load_global_registry().namespaces == {}

    written = save_global_registry(
        GlobalWikiRegistry(namespaces={"n": WikiNamespaceConfig(store="/s")})
    )
    assert written == global_registry_path()
    assert stat.S_IMODE(written.stat().st_mode) == 0o600
    assert load_global_registry().namespaces["n"].kind == "store"


def test_global_registry_invalid_raises(parrot_home_dir: Path) -> None:
    path = global_registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(WikiConfigError):
        load_global_registry()


def test_global_registry_save_leaves_no_temp_files(
    parrot_home_dir: Path,
) -> None:
    save_global_registry(
        GlobalWikiRegistry(namespaces={"n": WikiNamespaceConfig(path="/p")})
    )
    assert sorted(p.name for p in parrot_home_dir.iterdir()) == ["wikis.json"]


def test_parrot_home_env_is_read_per_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "a"))
    assert parrot_home() == tmp_path / "a"
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "b"))
    assert parrot_home() == tmp_path / "b"


# --------------------------------------------------------------------------
# merge_namespaces / resolve_entry_base
# --------------------------------------------------------------------------


def test_merge_namespaces_repo_wins() -> None:
    merged = merge_namespaces(
        {"a": WikiNamespaceConfig(path="r")},
        {
            "a": WikiNamespaceConfig(path="g"),
            "b": WikiNamespaceConfig(path="g"),
        },
    )
    assert merged["a"][0].path == "r"
    assert merged["a"][1] == "repo"
    assert merged["b"][1] == "global"


def test_resolve_entry_base(parrot_home_dir: Path, tmp_path: Path) -> None:
    root = tmp_path / "repo"
    assert resolve_entry_base("repo", root) == root
    assert resolve_entry_base("global", root) == parrot_home_dir
