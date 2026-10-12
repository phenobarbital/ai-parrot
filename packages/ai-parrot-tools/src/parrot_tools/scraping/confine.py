"""Host confinement of the scraping tools' own file and navigation access (PA-14).

A host (Agent Studio) builds ``WebScrapingToolkit(confine_paths=True, plans_dir=<tenant dir>)``: while a scrape or
crawl runs, :data:`FILES_ROOT` holds ``<plans_dir>/files`` and every path an action reads or writes (screenshot
``output_path``, upload source, download directory, ``move_to``) must resolve inside it; relative paths are taken
relative to it. Unset (the default) nothing changes. :func:`check_navigation` applies the PA-13 host check
(canonicalised literals, internal names, names resolved through the guarded resolver) to ``navigate`` targets when
the host enabled the egress guard.
"""

from __future__ import annotations

import contextvars
import functools
from pathlib import Path
from typing import Optional

FILES_ROOT: contextvars.ContextVar[Optional[Path]] = contextvars.ContextVar("scraping_files_root", default=None)


class PathConfinementError(PermissionError):
    """A path escapes the server-set root."""


def within_root(raw: str | Path) -> Optional[Path]:
    """``raw`` resolved inside :data:`FILES_ROOT`, ``None`` when no root is set (unconfined), error when it escapes."""
    root = FILES_ROOT.get()
    if root is None:
        return None
    if "\0" in str(raw):
        raise PathConfinementError("path contains a null byte")
    candidate = Path(str(raw)).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise PathConfinementError(f"path outside the permitted directory: {raw}") from exc
    return resolved


def confined_file(directory: str | Path, filename: str) -> Optional[Path]:
    """The FINAL ``directory/filename`` of a file an action writes, inside :data:`FILES_ROOT`; ``None`` when unconfined.

    ``filename`` must be a bare name: a path component (``/``, ``\\``, ``..``, absolute, NUL) is refused, and the
    joined path is resolved and checked against the root, so neither half can leave it.
    """
    if FILES_ROOT.get() is None:
        return None
    name = str(filename)
    if not name or name in (".", "..") or "\0" in name or "/" in name or "\\" in name or Path(name).name != name:
        raise PathConfinementError(f"file name is not a plain name: {filename!r}")
    return within_root(Path(str(directory or "")) / name)


def confine_to_files_root(method):
    """Run an async method of a tool built ``confine_paths=True`` with :data:`FILES_ROOT` set to ``self.files_root``.

    The root is a context variable: tasks spawned inside the call inherit it. Checks run on the event loop (never in
    an executor thread, which would not see it).
    """

    @functools.wraps(method)
    async def wrapper(self, *args, **kwargs):
        if not getattr(self, "confine_paths", False):
            return await method(self, *args, **kwargs)
        root = self.files_root
        root.mkdir(parents=True, exist_ok=True)
        token = FILES_ROOT.set(root)
        try:
            return await method(self, *args, **kwargs)
        finally:
            FILES_ROOT.reset(token)

    return wrapper


async def check_navigation(url: str) -> None:
    """Refuse ``url`` when the egress guard is on and it targets an internal name or a non-public address.

    The host is canonicalised (``127.1``, ``0x7f.0.0.1``, ``0177.0.0.1``, ``localhost.``, full-width digits) and a
    NAME is resolved through the guarded resolver, so ``metadata.google.internal`` or a name that points at a private
    address is refused before the browser is asked to go there.
    """
    import parrot.tools.egress as egress

    if egress.is_enabled():
        await egress.resolve_check(url)
