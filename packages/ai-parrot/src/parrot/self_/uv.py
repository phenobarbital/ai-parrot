"""Bounded uv resolution for the managed runtime (brief installer-uv-shadowing)."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from parrot.launcher import parrot_home

logger = logging.getLogger(__name__)

PINNED_UV_VERSION: str = "0.11.28"
UV_MIN_VERSION: str = "0.11.28"
UV_MAX_VERSION: str = "0.12"
LIBEXEC_DIR: str = "libexec"
UV_PATH_FILE: str = "uv-path"

UvSource = Literal["managed", "recorded", "path", "legacy"]
_VERSION_RE = re.compile(r"\d+(?:\.\d+)*")


class UvResolution(BaseModel):
    """The uv the runtime runs, its version, and where it was found."""

    path: Path
    version: str
    source: UvSource


def _exe(name: str) -> str:
    """Return ``name`` with a Windows executable suffix when needed."""
    return f"{name}.exe" if os.name == "nt" else name


def _resolved(path: Path) -> str:
    """Return a best-effort resolved form used only for PATH comparisons."""
    try:
        return str(path.expanduser().resolve())
    except (OSError, RuntimeError):
        return str(path)


def libexec_dir() -> Path:
    """Return the private ``parrot_home()/libexec`` directory."""
    return parrot_home() / LIBEXEC_DIR


def managed_uv() -> Path:
    """Return the pinned uv installed in ``libexec``."""
    return libexec_dir() / _exe("uv")


def uv_path_file() -> Path:
    """Return the recorded compatible system-uv path file."""
    return libexec_dir() / UV_PATH_FILE


def legacy_uv_files() -> list[Path]:
    """Return legacy uv and uvx files or symlinks under ``parrot_home()/bin``."""
    bin_dir = parrot_home() / "bin"
    return [path for path in (bin_dir / _exe("uv"), bin_dir / _exe("uvx")) if path.is_symlink() or path.is_file()]


def parse_version(text: str) -> tuple[int, ...] | None:
    """Return numeric parts of the first version-like token in ``text``."""
    for token in text.split():
        match = _VERSION_RE.match(token)
        if match:
            return tuple(int(part) for part in match.group(0).split("."))
    return None


def _padded(parts: tuple[int, ...], width: int) -> tuple[int, ...]:
    """Pad version parts with zeros to make tuple comparisons stable."""
    return parts + (0,) * (width - len(parts))


def in_range(version: str | None) -> bool:
    """Return whether ``version`` is within the supported uv range."""
    parsed = parse_version(version) if version else None
    low, high = parse_version(UV_MIN_VERSION), parse_version(UV_MAX_VERSION)
    if parsed is None or low is None or high is None:
        return False
    width = max(len(parsed), len(low), len(high))
    return _padded(low, width) <= _padded(parsed, width) < _padded(high, width)


def probe_version(path: Path) -> str | None:
    """Run ``<path> --version`` and return a parsed version, if available."""
    try:
        result = subprocess.run([str(path), "--version"], capture_output=True, text=True, check=False, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    parts = parse_version(result.stdout) if result.returncode == 0 else None
    return ".".join(str(part) for part in parts) if parts else None


def find_path_uv() -> Path | None:
    """Return the first PATH uv outside the Parrot bin and libexec directories."""
    own = {_resolved(parrot_home() / "bin"), _resolved(libexec_dir())}
    entries = [
        entry for entry in os.environ.get("PATH", "").split(os.pathsep) if entry and _resolved(Path(entry)) not in own
    ]
    found = shutil.which("uv", path=os.pathsep.join(entries)) if entries else None
    return Path(found).absolute() if found else None


def read_recorded_uv() -> Path | None:
    """Return the first non-empty recorded uv path, if present."""
    try:
        lines = uv_path_file().read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return None
    line = next((line.strip() for line in lines if line.strip()), "")
    return Path(line) if line else None


def record_system_uv(path: Path) -> Path:
    """Atomically record an absolute system-uv path without resolving symlinks."""
    target = uv_path_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.tmp.{os.getpid()}")
    temporary.write_text(f"{path.absolute()}\n", encoding="utf-8")
    os.replace(temporary, target)
    return target


def _compatible(path: Path | None) -> str | None:
    """Return ``path``'s version only when the path exists and is in range."""
    if path is None or not path.is_file():
        return None
    version = probe_version(path)
    return version if in_range(version) else None


def resolve_uv() -> UvResolution:
    """Resolve a compatible uv from managed, recorded, PATH, then legacy locations.

    Raises:
        FileNotFoundError: No compatible uv is available.
    """
    candidates: list[tuple[UvSource, Path | None]] = [
        ("managed", managed_uv()),
        ("recorded", read_recorded_uv()),
        ("path", find_path_uv()),
        ("legacy", parrot_home() / "bin" / _exe("uv")),
    ]
    tried: list[str] = []
    for source, path in candidates:
        if path is None or not path.is_file():
            continue
        version = probe_version(path)
        if version is not None and in_range(version):
            if source in ("path", "legacy"):
                logger.warning(
                    "using %s uv %s at %s; `parrot self update` or install-parrot --global sets up ~/.parrot/libexec",
                    source,
                    version,
                    path,
                )
            return UvResolution(path=path, version=version, source=source)
        tried.append(f"{path} ({version or 'unknown version'})")
    checked = f"; checked: {', '.join(tried)}" if tried else ""
    raise FileNotFoundError(f"no uv in >={UV_MIN_VERSION},<{UV_MAX_VERSION}{checked} — re-run install-parrot --global")


def _symlink_target_uv(link: Path) -> Path | None:
    """Return a compatible external uv target for a legacy ``bin/uv`` symlink, if any."""
    if not link.is_symlink():
        return None
    try:
        target = Path(os.readlink(link))
        if not target.is_absolute():
            target = link.parent / target
        target = target.parent.resolve(strict=True) / target.name
        current = target
        seen: set[Path] = set()
        own = {_resolved(parrot_home() / "bin"), _resolved(libexec_dir())}
        while True:
            if _resolved(current.parent) in own or current in seen:
                return None
            seen.add(current)
            if not current.is_symlink():
                break
            destination = Path(os.readlink(current))
            if not destination.is_absolute():
                destination = current.parent / destination
            current = destination.parent.resolve(strict=True) / destination.name
        current.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    return target if _compatible(target) else None


def migrate_legacy_uv() -> list[str]:
    """Move a legacy bin uv layout into libexec or record a compatible system uv."""
    legacy = legacy_uv_files()
    if not legacy:
        return []
    log: list[str] = []
    bin_uv = parrot_home() / "bin" / _exe("uv")
    if _compatible(managed_uv()) or _compatible(read_recorded_uv()):
        pass
    elif (system := find_path_uv()) is not None and _compatible(system):
        record_system_uv(system)
        log.append(f"using your uv at {system}: recorded in {uv_path_file()}")
    elif bin_uv in legacy and (target := _symlink_target_uv(bin_uv)) is not None:
        record_system_uv(target)
        log.append(f"using your uv at {target}: recorded in {uv_path_file()}")
    elif bin_uv in legacy and not bin_uv.is_symlink() and _compatible(bin_uv):
        libexec_dir().mkdir(parents=True, exist_ok=True)
        os.replace(bin_uv, managed_uv())
        log.append(f"moved {bin_uv} to {managed_uv()} (off PATH)")
    else:
        log.append(
            f"warning: no uv in >={UV_MIN_VERSION},<{UV_MAX_VERSION} to replace "
            f"{', '.join(str(path) for path in legacy)}; re-run install-parrot --global"
        )
        return log
    for path in legacy:
        if path.is_symlink() or path.exists():
            path.unlink()
            log.append(f"removed legacy {path} (it shadowed the uv on your PATH)")
    return log
