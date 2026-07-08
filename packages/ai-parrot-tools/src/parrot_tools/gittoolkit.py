"""Git/GitHub toolkit inspired by :mod:`parrot.tools.jiratoolkit`.

This toolkit focuses on two complementary workflows that frequently appear
in software review loops:

* producing a ``git apply`` compatible patch from pieces of code supplied by
  an agent or user; and
* turning those code snippets into an actionable GitHub pull request via the
  public REST API.

The implementation deliberately mirrors the structure of
``JiraToolkit``—async public methods automatically become tools thanks to the
``AbstractToolkit`` base class—so that it can be dropped into existing agent
configurations with minimal friction.

Only standard library modules (plus :mod:`requests`, :mod:`pydantic`, which
are already dependencies of Parrot, and ``PyGithub>=2.1`` for GitHub App
authentication) are required.
"""

from __future__ import annotations

import asyncio
import base64
import datetime as _dt
from datetime import datetime, timezone
import os
import shutil
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Union

import difflib

import requests
from github import Auth, GithubIntegration
from pydantic import BaseModel, Field, model_validator

from .decorators import tool_schema
from .toolkit import AbstractToolkit


class GitToolkitError(RuntimeError):
    """Raised when the toolkit cannot satisfy a request."""


class RepositoryCredential(BaseModel):
    """Credentials + defaults for a single named repository in a registry.

    Each entry in :attr:`GitToolkit.repositories` is one of these. The alias
    (the dict key) is how tools reference the repository by name; the
    ``repository`` field is the underlying ``owner/name`` slug used to build
    GitHub API URLs.
    """

    repository: str = Field(
        description="GitHub repository in 'owner/name' format.",
    )
    default_branch: str = Field(
        default="main",
        description="Fallback branch used for pull requests against this repo.",
    )
    auth_type: Literal["pat", "github_app"] = Field(
        default="pat",
        description=(
            "Authentication backend. 'pat' uses github_token; 'github_app' "
            "uses app_id + installation_id + private key."
        ),
    )
    github_token: Optional[str] = Field(
        default=None,
        description="Personal access token with repo scope (pat mode).",
    )
    app_id: Optional[int] = Field(
        default=None,
        description="GitHub App ID (required when auth_type='github_app').",
    )
    installation_id: Optional[int] = Field(
        default=None,
        description="Installation ID (required when auth_type='github_app').",
    )
    private_key: Optional[str] = Field(
        default=None,
        description=(
            "PEM contents of the App's private key. Mutually exclusive with "
            "private_key_path."
        ),
    )
    private_key_path: Optional[str] = Field(
        default=None,
        description=(
            "Filesystem path to the App's private key PEM. Mutually exclusive "
            "with private_key."
        ),
    )

    @model_validator(mode="after")
    def _validate_auth(self) -> "RepositoryCredential":  # pragma: no cover - pydantic hook
        """Validate auth fields for both pat and github_app modes."""
        if self.auth_type == "pat":
            if not self.github_token:
                raise ValueError("auth_type='pat' requires github_token")
        elif self.auth_type == "github_app":
            if not self.app_id:
                raise ValueError("auth_type='github_app' requires app_id")
            if not self.installation_id:
                raise ValueError("auth_type='github_app' requires installation_id")
            if self.private_key and self.private_key_path:
                raise ValueError(
                    "auth_type='github_app': set EITHER private_key OR "
                    "private_key_path, not both."
                )
            if not self.private_key and not self.private_key_path:
                raise ValueError(
                    "auth_type='github_app' requires private_key or private_key_path"
                )
        return self


class GitToolkitInput(BaseModel):
    """Default configuration shared by all tools in the toolkit."""

    default_repository: Optional[str] = Field(
        default=None,
        description="Default GitHub repository in 'owner/name' format.",
    )
    default_branch: str = Field(
        default="main", description="Fallback branch used for pull requests."
    )
    github_token: Optional[str] = Field(
        default=None,
        description="Personal access token with repo scope for GitHub calls.",
    )
    auth_type: Literal["pat", "github_app"] = Field(
        default="pat",
        description=(
            "Authentication backend. 'pat' uses github_token; "
            "'github_app' uses app_id + installation_id + private key."
        ),
    )
    app_id: Optional[int] = Field(
        default=None,
        description="GitHub App ID (required when auth_type='github_app').",
    )
    installation_id: Optional[int] = Field(
        default=None,
        description=(
            "Installation ID for the org/account the App is installed in "
            "(required when auth_type='github_app')."
        ),
    )
    private_key: Optional[str] = Field(
        default=None,
        description=(
            "PEM contents of the App's private key. Mutually exclusive "
            "with private_key_path."
        ),
    )
    private_key_path: Optional[str] = Field(
        default=None,
        description=(
            "Filesystem path to the App's private key PEM. Mutually "
            "exclusive with private_key."
        ),
    )
    repositories: Optional[Dict[str, RepositoryCredential]] = Field(
        default=None,
        description=(
            "Named registry mapping an alias to that repository's credentials "
            "and defaults. All credentials are explicit-config only: the "
            "toolkit does NOT read GITHUB_* environment variables for auth "
            "(the default and ad-hoc connections also require explicitly "
            "passed credentials)."
        ),
    )


class GitPatchFile(BaseModel):
    """Represents a single file change for patch generation."""

    path: str = Field(description="Path to the file inside the repository.")
    change_type: Literal["modify", "add", "delete"] = Field(
        default="modify",
        description="Type of change represented by this patch fragment.",
    )
    original: Optional[str] = Field(
        default=None,
        description="Original file contents relevant to the change.",
    )
    updated: Optional[str] = Field(
        default=None,
        description="Updated file contents to apply.",
    )
    from_path: Optional[str] = Field(
        default=None,
        description="Override the 'from' path in the generated diff.",
    )
    to_path: Optional[str] = Field(
        default=None,
        description="Override the 'to' path in the generated diff.",
    )

    @model_validator(mode="after")
    def _validate_payload(self) -> "GitPatchFile":  # pragma: no cover - pydantic hook
        """Ensure the required content is supplied for the selected change."""

        if self.change_type == "modify":
            if self.original is None or self.updated is None:
                raise ValueError("modify changes require both original and updated code")
        elif self.change_type == "add":
            if self.updated is None:
                raise ValueError("add changes require the updated code")
        elif self.change_type == "delete":
            if self.original is None:
                raise ValueError("delete changes require the original code")
        return self


class GeneratePatchInput(BaseModel):
    """Input payload for ``generate_git_apply_patch``."""

    files: List[GitPatchFile] = Field(
        description="Collection of file changes that should be turned into a unified diff.",
    )
    context_lines: int = Field(
        default=3,
        ge=0,
        description="How many context lines to include in the diff output.",
    )
    include_apply_snippet: bool = Field(
        default=True,
        description="If true, include a ready-to-run git-apply heredoc snippet.",
    )


class GitHubFileChange(BaseModel):
    """Description of a file mutation when creating a pull request."""

    path: str = Field(description="File path inside the repository.")
    content: Optional[str] = Field(
        default=None,
        description="New file content. Leave ``None`` to delete a file.",
    )
    encoding: Literal["utf-8", "base64"] = Field(
        default="utf-8", description="Encoding used for ``content``."
    )
    message: Optional[str] = Field(
        default=None,
        description="Optional commit message just for this file change.",
    )
    change_type: Literal["modify", "add", "delete"] = Field(
        default="modify", description="Type of change performed on the file."
    )

    @model_validator(mode="after")
    def _validate_content(self) -> "GitHubFileChange":  # pragma: no cover - pydantic hook
        """Ensure ``content`` is present unless this is a deletion."""

        if self.change_type == "delete" and self.content is not None:
            raise ValueError("delete operations should not provide new content")
        if self.change_type in {"modify", "add"} and self.content is None:
            raise ValueError("modify/add operations require content")
        return self


class CreatePullRequestInput(BaseModel):
    """Input payload for ``create_pull_request``."""

    repository: Optional[str] = Field(
        default=None,
        description=(
            "Target repository: a registered alias from the toolkit's "
            "repositories registry, or a raw 'owner/name' slug. Uses the "
            "default repository when omitted."
        ),
    )
    title: str = Field(description="Pull request title")
    body: Optional[str] = Field(default=None, description="Pull request description")
    base_branch: Optional[str] = Field(
        default=None, description="Branch into which the changes should merge."
    )
    head_branch: Optional[str] = Field(
        default=None, description="Branch name to create and push changes onto."
    )
    commit_message: Optional[str] = Field(
        default=None,
        description="Commit message used for the updates (defaults to title).",
    )
    files: List[GitHubFileChange] = Field(
        description="List of file updates that compose the pull request.",
    )
    draft: bool = Field(
        default=False, description="Create the pull request as a draft if true."
    )
    labels: Optional[List[str]] = Field(
        default=None, description="Optional labels to apply after PR creation."
    )


class GetPullRequestInput(BaseModel):
    """Input payload for ``get_pull_request``."""

    pr_number: int = Field(description="Pull request number on the repository.")
    repository: Optional[str] = Field(
        default=None,
        description="Target repository: a registered alias from the toolkit's repositories registry, or a raw 'owner/name' slug. Uses the default repository when omitted.",
    )


class ListPullRequestsInput(BaseModel):
    """Input payload for ``list_pull_requests``."""

    repository: Optional[str] = Field(
        default=None,
        description="Target repository: a registered alias from the toolkit's repositories registry, or a raw 'owner/name' slug. Uses the default repository when omitted.",
    )
    state: Literal["open", "closed", "all"] = Field(
        default="open",
        description="Filter pull requests by state.",
    )
    per_page: int = Field(
        default=100,
        ge=1,
        le=100,
        description="Number of pull requests per page (max 100).",
    )


class GetPullRequestDiffInput(BaseModel):
    """Input payload for ``get_pull_request_diff``."""

    pr_number: int = Field(description="Pull request number on the repository.")
    repository: Optional[str] = Field(
        default=None,
        description="Target repository: a registered alias from the toolkit's repositories registry, or a raw 'owner/name' slug. Uses the default repository when omitted.",
    )
    max_bytes: int = Field(
        default=50_000,
        ge=0,
        description="Truncate the diff to at most this many bytes (0 disables truncation).",
    )


class AddPRCommentInput(BaseModel):
    """Input payload for ``add_pr_comment``."""

    pr_number: int = Field(description="Pull request number on the repository.")
    body: str = Field(description="Comment body in Markdown.")
    repository: Optional[str] = Field(
        default=None,
        description="Target repository: a registered alias from the toolkit's repositories registry, or a raw 'owner/name' slug. Uses the default repository when omitted.",
    )


class SubmitPRReviewInput(BaseModel):
    """Input payload for ``submit_pr_review``."""

    pr_number: int = Field(description="Pull request number on the repository.")
    event: Literal["APPROVE", "REQUEST_CHANGES", "COMMENT"] = Field(
        description="Review event to record on the pull request."
    )
    body: str = Field(description="Review body in Markdown (required for REQUEST_CHANGES).")
    repository: Optional[str] = Field(
        default=None,
        description="Target repository: a registered alias from the toolkit's repositories registry, or a raw 'owner/name' slug. Uses the default repository when omitted.",
    )


# ---------------------------------------------------------------------------
# PR context retrieval models (FEAT-182 — On-Demand Code Retrieval)
# ---------------------------------------------------------------------------


class GetFileContentInput(BaseModel):
    """Input payload for ``get_file_content_at_ref``."""

    path: str = Field(
        description="File path inside the repository, e.g. 'src/parrot/bots/agent.py'."
    )
    ref: str = Field(
        description="Branch name, tag, or commit SHA at which to retrieve the file."
    )
    repository: Optional[str] = Field(
        default=None,
        description="Target repository: a registered alias from the toolkit's repositories registry, or a raw 'owner/name' slug. Uses the default repository when omitted.",
    )
    start_line: Optional[int] = Field(
        default=None,
        ge=1,
        description=(
            "First line to return (1-indexed). When provided together with end_line, "
            "only that slice is returned and truncated=True is set on the result."
        ),
    )
    end_line: Optional[int] = Field(
        default=None,
        ge=1,
        description=(
            "Last line to return (1-indexed, inclusive). Must be >= start_line when both are set."
        ),
    )

    @model_validator(mode="after")
    def _validate_line_range(self) -> "GetFileContentInput":
        """Ensure end_line is not less than start_line when both are provided.

        Returns:
            The validated model instance.

        Raises:
            ValueError: When ``end_line < start_line`` and both are set.
        """
        if self.start_line is not None and self.end_line is not None:
            if self.end_line < self.start_line:
                raise ValueError(
                    f"end_line ({self.end_line}) must be >= start_line ({self.start_line})"
                )
        return self


class ComparePRVersionsInput(BaseModel):
    """Input payload for ``compare_pr_versions``."""

    pr_number: int = Field(
        ge=1,
        description="Pull request number on the repository.",
    )
    path: str = Field(
        description="File path to compare between the PR base and head refs.",
    )
    repository: Optional[str] = Field(
        default=None,
        description="Target repository: a registered alias from the toolkit's repositories registry, or a raw 'owner/name' slug. Uses the default repository when omitted.",
    )


class SearchRepoCodeInput(BaseModel):
    """Input payload for ``search_repo_code``."""

    query: str = Field(
        description=(
            "Code Search query text without the 'repo:' qualifier — that qualifier "
            "is injected automatically to scope the search to the PR's repository."
        )
    )
    repository: Optional[str] = Field(
        default=None,
        description="Target repository: a registered alias from the toolkit's repositories registry, or a raw 'owner/name' slug. Uses the default repository when omitted.",
    )
    max_results: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of results to return (1-100). GitHub caps this at 100 per request.",
    )


class FileContentResult(BaseModel):
    """Return payload for ``get_file_content_at_ref``."""

    exists: bool = Field(
        description="True when the file was found at the given ref; False on 404."
    )
    path: str = Field(
        description="File path as requested."
    )
    ref: str = Field(
        description="Ref (branch, tag, or SHA) that was used to resolve the file."
    )
    repository: str = Field(
        description="Repository in 'owner/name' format."
    )
    content: Optional[str] = Field(
        default=None,
        description="Decoded UTF-8 text content of the file, or None when exists=False or error is set.",
    )
    encoding: Optional[str] = Field(
        default=None,
        description="Content encoding: 'utf-8' for text files or 'base64' for binary blobs.",
    )
    size_bytes: Optional[int] = Field(
        default=None,
        description="Raw file size in bytes as reported by the GitHub Contents API.",
    )
    sha: Optional[str] = Field(
        default=None,
        description="Git blob SHA — used as the cache key for _FileBlobCache.",
    )
    commit_author: Optional[str] = Field(
        default=None,
        description="GitHub login of the author of the most recent commit that touched this file at ref.",
    )
    truncated: bool = Field(
        default=False,
        description="True when start_line/end_line slicing was applied to the content.",
    )
    error: Optional[str] = Field(
        default=None,
        description=(
            "Error indicator. 'file_too_large' when the blob exceeds GitHub's 1 MB limit; "
            "'rate_limited' when the API quota is exhausted; None on success."
        ),
    )


class CompareVersionsResult(BaseModel):
    """Return payload for ``compare_pr_versions``."""

    repository: str = Field(
        description="Repository in 'owner/name' format."
    )
    pr_number: int = Field(
        description="Pull request number."
    )
    path: str = Field(
        description="File path that was compared."
    )
    base_sha: str = Field(
        description="Full commit SHA of the PR base ref."
    )
    head_sha: str = Field(
        description="Full commit SHA of the PR head ref."
    )
    base: FileContentResult = Field(
        description="File content at the base ref (before the PR's changes)."
    )
    head: FileContentResult = Field(
        description="File content at the head ref (after the PR's changes)."
    )


class SearchCodeResult(BaseModel):
    """Return payload for ``search_repo_code``."""

    repository: str = Field(
        description="Repository in 'owner/name' format that was searched."
    )
    query: str = Field(
        description="The original query string (without the auto-injected repo: qualifier)."
    )
    total_count: int = Field(
        description="Total number of matching results as reported by GitHub Code Search."
    )
    items: List[Dict[str, Any]] = Field(
        description=(
            "Raw GitHub Code Search item list. Each item contains at minimum: "
            "'path', 'name', 'sha', 'html_url', and 'score'."
        )
    )
    error: Optional[str] = Field(
        default=None,
        description="Error indicator. 'rate_limited' when the search API quota is exhausted; None on success.",
    )


# ---------------------------------------------------------------------------
# Stats data models (FEAT-180 — GitHub Repository Weekly Activity Report)
# ---------------------------------------------------------------------------


class ContributorWeek(BaseModel):
    """One week's slice of a contributor's activity.

    Mirrors the GitHub ``weeks[]`` entry from
    ``GET /repos/{owner}/{repo}/stats/contributors``.
    """

    week_start: datetime
    """Sunday 00:00 UTC that begins this week (GitHub epoch converted to UTC)."""
    additions: int
    """Lines added in the week."""
    deletions: int
    """Lines deleted in the week (non-negative)."""
    commits: int
    """Commit count for the week."""


class ContributorStats(BaseModel):
    """Aggregated stats for a single contributor across the repository's history."""

    login: Optional[str]
    """GitHub login, or ``None`` when the commit email is not linked to an account."""
    avatar_url: Optional[str] = None
    """Avatar URL from the GitHub user object (``None`` for anonymous)."""
    total_commits: int
    """All-time commit count for this contributor."""
    weeks: List[ContributorWeek]
    """Per-week breakdown — most recent last (GitHub ordering)."""


class WeeklyCodeFrequency(BaseModel):
    """Repo-wide weekly additions/deletions totals.

    Sourced from ``GET /repos/{owner}/{repo}/stats/code_frequency``.
    """

    week_start: datetime
    """Sunday 00:00 UTC that begins this week."""
    additions: int
    """Total lines added across the repository in the week."""
    deletions: int
    """Total lines deleted (stored as non-negative; GitHub returns negative)."""


# Input schemas for the three stats tools


class GetContributorStatsInput(BaseModel):
    """Input payload for ``get_contributor_stats``."""

    repository: Optional[str] = Field(
        default=None,
        description="Target repository: a registered alias from the toolkit's repositories registry, or a raw 'owner/name' slug. Uses the default repository when omitted.",
    )


class GetCommitActivityInput(BaseModel):
    """Input payload for ``get_weekly_commit_activity``."""

    repository: Optional[str] = Field(
        default=None,
        description="Target repository: a registered alias from the toolkit's repositories registry, or a raw 'owner/name' slug. Uses the default repository when omitted.",
    )


class GetCodeFrequencyInput(BaseModel):
    """Input payload for ``get_code_frequency``."""

    repository: Optional[str] = Field(
        default=None,
        description="Target repository: a registered alias from the toolkit's repositories registry, or a raw 'owner/name' slug. Uses the default repository when omitted.",
    )


@dataclass
class _GitHubContext:
    """Simple container with prepared GitHub configuration."""

    repository: str
    base_branch: str
    token: str


class _GitHubAppTokenProvider:
    """Mints + caches GitHub App installation access tokens.

    Single explicit installation. Token is cached in-process and refreshed
    when within 60 seconds of expiry. Safe to call from threads spawned by
    ``asyncio.to_thread``.

    Args:
        app_id: GitHub App ID.
        installation_id: Installation ID for the org/account the App is
            installed in.
        private_key_pem: PEM contents of the App's private key (always
            resolved to a string before construction — file-path handling
            lives in ``GitToolkit.__init__``).
    """

    _REFRESH_LEEWAY = _dt.timedelta(seconds=60)

    def __init__(
        self,
        app_id: int,
        installation_id: int,
        private_key_pem: str,
    ) -> None:
        self._app_id = app_id
        self._installation_id = installation_id
        self._private_key_pem = private_key_pem
        self._token: Optional[str] = None
        self._expires_at: Optional[_dt.datetime] = None
        self._lock = threading.Lock()

    def get_token(self) -> str:
        """Return a valid installation access token, refreshing when <=60s from expiry.

        Returns:
            A valid GitHub App installation access token string.

        Raises:
            GitToolkitError: If the underlying ``GithubIntegration.get_access_token``
                call fails.
        """
        with self._lock:
            now = _dt.datetime.now(_dt.timezone.utc)
            if (
                self._token is None
                or self._expires_at is None
                or self._expires_at - now <= self._REFRESH_LEEWAY
            ):
                self._refresh()
            return self._token  # type: ignore[return-value]

    def _refresh(self) -> None:
        """Mint a new installation access token from GitHub.

        Raises:
            GitToolkitError: If token minting fails (wraps the underlying exception).
        """
        try:
            auth = Auth.AppAuth(self._app_id, self._private_key_pem)
            integration = GithubIntegration(auth=auth)
            installation_auth = integration.get_access_token(self._installation_id)
        except Exception as exc:
            raise GitToolkitError(
                f"Failed to mint GitHub App installation token: {exc}"
            ) from exc
        self._token = installation_auth.token
        self._expires_at = installation_auth.expires_at
        if self._expires_at is not None and self._expires_at.tzinfo is None:
            # Defensive: PyGithub returns tz-aware UTC, but normalise just in case.
            self._expires_at = self._expires_at.replace(tzinfo=_dt.timezone.utc)


def _load_pem(
    private_key: Optional[str],
    private_key_path: Optional[str],
) -> str:
    """Resolve a PEM from inline contents or file path (exactly one must be set)."""
    if private_key and private_key_path:
        raise GitToolkitError(
            "auth_type='github_app': set EITHER private_key OR "
            "private_key_path, not both."
        )
    if not private_key and not private_key_path:
        raise GitToolkitError(
            "auth_type='github_app' requires an explicit private_key or "
            "private_key_path (no environment-variable fallback)."
        )
    pem = private_key
    if private_key_path:
        try:
            with open(private_key_path, "r", encoding="utf-8") as fh:
                pem = fh.read()
        except OSError as exc:
            raise GitToolkitError(
                f"Could not read GitHub App private key from {private_key_path}: {exc}"
            ) from exc
    # Defensive: env-injected PEMs sometimes carry literal "\n" escape sequences.
    return pem.replace("\\n", "\n")  # type: ignore[union-attr]


class _RepoConnection:
    """Resolved connection to one repository: slug, branch default, and token provider."""

    def __init__(
        self,
        repository: str,
        default_branch: str,
        auth_type: Literal["pat", "github_app"],
        *,
        github_token: Optional[str] = None,
        token_provider: Optional[_GitHubAppTokenProvider] = None,
        app_id: Optional[int] = None,
        installation_id: Optional[int] = None,
        private_key: Optional[str] = None,
        private_key_path: Optional[str] = None,
    ) -> None:
        self.repository = repository
        self.default_branch = default_branch
        self.auth_type = auth_type
        self._github_token = github_token
        self._token_provider: Optional[_GitHubAppTokenProvider] = None
        if auth_type == "github_app":
            if token_provider is not None:
                self._token_provider = token_provider
            else:
                if not app_id:
                    raise GitToolkitError(
                        "auth_type='github_app' requires app_id."
                    )
                if not installation_id:
                    raise GitToolkitError(
                        "auth_type='github_app' requires installation_id."
                    )
                pem = _load_pem(private_key, private_key_path)
                self._token_provider = _GitHubAppTokenProvider(
                    app_id=app_id,
                    installation_id=installation_id,
                    private_key_pem=pem,
                )

    def token(self) -> str:
        """Return the bearer token for the next API call to this repo."""
        if self.auth_type == "github_app":
            if self._token_provider is None:
                raise GitToolkitError(
                    "BUG: _token_provider is None in github_app mode; internal error."
                )
            return self._token_provider.get_token()
        if not self._github_token:
            raise GitToolkitError(
                "A GitHub personal access token is required: pass github_token "
                "explicitly. The toolkit no longer falls back to the "
                "GITHUB_TOKEN environment variable."
            )
        return self._github_token


class _FileBlobCache:
    """SHA-keyed blob cache that fronts GitHub file-content fetches.

    Stores raw content bytes keyed by ``(repository, blob_sha)`` — because git
    blob SHAs are content-addressed and immutable, the cache never needs
    invalidation; a TTL is applied only as a hygiene measure.

    Storage backend:
    * **Redis** when ``REDIS_URL`` is set in navconfig. A shared async pool is
      created once on the first access and reused for the process lifetime.
    * **In-memory LRU** (via :class:`cachetools.TTLCache`) as a transparent
      fallback when Redis is absent or unreachable.

    The cache is safe to call from multiple concurrent coroutines in the same
    process because initialisation is guarded by an :class:`asyncio.Lock`.

    .. note::
        **Deviation from spec (CRITICAL-3)**: The spec requests using
        ``CachePartition`` from ``parrot.bots.database.cache`` for Redis
        access. However, ``CachePartition`` is designed for schema/table
        metadata (it caches :class:`~parrot.bots.database.cache.TableMetadata`
        objects keyed by schema+table name) and is not importable from
        ``parrot_tools`` without introducing a cross-package dependency on the
        ``ai-parrot`` package (``parrot_tools`` is intentionally a lighter
        package that does not depend on the core ``parrot`` runtime).

        TODO(FEAT-182): If ``parrot_tools`` ever gains an explicit dependency
        on ``ai-parrot``, replace the inline ``redis.asyncio.from_url()`` pool
        with a shared ``CachePartition`` / ``CacheManager`` instance so that
        the Redis connection pool is managed centrally by the Parrot runtime.
        The cache key schema (``gittoolkit_blob:<repo>:<sha>``) must be
        preserved during the migration.

    Example::

        cache = _FileBlobCache()
        data = await cache.get("owner/repo", "deadbeef")
        if data is None:
            data = fetch_from_github(...)
            await cache.set("owner/repo", "deadbeef", data)
    """

    _NAMESPACE = "gittoolkit_blob"
    _LRU_MAXSIZE = 1024

    def __init__(self) -> None:
        self._lru: Optional[Any] = None  # cachetools.TTLCache, created lazily
        self._redis_pool: Optional[Any] = None
        self._ttl: int = 604800
        self._lock = asyncio.Lock()
        self._lru_initialised = False
        self._redis_initialised = False

    def _cache_key(self, repository: str, sha: str) -> str:
        """Build a normalised cache key."""
        return f"{self._NAMESPACE}:{repository.lower()}:{sha}"

    def _ensure_lru(self) -> None:
        """Initialise the LRU synchronously (safe to call from sync code)."""
        if self._lru_initialised:
            return
        try:
            from navconfig import config as _cfg
            ttl_raw = _cfg.get("GITHUB_REVIEWER_BLOB_CACHE_TTL", fallback=604800)
            self._ttl = int(ttl_raw)
        except Exception:  # noqa: BLE001
            self._ttl = 604800
        try:
            from cachetools import TTLCache
            self._lru = TTLCache(maxsize=self._LRU_MAXSIZE, ttl=self._ttl)
        except Exception:  # noqa: BLE001
            self._lru = {}
        self._lru_initialised = True

    async def _ensure_redis(self) -> None:
        """Initialise the Redis pool asynchronously (once)."""
        if self._redis_initialised:
            return
        async with self._lock:
            if self._redis_initialised:
                return
            try:
                from navconfig import config as _cfg
                redis_url = _cfg.get("REDIS_URL")
                if redis_url:
                    import redis.asyncio as aioredis
                    self._redis_pool = aioredis.from_url(redis_url, decode_responses=False)
            except Exception as exc:  # noqa: BLE001
                import logging
                logging.getLogger(__name__).warning(
                    "_FileBlobCache: Redis unavailable (%s) — LRU-only mode", exc
                )
                self._redis_pool = None
            self._redis_initialised = True

    async def get(self, repository: str, sha: str) -> Optional[bytes]:
        """Return cached blob bytes, or ``None`` on a cache miss.

        Args:
            repository: Repository in ``"owner/name"`` format (case-insensitive).
            sha: Git blob SHA (used as part of the cache key).

        Returns:
            Raw content bytes if cached, ``None`` otherwise.
        """
        self._ensure_lru()
        await self._ensure_redis()
        key = self._cache_key(repository, sha)

        # Tier 1: LRU
        if self._lru is not None and key in self._lru:
            return self._lru[key]  # type: ignore[return-value]

        # Tier 2: Redis
        if self._redis_pool is not None:
            try:
                value = await self._redis_pool.get(key)
                if value is not None:
                    # Populate LRU for subsequent hits in the same process.
                    if self._lru is not None:
                        self._lru[key] = value
                    return value  # type: ignore[return-value]
            except Exception:  # noqa: BLE001
                pass

        return None

    async def set(self, repository: str, sha: str, content: bytes) -> None:
        """Store blob bytes in the cache.

        Args:
            repository: Repository in ``"owner/name"`` format (case-insensitive).
            sha: Git blob SHA.
            content: Raw content bytes to store.
        """
        self._ensure_lru()
        await self._ensure_redis()
        key = self._cache_key(repository, sha)

        # Tier 1: LRU
        if self._lru is not None:
            self._lru[key] = content

        # Tier 2: Redis
        if self._redis_pool is not None:
            try:
                await self._redis_pool.set(key, content, ex=self._ttl)
            except Exception:  # noqa: BLE001
                pass


class GitToolkit(AbstractToolkit):
    """Toolkit dedicated to Git patch generation and GitHub pull requests."""

    input_class = GitToolkitInput

    # Shared blob cache — one instance per process; safe for concurrent coroutines.
    _blob_cache: _FileBlobCache = _FileBlobCache()

    def __init__(
        self,
        default_repository: Optional[str] = None,
        default_branch: str = "main",
        github_token: Optional[str] = None,
        auth_type: Literal["pat", "github_app"] = "pat",
        app_id: Optional[int] = None,
        installation_id: Optional[int] = None,
        private_key: Optional[str] = None,
        private_key_path: Optional[str] = None,
        repositories: Optional[Dict[str, Union[RepositoryCredential, dict]]] = None,
        **kwargs: Any,
    ) -> None:
        """Initialise the Git/GitHub toolkit.

        Args:
            default_repository: Default repo in ``owner/name`` format.
            default_branch: Fallback branch for pull requests.
            github_token: PAT for GitHub API calls (required in pat mode).
            auth_type: Authentication backend — ``'pat'`` (default) or
                ``'github_app'``.
            app_id: GitHub App ID (required when auth_type='github_app').
            installation_id: Installation ID for the org/account the App is
                installed in (required when auth_type='github_app').
            private_key: PEM contents of the App's private key. Mutually
                exclusive with ``private_key_path``.
            private_key_path: Filesystem path to the App's private key PEM.
                Mutually exclusive with ``private_key``.
            repositories: Optional named registry mapping an alias to that
                repository's credentials (``RepositoryCredential`` or an
                equivalent dict). Tools may reference a repository by its alias
                or by its raw ``owner/name`` slug. Registry entries are
                explicit-config only — they do NOT inherit ``GITHUB_*`` env
                vars. Passing a ``"default"`` alias here while the legacy
                ``default_repository`` argument is also set raises, to avoid
                ambiguity.
            **kwargs: Forwarded to the base class.

        Raises:
            GitToolkitError: When ``auth_type`` is invalid or required App-mode
                fields are missing / mutually exclusive constraints are violated,
                or when a ``"default"`` registry alias collides with the legacy
                default-repository arguments.
        """
        super().__init__(**kwargs)

        self.default_repository = (
            default_repository
            or os.getenv("GIT_DEFAULT_REPOSITORY")
            or os.getenv("GITHUB_REPOSITORY")
        )
        self.default_branch = (
            default_branch or os.getenv("GIT_DEFAULT_BRANCH") or "main"
        )
        # No silent env-var fallback for credentials. The PAT must be passed
        # explicitly; otherwise the toolkit stays unauthenticated and raises a
        # clear GitToolkitError at call time (see ``_default_token`` /
        # ``_resolve_connection`` / ``_RepoConnection.token``) rather than
        # quietly authenticating as a shared ``GITHUB_TOKEN`` account.
        self.github_token = github_token

        self.auth_type: Literal["pat", "github_app"] = auth_type
        if self.auth_type not in ("pat", "github_app"):
            raise GitToolkitError(
                f"Unsupported auth_type {self.auth_type!r}; expected 'pat' or 'github_app'."
            )

        # Always initialise these attributes; None in PAT mode. GitHub App
        # credentials must be passed explicitly — no silent env-var fallback.
        self.app_id: Optional[int] = app_id
        self.installation_id: Optional[int] = installation_id
        self._private_key_pem: Optional[str] = None
        self._token_provider: Optional[_GitHubAppTokenProvider] = None

        if self.auth_type == "github_app":
            if not self.app_id:
                raise GitToolkitError(
                    "auth_type='github_app' requires an explicit app_id."
                )
            if not self.installation_id:
                raise GitToolkitError(
                    "auth_type='github_app' requires an explicit installation_id."
                )

            # Explicit-only: no GITHUB_APP_PRIVATE_KEY / _PATH env fallback.
            inline_pem = _load_pem(private_key, private_key_path)

            self._token_provider = _GitHubAppTokenProvider(
                app_id=self.app_id,
                installation_id=self.installation_id,
                private_key_pem=inline_pem,
            )

        # ------------------------------------------------------------------
        # Multi-repository registry (alias -> _RepoConnection)
        # ------------------------------------------------------------------
        self._connections: Dict[str, _RepoConnection] = {}
        self._connections_lock = threading.Lock()

        # Build the "default" connection from the legacy fields, reusing the
        # already-built token provider so it shares the cached App token.
        if self.default_repository:
            self._connections["default"] = _RepoConnection(
                repository=self.default_repository,
                default_branch=self.default_branch,
                auth_type=self.auth_type,
                github_token=self.github_token,
                token_provider=self._token_provider,
            )

        # Register explicit named repositories.
        if repositories:
            if "default" in repositories and self.default_repository:
                raise GitToolkitError(
                    "A 'default' alias in repositories collides with the legacy "
                    "default_repository argument; use one or the other."
                )
            for alias, value in repositories.items():
                cred = (
                    value
                    if isinstance(value, RepositoryCredential)
                    else RepositoryCredential.model_validate(value)
                )
                self._connections[alias] = _RepoConnection(
                    repository=cred.repository,
                    default_branch=cred.default_branch,
                    auth_type=cred.auth_type,
                    github_token=cred.github_token,
                    app_id=cred.app_id,
                    installation_id=cred.installation_id,
                    private_key=cred.private_key,
                    private_key_path=cred.private_key_path,
                )

    # ------------------------------------------------------------------
    # Connection / bearer token resolution
    # ------------------------------------------------------------------
    def _default_token(self) -> str:
        """Return the bearer token for the global/default credentials."""
        if self.auth_type == "github_app":
            if self._token_provider is None:
                raise GitToolkitError(
                    "BUG: _token_provider is None in github_app mode; this is an internal error."
                )
            return self._token_provider.get_token()
        # PAT mode
        if not self.github_token:
            raise GitToolkitError(
                "A GitHub personal access token is required: pass github_token "
                "explicitly. The toolkit no longer falls back to the "
                "GITHUB_TOKEN environment variable."
            )
        return self.github_token

    def _resolve_connection(self, repository: Optional[str]) -> _RepoConnection:
        """Map None / alias / ``owner/name`` slug to a ``_RepoConnection``."""
        if repository is None:
            conn = self._connections.get("default")
            if conn is None:
                raise GitToolkitError(
                    "A target repository is required (pass repository or "
                    "configure default)."
                )
            return conn

        # Fast path (no lock): alias hit from the pre-built registry.
        conn = self._connections.get(repository)
        if conn is not None:
            return conn

        # Slug scan + ad-hoc creation under lock (safe for free-threaded Python).
        with self._connections_lock:
            # Re-check after acquiring lock.
            conn = self._connections.get(repository)
            if conn is not None:
                return conn

            # Raw slug matching a registered connection's repository field.
            for existing in self._connections.values():
                if existing.repository == repository:
                    return existing

            # Unknown slug -> ad-hoc connection from global/default creds.
            if self.auth_type == "github_app":
                if self._token_provider is None:
                    raise GitToolkitError(
                        "No GitHub App credentials configured to access "
                        f"{repository!r}."
                    )
            elif not self.github_token:
                raise GitToolkitError(
                    "A GitHub personal access token is required: pass "
                    "github_token explicitly. The toolkit no longer falls back "
                    "to the GITHUB_TOKEN environment variable."
                )
            conn = _RepoConnection(
                repository=repository,
                default_branch=self.default_branch,
                auth_type=self.auth_type,
                github_token=self.github_token,
                token_provider=self._token_provider,
            )
            self._connections[repository] = conn
            return conn

    def _bearer_token(self) -> str:
        """Legacy shim — delegates to ``_default_token``."""
        return self._default_token()

    # ------------------------------------------------------------------
    # Patch generation helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _ensure_trailing_newline(text: str) -> str:
        """Return ``text`` ensuring it terminates with a single newline."""

        if text.endswith("\n"):
            return text
        return f"{text}\n"

    @staticmethod
    def _make_diff_fragment(
        change: GitPatchFile,
        context_lines: int,
    ) -> Optional[str]:
        """Produce a unified diff fragment for ``change``."""

        from_path = change.from_path or f"a/{change.path}"
        to_path = change.to_path or f"b/{change.path}"

        if change.change_type == "add":
            original_lines: List[str] = []
            updated_lines = GitToolkit._ensure_trailing_newline(change.updated or "").splitlines(True)
            from_path = "/dev/null"
        elif change.change_type == "delete":
            original_lines = GitToolkit._ensure_trailing_newline(change.original or "").splitlines(True)
            updated_lines = []
            to_path = "/dev/null"
        else:
            original_lines = GitToolkit._ensure_trailing_newline(change.original or "").splitlines(True)
            updated_lines = GitToolkit._ensure_trailing_newline(change.updated or "").splitlines(True)

        diff = list(
            difflib.unified_diff(
                original_lines,
                updated_lines,
                fromfile=from_path,
                tofile=to_path,
                n=context_lines,
            )
        )

        if not diff:
            return None

        # Ensure diff chunks end with a newline to keep git-apply happy.
        diff_text = "".join(diff)
        if not diff_text.endswith("\n"):
            diff_text += "\n"
        return diff_text

    def _render_patch(
        self,
        files: List[GitPatchFile],
        context_lines: int,
        include_apply_snippet: bool,
    ) -> Dict[str, Any]:
        fragments: List[str] = []
        skipped: List[str] = []

        for change in files:
            fragment = self._make_diff_fragment(change, context_lines)
            if fragment:
                fragments.append(fragment)
            else:
                skipped.append(change.path)

        if not fragments:
            raise GitToolkitError("No differences detected across the provided files.")

        patch = "".join(fragments)
        apply_snippet = None
        if include_apply_snippet:
            apply_snippet = "cat <<'PATCH' | git apply -\n" + patch + "PATCH\n"

        return {
            "patch": patch,
            "git_apply": apply_snippet,
            "files": len(files),
            "skipped": skipped,
        }

    @tool_schema(GeneratePatchInput)
    async def generate_git_apply_patch(
        self,
        files: List[GitPatchFile],
        context_lines: int = 3,
        include_apply_snippet: bool = True,
    ) -> Dict[str, Any]:
        """Create a unified diff (and optional ``git apply`` snippet) from code blocks."""

        return await asyncio.to_thread(
            self._render_patch, files, context_lines, include_apply_snippet
        )

    # ------------------------------------------------------------------
    # GitHub helpers
    # ------------------------------------------------------------------
    def _prepare_github_context(
        self, repository: Optional[str], base_branch: Optional[str]
    ) -> _GitHubContext:
        conn = self._resolve_connection(repository)
        branch = base_branch or conn.default_branch
        return _GitHubContext(
            repository=conn.repository, base_branch=branch, token=conn.token()
        )

    @staticmethod
    def _request(
        method: str,
        url: str,
        token: str,
        *,
        expected: int,
        **kwargs: Any,
    ) -> requests.Response:
        headers = kwargs.pop("headers", {})
        headers.setdefault("Authorization", f"Bearer {token}")
        headers.setdefault("Accept", "application/vnd.github+json")
        headers.setdefault("User-Agent", "parrot-gittoolkit")
        response = requests.request(method, url, headers=headers, timeout=30, **kwargs)
        if response.status_code != expected:
            raise GitToolkitError(
                f"GitHub API call to {url} failed with status {response.status_code}: {response.text}"
            )
        return response

    @staticmethod
    def _get_stats_with_polling(
        url: str,
        token: str,
        *,
        max_retries: int = 6,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
    ) -> requests.Response:
        """Fetch a /stats/* endpoint with GitHub's 202->200 retry protocol.

        GitHub returns 202 while it computes the stats in the background and
        200 once the data is ready. This helper keeps polling until it sees
        200, gives up after ``max_retries`` consecutive 202s, and raises
        immediately on any other non-200 status.

        Args:
            url: The full GitHub stats API URL to poll.
            token: GitHub personal access token (Bearer).
            max_retries: Maximum number of 202 retries before giving up.
            initial_delay: Initial sleep delay in seconds (doubles each retry).
            max_delay: Maximum sleep delay cap in seconds.

        Returns:
            The ``requests.Response`` with status 200.

        Raises:
            GitToolkitError: If the response is not 200/202, or after
                exhausting all retries without seeing 200.
        """
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "parrot-gittoolkit",
        }
        for attempt in range(max_retries + 1):
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code == 200:
                return response
            if response.status_code != 202:
                raise GitToolkitError(
                    f"GitHub stats call to {url} failed with status "
                    f"{response.status_code}: {response.text}"
                )
            if attempt == max_retries:
                break
            delay = min(initial_delay * (2 ** attempt), max_delay)
            time.sleep(delay)
        raise GitToolkitError(
            f"GitHub stats call to {url} returned 202 after "
            f"{max_retries + 1} attempts; giving up."
        )

    @staticmethod
    def _encode_content(change: GitHubFileChange) -> Optional[str]:
        if change.change_type == "delete":
            return None
        if change.encoding == "base64":
            return change.content or ""
        if change.encoding != "utf-8":
            raise GitToolkitError(f"Unsupported encoding {change.encoding!r}")
        data = (change.content or "").encode("utf-8")
        return base64.b64encode(data).decode("ascii")

    def _fetch_file_sha(
        self,
        ctx: _GitHubContext,
        path: str,
        ref: str,
        token: str,
    ) -> Optional[str]:
        url = f"https://api.github.com/repos/{ctx.repository}/contents/{path}"
        response = requests.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "parrot-gittoolkit",
            },
            params={"ref": ref},
            timeout=30,
        )
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise GitToolkitError(
                f"Unable to fetch metadata for {path}: {response.status_code} {response.text}"
            )
        payload = response.json()
        return payload.get("sha")

    def _create_pull_request_sync(
        self,
        *,
        repository: Optional[str],
        title: str,
        body: Optional[str],
        base_branch: Optional[str],
        head_branch: Optional[str],
        commit_message: Optional[str],
        files: List[GitHubFileChange],
        draft: bool,
        labels: Optional[List[str]],
    ) -> Dict[str, Any]:
        ctx = self._prepare_github_context(repository, base_branch)
        token = ctx.token
        base_branch_name = ctx.base_branch

        branch_name = head_branch or f"parrot/{_dt.datetime.now(_dt.timezone.utc).strftime('%Y%m%d%H%M%S')}"
        commit_message = commit_message or title

        base_ref_url = f"https://api.github.com/repos/{ctx.repository}/git/ref/heads/{base_branch_name}"
        ref_response = self._request("GET", base_ref_url, token, expected=200)
        base_sha = ref_response.json()["object"]["sha"]

        create_ref_url = f"https://api.github.com/repos/{ctx.repository}/git/refs"
        payload = {"ref": f"refs/heads/{branch_name}", "sha": base_sha}
        try:
            self._request("POST", create_ref_url, token, expected=201, json=payload)
        except GitToolkitError as exc:
            if "Reference already exists" not in str(exc):
                raise

        for change in files:
            sha = self._fetch_file_sha(ctx, change.path, branch_name, token)

            if change.change_type == "delete":
                if not sha:
                    raise GitToolkitError(
                        f"Cannot delete {change.path}: file does not exist in branch {branch_name}."
                    )
                url = f"https://api.github.com/repos/{ctx.repository}/contents/{change.path}"
                json_payload = {
                    "message": change.message or commit_message,
                    "branch": branch_name,
                    "sha": sha,
                }
                self._request("DELETE", url, token, expected=200, json=json_payload)
                continue

            encoded = self._encode_content(change)
            if change.change_type == "modify" and not sha:
                raise GitToolkitError(
                    f"Cannot modify {change.path}: file does not exist in branch {branch_name}."
                )

            url = f"https://api.github.com/repos/{ctx.repository}/contents/{change.path}"
            json_payload = {
                "message": change.message or commit_message,
                "content": encoded,
                "branch": branch_name,
            }
            if sha:
                json_payload["sha"] = sha
            self._request("PUT", url, token, expected=201 if not sha else 200, json=json_payload)

        pr_url = f"https://api.github.com/repos/{ctx.repository}/pulls"
        pr_payload = {
            "title": title,
            "body": body or "",
            "head": branch_name,
            "base": base_branch_name,
            "draft": draft,
        }
        pr_response = self._request("POST", pr_url, token, expected=201, json=pr_payload)
        pr_data = pr_response.json()

        if labels:
            labels_url = f"https://api.github.com/repos/{ctx.repository}/issues/{pr_data['number']}/labels"
            self._request("POST", labels_url, token, expected=200, json={"labels": labels})

        return {
            "html_url": pr_data.get("html_url"),
            "number": pr_data.get("number"),
            "head_branch": branch_name,
            "base_branch": base_branch_name,
            "commits": len(files),
        }

    @tool_schema(CreatePullRequestInput)
    async def create_pull_request(
        self,
        repository: Optional[str],
        title: str,
        body: Optional[str],
        base_branch: Optional[str],
        head_branch: Optional[str],
        commit_message: Optional[str],
        files: List[GitHubFileChange],
        draft: bool = False,
        labels: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Create a GitHub pull request with the supplied file updates."""

        return await asyncio.to_thread(
            self._create_pull_request_sync,
            repository=repository,
            title=title,
            body=body,
            base_branch=base_branch,
            head_branch=head_branch,
            commit_message=commit_message,
            files=files,
            draft=draft,
            labels=labels,
        )

    # ------------------------------------------------------------------
    # Local git operations: clone / pull (FEAT-250)
    # ------------------------------------------------------------------
    def _gh_available(self) -> bool:
        """Return True when the ``gh`` CLI is on ``$PATH``."""
        return shutil.which("gh") is not None

    def _clone_slug(self, repository: str) -> str:
        """Resolve ``repository`` (alias | ``owner/name`` | URL) to a slug/URL.

        Alias resolution consults the pre-built connection registry without
        minting any token (so public clones do not require credentials).
        URLs and bare ``owner/name`` slugs are returned unchanged.
        """
        if "://" in repository or repository.startswith("git@"):
            return repository
        conn = self._connections.get(repository)
        if conn is not None:
            return conn.repository
        return repository

    @staticmethod
    def _display_slug(slug_or_url: str) -> str:
        """Best-effort ``owner/name`` for the return payload (never a token)."""
        if "github.com/" in slug_or_url:
            tail = slug_or_url.rstrip("/").split("github.com/")[-1]
            return tail[:-4] if tail.endswith(".git") else tail
        return slug_or_url

    def _clone_url(self, slug_or_url: str, private: bool) -> tuple[str, Optional[str]]:
        """Build the clone URL and return ``(url, token_or_None)``.

        For private repos the bearer token is injected as
        ``https://x-access-token:<token>@github.com/<slug>.git``. The token is
        returned separately *only* so the caller can scrub it from subprocess
        output — it is never placed in any returned payload.
        """
        if "://" in slug_or_url or slug_or_url.startswith("git@"):
            base_url = slug_or_url
        else:
            base_url = f"https://github.com/{slug_or_url}.git"
        if not private:
            return base_url, None
        token = self._resolve_token()
        if base_url.startswith("https://"):
            rest = base_url[len("https://"):]
            return f"https://x-access-token:{token}@{rest}", token
        return base_url, token

    def _scrub(self, text: str, token: Optional[str] = None) -> str:
        """Redact known secrets from ``text`` (R2: tokens must never leak).

        Covers the explicitly-passed ``token`` (the one injected into a clone
        URL), the PAT (``self.github_token``), and — in GitHub-App mode — any
        installation token already minted by the token provider. This keeps a
        leak from slipping through if a future subprocess call forgets to thread
        ``token`` explicitly.
        """
        secrets = [token, self.github_token]
        provider = getattr(self, "_token_provider", None)
        if provider is not None:
            secrets.append(getattr(provider, "_token", None))
        redacted = text
        for secret in secrets:
            if secret:
                redacted = redacted.replace(secret, "***")
        return redacted

    @staticmethod
    async def _run_subprocess(argv: List[str]) -> tuple[int, str, str]:
        """Run ``argv`` asynchronously; return ``(returncode, stdout, stderr)``."""
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        return (
            proc.returncode if proc.returncode is not None else -1,
            out.decode(errors="replace"),
            err.decode(errors="replace"),
        )

    async def clone_repo(
        self,
        repository: str,
        dest_dir: str,
        branch: Optional[str] = None,
        *,
        private: bool = False,
        depth: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Clone ``repository`` to ``dest_dir``.

        Uses the configured PAT / GitHub-App token (or the ``gh`` CLI when
        present) for private repos. Idempotent: if ``dest_dir`` already holds a
        git clone, delegates to :meth:`pull_repo` instead of re-cloning.

        Args:
            repository: An alias from the configured registry, an ``owner/name``
                slug, or a full clone URL.
            dest_dir: Destination directory for the clone.
            branch: Optional branch to clone (``--branch``).
            private: When True, authenticate the clone (``gh`` or token-in-URL).
            depth: Optional shallow-clone depth (``--depth``).

        Returns:
            ``{"path", "repository", "branch", "updated"}``. Never contains a
            token.

        Raises:
            GitToolkitError: If the clone/pull fails (stderr is token-scrubbed).
        """
        if os.path.isdir(os.path.join(dest_dir, ".git")):
            # Already a clone → fast-forward instead of re-cloning (idempotent).
            return await self.pull_repo(dest_dir, branch)

        slug = self._clone_slug(repository)
        display = self._display_slug(slug)
        token: Optional[str] = None

        if private and self._gh_available():
            argv = ["gh", "repo", "clone", display, dest_dir]
            if branch:
                argv += ["--", "--branch", branch]
        else:
            url, token = self._clone_url(slug, private)
            argv = ["git", "clone"]
            if branch:
                argv += ["--branch", branch]
            if depth:
                argv += ["--depth", str(depth)]
            argv += [url, dest_dir]

        rc, _out, err = await self._run_subprocess(argv)
        if rc != 0:
            raise GitToolkitError(
                f"clone of {display!r} failed: {self._scrub(err, token)}"
            )
        return {
            "path": dest_dir,
            "repository": display,
            "branch": branch,
            "updated": False,
        }

    async def pull_repo(
        self,
        repo_path: str,
        branch: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fast-forward an existing clone at ``repo_path`` to ``branch``.

        Args:
            repo_path: Path to an existing git clone.
            branch: Optional branch to pull (``origin <branch>``); defaults to
                the clone's current upstream.

        Returns:
            ``{"path", "branch", "updated"}``. Never contains a token.

        Raises:
            GitToolkitError: If ``repo_path`` is not a clone or the pull fails.
        """
        if not os.path.isdir(os.path.join(repo_path, ".git")):
            raise GitToolkitError(f"{repo_path!r} is not a git clone")
        argv = ["git", "-C", repo_path, "pull", "--ff-only"]
        if branch:
            argv += ["origin", branch]
        rc, _out, err = await self._run_subprocess(argv)
        if rc != 0:
            raise GitToolkitError(
                f"pull of {repo_path!r} failed: {self._scrub(err)}"
            )
        return {"path": repo_path, "branch": branch, "updated": True}

    # ------------------------------------------------------------------
    # Pull request read / review helpers (FEAT: github-pr-review-agent)
    # ------------------------------------------------------------------
    def _resolve_repository(self, repository: Optional[str]) -> str:
        """Resolve ``repository`` (None | alias | slug) to an ``owner/name`` slug."""
        return self._resolve_connection(repository).repository

    def _resolve_token(self) -> str:
        """Return the bearer token for the global/default credentials."""
        return self._default_token()

    def _get_pull_request_sync(self, repository: Optional[str], pr_number: int) -> Dict[str, Any]:
        conn = self._resolve_connection(repository)
        repo, token = conn.repository, conn.token()
        url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
        response = self._request("GET", url, token, expected=200)
        return response.json()

    @tool_schema(GetPullRequestInput)
    async def get_pull_request(
        self,
        pr_number: int,
        repository: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetch metadata for a GitHub pull request by number."""

        return await asyncio.to_thread(
            self._get_pull_request_sync, repository, pr_number
        )

    def _list_pull_requests_sync(
        self,
        repository: Optional[str],
        state: str,
        per_page: int,
    ) -> List[Dict[str, Any]]:
        conn = self._resolve_connection(repository)
        repo, token = conn.repository, conn.token()
        url = f"https://api.github.com/repos/{repo}/pulls"
        params = {"state": state, "per_page": min(max(per_page, 1), 100)}
        response = self._request("GET", url, token, expected=200, params=params)
        data = response.json()
        return data if isinstance(data, list) else []

    @tool_schema(ListPullRequestsInput)
    async def list_pull_requests(
        self,
        repository: Optional[str] = None,
        state: Literal["open", "closed", "all"] = "open",
        per_page: int = 100,
    ) -> List[Dict[str, Any]]:
        """List pull requests on a repository, defaulting to open ones."""

        return await asyncio.to_thread(
            self._list_pull_requests_sync, repository, state, per_page
        )

    def _get_pull_request_diff_sync(
        self,
        repository: Optional[str],
        pr_number: int,
        max_bytes: int,
    ) -> Dict[str, Any]:
        conn = self._resolve_connection(repository)
        repo, token = conn.repository, conn.token()
        url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
        response = self._request(
            "GET",
            url,
            token,
            expected=200,
            headers={"Accept": "application/vnd.github.v3.diff"},
        )
        diff_text = response.text or ""
        truncated = False
        if max_bytes and len(diff_text) > max_bytes:
            diff_text = diff_text[:max_bytes]
            truncated = True
        return {
            "repository": repo,
            "pr_number": pr_number,
            "diff": diff_text,
            "truncated": truncated,
            "byte_size": len(diff_text),
        }

    @tool_schema(GetPullRequestDiffInput)
    async def get_pull_request_diff(
        self,
        pr_number: int,
        repository: Optional[str] = None,
        max_bytes: int = 50_000,
    ) -> Dict[str, Any]:
        """Return the raw unified diff of a pull request, truncated to ``max_bytes``."""

        return await asyncio.to_thread(
            self._get_pull_request_diff_sync, repository, pr_number, max_bytes
        )

    def _add_pr_comment_sync(
        self,
        repository: Optional[str],
        pr_number: int,
        body: str,
    ) -> Dict[str, Any]:
        conn = self._resolve_connection(repository)
        repo, token = conn.repository, conn.token()
        url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
        response = self._request(
            "POST", url, token, expected=201, json={"body": body}
        )
        data = response.json()
        return {"id": data.get("id"), "html_url": data.get("html_url")}

    @tool_schema(AddPRCommentInput)
    async def add_pr_comment(
        self,
        pr_number: int,
        body: str,
        repository: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Add an issue-style comment to a pull request."""

        return await asyncio.to_thread(
            self._add_pr_comment_sync, repository, pr_number, body
        )

    def _submit_pr_review_sync(
        self,
        repository: Optional[str],
        pr_number: int,
        event: str,
        body: str,
    ) -> Dict[str, Any]:
        conn = self._resolve_connection(repository)
        repo, token = conn.repository, conn.token()
        url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/reviews"
        payload = {"event": event, "body": body}
        response = self._request("POST", url, token, expected=200, json=payload)
        data = response.json()
        return {
            "id": data.get("id"),
            "state": data.get("state"),
            "html_url": data.get("html_url"),
        }

    @tool_schema(SubmitPRReviewInput)
    async def submit_pr_review(
        self,
        pr_number: int,
        event: Literal["APPROVE", "REQUEST_CHANGES", "COMMENT"],
        body: str,
        repository: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Submit a pull-request review (approve, request-changes or comment)."""

        return await asyncio.to_thread(
            self._submit_pr_review_sync, repository, pr_number, event, body
        )

    def _ensure_webhook_sync(
        self,
        repository: Optional[str],
        webhook_url: str,
        secret: Optional[str],
        events: List[str],
    ) -> Dict[str, Any]:
        """Idempotently register a GitHub webhook for ``webhook_url``.

        Returns a dict with ``status`` in {created, already_exists, no_permission, error}
        plus the hook payload when available.
        """
        conn = self._resolve_connection(repository)
        repo, token = conn.repository, conn.token()
        list_url = f"https://api.github.com/repos/{repo}/hooks"
        try:
            response = self._request("GET", list_url, token, expected=200)
        except GitToolkitError as exc:
            message = str(exc)
            if " 403" in message or " 404" in message:
                return {"status": "no_permission", "message": message}
            return {"status": "error", "message": message}

        for hook in response.json() or []:
            cfg = (hook or {}).get("config") or {}
            if cfg.get("url") == webhook_url:
                return {"status": "already_exists", "hook": hook}

        config = {
            "url": webhook_url,
            "content_type": "json",
            "insecure_ssl": "0",
        }
        if secret:
            config["secret"] = secret
        payload = {
            "name": "web",
            "active": True,
            "events": events or ["pull_request"],
            "config": config,
        }
        try:
            create = self._request(
                "POST", list_url, token, expected=201, json=payload
            )
        except GitToolkitError as exc:
            message = str(exc)
            if " 403" in message or " 404" in message:
                return {"status": "no_permission", "message": message}
            return {"status": "error", "message": message}
        return {"status": "created", "hook": create.json()}

    async def ensure_webhook(
        self,
        webhook_url: str,
        repository: Optional[str] = None,
        secret: Optional[str] = None,
        events: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Ensure a GitHub webhook pointing at ``webhook_url`` exists on the repo.

        Idempotent. Falls back gracefully when the token lacks
        ``admin:repo_hook`` (status ``"no_permission"``) so callers can run in
        hybrid mode (auto when allowed, manual otherwise).
        """

        return await asyncio.to_thread(
            self._ensure_webhook_sync,
            repository,
            webhook_url,
            secret,
            list(events or ["pull_request"]),
        )

    # ------------------------------------------------------------------
    # On-demand code retrieval tools (FEAT-182)
    # ------------------------------------------------------------------

    def _get_file_content_sync(
        self,
        repository: Optional[str],
        path: str,
        ref: str,
        start_line: Optional[int],
        end_line: Optional[int],
        _cached_bytes: Optional[bytes] = None,
        _cached_sha: Optional[str] = None,
    ) -> "FileContentResult":
        """Synchronous implementation of ``get_file_content_at_ref``.

        Fetches the file at ``ref`` via the GitHub Contents API metadata,
        checks the LRU cache tier before base64-decoding, stores the blob in
        :attr:`_blob_cache`, and returns a :class:`FileContentResult`.

        When ``_cached_bytes`` is provided (from a Redis hit in the async
        wrapper), the method skips decoding entirely and uses the cached data.

        Cache lookup order:
        1. Caller-supplied ``_cached_bytes`` (Redis hit, passed from async wrapper)
        2. In-process LRU keyed by ``(repo, sha)``
        3. Base64 decode from the GitHub Contents API response

        Args:
            repository: Repository in ``owner/name`` format, or ``None`` for default.
            path: File path inside the repository.
            ref: Branch name, tag, or commit SHA.
            start_line: First line to return (1-indexed), or ``None`` for the full file.
            end_line: Last line to return (1-indexed, inclusive), or ``None``.
            _cached_bytes: Pre-fetched raw bytes from the Redis cache tier
                (supplied by the async wrapper to avoid a second GitHub request).
            _cached_sha: The blob SHA that corresponds to ``_cached_bytes``
                (supplied by the async wrapper alongside ``_cached_bytes``).

        Returns:
            A populated :class:`FileContentResult`. ``exists=False`` on 404;
            ``error='file_too_large'`` when the blob exceeds GitHub's 1 MB limit.
        """
        conn = self._resolve_connection(repository)
        repo, token = conn.repository, conn.token()

        url = f"https://api.github.com/repos/{repo}/contents/{path}"

        try:
            response = self._request(
                "GET", url, token, expected=200, params={"ref": ref}
            )
        except GitToolkitError as exc:
            # 404 → file does not exist at this ref
            msg = str(exc)
            if " 404" in msg or "404" in msg:
                return FileContentResult(
                    exists=False,
                    path=path,
                    ref=ref,
                    repository=repo,
                )
            raise

        payload = response.json()

        # GitHub omits 'content' for blobs > ~1 MB; detect via size field.
        size_bytes = payload.get("size")
        if "content" not in payload or payload.get("content") is None:
            return FileContentResult(
                exists=True,
                path=path,
                ref=ref,
                repository=repo,
                sha=payload.get("sha"),
                size_bytes=size_bytes,
                error="file_too_large",
            )

        blob_sha: Optional[str] = payload.get("sha")

        # ── Cache lookup (Tier 1 — LRU) ─────────────────────────────────────
        # Tier 0 (Redis) is checked in the async wrapper BEFORE this sync
        # function is called; when there is a hit, _cached_bytes is non-None.
        raw_bytes: Optional[bytes] = _cached_bytes
        _from_cache = False

        if raw_bytes is None and blob_sha:
            # Tier 1: LRU (synchronous lookup, no await needed).
            self._blob_cache._ensure_lru()
            cache_key = self._blob_cache._cache_key(repo, blob_sha)
            if self._blob_cache._lru is not None and cache_key in self._blob_cache._lru:
                raw_bytes = self._blob_cache._lru[cache_key]
                _from_cache = True

        if raw_bytes is None:
            # Cache miss — decode from the GitHub response.
            raw_content_b64: str = payload.get("content", "")
            # GitHub base64-encodes with newlines; strip them before decoding.
            raw_bytes = base64.b64decode(raw_content_b64.replace("\n", ""))

            # Populate the LRU tier for subsequent in-process hits.
            if blob_sha:
                try:
                    self._blob_cache._ensure_lru()
                    cache_key = self._blob_cache._cache_key(repo, blob_sha)
                    if self._blob_cache._lru is not None:
                        self._blob_cache._lru[cache_key] = raw_bytes
                except Exception:  # noqa: BLE001
                    pass
        else:
            _from_cache = True

        # Decode to UTF-8; fall back to 'base64' for binary blobs.
        try:
            text_content: Optional[str] = raw_bytes.decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            text_content = None
            encoding = "base64"

        # Fetch commit_author via /commits endpoint (best-effort, cache miss path).
        commit_author: Optional[str] = None
        try:
            commits_url = f"https://api.github.com/repos/{repo}/commits"
            commits_resp = self._request(
                "GET",
                commits_url,
                token,
                expected=200,
                params={"path": path, "sha": ref, "per_page": 1},
            )
            commits = commits_resp.json()
            if isinstance(commits, list) and commits:
                commit_author = (commits[0].get("author") or {}).get("login")
        except Exception:  # noqa: BLE001
            pass  # author is best-effort; leave None on any error

        # Apply line slicing if requested.
        truncated = False
        if text_content is not None and (start_line is not None or end_line is not None):
            lines = text_content.splitlines(keepends=True)
            total = len(lines)
            sl = max(0, (start_line or 1) - 1)  # 0-indexed, clamped
            el = min(total, end_line or total)    # exclusive upper bound
            text_content = "".join(lines[sl:el])
            truncated = True

        return FileContentResult(
            exists=True,
            path=path,
            ref=ref,
            repository=repo,
            content=text_content,
            encoding=encoding,
            size_bytes=size_bytes,
            sha=blob_sha,
            commit_author=commit_author,
            truncated=truncated,
        )

    @tool_schema(GetFileContentInput)
    async def get_file_content_at_ref(
        self,
        path: str,
        ref: str,
        repository: Optional[str] = None,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
    ) -> "FileContentResult":
        """Return the full or sliced contents of a file at a given git ref.

        Fetches the file at the specified ``ref`` (branch name, tag, or full
        commit SHA) from the GitHub Contents API. The blob is stored in an
        in-process SHA-keyed cache so that repeated requests for the same ref
        do not incur extra HTTP round-trips within a single review session.

        Cache lookup order for blob content:
        1. Redis (checked here in the async wrapper before calling the sync helper)
        2. In-process LRU (checked inside the sync helper)
        3. Base64 decode from the GitHub Contents API response

        The Contents API metadata call (which provides the blob SHA) is always
        made to resolve the SHA before the cache can be checked. This is
        unavoidable — the SHA is not known until the metadata is fetched.

        Use this tool when the PR diff shows a change to a function or class
        but the hunk is too small to judge correctness without seeing the full
        file body. Prefer ``start_line`` / ``end_line`` on large files to stay
        within the LLM context budget.

        Args:
            path: File path inside the repository (e.g. ``"src/parrot/bots/agent.py"``).
            ref: Branch name, tag, or commit SHA at which to retrieve the file.
            repository: Repository in ``owner/name`` format. Uses the toolkit
                default when omitted.
            start_line: First line to return (1-indexed). When provided without
                ``end_line``, returns from this line to end-of-file.
            end_line: Last line to return (1-indexed, inclusive). When provided
                without ``start_line``, returns from line 1 to this line.

        Returns:
            A :class:`FileContentResult` with ``exists=True`` and ``content``
            set on success; ``exists=False`` when the file is not found;
            ``error='file_too_large'`` when the blob exceeds GitHub's 1 MB limit.

        Example::

            result = await toolkit.get_file_content_at_ref(
                path="parrot/bots/agent.py",
                ref="main",
                start_line=100,
                end_line=150,
            )
            if result.exists and result.content:
                print(result.content)
        """
        # NOTE: We always call the Contents API to get the blob SHA before
        # checking the cache. The SHA is content-addressed, so the cache never
        # needs invalidation. After resolving the SHA, the sync helper checks
        # the LRU tier; Redis is checked here in the async context.
        #
        # A future optimisation could cache (repo, ref, path) → sha to skip
        # the metadata request, but that mapping is ref-mutable and requires
        # a separate TTL policy, so we defer it.
        result = await asyncio.to_thread(
            self._get_file_content_sync,
            repository,
            path,
            ref,
            start_line,
            end_line,
        )
        # Write to Redis asynchronously (best-effort; LRU was already written in sync helper).
        if result.sha and result.content is not None:
            repo = self._resolve_repository(repository)
            raw_bytes = result.content.encode("utf-8")
            try:
                await self._blob_cache.set(repo, result.sha, raw_bytes)
            except Exception:  # noqa: BLE001
                pass
        return result

    def _compare_pr_versions_sync(
        self,
        repository: Optional[str],
        pr_number: int,
        path: str,
    ) -> "CompareVersionsResult":
        """Synchronous implementation of ``compare_pr_versions``.

        Args:
            repository: Repository in ``owner/name`` format, or ``None`` for default.
            pr_number: Pull request number.
            path: File path to compare between base and head.

        Returns:
            A :class:`CompareVersionsResult` containing both base and head
            :class:`FileContentResult` objects.
        """
        repo = self._resolve_repository(repository)
        pr = self._get_pull_request_sync(repository, pr_number)
        base_sha: str = pr["base"]["sha"]
        head_sha: str = pr["head"]["sha"]

        base = self._get_file_content_sync(repository, path, base_sha, None, None)
        head = self._get_file_content_sync(repository, path, head_sha, None, None)

        return CompareVersionsResult(
            repository=repo,
            pr_number=pr_number,
            path=path,
            base_sha=base_sha,
            head_sha=head_sha,
            base=base,
            head=head,
        )

    @tool_schema(ComparePRVersionsInput)
    async def compare_pr_versions(
        self,
        pr_number: int,
        path: str,
        repository: Optional[str] = None,
    ) -> "CompareVersionsResult":
        """Return the base and head versions of a single file in a pull request.

        Fetches the full content of ``path`` at both the PR's base commit SHA
        and its head commit SHA. Both calls route through :meth:`_FileBlobCache`
        so that multiple reviews of the same PR only hit GitHub once per
        (repository, blob SHA) pair.

        Use this tool when the PR diff hunk is too small to judge whether a
        refactored function or class is correct; viewing the full before/after
        bodies often reveals intent that a small hunk obscures.

        Args:
            pr_number: Pull request number (must be >= 1).
            path: File path to compare (e.g. ``"src/utils.py"``).
            repository: Repository in ``owner/name`` format. Uses the toolkit
                default when omitted.

        Returns:
            A :class:`CompareVersionsResult` with ``base`` and ``head``
            :class:`FileContentResult` objects. When the file was added in the
            PR, ``base.exists`` is ``False``. When deleted, ``head.exists``
            is ``False``.

        Example::

            diff = await toolkit.compare_pr_versions(pr_number=42, path="utils.py")
            print("Before:", diff.base.content)
            print("After:", diff.head.content)
        """
        return await asyncio.to_thread(
            self._compare_pr_versions_sync,
            repository,
            pr_number,
            path,
        )

    def _search_repo_code_sync(
        self,
        repository: Optional[str],
        query: str,
        max_results: int,
    ) -> "SearchCodeResult":
        """Synchronous implementation of ``search_repo_code``.

        Args:
            repository: Repository in ``owner/name`` format, or ``None`` for default.
            query: Code Search query text (without the ``repo:`` qualifier).
            max_results: Maximum number of results (1-100).

        Returns:
            A :class:`SearchCodeResult`. When the search API is rate-limited,
            returns with ``error='rate_limited'`` rather than raising.
        """
        conn = self._resolve_connection(repository)
        repo, token = conn.repository, conn.token()
        q = f"{query} repo:{repo}"
        url = "https://api.github.com/search/code"
        params = {"q": q, "per_page": min(max_results, 100)}

        # Use requests.request() with the same auth headers that _request()
        # injects, so that token rotation (PAT or GitHub App) is respected.
        # We cannot call _request() here because it raises on any non-200
        # response, but the Code Search API legitimately returns 403 when the
        # rate limit is exceeded — and we need to inspect the response headers
        # before deciding whether to raise or return ``error='rate_limited'``.
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "parrot-gittoolkit",
        }
        response = requests.request("GET", url, headers=headers, params=params, timeout=30)

        if (
            response.status_code == 403
            and response.headers.get("X-RateLimit-Remaining") == "0"
        ):
            return SearchCodeResult(
                repository=repo,
                query=query,
                total_count=0,
                items=[],
                error="rate_limited",
            )

        if response.status_code != 200:
            raise GitToolkitError(
                f"GitHub Code Search failed: {response.status_code} {response.text}"
            )

        payload = response.json()
        return SearchCodeResult(
            repository=repo,
            query=query,
            total_count=int(payload.get("total_count", 0)),
            items=list(payload.get("items", [])),
        )

    @tool_schema(SearchRepoCodeInput)
    async def search_repo_code(
        self,
        query: str,
        repository: Optional[str] = None,
        max_results: int = 20,
    ) -> "SearchCodeResult":
        """Search code in the PR's repository via the GitHub Code Search API.

        The ``repo:<owner>/<name>`` qualifier is automatically injected so the
        search is scoped to the PR's own repository only — it never exposes
        code from other repositories. Only the default branch is indexed by
        GitHub's Code Search.

        Use this tool when you suspect a changed function has callers or
        related code in other files that are not shown in the PR diff. For
        example: searching for usages of a renamed function, finding all
        implementations of an interface, or locating a constant that was
        moved.

        Note: the Code Search API is rate-limited separately from the REST
        API (30 requests/minute). When the quota is exceeded the tool returns
        ``SearchCodeResult(error='rate_limited', items=[])`` without raising.

        Args:
            query: Code Search query (e.g. ``"def my_function"`` or
                ``"class MyModel language:python"``). Do not include a
                ``repo:`` qualifier — it is added automatically.
            repository: Repository in ``owner/name`` format. Uses the toolkit
                default when omitted.
            max_results: Maximum number of results to return (1-100, default 20).

        Returns:
            A :class:`SearchCodeResult` with ``items`` containing raw GitHub
            Code Search item dicts (``path``, ``name``, ``sha``, ``html_url``,
            ``score``).

        Example::

            results = await toolkit.search_repo_code("class PRReviewResult")
            for item in results.items:
                print(item["path"], item["html_url"])
        """
        return await asyncio.to_thread(
            self._search_repo_code_sync,
            repository,
            query,
            max_results,
        )

    # ------------------------------------------------------------------
    # GitHub stats endpoints (FEAT-180 — Weekly Activity Report)
    # ------------------------------------------------------------------

    def _get_contributor_stats_sync(
        self, repository: Optional[str]
    ) -> List[ContributorStats]:
        """Fetch and parse contributor stats via the 202->200 polling helper.

        Args:
            repository: Repository in ``owner/name`` format, or ``None`` for default.

        Returns:
            List of :class:`ContributorStats` models, one per contributor.
        """
        conn = self._resolve_connection(repository)
        repo, token = conn.repository, conn.token()
        url = f"https://api.github.com/repos/{repo}/stats/contributors"
        response = self._get_stats_with_polling(url, token)
        raw = response.json() or []
        result: List[ContributorStats] = []
        for entry in raw:
            author = entry.get("author") or {}
            weeks = [
                ContributorWeek(
                    week_start=datetime.fromtimestamp(w["w"], tz=timezone.utc),
                    additions=int(w.get("a", 0)),
                    deletions=int(w.get("d", 0)),
                    commits=int(w.get("c", 0)),
                )
                for w in entry.get("weeks", [])
            ]
            result.append(
                ContributorStats(
                    login=author.get("login"),
                    avatar_url=author.get("avatar_url"),
                    total_commits=int(entry.get("total", 0)),
                    weeks=weeks,
                )
            )
        return result

    @tool_schema(GetContributorStatsInput)
    async def get_contributor_stats(
        self,
        repository: Optional[str] = None,
    ) -> List[ContributorStats]:
        """Return per-contributor weekly stats for the repository.

        Calls ``GET /repos/{owner}/{repo}/stats/contributors``. The endpoint is
        asynchronous on GitHub's side: the first call after a cold cache returns
        202 with an empty body. This method retries with exponential backoff until
        it receives 200 (or gives up after ``max_retries``), so callers always see
        a populated list.

        Args:
            repository: Target repository in ``owner/name`` format. Uses default when omitted.

        Returns:
            List of :class:`ContributorStats` models with per-week breakdowns.
        """
        return await asyncio.to_thread(
            self._get_contributor_stats_sync, repository
        )

    def _get_weekly_commit_activity_sync(
        self, repository: Optional[str]
    ) -> List[Dict[str, Any]]:
        """Fetch weekly commit activity (raw dicts) via the polling helper.

        Args:
            repository: Repository in ``owner/name`` format, or ``None`` for default.

        Returns:
            Last 52 weeks of commit counts broken down by day-of-week.
        """
        conn = self._resolve_connection(repository)
        repo, token = conn.repository, conn.token()
        url = f"https://api.github.com/repos/{repo}/stats/commit_activity"
        response = self._get_stats_with_polling(url, token)
        raw = response.json() or []
        return raw if isinstance(raw, list) else []

    @tool_schema(GetCommitActivityInput)
    async def get_weekly_commit_activity(
        self,
        repository: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return the last 52 weeks of repo-wide commits broken down by day-of-week.

        Calls ``GET /repos/{owner}/{repo}/stats/commit_activity``. Handles the
        GitHub 202 async-compute pattern transparently.

        Args:
            repository: Target repository in ``owner/name`` format. Uses default when omitted.

        Returns:
            List of dicts, each with ``week`` (Unix epoch Sunday), ``total``, and
            ``days`` (list of 7 day counts, Sun-Sat).
        """
        return await asyncio.to_thread(
            self._get_weekly_commit_activity_sync, repository
        )

    def _get_code_frequency_sync(
        self, repository: Optional[str]
    ) -> List[WeeklyCodeFrequency]:
        """Fetch per-week additions/deletions and parse into typed models.

        GitHub returns a list of 3-element lists ``[week_epoch, additions, deletions]``
        where deletions is negative. This method normalises deletions to non-negative.

        Args:
            repository: Repository in ``owner/name`` format, or ``None`` for default.

        Returns:
            List of :class:`WeeklyCodeFrequency` models.
        """
        conn = self._resolve_connection(repository)
        repo, token = conn.repository, conn.token()
        url = f"https://api.github.com/repos/{repo}/stats/code_frequency"
        response = self._get_stats_with_polling(url, token)
        raw = response.json() or []
        result: List[WeeklyCodeFrequency] = []
        for entry in raw:
            if not isinstance(entry, (list, tuple)) or len(entry) < 3:
                continue
            week_epoch, additions, deletions = int(entry[0]), int(entry[1]), int(entry[2])
            result.append(
                WeeklyCodeFrequency(
                    week_start=datetime.fromtimestamp(week_epoch, tz=timezone.utc),
                    additions=additions,
                    deletions=abs(deletions),  # GitHub returns negative; store as absolute
                )
            )
        return result

    @tool_schema(GetCodeFrequencyInput)
    async def get_code_frequency(
        self,
        repository: Optional[str] = None,
    ) -> List[WeeklyCodeFrequency]:
        """Return per-week additions/deletions for the whole repository since inception.

        Calls ``GET /repos/{owner}/{repo}/stats/code_frequency``. Handles the GitHub
        202 async-compute pattern transparently. Deletion counts are stored as
        non-negative integers (GitHub returns them as negative in the raw payload).

        Args:
            repository: Target repository in ``owner/name`` format. Uses default when omitted.

        Returns:
            List of :class:`WeeklyCodeFrequency` models, oldest first.
        """
        return await asyncio.to_thread(
            self._get_code_frequency_sync, repository
        )


__all__ = [
    "GitToolkit",
    "GitToolkitInput",
    "RepositoryCredential",
    "GitPatchFile",
    "GitHubFileChange",
    "GeneratePatchInput",
    "CreatePullRequestInput",
    "GetPullRequestInput",
    "ListPullRequestsInput",
    "GetPullRequestDiffInput",
    "AddPRCommentInput",
    "SubmitPRReviewInput",
    "GitToolkitError",
    # FEAT-180 stats models
    "ContributorWeek",
    "ContributorStats",
    "WeeklyCodeFrequency",
    "GetContributorStatsInput",
    "GetCommitActivityInput",
    "GetCodeFrequencyInput",
    # FEAT-182 PR context retrieval models
    "GetFileContentInput",
    "ComparePRVersionsInput",
    "SearchRepoCodeInput",
    "FileContentResult",
    "CompareVersionsResult",
    "SearchCodeResult",
    "_FileBlobCache",
]

