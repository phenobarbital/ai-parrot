"""Host confinement of the scraping tools' own file and navigation access (PA-14).

A host (Agent Studio) builds ``WebScrapingToolkit(confine_paths=True, plans_dir=<tenant dir>)``: while a scrape or
crawl runs, :data:`FILES_ROOT` holds ``<plans_dir>/files`` and every path an action reads or writes (screenshot
``output_path``, upload source, download directory, ``move_to``) must resolve inside it; relative paths are taken
relative to it. Unset (the default) nothing changes. :func:`check_navigation` applies the PA-13 literal-host check to
``navigate`` targets when the host enabled the egress guard (names are still resolved by the browser itself).
"""

from __future__ import annotations

import contextvars
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
    candidate = Path(str(raw)).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise PathConfinementError(f"path outside the permitted directory: {raw}") from exc
    return resolved


def check_navigation(url: str) -> None:
    """Refuse ``url`` when the egress guard is on and it targets localhost or a non-public IP literal."""
    import parrot.tools.egress as egress

    if egress.is_enabled():
        egress.check_url(url)
