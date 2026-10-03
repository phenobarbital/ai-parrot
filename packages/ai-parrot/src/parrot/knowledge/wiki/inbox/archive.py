"""Date-stamped original archiving and git index bookkeeping."""
from datetime import date
import errno
import logging
import os
from pathlib import Path
import shutil
import subprocess

from parrot.knowledge.wiki.inbox.models import ArchiveResult
from parrot.knowledge.wiki.sources import SourceCollectionManager

logger = logging.getLogger(__name__)

_GIT_TIMEOUT = 30.0


def _safe_stamp(date_format: str, today: date) -> str:
    """Render the date stamp, rejecting values that could escape the archive directory.

    Args:
        date_format: ``strftime`` format string.
        today: Date to render.

    Returns:
        The rendered stamp.

    Raises:
        ValueError: If the stamp is empty, ``.``/``..`` or contains a path separator or NUL.
    """
    stamp = today.strftime(date_format)
    seps = {"/", "\\", "\x00"}
    if os.sep:
        seps.add(os.sep)
    if os.altsep:
        seps.add(os.altsep)
    if not stamp or stamp in {".", ".."} or any(sep in stamp for sep in seps) or ".." in stamp:
        raise ValueError(f"Unsafe archive date component: {stamp!r}")
    return stamp


def archive_destination(
    archive_dir: Path,
    source: Path,
    *,
    rejected: bool,
    rejected_subdir: str,
    date_format: str,
    today: date,
) -> Path:
    """Choose a free date-stamped filename, adding -N before the extension.

    Args:
        archive_dir: Archive root directory.
        source: Original file being archived.
        rejected: Whether to place the file under ``rejected_subdir``.
        rejected_subdir: Subdirectory name for rejected originals.
        date_format: ``strftime`` format for the date stamp.
        today: Date used for the stamp.

    Returns:
        A destination path that does not exist yet.

    Raises:
        ValueError: If the date stamp or ``rejected_subdir`` is unsafe.
    """
    stamp = _safe_stamp(date_format, today)
    base = Path(archive_dir)
    if rejected:
        if (
            not rejected_subdir
            or rejected_subdir in {".", ".."}
            or "/" in rejected_subdir
            or "\\" in rejected_subdir
            or ".." in rejected_subdir
        ):
            raise ValueError(f"Unsafe rejected_subdir: {rejected_subdir!r}")
        base = base / rejected_subdir
    suffix = source.suffix
    stem = source.name[: len(source.name) - len(suffix)] if suffix else source.name
    candidate = base / f"{stem}.{stamp}{suffix}"
    counter = 0
    while os.path.lexists(candidate):
        counter += 1
        candidate = base / f"{stem}.{stamp}-{counter}{suffix}"
    return candidate


def _relative(root: Path, path: Path) -> str:
    """Return ``path`` relative to ``root`` (falling back to the path itself)."""
    try:
        return str(Path(path).relative_to(root))
    except ValueError:
        return str(path)


def is_git_tracked(root: Path, path: Path) -> bool:
    """Check ``git ls-files --error-unmatch``; return False if git cannot run.

    Args:
        root: Repository root.
        path: File to check.

    Returns:
        True only when git runs successfully and tracks the file.
    """
    cmd = ["git", "-C", str(root), "ls-files", "--error-unmatch", "--", _relative(root, path)]
    try:
        proc = subprocess.run(cmd, capture_output=True, check=False, timeout=_GIT_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def stage_git_removal(root: Path, path: Path) -> bool:
    """Stage only an index deletion after the move; never raise or commit.

    Args:
        root: Repository root.
        path: Original (now moved) path.

    Returns:
        True when ``git rm --cached`` succeeded.
    """
    cmd = ["git", "-C", str(root), "rm", "--cached", "--quiet", "--", _relative(root, path)]
    try:
        proc = subprocess.run(cmd, capture_output=True, check=False, timeout=_GIT_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("git rm --cached failed for %s: %s", path, exc)
        return False
    if proc.returncode != 0:
        logger.warning("git rm --cached exited %s for %s", proc.returncode, path)
        return False
    return True


def archive_original(root: Path, source: Path, destination: Path, *, stage_git: bool) -> ArchiveResult:
    """Move without overwrite, verify destination, then optionally stage removal.

    ``rejected`` is returned as False; the caller sets it from its triage decision.

    Args:
        root: Repository root.
        source: Original file.
        destination: Target path from :func:`archive_destination`.
        stage_git: Whether to stage the deletion of a tracked original.

    Returns:
        The :class:`ArchiveResult`.

    Raises:
        FileExistsError: If ``destination`` already exists.
        FileNotFoundError: If the destination is missing after the move.
    """
    if os.path.lexists(destination):
        raise FileExistsError(f"Archive destination already exists: {destination}")
    tracked = is_git_tracked(root, source) if stage_git else False
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(source, destination)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        shutil.move(str(source), str(destination))
    if not destination.exists():
        raise FileNotFoundError(f"Archive destination missing after move: {destination}")
    staged = stage_git_removal(root, source) if tracked else False
    return ArchiveResult(source=source, destination=destination, rejected=False, staged_git=staged)


def repoint_source(sources: SourceCollectionManager, source_id: str, destination: Path) -> None:
    """Repoint the manifest, logging recoverable source errors without undoing the move.

    Args:
        sources: Source manifest manager.
        source_id: Tracked source to repoint.
        destination: Archived file location.
    """
    try:
        sources.update_source_uri(source_id, destination)
    except (FileNotFoundError, ValueError) as exc:
        logger.warning("repoint_source: could not repoint %s to %s: %s", source_id, destination, exc)
