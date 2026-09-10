"""Unified-diff parsing, in-memory application and artifact storage (FEAT-543).

This module is pure Python, stdlib-only and model-free. It takes the
unified diff a delegate returned and decides — deterministically — whether
it is a legal, in-scope CREATE/MODIFY patch, then applies it *in memory*
against the expected source bytes so nothing is written until the caller
has verified the outcome.

Two deliberate design choices:

* **Patches are applied in pure Python with exact context matching and zero
  fuzz.** No external diff tool is invoked, so a model-written path can
  never reach an external command's argument list, and a mismatch is a
  clean rejection returned to the thinking model rather than a guess.
* **v1 supports CREATE and MODIFY only.** Deletions, renames, copies, mode
  changes, binary payloads and submodule updates are each rejected with
  their own code, so the refusal is explainable.

Artifacts live under ``<repo_root>/artifacts/tool-optimizations/<id>/``,
which is gitignored (`.gitignore:283`), with ``0o700`` directories and
``0o600`` files.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import time
import uuid
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .models import PatchManifest
from .policy import compact_json

__all__ = (
    "ApplyJournal",
    "ArtifactStore",
    "FilePatch",
    "Hunk",
    "JournalEntry",
    "PatchError",
    "apply_file_patch",
    "apply_in_memory",
    "check_scope",
    "normalize_patch",
    "parse_patch",
)

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_ARTIFACT_ID = re.compile(r"^[0-9a-f]{32}$")
_NO_NEWLINE = "\\ No newline at end of file"

#: Sweep abandoned temp directories older than this (seconds).
_TMP_TTL_SECONDS = 3600


class PatchError(ValueError):
    """A patch is malformed, out of scope, or does not match its source.

    Attributes:
        code: A stable snake_case code identifying the rejection.
        details: Structured context for the thinking model.
    """

    def __init__(self, code: str, message: str = "", details: Optional[dict[str, Any]] = None) -> None:
        """Initialize the error.

        Args:
            code: The stable rejection code.
            message: A human-readable explanation.
            details: Structured context (path, hunk index, expected vs actual).
        """
        super().__init__(message or code)
        self.code = code
        self.details = details or {}


class Hunk(BaseModel):
    """One ``@@`` hunk of a unified diff.

    Attributes:
        old_start: 1-based start line in the original file (0 for a create).
        old_count: Number of original lines the hunk covers.
        new_start: 1-based start line in the resulting file.
        new_count: Number of resulting lines the hunk produces.
        lines: Body lines with their leading ``' '``, ``'-'`` or ``'+'``
            marker preserved.
        no_newline_old: The original file had no trailing newline.
        no_newline_new: The resulting file has no trailing newline.
    """

    model_config = ConfigDict(extra="forbid")

    old_start: int = Field(..., ge=0)
    old_count: int = Field(..., ge=0)
    new_start: int = Field(..., ge=0)
    new_count: int = Field(..., ge=0)
    lines: list[str] = Field(default_factory=list)
    no_newline_old: bool = False
    no_newline_new: bool = False


class FilePatch(BaseModel):
    """All hunks that apply to one file.

    Attributes:
        path: The repo-relative POSIX path, with any ``a/``/``b/`` prefix
            stripped.
        is_create: True when the patch creates the file (``--- /dev/null``).
        hunks: The hunks, in file order.
    """

    model_config = ConfigDict(extra="forbid")

    path: str
    is_create: bool = False
    hunks: list[Hunk] = Field(default_factory=list)


class JournalEntry(BaseModel):
    """The recorded state of one file during an apply operation.

    Attributes:
        path: The repo-relative path.
        before_sha256: The file's digest before, or None when it was absent.
        after_sha256: The digest this operation intended to write.
        before_index: Index of the saved ``before/<n>.bin`` payload.
        state: How far this file got.
    """

    model_config = ConfigDict(extra="forbid")

    path: str
    before_sha256: Optional[str] = None
    after_sha256: str
    before_index: int = Field(..., ge=0)
    state: Literal["pending", "written", "verified", "restored", "unrecoverable"] = "pending"


class ApplyJournal(BaseModel):
    """A recovery journal for one multi-file apply operation.

    Multi-file filesystem mutation is not globally atomic, so the journal
    records what was intended and what was achieved, allowing a targeted
    rollback that never overwrites a concurrent edit.

    Attributes:
        artifact_id: The artifact being applied.
        started_at: ISO-8601 UTC start time.
        entries: One entry per target file.
        state: The operation's overall outcome.
    """

    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    started_at: str
    entries: list[JournalEntry] = Field(default_factory=list)
    state: Literal["pending", "applied", "rolled_back", "recovery_required"] = "pending"


# --------------------------------------------------------------------------- #
# Normalization and parsing
# --------------------------------------------------------------------------- #
def normalize_patch(text: str) -> str:
    """Canonicalize patch text and reject prose or fenced output.

    The returned text is what gets hashed and stored, so this function is
    idempotent: ``normalize_patch(normalize_patch(x)) == normalize_patch(x)``.

    Args:
        text: The raw model output.

    Returns:
        The canonical patch text, ending in a single newline.

    Raises:
        PatchError: The text is fenced, contains prose before the first
            header, or has no diff header at all (``not_a_patch``).
    """
    lines = text.split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        raise PatchError("not_a_patch", "the response contains no patch")

    for line in lines:
        if line.startswith("```"):
            raise PatchError("not_a_patch", "the response is fenced; return a bare unified diff")
        if line.startswith("--- ") or line.startswith("diff --git "):
            break
        if line.strip():
            raise PatchError(
                "not_a_patch",
                "the response contains prose before the first diff header",
                {"first_line": line[:200]},
            )
    else:
        raise PatchError("not_a_patch", "no unified-diff header was found")

    return "\n".join(lines) + "\n"


def _scan_forbidden(lines: list[str]) -> None:
    """Reject diff features that v1 does not support.

    Args:
        lines: The normalized patch lines.

    Raises:
        PatchError: A binary, rename, copy, deletion, mode change or
            submodule update was requested.
    """
    for line in lines:
        if line.startswith("GIT binary patch") or line.startswith("Binary files "):
            raise PatchError("binary_rejected", "binary patches are not supported", {"line": line[:200]})
        if line.startswith(("rename from ", "rename to ", "similarity index ", "copy from ", "copy to ")):
            raise PatchError("rename_rejected", "renames and copies are not supported", {"line": line[:200]})
        if line.startswith("deleted file mode"):
            raise PatchError("deletion_rejected", "deletions are not supported", {"line": line[:200]})
        if line.startswith(("old mode ", "new mode ")):
            raise PatchError("mode_change_rejected", "mode changes are not supported", {"line": line[:200]})
        if line.startswith("new file mode ") and line.split()[-1] not in {"100644", "100755"}:
            raise PatchError("mode_change_rejected", "only regular files are supported", {"line": line[:200]})
        if line[1:].startswith("Subproject commit ") and line[:1] in {" ", "-", "+"}:
            raise PatchError("submodule_rejected", "submodule updates are not supported", {"line": line[:200]})


def _strip_prefix(raw: str) -> str:
    """Strip a diff header's ``a/``/``b/`` prefix and trailing metadata.

    Args:
        raw: The path portion of a ``---``/``+++`` header.

    Returns:
        The bare path.
    """
    path = raw.split("\t", 1)[0].strip()
    if path.startswith(("a/", "b/")):
        path = path[2:]
    return path


def _validate_patch_path(path: str) -> str:
    """Validate a path taken from a diff header.

    Args:
        path: The prefix-stripped path.

    Returns:
        The path, unchanged.

    Raises:
        PatchError: The path is absolute, escapes the root, or is malformed.
    """
    if not path:
        raise PatchError("not_a_patch", "a diff header has an empty path")
    if path.startswith("/") or (len(path) > 1 and path[1] == ":"):
        raise PatchError("absolute_path", f"{path!r} is absolute", {"path": path})
    if "\\" in path:
        raise PatchError("path_escape", f"{path!r} contains a backslash", {"path": path})
    if any(segment in ("", ".", "..") for segment in path.split("/")):
        raise PatchError("path_escape", f"{path!r} contains a traversal segment", {"path": path})
    return path


def parse_patch(text: str, *, max_bytes: int) -> list[FilePatch]:
    """Parse a normalized unified diff into per-file patches.

    Args:
        text: Normalized patch text (see :func:`normalize_patch`).
        max_bytes: The largest patch accepted.

    Returns:
        One :class:`FilePatch` per target file, in patch order.

    Raises:
        PatchError: The patch is too large, uses an unsupported feature, has
            an invalid path, targets a file twice, or has a malformed hunk.
    """
    encoded = text.encode("utf-8")
    if len(encoded) > max_bytes:
        raise PatchError(
            "patch_too_large",
            f"the patch is {len(encoded)} bytes, above the {max_bytes}-byte budget",
            {"bytes": len(encoded), "max_bytes": max_bytes},
        )

    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    _scan_forbidden(lines)

    patches: list[FilePatch] = []
    seen: set[str] = set()
    index = 0
    current: Optional[FilePatch] = None

    while index < len(lines):
        line = lines[index]

        if line.startswith("diff --git ") or line.startswith("index ") or line.startswith("new file mode "):
            index += 1
            continue

        if line.startswith("--- "):
            old_raw = line[4:]
            if index + 1 >= len(lines) or not lines[index + 1].startswith("+++ "):
                raise PatchError("not_a_patch", "a '---' header is not followed by '+++'", {"line": line[:200]})
            new_raw = lines[index + 1][4:]
            if _strip_prefix(new_raw) == "/dev/null" or new_raw.split("\t", 1)[0].strip() == "/dev/null":
                raise PatchError("deletion_rejected", "deletions are not supported", {"line": lines[index + 1][:200]})

            is_create = old_raw.split("\t", 1)[0].strip() == "/dev/null"
            path = _validate_patch_path(_strip_prefix(new_raw))
            if path in seen:
                raise PatchError("duplicate_target", f"{path!r} is patched more than once", {"path": path})
            seen.add(path)
            current = FilePatch(path=path, is_create=is_create, hunks=[])
            patches.append(current)
            index += 2
            continue

        if line.startswith("@@"):
            if current is None:
                raise PatchError("not_a_patch", "a hunk appears before any file header", {"line": line[:200]})
            hunk, index = _parse_hunk(lines, index, current.path)
            current.hunks.append(hunk)
            continue

        if not line.strip():
            index += 1
            continue

        raise PatchError("not_a_patch", "unexpected line outside the diff grammar", {"line": line[:200]})

    if not patches:
        raise PatchError("not_a_patch", "no file headers were found")
    for patch in patches:
        if not patch.hunks:
            raise PatchError("malformed_hunk", f"{patch.path!r} has no hunks", {"path": patch.path})
    return patches


def _parse_hunk(lines: list[str], index: int, path: str) -> tuple[Hunk, int]:
    """Parse one hunk starting at ``lines[index]``.

    Args:
        lines: The patch lines.
        index: Index of the ``@@`` header.
        path: The file this hunk belongs to, for error details.

    Returns:
        A ``(hunk, next_index)`` tuple.

    Raises:
        PatchError: The header is malformed or the body does not match the
            declared line counts.
    """
    match = _HUNK.match(lines[index])
    if match is None:
        raise PatchError("malformed_hunk", "malformed @@ header", {"path": path, "line": lines[index][:200]})
    old_start = int(match.group(1))
    old_count = int(match.group(2)) if match.group(2) is not None else 1
    new_start = int(match.group(3))
    new_count = int(match.group(4)) if match.group(4) is not None else 1

    body: list[str] = []
    old_seen = new_seen = 0
    no_newline_old = no_newline_new = False
    cursor = index + 1

    while cursor < len(lines) and (old_seen < old_count or new_seen < new_count):
        raw = lines[cursor]
        if raw == _NO_NEWLINE:
            if body and body[-1][0] == "+":
                no_newline_new = True
            else:
                no_newline_old = True
                no_newline_new = no_newline_new or (body and body[-1][0] == " ")
            cursor += 1
            continue
        if raw.startswith("@@") or raw.startswith("--- ") or raw.startswith("diff --git "):
            break
        marker = raw[0] if raw else " "
        if marker not in (" ", "-", "+"):
            break
        body.append(raw if raw else " ")
        if marker in (" ", "-"):
            old_seen += 1
        if marker in (" ", "+"):
            new_seen += 1
        cursor += 1

    if cursor < len(lines) and lines[cursor] == _NO_NEWLINE:
        if body and body[-1][0] == "+":
            no_newline_new = True
        else:
            no_newline_old = True
            no_newline_new = no_newline_new or bool(body and body[-1][0] == " ")
        cursor += 1

    if old_seen != old_count or new_seen != new_count:
        raise PatchError(
            "malformed_hunk",
            "the hunk body does not match its declared line counts",
            {
                "path": path,
                "declared_old": old_count,
                "actual_old": old_seen,
                "declared_new": new_count,
                "actual_new": new_seen,
            },
        )

    return (
        Hunk(
            old_start=old_start,
            old_count=old_count,
            new_start=new_start,
            new_count=new_count,
            lines=body,
            no_newline_old=no_newline_old,
            no_newline_new=no_newline_new,
        ),
        cursor,
    )


# --------------------------------------------------------------------------- #
# Scope
# --------------------------------------------------------------------------- #
def check_scope(patches: list[FilePatch], allowed: dict[str, str]) -> None:
    """Verify every patched path is approved with matching create semantics.

    Args:
        patches: The parsed patches.
        allowed: Approved path -> ``"create"`` or ``"modify"``.

    Raises:
        PatchError: A path is outside the approved scope, or its create /
            modify semantics disagree with the packet.
    """
    for patch in patches:
        action = allowed.get(patch.path)
        if action is None:
            raise PatchError(
                "path_outside_scope",
                f"{patch.path!r} is not an approved target",
                {"path": patch.path, "allowed": sorted(allowed)},
            )
        if action == "create" and not patch.is_create:
            raise PatchError(
                "create_needs_dev_null",
                f"{patch.path!r} is declared as a create, so its patch must start from /dev/null",
                {"path": patch.path},
            )
        if action == "modify" and patch.is_create:
            raise PatchError(
                "path_outside_scope",
                f"{patch.path!r} is declared as a modify but the patch creates it",
                {"path": patch.path, "declared": action},
            )


# --------------------------------------------------------------------------- #
# Application
# --------------------------------------------------------------------------- #
def _newline_for(source_lines: list[str]) -> str:
    """Infer the newline an added line should use.

    Args:
        source_lines: The original file's lines, with endings preserved.

    Returns:
        ``"\\r\\n"`` when the file consistently uses CRLF, else ``"\\n"``.
    """
    terminated = [line for line in source_lines if line.endswith("\n")]
    if terminated and all(line.endswith("\r\n") for line in terminated):
        return "\r\n"
    return "\n"


def apply_file_patch(before: Optional[bytes], patch: FilePatch) -> bytes:
    """Apply one file's hunks in memory, with exact context matching.

    There is no fuzz factor and no offset search: a context line that does
    not match the source exactly is a rejection, not a guess.

    Args:
        before: The original file bytes, or None for a create.
        patch: The parsed patch for this file.

    Returns:
        The resulting file bytes.

    Raises:
        PatchError: The source does not decode as UTF-8, a hunk is out of
            order, or a context/removed line does not match the source.
    """
    try:
        source = (before or b"").decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PatchError("binary_rejected", f"{patch.path!r} is not valid UTF-8 text", {"path": patch.path}) from exc

    source_lines = source.splitlines(keepends=True)
    newline = _newline_for(source_lines)
    out: list[str] = []
    cursor = 0

    for hunk_index, hunk in enumerate(patch.hunks):
        target = hunk.old_start - 1 if hunk.old_count else hunk.old_start
        if target < cursor or target > len(source_lines):
            raise PatchError(
                "malformed_hunk",
                "hunks are out of order or start past the end of the file",
                {"path": patch.path, "hunk_index": hunk_index, "start": hunk.old_start, "lines": len(source_lines)},
            )
        out.extend(source_lines[cursor:target])
        cursor = target

        for body in hunk.lines:
            marker, content = body[0], body[1:]
            if marker in (" ", "-"):
                actual = source_lines[cursor].rstrip("\r\n") if cursor < len(source_lines) else None
                if actual != content:
                    raise PatchError(
                        "context_mismatch",
                        f"{patch.path!r} does not match the patch context",
                        {
                            "path": patch.path,
                            "hunk_index": hunk_index,
                            "line_no": cursor + 1,
                            "expected": content,
                            "expected_line": content,
                            "actual": actual,
                            "actual_line": actual,
                        },
                    )
                if marker == " ":
                    out.append(source_lines[cursor])
                cursor += 1
            elif marker == "+":
                out.append(content + newline)

    out.extend(source_lines[cursor:])
    result = "".join(out)

    last_hunk = patch.hunks[-1] if patch.hunks else None
    if last_hunk is not None and last_hunk.no_newline_new and cursor >= len(source_lines):
        result = result.rstrip("\r\n")
    return result.encode("utf-8")


def apply_in_memory(patches: list[FilePatch], sources: dict[str, Optional[bytes]]) -> dict[str, bytes]:
    """Apply every file patch against its expected source bytes.

    Args:
        patches: The parsed, scope-checked patches.
        sources: Path -> current bytes, or None when the file is absent.

    Returns:
        Path -> resulting bytes, for every patched path.

    Raises:
        PatchError: A modify target is missing, or a hunk does not match.
    """
    result: dict[str, bytes] = {}
    for patch in patches:
        before = sources.get(patch.path)
        if not patch.is_create and before is None:
            raise PatchError(
                "context_mismatch",
                f"{patch.path!r} does not exist but the patch modifies it",
                {"path": patch.path, "hunk_index": 0, "line_no": 1, "expected": None, "actual": None},
            )
        result[patch.path] = apply_file_patch(None if patch.is_create else before, patch)
    return result


# --------------------------------------------------------------------------- #
# Artifact store
# --------------------------------------------------------------------------- #
class ArtifactStore:
    """Durable, restrictive storage for generated patch artifacts.

    Artifacts are opaque data, never executable commands: ids are random
    hex, directories are ``0o700`` and files are ``0o600``.
    """

    def __init__(self, repo_root: Path) -> None:
        """Initialize the store.

        Args:
            repo_root: The repository root; artifacts live beneath it.
        """
        self.repo_root = Path(repo_root)
        self.root = self.repo_root / "artifacts" / "tool-optimizations"

    @staticmethod
    def new_id() -> str:
        """Return a fresh opaque artifact id.

        Returns:
            32 lowercase hex characters.
        """
        return uuid.uuid4().hex

    def _artifact_dir(self, artifact_id: str) -> Path:
        """Resolve and validate an artifact directory.

        Args:
            artifact_id: The artifact identifier.

        Returns:
            The artifact directory path.

        Raises:
            PatchError: The id is malformed or the directory is a symlink.
        """
        if not _ARTIFACT_ID.match(artifact_id):
            raise PatchError("invalid_artifact_id", f"{artifact_id!r} is not a valid artifact id")
        target = self.root / artifact_id
        if target.is_symlink() or (target.parent.exists() and target.parent.is_symlink()):
            raise PatchError("artifact_tampered", "the artifact directory is a symlink", {"artifact_id": artifact_id})
        return target

    def _sweep_stale_temp_dirs(self) -> None:
        """Remove abandoned temp directories left by a crashed generation."""
        if not self.root.exists():
            return
        cutoff = time.time() - _TMP_TTL_SECONDS
        for entry in self.root.iterdir():
            # NEVER follow a symlink here. `is_dir()` and `stat()` both follow
            # links, so a `.tmp-*` symlink pointing outside the repository
            # would pass every check and we would delete the *target's*
            # contents. Only real directories we created are swept.
            if entry.is_symlink():
                continue
            if not entry.name.startswith(".tmp-") or not entry.is_dir():
                continue
            try:
                if entry.lstat().st_mtime > cutoff:
                    continue
                for child in entry.iterdir():
                    if child.is_symlink() or child.is_file():
                        child.unlink()
                entry.rmdir()
            except OSError:  # pragma: no cover — best-effort housekeeping
                continue

    @staticmethod
    def _write_private(path: Path, text: str) -> None:
        """Write ``text`` to a new ``0o600`` file, flushed to disk.

        Args:
            path: The file to create; it must not already exist.
            text: The contents.
        """
        handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())

    def write_generation(self, artifact_id: str, *, manifest: PatchManifest, patch_text: str, packet_json: str) -> Path:
        """Store a generated artifact atomically.

        Everything is written into a private temp directory and published
        with a single rename, so a crash can never leave a half-written
        artifact that :meth:`load` would accept.

        Args:
            artifact_id: The artifact identifier.
            manifest: The provenance manifest.
            patch_text: The normalized patch.
            packet_json: The canonical packet JSON.

        Returns:
            The published artifact directory.

        Raises:
            PatchError: The id is malformed.
        """
        final = self._artifact_dir(artifact_id)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._sweep_stale_temp_dirs()

        temp = self.root / f".tmp-{artifact_id}"
        temp.mkdir(mode=0o700, parents=True)
        self._write_private(temp / "manifest.json", compact_json(manifest.model_dump(mode="json")))
        self._write_private(temp / "patch.diff", patch_text)
        self._write_private(temp / "packet.json", packet_json)
        os.rename(temp, final)
        return final

    def load(self, artifact_id: str) -> tuple[PatchManifest, str, str]:
        """Load an artifact, verifying it has not been edited.

        Args:
            artifact_id: The artifact identifier.

        Returns:
            A ``(manifest, patch_text, packet_json)`` tuple.

        Raises:
            PatchError: The artifact is missing, or its stored patch or
                packet no longer hashes to the manifest's recorded value.
        """
        directory = self._artifact_dir(artifact_id)
        if not directory.is_dir():
            raise PatchError("artifact_not_found", f"no artifact {artifact_id!r}", {"artifact_id": artifact_id})

        try:
            manifest = PatchManifest.model_validate_json((directory / "manifest.json").read_text(encoding="utf-8"))
            patch_text = (directory / "patch.diff").read_text(encoding="utf-8")
            packet_json = (directory / "packet.json").read_text(encoding="utf-8")
        except (OSError, ValueError) as exc:
            raise PatchError(
                "artifact_tampered", f"artifact {artifact_id!r} is unreadable", {"artifact_id": artifact_id}
            ) from exc

        if hashlib.sha256(patch_text.encode("utf-8")).hexdigest() != manifest.patch_sha256:
            raise PatchError(
                "artifact_tampered", "the stored patch does not match its manifest hash", {"artifact_id": artifact_id}
            )
        if hashlib.sha256(packet_json.encode("utf-8")).hexdigest() != manifest.packet_sha256:
            raise PatchError(
                "artifact_tampered", "the stored packet does not match its manifest hash", {"artifact_id": artifact_id}
            )
        return manifest, patch_text, packet_json

    def write_journal(self, artifact_id: str, journal: ApplyJournal) -> None:
        """Persist the recovery journal for an apply operation.

        Args:
            artifact_id: The artifact identifier.
            journal: The journal to write.
        """
        directory = self._artifact_dir(artifact_id)
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = directory / "journal.json"
        temp = directory / ".journal.json.tmp"
        if temp.exists():
            temp.unlink()
        self._write_private(temp, compact_json(journal.model_dump(mode="json")))
        os.replace(temp, path)

    def read_journal(self, artifact_id: str) -> Optional[ApplyJournal]:
        """Read the recovery journal, if one exists.

        Args:
            artifact_id: The artifact identifier.

        Returns:
            The journal, or None when the artifact has never been applied.
        """
        path = self._artifact_dir(artifact_id) / "journal.json"
        if not path.is_file():
            return None
        return ApplyJournal.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def save_before(self, artifact_id: str, index: int, data: Optional[bytes]) -> None:
        """Save a file's pre-application bytes for rollback.

        Args:
            artifact_id: The artifact identifier.
            index: The journal entry index.
            data: The original bytes, or None when the file did not exist
                (in which case nothing is stored and rollback means delete).
        """
        directory = self._artifact_dir(artifact_id) / "before"
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        target = directory / f"{index}.bin"
        if data is None:
            if target.exists():
                target.unlink()
            return
        if target.exists():
            target.unlink()
        handle = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())

    def load_before(self, artifact_id: str, index: int) -> Optional[bytes]:
        """Load a file's saved pre-application bytes.

        Args:
            artifact_id: The artifact identifier.
            index: The journal entry index.

        Returns:
            The original bytes, or None when the file did not exist.
        """
        target = self._artifact_dir(artifact_id) / "before" / f"{index}.bin"
        if not target.is_file():
            return None
        return target.read_bytes()

    def directory_mode(self, artifact_id: str) -> int:
        """Return the artifact directory's permission bits.

        Args:
            artifact_id: The artifact identifier.

        Returns:
            The mode bits, e.g. ``0o700``.
        """
        return stat.S_IMODE(self._artifact_dir(artifact_id).stat().st_mode)
