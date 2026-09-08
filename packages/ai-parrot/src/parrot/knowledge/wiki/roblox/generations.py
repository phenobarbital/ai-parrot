"""Atomic active-generation metadata and writer coordination (FEAT-532 TASK-2902).

The Roblox API plane lives at ``parrot_home()/roblox/`` (never inside the
repository):

```
parrot_home()/roblox/
    active.json              <- ActivePointer (generation_id + manifest)
    current -> generations/<generation_id>/   (atomically re-pointed symlink)
    .publish.lock             <- exclusive-lock file, never opened for content
    generations/
        <generation_id>/
            wiki.db           <- one immutable SQLite generation
```

``current`` is the **stable path** a namespace registration
(``wikitoolkit ns add roblox --store <current>``) should point ``store``
at — never a per-generation directory, so a namespace declaration never
needs updating across refreshes. Publication atomically re-points
``current`` (an ``os.symlink`` into a fresh temp name, then
``os.replace`` — never mutates an existing symlink in place) and
``active.json`` together, under a real OS-level exclusive lock
(POSIX ``fcntl.flock``) so two concurrent publishers can never interleave
a read-compare-write into a lost update (spec: "atomic replace alone
does not prevent lost updates").
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from parrot.knowledge.wiki.project import parrot_home

GENERATIONS_DIRNAME = "roblox"
GENERATIONS_SUBDIR = "generations"
ACTIVE_POINTER_FILENAME = "active.json"
CURRENT_LINK_NAME = "current"
LOCK_FILENAME = ".publish.lock"


def roblox_root() -> Path:
    """Root of the Roblox API plane, under ``PARROT_HOME`` — never the repo."""
    return parrot_home() / GENERATIONS_DIRNAME


def generations_dir() -> Path:
    """Directory holding every immutable generation, past and present."""
    return roblox_root() / GENERATIONS_SUBDIR


def generation_dir_for(generation_id: str) -> Path:
    """The (possibly not-yet-built) directory for one generation id."""
    return generations_dir() / generation_id


def current_store_dir() -> Path:
    """The stable path a namespace registration should point ``--store`` at."""
    return roblox_root() / CURRENT_LINK_NAME


def _pointer_path() -> Path:
    return roblox_root() / ACTIVE_POINTER_FILENAME


def _lock_path() -> Path:
    return roblox_root() / LOCK_FILENAME


class ActivePointer:
    """The currently-published generation's identity + manifest.

    A plain value object (not a Pydantic model): it round-trips an
    already-serialized manifest dict verbatim without importing
    ``roblox/models.py``'s ``RobloxApiManifest`` here — this module
    stays a leaf dependency for ``ingest.py`` to build on, not the other
    way around.
    """

    def __init__(self, generation_id: str, manifest: dict[str, Any]) -> None:
        self.generation_id = generation_id
        self.manifest = manifest

    def to_json(self) -> dict[str, Any]:
        return {"generation_id": self.generation_id, "manifest": self.manifest}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> ActivePointer:
        return cls(generation_id=data["generation_id"], manifest=data["manifest"])


def read_active_pointer() -> ActivePointer | None:
    """Read the active-generation pointer, or ``None``.

    Never raises: a missing, unreadable, or malformed pointer file is
    treated identically to "no generation published yet" — the caller
    (``ingest.py``) is responsible for turning that into an actionable
    "run --refresh" message rather than a stack trace.
    """
    path = _pointer_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return ActivePointer.from_json(data)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def generation_is_valid(generation_id: str) -> bool:
    """Whether ``generation_id``'s directory contains an openable ``wiki.db``.

    A cheap existence + non-empty-file check — the real "does it open and
    answer queries" validation happens once, right after building a new
    generation (:func:`~parrot.knowledge.wiki.roblox.ingest.ingest_roblox_api`),
    not on every read of an already-published pointer.
    """
    db_path = generation_dir_for(generation_id) / "wiki.db"
    return db_path.is_file() and db_path.stat().st_size > 0


def _atomic_write_pointer(pointer: ActivePointer) -> None:
    target = _pointer_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(pointer.to_json(), indent=2) + "\n"
    handle, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=".active-", suffix=".json")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(payload)
        os.replace(tmp_path, target)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def _atomic_repoint_current(generation_id: str) -> None:
    """Atomically re-point the ``current`` symlink at ``generation_id``.

    Builds a brand-new symlink under a private temp name and
    ``os.replace``s it over ``current`` — never removes-then-recreates
    the live symlink in place, so a reader mid-open never sees a missing
    ``current``.
    """
    link_path = current_store_dir()
    link_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_link = link_path.parent / f".{CURRENT_LINK_NAME}-tmp-{os.getpid()}"
    tmp_link.unlink(missing_ok=True)
    os.symlink(generation_dir_for(generation_id), tmp_link)
    os.replace(tmp_link, link_path)


@contextlib.contextmanager
def publish_lock():
    """Exclusive OS-level lock (POSIX ``fcntl.flock``) around one CAS publish.

    Held only around the metadata read-compare-write in
    :func:`publish_generation_cas` — never around the (potentially slow)
    SQLite generation build itself, so a slow renderer never blocks other
    readers/writers from checking the current pointer.
    """
    roblox_root().mkdir(parents=True, exist_ok=True)
    lock_path = _lock_path()
    handle = open(lock_path, "a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def publish_generation_cas(expected_current_id: str | None, new_pointer: ActivePointer) -> bool:
    """Atomically promote ``new_pointer``, iff nobody else got there first.

    Compares the *currently active* generation id against
    ``expected_current_id`` (the id this caller observed before doing its
    — possibly slow — acquisition/render/build work) and only then writes
    ``active.json`` + re-points ``current``. The whole check-and-write
    happens inside :func:`publish_lock`, so no concurrent publisher can
    observe a stale "no conflict" result (the lock, not the compare
    alone, is what prevents the lost update — the compare is a second,
    belt-and-suspenders guard against a caller that forgot to hold it).

    Args:
        expected_current_id: The generation id this caller last observed
            as active (``None`` if none was ever published).
        new_pointer: The freshly built, already-validated generation to
            promote.

    Returns:
        ``True`` if promoted. ``False`` if a concurrent publisher already
        changed the active generation since ``expected_current_id`` was
        observed — the caller's own newly-built generation directory is
        left on disk (never deleted here; not garbage collection's job)
        and the caller should treat the now-current generation as
        authoritative rather than retry-clobber it.
    """
    with publish_lock():
        current = read_active_pointer()
        current_id = current.generation_id if current is not None else None
        if current_id != expected_current_id:
            return False
        _atomic_write_pointer(new_pointer)
        _atomic_repoint_current(new_pointer.generation_id)
        return True
