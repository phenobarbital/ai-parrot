"""Component install engine for ``parrot self`` (FEAT-633, spec §3 M3).

Synchronous by design: only the one-shot ``parrot self`` CLI calls this module.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from parrot.launcher import find_project_root, parrot_home, script_path  # TASK-4071
from parrot.mcp.toolkit_seed import load_template  # verified: mcp/toolkit_seed.py:63

logger = logging.getLogger(__name__)

#: Only these children of ``parrot_home()`` belong to the runtime (spec §7).
RUNTIME_DIRS: tuple[str, ...] = ("bin", "venv", "python")
#: Distribution upgraded by ``update_runtime``.
CORE_DIST: str = "ai-parrot"
#: Spec rev 0.5 C20 — part of the base runtime, always at the same version pin as CORE_DIST.
TOOLS_DIST: str = "ai-parrot-tools"
BASE_DISTS: tuple[str, ...] = (CORE_DIST, TOOLS_DIST)


def managed_venv() -> Path:
    """Return ``parrot_home()/'venv'`` (the managed venv)."""
    return parrot_home() / "venv"


def bundled_uv() -> Path:
    """Return the pinned uv placed by the ``--global`` bootstrap.

    ``parrot_home()/'bin'/'uv'`` (``uv.exe`` on Windows). Falls back to ``shutil.which('uv')``
    with a logged warning so dev setups without the bootstrap still work.

    Raises:
        FileNotFoundError: neither the bundled uv nor a PATH uv exists.
    """
    bundled = parrot_home() / "bin" / ("uv.exe" if os.name == "nt" else "uv")
    if bundled.is_file():
        return bundled
    found = shutil.which("uv")
    if found:
        logger.warning("bundled uv missing at %s; falling back to %s", bundled, found)
        return Path(found)
    raise FileNotFoundError(f"uv not found at {bundled} nor on PATH — run install-parrot --global")


def _venv_python(venv: Path) -> Path:
    """Interpreter of ``venv`` (``bin/python`` or ``Scripts\\python.exe``)."""
    python = script_path(venv, "python")
    if not python.exists():
        raise FileNotFoundError(f"no interpreter in venv {venv} (expected {python})")
    return python


def _project_venv() -> Path:
    """The project venv ``--here`` targets: ``<project root>/.venv``.

    Raises:
        FileNotFoundError: no project root, or the root has no ``.venv``.
    """
    root = find_project_root(sys.argv[1:], os.environ, Path.cwd())
    if root is None:
        raise FileNotFoundError(f"no project root found from {Path.cwd()} — cannot use --here")
    candidate = root / ".venv"
    _venv_python(candidate)  # raises FileNotFoundError when the project has no usable .venv
    return candidate


def _run(argv: list[str], log: list[str]) -> None:
    """Run one argv (no shell, check=True) and record it in ``log``."""
    logger.info("running: %s", argv)
    log.append("$ " + " ".join(argv))
    subprocess.run(argv, check=True)


def install_component(name: str, *, venv: Path, here: bool = False) -> list[str]:
    """Install toolkit template ``name``'s ``requires_pip`` and run its ``post_install``.

    Args:
        name: Packaged toolkit template name (``available_templates()``).
        venv: Target venv when ``here`` is False — MUST be the managed venv.
        here: Target the project venv instead (the only path into a project).

    Returns:
        Human-readable action log.

    Raises:
        KeyError: unknown template.
        ValueError: ``here`` is False and ``venv`` is not the managed venv.
        FileNotFoundError: no uv, or the target venv has no interpreter.
        subprocess.CalledProcessError: uv or post_install failed.
    """
    template = load_template(name)
    target = _project_venv() if here else Path(venv)
    if not here and target.resolve() != managed_venv().resolve():
        raise ValueError(f"refusing to install into {target}: use --here for a project venv")
    python = _venv_python(target)
    log: list[str] = [f"target venv: {target} ({'project' if here else 'managed'})"]
    if not template.requires_pip:
        log.append(f"{name}: nothing to install (core-only toolkit)")
        return log
    _run([str(bundled_uv()), "pip", "install", "--python", str(python), *template.requires_pip], log)
    if template.post_install:
        argv = list(template.post_install)
        if argv[0] == "python":
            argv[0] = str(python)  # leading `python` placeholder = target venv interpreter (TASK-4077 contract)
        _run(argv, log)
    log.append(f"{name}: installed — now run `parrot toolkits install {name}` to expose it")
    return log


def update_runtime(version: str | None = None) -> list[str]:
    """Upgrade the base runtime (ai-parrot + ai-parrot-tools, spec rev 0.5 C20) in the managed venv.

    Both distributions always end at the same version (lockstep, C20). With ``version`` both get
    ``==version``. Without it, ``ai-parrot`` is upgraded first and ``ai-parrot-tools`` is then pinned
    to the ``ai-parrot`` version that uv resolved (resolved in the PR #1746 review, 2026-10-20).
    """
    python = _venv_python(managed_venv())
    uv = str(bundled_uv())
    log: list[str] = []
    # No state file exists and uv keeps already-installed extras, so a plain `--upgrade` suffices (spec §1, §7).
    if version:
        _run([uv, "pip", "install", "--python", str(python), "--upgrade", *(f"{d}=={version}" for d in BASE_DISTS)], log)
        return log
    _run([uv, "pip", "install", "--python", str(python), "--upgrade", CORE_DIST], log)
    resolved = _installed_version(python, CORE_DIST)
    _run([uv, "pip", "install", "--python", str(python), f"{TOOLS_DIST}=={resolved}"], log)
    return log


def _installed_version(python: Path, dist: str) -> str:
    """Return ``dist``'s installed version inside the venv of ``python`` (``importlib.metadata``)."""
    result = subprocess.run(
        [str(python), "-c", f"import importlib.metadata as m; print(m.version({dist!r}))"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def uninstall_runtime(*, yes: bool) -> list[str]:
    """Remove the managed runtime (``bin/``, ``venv/``, ``python/``) — never user data.

    Raises:
        PermissionError: ``yes`` is False (the CLI confirms before calling with ``yes=True``).
    """
    if not yes:
        raise PermissionError("uninstall requires explicit confirmation (--yes)")
    home = parrot_home().resolve()
    log: list[str] = []
    for child in RUNTIME_DIRS:
        path = home / child
        if not path.is_symlink() and not path.exists():
            continue
        if path.is_symlink():
            path.unlink()
            log.append(f"removed symlink {path}")
            continue
        if path.resolve().parent != home:
            log.append(f"skipped {path}: resolves outside {home}")
            continue
        try:
            shutil.rmtree(path)
            log.append(f"removed {path}")
        except OSError as exc:
            logger.warning("could not remove %s: %s", path, exc)
            log.append(f"could not remove {path} ({exc}); remove it manually after this process exits")
    log.append(f"kept user data in {home} (wikis, library, skills, brains, parrot.db, services, jira)")
    return log
