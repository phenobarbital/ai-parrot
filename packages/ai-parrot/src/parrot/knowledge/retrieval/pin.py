"""`WorkspacePin` — the cross-repo unit of coherence (spec §3.4, TASK-2274).

A retrieval request is scoped not to a single ``(repo, rev)`` but to a
**frozen set of pins**, resolved once at request admission. HEAD moving
underneath a long-lived session does not change retrieval results;
advancing is an explicit, separate action (a `dev_loop` reducer concern,
out of scope here).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType

import aiosqlite
from pydantic import BaseModel, ConfigDict, field_validator

from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence
from parrot.knowledge.ontology.schema import TenantContext
from parrot.knowledge.retrieval.exceptions import IndexPinMismatchError, StalePinError

logger = logging.getLogger(__name__)

#: A concrete git SHA: 7-40 hex characters — same shape `NodeRef.rev`
#: validates (spec §3.1/§3.4: "rev is a concrete SHA, never a symbolic
#: ref"). Defense in depth (code review): `resolve_workspace()` already
#: only ever produces concrete SHAs via `git rev-parse --verify`, but a
#: `WorkspacePin` constructed directly (bypassing `resolve_workspace`)
#: had no equivalent guard.
_PIN_REV_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")

#: Default threshold (days) past which a pin's age is flagged on the trace
#: (spec §3.4: "pin drift vs L1" — a stale-but-valid pin is expensive, not
#: incorrect, so this is a warning, never an error).
DEFAULT_STALE_PIN_WARNING_DAYS = 7

#: Default bounded sample size for the pin-coherence check (spec §3.5.3).
#: Exhaustive checking would cost O(files) git calls per request; this is
#: deliberately bounded and configurable.
DEFAULT_PIN_VERIFICATION_SAMPLE = 16


class WorkspacePin(BaseModel):
    """A frozen, hashable set of repo→rev pins for one retrieval session.

    Attributes:
        primary: Name of the repo that anchors relative resolution (e.g.
            the repo the session was opened against).
        pins: ``repo -> concrete SHA`` for every repo in the workspace.
            Never symbolic refs. Coerced to an immutable mapping at
            construction so mutation after the fact raises, keeping the
            "frozen for the request's lifetime" guarantee real rather than
            nominal.
        pinned_at: UTC timestamp the pins were resolved at.
        weight_table_version: Version of the `EdgeWeightTable` (spec §5.3)
            in effect when this pin was created — stamped here so a
            replayed trace reproduces exactly.
        package_map_version: Version of the `PackageRepoMap` (spec §5.3.1,
            RQ-1) in effect, if cross-repo resolution is enabled. ``None``
            when not applicable.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    primary: str
    pins: MappingProxyType[str, str]
    pinned_at: datetime
    weight_table_version: str
    package_map_version: str | None = None

    @field_validator("pins", mode="before")
    @classmethod
    def _freeze_pins(cls, value: Mapping[str, str]) -> MappingProxyType[str, str]:
        """Coerce the input mapping to an immutable `MappingProxyType`.

        A bare ``Mapping`` type annotation does not stop a caller from
        passing (and later mutating) a plain ``dict``; this validator makes
        the immutability real.
        """
        for repo, rev in value.items():
            if not _PIN_REV_RE.match(rev):
                raise ValueError(
                    f"WorkspacePin.pins[{repo!r}] must be a concrete git SHA "
                    f"(7-40 hex chars); got symbolic or malformed ref: {rev!r}"
                )
        return MappingProxyType(dict(value))

    @field_validator("pinned_at")
    @classmethod
    def _require_timezone_aware(cls, value: datetime) -> datetime:
        """Reject naive datetimes — staleness comparisons must be unambiguous."""
        if value.tzinfo is None:
            raise ValueError("WorkspacePin.pinned_at must be timezone-aware (UTC)")
        return value

    def __hash__(self) -> int:
        """Hash over all fields, using a sorted-items tuple for `pins`.

        `MappingProxyType` itself is not hashable (it wraps a mutable
        ``dict``), so the default Pydantic frozen-model hash would raise.
        This override makes `WorkspacePin` genuinely hashable and cacheable
        per spec §3.4.
        """
        return hash(
            (
                self.primary,
                tuple(sorted(self.pins.items())),
                self.pinned_at,
                self.weight_table_version,
                self.package_map_version,
            )
        )

    def rev_of(self, repo: str) -> str:
        """Return the concrete SHA pinned for `repo`.

        Args:
            repo: Repository name.

        Returns:
            The concrete git SHA pinned for that repo.

        Raises:
            KeyError: If `repo` is not present in `pins`.
        """
        try:
            return self.pins[repo]
        except KeyError as exc:
            raise KeyError(
                f"WorkspacePin has no pin for repo {repo!r}; "
                f"pinned repos: {sorted(self.pins)}"
            ) from exc

    def is_stale(
        self,
        *,
        now: datetime | None = None,
        warning_days: int = DEFAULT_STALE_PIN_WARNING_DAYS,
    ) -> bool:
        """Whether this pin is older than `warning_days` (spec §3.4).

        A long-lived session pinned far behind HEAD gets correct staleness
        answers from the L1 wiki cache (it is indexed by ``(node, digest)``,
        not by rev), but regenerating most pages against old source is
        expensive — this is a warning signal, not an error.

        Args:
            now: Reference time to compare against (defaults to
                ``datetime.now(timezone.utc)``).
            warning_days: Age threshold in days.

        Returns:
            ``True`` if the pin is older than ``warning_days``.
        """
        reference = now if now is not None else datetime.now(UTC)
        age = reference - self.pinned_at
        stale = age.days > warning_days
        if stale:
            logger.warning(
                "WorkspacePin %r pinned_at=%s is %d day(s) old (warning threshold=%d)",
                self.primary,
                self.pinned_at.isoformat(),
                age.days,
                warning_days,
            )
        return stale


async def _resolve_ref(repo: str, ref: str, repo_path: Path) -> str:
    """Resolve `ref` to a concrete SHA within `repo_path` via async git.

    Uses ``git rev-parse --verify <ref>^{commit}``: the ``^{commit}``
    suffix together with ``--verify`` makes an unreachable or non-commit
    ref exit non-zero instead of echoing the input back — exactly the
    failure `StalePinError` must catch.

    Args:
        repo: Repository name (for error messages only).
        ref: The ref/SHA/branch name to resolve.
        repo_path: Local filesystem path to the repo's working tree.

    Returns:
        The resolved concrete SHA.

    Raises:
        StalePinError: If the ref cannot be resolved to a reachable commit.
    """
    process = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        str(repo_path),
        "rev-parse",
        "--verify",
        f"{ref}^{{commit}}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise StalePinError(repo, ref, detail=stderr.decode("utf-8", errors="replace").strip())
    return stdout.decode("utf-8").strip()


async def resolve_workspace(
    refs: Mapping[str, str],
    *,
    primary: str,
    weight_table_version: str,
    repo_paths: Mapping[str, Path],
    package_map_version: str | None = None,
) -> WorkspacePin:
    """Resolve every repo's ref to a concrete SHA and freeze it into a pin.

    Resolution happens once, at admission — the resulting `WorkspacePin` is
    then held for the whole request/session (spec §3.4, OQ-1).

    Args:
        refs: ``repo -> ref`` mapping (branch name, tag, ``HEAD``, or an
            already-concrete SHA) to resolve.
        primary: Name of the repo that anchors relative resolution.
        weight_table_version: `EdgeWeightTable` version in effect.
        repo_paths: ``repo -> local working-tree path``, used to run
            ``git rev-parse`` in the right repository.
        package_map_version: `PackageRepoMap` version in effect, if any.

    Returns:
        A frozen `WorkspacePin` with every repo resolved to a concrete SHA.

    Raises:
        StalePinError: If any repo's ref cannot be resolved to a reachable
            commit. Per spec §3.4, this never silently falls back to HEAD.
        KeyError: If `repo_paths` is missing an entry for a repo in `refs`.
    """
    resolved: dict[str, str] = {}
    for repo, ref in refs.items():
        if repo not in repo_paths:
            raise KeyError(f"resolve_workspace: no repo_path given for repo {repo!r}")
        resolved[repo] = await _resolve_ref(repo, ref, repo_paths[repo])

    return WorkspacePin(
        primary=primary,
        pins=MappingProxyType(resolved),
        pinned_at=datetime.now(UTC),
        weight_table_version=weight_table_version,
        package_map_version=package_map_version,
    )


class CoherenceReport(BaseModel):
    """Result of a bounded pin-coherence check (spec §3.5.3).

    A sampled check can **false-pass**: it corroborates that the index
    likely corresponds to the pin, it does not verify it exhaustively.
    This is strictly weaker than storing the build rev in L0, and is the
    accepted price of keeping L0 read-only (spec §1.2). The residual risk
    is removed entirely if/when L0 gains a one-column ``build_rev`` on the
    ``files`` table (out of scope here — see spec §3.5.3, RQ-1-adjacent).

    Attributes:
        repo: The repo this report is about.
        sampled_paths: The ``source_uri``s that were sampled, in the
            deterministic order they were checked — same pin, same sample.
        mismatched_paths: The subset of ``sampled_paths`` whose content at
            the pinned rev did not hash to the stored ``sha1`` (or could
            not be read at that rev at all).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    repo: str
    sampled_paths: tuple[str, ...]
    mismatched_paths: tuple[str, ...] = ()

    @property
    def sampled(self) -> int:
        """Number of files sampled."""
        return len(self.sampled_paths)

    @property
    def mismatched(self) -> int:
        """Number of sampled files whose content did not match."""
        return len(self.mismatched_paths)

    @property
    def coherent(self) -> bool:
        """``True`` iff no sampled file mismatched."""
        return not self.mismatched_paths


async def read_at_rev(repo_path: Path, rev: str, path: str) -> bytes:
    """Read a file's exact content **at a pinned rev**, via ``git cat-file``.

    All content served by any retrieval policy flows through this
    function, so `Evidence.digest` (TASK-2273) always hashes bytes that
    provably match the pin — never the working tree, which may have moved.

    Args:
        repo_path: Local filesystem path to the repo's working tree.
        rev: Concrete git SHA to read at.
        path: Repo-relative file path.

    Returns:
        The raw file bytes as they existed at ``rev``.

    Raises:
        LookupError: If the path does not exist at that rev, or the
            object cannot be read (deleted file, corrupted repo, etc.).
    """
    process = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        str(repo_path),
        "cat-file",
        "blob",
        f"{rev}:{path}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise LookupError(
            f"Cannot read {path!r} at rev {rev!r} in {repo_path}: "
            f"{stderr.decode('utf-8', errors='replace').strip()}"
        )
    return stdout


async def _read_files_table_sample(db_path: Path) -> list[tuple[str, str]]:
    """Read every ``(source_uri, sha1)`` row from the ``files`` table.

    Args:
        db_path: Path to the tenant's SQLite database file.

    Returns:
        Rows sorted by ``source_uri`` — a stable order the deterministic
        sampler in `check_pin_coherence` relies on.
    """
    async with aiosqlite.connect(str(db_path)) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT source_uri, sha1 FROM files ORDER BY source_uri"
        ) as cur:
            rows = await cur.fetchall()
    return [(row["source_uri"], row["sha1"]) for row in rows]


def _select_deterministic_sample(
    rows: list[tuple[str, str]], sample: int
) -> list[tuple[str, str]]:
    """Pick up to `sample` rows via a stable stride over sorted `rows`.

    Deterministic given the same input (spec §3.5.3: "Sampling must be
    deterministic... so INV-3-style replay of a request is reproducible"),
    with no reliance on `random`.

    Args:
        rows: All candidate rows, already sorted by ``source_uri``.
        sample: Maximum number of rows to select.

    Returns:
        Up to `sample` rows, evenly strided across `rows`.
    """
    if len(rows) <= sample or sample <= 0:
        return rows
    stride = len(rows) / sample
    indices = sorted({int(i * stride) for i in range(sample)})
    return [rows[i] for i in indices]


async def check_pin_coherence(
    pin: WorkspacePin,
    persistence: SQLitePersistence,
    ctx: TenantContext,
    repo: str,
    repo_path: Path,
    *,
    sample: int = DEFAULT_PIN_VERIFICATION_SAMPLE,
    allow_stale: bool = True,
) -> CoherenceReport:
    """Corroborate (not verify) that the GraphIndex corresponds to `pin`.

    L0 does not record the rev it was built from, so exact verification is
    impossible without an L0 schema change (out of scope, spec §1.2).
    Instead: hash a bounded, deterministic sample of the ``files`` table's
    content **at the pinned rev**, using the exact hash function the
    builder used (plain ``sha1`` of file bytes — NOT a git blob hash, which
    includes a ``"blob <len>\\0"`` prefix and would never match).

    Args:
        pin: The `WorkspacePin` to corroborate.
        persistence: The tenant's `SQLitePersistence` backend.
        ctx: Tenant context, used to resolve the SQLite db path.
        repo: Which repo in `pin` this check is for.
        repo_path: Local filesystem path to that repo's working tree.
        sample: Maximum number of files to sample (bounded — never
            exhaustive; spec §3.5.3 explicitly rejects O(files) git calls).
        allow_stale: If ``False`` and the check finds a mismatch, raises
            `IndexPinMismatchError`. If ``True`` (default, matches
            `RetrievalBudget.allow_stale`'s default), mismatches are
            returned on the report instead of raised.

    Returns:
        A `CoherenceReport` describing what was sampled and what, if
        anything, mismatched.

    Raises:
        IndexPinMismatchError: If a mismatch is found and
            ``allow_stale=False``.
    """
    db_path = persistence._db_path(ctx)
    all_rows = await _read_files_table_sample(db_path)
    sampled_rows = _select_deterministic_sample(all_rows, sample)

    rev = pin.rev_of(repo)
    mismatched: list[str] = []
    for source_uri, stored_sha1 in sampled_rows:
        try:
            content = await read_at_rev(repo_path, rev, source_uri)
        except LookupError:
            mismatched.append(source_uri)
            continue
        actual_sha1 = hashlib.sha1(content).hexdigest()
        if actual_sha1 != stored_sha1:
            mismatched.append(source_uri)

    report = CoherenceReport(
        repo=repo,
        sampled_paths=tuple(uri for uri, _ in sampled_rows),
        mismatched_paths=tuple(mismatched),
    )
    if not report.coherent and not allow_stale:
        raise IndexPinMismatchError(repo, report.sampled, report.mismatched)
    return report
