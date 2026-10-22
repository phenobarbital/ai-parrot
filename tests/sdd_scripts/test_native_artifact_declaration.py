"""Contract tests for the [tool.parrot.worktree] native-artifact declaration (FEAT-722).

These read the TOML and the Makefile directly — never
`parrot.flows.dev_loop.native_artifacts`, which TASK-4606 adds — so the
declaration is gated independently of the helper that consumes it.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
NAVRULES = REPO_ROOT / "packages" / "navrules"


def _worktree_table() -> dict:
    """The parsed ``[tool.parrot.worktree]`` table of the root pyproject.toml."""
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["tool"]["parrot"]["worktree"]


def _group(name: str) -> dict:
    """The declared native group called ``name``."""
    return next(group for group in _worktree_table()["native_group"] if group["name"] == name)


def _makefile_recipe(target: str) -> str:
    """The TAB-indented recipe lines of ``target`` in the navrules Makefile."""
    lines = (NAVRULES / "Makefile").read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{target}:"))
    recipe: list[str] = []
    for line in lines[start + 1 :]:
        if not line.startswith("\t"):
            break
        recipe.append(line)
    return "\n".join(recipe)


def test_table_declares_both_groups() -> None:
    table = _worktree_table()
    assert table["enabled"] is True
    assert [group["name"] for group in table["native_group"]] == ["cython-core", "navrules-pyo3"]


def test_every_group_is_autobuildable() -> None:
    """Spec §8 Q1: both groups build automatically when their artifact is missing."""
    for group in _worktree_table()["native_group"]:
        assert group["autobuild"] is True, group["name"]
        assert group["build"], group["name"]
        assert group["manual_hint"], group["name"]


def test_cython_group_pairs_sources_with_artifacts() -> None:
    group = _group("cython-core")
    assert group["copy_globs"] == ["packages/ai-parrot/src/parrot/**/*.so"]
    assert group["pair_sources"] == ["packages/ai-parrot/src/parrot/**/*.pyx"]
    assert group["abi_scoped"] is True
    assert group["build"] == ["{python}", "setup.py", "build_ext", "--inplace"]
    assert group["build_cwd"] == "packages/ai-parrot"


def test_navrules_group_targets_the_wheel_build() -> None:
    group = _group("navrules-pyo3")
    assert group["copy_globs"] == ["packages/navrules/src/navrules/_native/*.so"]
    assert group["abi_scoped"] is False
    assert group["build"] == ["make", "-C", "packages/navrules", "build-rust-wheel"]


def test_navrules_wheel_target_never_installs_into_the_shared_venv() -> None:
    """`maturin develop` reinstalls navrules into the active env — banned here."""
    recipe = _makefile_recipe("build-rust-wheel")
    assert "maturin build" in recipe
    assert "--locked" in recipe
    assert "maturin develop" not in recipe


def test_cargo_lock_pins_the_current_crate_version() -> None:
    """A `--locked` build fails unless the lock matches rust/Cargo.toml."""
    cargo_toml = (NAVRULES / "rust" / "Cargo.toml").read_text(encoding="utf-8")
    declared = re.search(r'^version = "([^"]+)"', cargo_toml, re.MULTILINE)
    assert declared is not None
    locked = re.search(
        r'name = "navrules_native"\nversion = "([^"]+)"',
        (NAVRULES / "rust" / "Cargo.lock").read_text(encoding="utf-8"),
    )
    assert locked is not None
    assert locked.group(1) == declared.group(1)
