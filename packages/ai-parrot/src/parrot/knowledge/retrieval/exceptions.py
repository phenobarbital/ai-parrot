"""Exceptions for the GraphIndex Retrieval Layer (FEAT-435).

Kept in their own module so downstream callers can catch them without
importing the full `pin`/`models` surface.
"""

from __future__ import annotations


class StalePinError(Exception):
    """A pinned ref cannot be resolved to a reachable commit.

    Raised at admission (spec §3.4) when a `WorkspacePin` entry names a SHA
    or ref that ``git rev-parse --verify <ref>^{commit}`` cannot resolve —
    typically because the commit was garbage-collected after a force-push
    or branch delete. Per spec §3.4, this must fail loudly: the request
    never silently falls back to ``HEAD``.

    Attributes:
        repo: The repo the unresolvable ref belongs to.
        ref: The ref or SHA that could not be resolved.
        detail: Optional stderr/diagnostic detail from the failed
            ``git rev-parse`` invocation.
    """

    def __init__(self, repo: str, ref: str, detail: str = "") -> None:
        self.repo = repo
        self.ref = ref
        self.detail = detail
        message = f"Unreachable ref {ref!r} in repo {repo!r}: pin cannot be resolved"
        if detail:
            message = f"{message} ({detail})"
        super().__init__(message)


class IndexPinMismatchError(Exception):
    """The GraphIndex does not correspond to the workspace pin (spec §3.5.3).

    L0 does not record the rev it was built from, so a pin cannot be
    *verified* against the index — only *corroborated* by a bounded sample
    of the ``files`` table. Raised when that sampled check finds content
    hashed at the pinned rev that does not match the stored ``sha1``, and
    the caller has NOT set ``budget.allow_stale`` (in which case the
    request is instead served with an ``index_pin_mismatch`` marker on the
    bundle rather than raising).

    Attributes:
        repo: The repo whose index appears stale relative to the pin.
        sampled: Number of files sampled for the coherence check.
        mismatched: Number of sampled files whose hash did not match.
    """

    def __init__(self, repo: str, sampled: int, mismatched: int) -> None:
        self.repo = repo
        self.sampled = sampled
        self.mismatched = mismatched
        super().__init__(
            f"Index/pin incoherence for repo {repo!r}: {mismatched}/{sampled} "
            "sampled files do not match the pinned rev's content"
        )
