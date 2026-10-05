"""Focused FEAT-626 regression and failure-path tests for inbox configuration."""

import itertools
import json
from pathlib import Path

import pytest

from parrot.knowledge.wiki.project import (
    InboxConfig,
    WikiConfigError,
    WikiProjectConfig,
    load_effective_config,
    validate_inbox_paths,
)


@pytest.fixture(autouse=True)
def _isolate_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep HOME/XDG/PARROT_HOME and wiki env selection inside tmp_path."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "parrot_home"))
    monkeypatch.delenv("PARROT_WIKI_ENV", raising=False)
    monkeypatch.delenv("ENV", raising=False)


def test_inbox_config_defaults_and_paths(tmp_path: Path) -> None:
    """Cover default, relative and absolute repository-contained paths."""
    cfg = WikiProjectConfig()
    assert cfg.inbox == InboxConfig()
    assert cfg.inbox.dir == "inbox"
    assert cfg.inbox.archive_dir == ".parrot/archive"
    assert cfg.inbox.rejected_subdir == "rejected"
    assert cfg.inbox.markdown_dir is None
    assert cfg.inbox.date_format == "%Y-%m-%d"
    assert cfg.inbox.stage_git is True
    assert cfg.inbox.max_candidates == 20
    assert cfg.inbox.lock_timeout == 30.0
    assert cfg.inbox_path(tmp_path) == tmp_path / "inbox"
    assert cfg.archive_path(tmp_path) == tmp_path / ".parrot/archive"
    assert cfg.inbox_markdown_path(tmp_path) == cfg.storage_path(tmp_path) / "inbox"

    custom = WikiProjectConfig(inbox=InboxConfig(dir=str(tmp_path / "abs_in"), archive_dir="arch", markdown_dir="md"))
    assert custom.inbox_path(tmp_path) == tmp_path / "abs_in"
    assert custom.archive_path(tmp_path) == tmp_path / "arch"
    assert custom.inbox_markdown_path(tmp_path) == tmp_path / "md"
    absolute_md = WikiProjectConfig(inbox=InboxConfig(markdown_dir=str(tmp_path / "x")))
    assert absolute_md.inbox_markdown_path(tmp_path) == tmp_path / "x"


@pytest.mark.parametrize("bad", [{"max_candidates": 0}, {"max_candidates": 101}, {"lock_timeout": -1.0}])
def test_inbox_bounds(bad: dict) -> None:
    """Numeric bounds are enforced."""
    with pytest.raises(ValueError):
        InboxConfig(**bad)


def test_env_overlay_merges_inbox(tmp_path: Path) -> None:
    """An inbox.dir-only overlay replaces the nested model with its own defaults."""
    parrot = tmp_path / ".parrot"
    parrot.mkdir()
    (parrot / "wiki.json").write_text(json.dumps({"inbox": {"dir": "base_in", "max_candidates": 5}}), encoding="utf-8")
    (parrot / "wiki.dev.json").write_text(json.dumps({"inbox": {"dir": "overlay_in"}}), encoding="utf-8")
    eff = load_effective_config(tmp_path, env="dev")
    assert isinstance(eff.config.inbox, InboxConfig)
    assert eff.config.inbox.dir == "overlay_in"
    assert eff.config.inbox.max_candidates == 20
    base_only = load_effective_config(tmp_path, env="nonexistent")
    assert base_only.config.inbox.dir == "base_in"
    assert base_only.config.inbox.max_candidates == 5


@pytest.mark.parametrize(
    "kwargs",
    [
        {"dir": ""},
        {"dir": "   "},
        {"archive_dir": ""},
        {"rejected_subdir": ""},
        {"rejected_subdir": "a/b"},
        {"rejected_subdir": "a\\b"},
        {"rejected_subdir": ".."},
        {"rejected_subdir": "x..y"},
    ],
)
def test_unsafe_layout_rejected(kwargs: dict) -> None:
    """Empty paths and unsafe rejected_subdir values are rejected."""
    with pytest.raises(ValueError):
        InboxConfig(**kwargs)


def test_validate_inbox_paths(tmp_path: Path) -> None:
    """Reject escapes, equality, nesting and symlinks; accept disjoint siblings."""
    root = tmp_path / "repo"
    root.mkdir()
    ok = {name: root / name for name in ("a", "b", "c")}
    before = sorted(p.name for p in root.iterdir())
    validate_inbox_paths(root, ok["a"], ok["b"], ok["c"])
    assert sorted(p.name for p in root.iterdir()) == before  # no writes

    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(WikiConfigError):
        validate_inbox_paths(root, outside, ok["b"], ok["c"])
    with pytest.raises(WikiConfigError):
        validate_inbox_paths(root, ok["a"], root / ".." / "outside", ok["c"])
    with pytest.raises(WikiConfigError):
        validate_inbox_paths(root, root, ok["b"], ok["c"])

    # symlink escape
    (root / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(WikiConfigError):
        validate_inbox_paths(root, root / "link", ok["b"], ok["c"])

    # symlink-resolved nesting
    (root / "a").mkdir()
    (root / "alias").symlink_to(root / "a", target_is_directory=True)
    with pytest.raises(WikiConfigError):
        validate_inbox_paths(root, root / "a", root / "alias" / "sub", ok["c"])


def _paths(root: Path) -> dict[str, Path]:
    return {"equal": root / "x", "parent": root / "x", "child": root / "x" / "y"}


@pytest.mark.parametrize("pair", list(itertools.permutations(range(3), 2)))
@pytest.mark.parametrize("relation", ["equal", "nested"])
def test_validate_inbox_paths_pairs(tmp_path: Path, pair: tuple[int, int], relation: str) -> None:
    """Every ordered pair of equal or nested paths is rejected."""
    root = tmp_path / "repo"
    root.mkdir()
    slots = [root / "p0", root / "p1", root / "p2"]
    first, second = pair
    slots[second] = slots[first] if relation == "equal" else slots[first] / "child"
    with pytest.raises(WikiConfigError):
        validate_inbox_paths(root, *slots)
