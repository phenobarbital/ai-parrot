"""`parrot.self_.components` (FEAT-633, TASK-4079). subprocess.run is always mocked."""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest

from parrot.self_ import components


@pytest.fixture
def fake_managed_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """~/.parrot-like tree: bin/uv + venv with an interpreter stub + live data; sets PARROT_HOME."""
    home = tmp_path / "parrot-home"
    bindir = "Scripts" if os.name == "nt" else "bin"
    exe = ".exe" if os.name == "nt" else ""
    (home / "bin").mkdir(parents=True)
    (home / "bin" / f"uv{exe}").write_text("", encoding="utf-8")
    (home / "venv" / bindir).mkdir(parents=True)
    (home / "venv" / bindir / f"python{exe}").write_text("", encoding="utf-8")
    (home / "wikis.json").write_text("{}", encoding="utf-8")
    (home / "library").mkdir()
    monkeypatch.setenv("PARROT_HOME", str(home))
    return home


def test_install_component_managed(fake_managed_home: Path) -> None:
    """requires_pip goes to `uv pip install --python <managed python>`; post_install's python is substituted."""
    with mock.patch.object(components.subprocess, "run") as run:
        log = components.install_component("scraping", venv=fake_managed_home / "venv")
    first, second = (call.args[0] for call in run.call_args_list)
    assert first[1:4] == ["pip", "install", "--python"] and first[-1] == "ai-parrot-tools[scraping]"
    assert second[0] == first[4]  # the venv interpreter, not a bare "python"
    assert second[1:] == ["-m", "playwright", "install", "chromium"]
    assert log


def test_install_rejects_non_managed_venv_without_here(fake_managed_home: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="--here"):
        components.install_component("scraping", venv=tmp_path / "other-venv")


def test_install_here_targets_project_venv(fake_managed_home: Path, tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    bindir = "Scripts" if os.name == "nt" else "bin"
    exe = ".exe" if os.name == "nt" else ""
    (repo / ".venv" / bindir).mkdir(parents=True)
    (repo / ".venv" / bindir / f"python{exe}").write_text("", encoding="utf-8")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(components, "find_project_root", lambda argv, env, cwd: repo)
    with mock.patch.object(components.subprocess, "run") as run:
        components.install_component("scraping", venv=fake_managed_home / "venv", here=True)
    first = run.call_args_list[0].args[0]
    assert Path(first[first.index("--python") + 1]).is_relative_to(repo / ".venv")


def test_core_only_template_installs_nothing(fake_managed_home: Path) -> None:
    with mock.patch.object(components.subprocess, "run") as run:
        components.install_component("memory", venv=fake_managed_home / "venv")
    run.assert_not_called()


def test_unknown_component_raises_keyerror(fake_managed_home: Path) -> None:
    with pytest.raises(KeyError):
        components.install_component("no-such-toolkit", venv=fake_managed_home / "venv")


def test_bundled_uv_falls_back_to_path_with_warning(tmp_path: Path, monkeypatch, caplog) -> None:
    home = tmp_path / "empty-home"
    home.mkdir()
    monkeypatch.setenv("PARROT_HOME", str(home))
    monkeypatch.setattr(components.shutil, "which", lambda name: "/usr/bin/uv")
    with caplog.at_level("WARNING"):
        assert components.bundled_uv() == Path("/usr/bin/uv")
    assert "falling back" in caplog.text


def test_update_runtime_pins_version(fake_managed_home: Path) -> None:
    with mock.patch.object(components.subprocess, "run") as run:
        components.update_runtime("9.9.9")
    assert run.call_args.args[0][-2:] == ["ai-parrot==9.9.9", "ai-parrot-tools==9.9.9"]  # rev 0.5 C20: same pin


def test_update_runtime_unpinned_keeps_lockstep(fake_managed_home: Path) -> None:
    """Unpinned update: upgrade ai-parrot, then pin ai-parrot-tools to the resolved version."""
    with mock.patch.object(components.subprocess, "run") as run, \
         mock.patch.object(components, "_installed_version", return_value="9.9.9"):
        components.update_runtime()
    calls = [c.args[0] for c in run.call_args_list]
    assert calls[0][-2:] == ["--upgrade", "ai-parrot"]
    assert calls[-1][-1] == "ai-parrot-tools==9.9.9"


def test_uninstall_keeps_user_data(fake_managed_home: Path) -> None:
    components.uninstall_runtime(yes=True)
    assert not (fake_managed_home / "venv").exists() and not (fake_managed_home / "bin").exists()
    assert (fake_managed_home / "wikis.json").exists() and (fake_managed_home / "library").is_dir()


def test_uninstall_requires_yes(fake_managed_home: Path) -> None:
    with pytest.raises(PermissionError):
        components.uninstall_runtime(yes=False)
