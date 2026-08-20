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
