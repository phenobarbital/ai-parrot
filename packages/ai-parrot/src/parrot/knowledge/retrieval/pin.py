"""`WorkspacePin` — the cross-repo unit of coherence (spec §3.4, TASK-2274).

A retrieval request is scoped not to a single ``(repo, rev)`` but to a
**frozen set of pins**, resolved once at request admission. HEAD moving
underneath a long-lived session does not change retrieval results;
advancing is an explicit, separate action (a `dev_loop` reducer concern,
out of scope here).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, field_validator

from parrot.knowledge.retrieval.exceptions import StalePinError

logger = logging.getLogger(__name__)

#: Default threshold (days) past which a pin's age is flagged on the trace
#: (spec §3.4: "pin drift vs L1" — a stale-but-valid pin is expensive, not
#: incorrect, so this is a warning, never an error).
DEFAULT_STALE_PIN_WARNING_DAYS = 7


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
