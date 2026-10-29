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


def test_credentials_file_created_private_from_template(fake_managed_home: Path, monkeypatch) -> None:
    """The bootstrap's starter credentials file: navconfig's env/.env under PARROT_HOME, every value commented out."""
    monkeypatch.delenv("ENV", raising=False)
    path, created = components.ensure_credentials_file()
    assert created and path == fake_managed_home / "env" / ".env"
    text = path.read_text(encoding="utf-8")
    assert text == components.CREDENTIALS_TEMPLATE
    assert "# ANTHROPIC_API_KEY=" in text and "# OPENAI_API_KEY=" in text
    assert all(line == "" or line.startswith("#") for line in text.splitlines()), "no live assignment may ship"
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.parent.stat().st_mode & 0o777 == 0o700


def test_credentials_file_follows_navconfig_env(fake_managed_home: Path, monkeypatch) -> None:
    """With ENV set, navconfig reads env/<ENV>/.env, so that is the file created."""
    monkeypatch.setenv("ENV", "dev")
    path, created = components.ensure_credentials_file()
    assert created and path == fake_managed_home / "env" / "dev" / ".env"
    if os.name != "nt":  # every directory the call creates is owner-only, not just the leaf
        assert (fake_managed_home / "env").stat().st_mode & 0o777 == 0o700
        assert (fake_managed_home / "env" / "dev").stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize("value", ["../../outside", "/etc", "a/b", "..", "."])
def test_credentials_file_rejects_non_plain_env(fake_managed_home: Path, monkeypatch, value: str) -> None:
    """An ENV that is not a plain name would put the file outside PARROT_HOME/env: refused, nothing created."""
    monkeypatch.setenv("ENV", value)
    with pytest.raises(ValueError):
        components.ensure_credentials_file()
    assert not (fake_managed_home / "env").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks")
def test_credentials_file_never_follows_a_symlink(fake_managed_home: Path, tmp_path: Path, monkeypatch) -> None:
    """A symlink at the target, dangling or not, is kept as is: nothing is created at or through it."""
    monkeypatch.delenv("ENV", raising=False)
    (fake_managed_home / "env").mkdir()
    victim = tmp_path / "victim"
    link = fake_managed_home / "env" / ".env"
    link.symlink_to(victim)  # dangling
    assert components.ensure_credentials_file() == (link, False)
    assert not victim.exists() and link.is_symlink()
    victim.write_text("theirs\n", encoding="utf-8")
    assert components.ensure_credentials_file() == (link, False)
    assert victim.read_text(encoding="utf-8") == "theirs\n"


def test_credentials_partial_write_is_removed(fake_managed_home: Path, monkeypatch) -> None:
    """A write that fails after the exclusive create leaves no truncated file that later runs would 'keep'."""
    monkeypatch.delenv("ENV", raising=False)
    real_fdopen = os.fdopen

    def failing_fdopen(fd, *args, **kwargs):
        handle = real_fdopen(fd, *args, **kwargs)
        handle.write = mock.Mock(side_effect=OSError(28, "No space left on device"))
        return handle

    monkeypatch.setattr(components.os, "fdopen", failing_fdopen)
    with pytest.raises(OSError):
        components.ensure_credentials_file()
    assert not (fake_managed_home / "env" / ".env").exists()


def test_restrict_to_owner_windows_acl(tmp_path: Path, monkeypatch) -> None:
    """Windows ignores mode bits: the new file gets an owner-only ACL via icacls; a failure only warns."""
    target = tmp_path / ".env"
    monkeypatch.setenv("USERNAME", "alice")
    with mock.patch.object(components.subprocess, "run", return_value=mock.Mock(returncode=0)) as run:
        monkeypatch.setattr(components.os, "name", "nt")
        components._restrict_to_owner(target)
        monkeypatch.setattr(components.os, "name", "posix")
    assert run.call_args.args[0] == ["icacls", str(target), "/inheritance:r", "/grant:r", "alice:F"]
    with mock.patch.object(components.subprocess, "run") as run:
        components._restrict_to_owner(target)  # POSIX: mode 0600 already applies, no icacls
    run.assert_not_called()


def test_credentials_file_never_overwritten(fake_managed_home: Path, monkeypatch) -> None:
    monkeypatch.delenv("ENV", raising=False)
    existing = fake_managed_home / "env" / ".env"
    existing.parent.mkdir()
    existing.write_text("OPENAI_API_KEY=sk-real\n", encoding="utf-8")
    existing.chmod(0o640)
    path, created = components.ensure_credentials_file()
    assert not created and path == existing
    assert existing.read_text(encoding="utf-8") == "OPENAI_API_KEY=sk-real\n"
    if os.name != "nt":
        assert existing.stat().st_mode & 0o777 == 0o640


def test_uninstall_keeps_credentials(fake_managed_home: Path, monkeypatch) -> None:
    monkeypatch.delenv("ENV", raising=False)
    path, _ = components.ensure_credentials_file()
    components.uninstall_runtime(yes=True)
    assert path.read_text(encoding="utf-8") == components.CREDENTIALS_TEMPLATE


def test_navconfig_ini_created_empty(fake_managed_home: Path) -> None:
    """Owner decision: an empty etc/config.ini under PARROT_HOME silences navconfig's missing-INI warning."""
    path, created = components.ensure_navconfig_ini()
    assert created and path == fake_managed_home / "etc" / "config.ini"
    assert path.read_bytes() == b""


def test_navconfig_ini_never_overwritten(fake_managed_home: Path) -> None:
    existing = fake_managed_home / "etc" / "config.ini"
    existing.parent.mkdir()
    existing.write_text("[general]\nDEBUG = true\n", encoding="utf-8")
    assert components.ensure_navconfig_ini() == (existing, False)
    assert existing.read_text(encoding="utf-8") == "[general]\nDEBUG = true\n"


def test_uninstall_keeps_navconfig_ini(fake_managed_home: Path) -> None:
    path, _ = components.ensure_navconfig_ini()
    components.uninstall_runtime(yes=True)
    assert path.is_file()
