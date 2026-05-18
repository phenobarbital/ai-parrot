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
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

import difflib

import requests
from github import Auth, GithubIntegration
from pydantic import BaseModel, Field, model_validator

from .decorators import tool_schema
from .toolkit import AbstractToolkit


class GitToolkitError(RuntimeError):
    """Raised when the toolkit cannot satisfy a request."""


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
        default=None, description="Target GitHub repository in 'owner/name' format."
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
        description="Target GitHub repository in 'owner/name' format. Uses default when omitted.",
    )


class ListPullRequestsInput(BaseModel):
    """Input payload for ``list_pull_requests``."""

    repository: Optional[str] = Field(
        default=None,
        description="Target GitHub repository in 'owner/name' format. Uses default when omitted.",
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
        description="Target GitHub repository in 'owner/name' format. Uses default when omitted.",
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
        description="Target GitHub repository in 'owner/name' format. Uses default when omitted.",
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
        description="Target GitHub repository in 'owner/name' format. Uses default when omitted.",
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
        description="Target GitHub repository in 'owner/name' format. Uses default when omitted.",
    )


class GetCommitActivityInput(BaseModel):
    """Input payload for ``get_weekly_commit_activity``."""

    repository: Optional[str] = Field(
        default=None,
        description="Target GitHub repository in 'owner/name' format. Uses default when omitted.",
    )


class GetCodeFrequencyInput(BaseModel):
    """Input payload for ``get_code_frequency``."""

    repository: Optional[str] = Field(
        default=None,
        description="Target GitHub repository in 'owner/name' format. Uses default when omitted.",
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


def _coerce_int(value: Optional[str]) -> Optional[int]:
    """Coerce a string env-var value to int, returning None for empty/missing.

    Args:
        value: String value to coerce, or None.

    Returns:
        Integer value, or None if value is None, empty, or non-numeric.
    """
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        # Intentionally returns None; caller raises a descriptive GitToolkitError
        # indicating the value was present but not a valid integer.
        return None


class GitToolkit(AbstractToolkit):
    """Toolkit dedicated to Git patch generation and GitHub pull requests."""

    input_class = GitToolkitInput

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
            **kwargs: Forwarded to the base class.

        Raises:
            GitToolkitError: When ``auth_type`` is invalid or required App-mode
                fields are missing / mutually exclusive constraints are violated.
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
        self.github_token = github_token or os.getenv("GITHUB_TOKEN")

        self.auth_type: Literal["pat", "github_app"] = auth_type
        if self.auth_type not in ("pat", "github_app"):
            raise GitToolkitError(
                f"Unsupported auth_type {self.auth_type!r}; expected 'pat' or 'github_app'."
            )

        # Always initialise these attributes; None in PAT mode.
        self.app_id: Optional[int] = app_id or _coerce_int(os.getenv("GITHUB_APP_ID"))
        self.installation_id: Optional[int] = (
            installation_id or _coerce_int(os.getenv("GITHUB_APP_INSTALLATION_ID"))
        )
        self._private_key_pem: Optional[str] = None
        self._token_provider: Optional[_GitHubAppTokenProvider] = None

        if self.auth_type == "github_app":
            if not self.app_id:
                raise GitToolkitError(
                    "auth_type='github_app' requires app_id (or GITHUB_APP_ID env)."
                )
            if not self.installation_id:
                raise GitToolkitError(
                    "auth_type='github_app' requires installation_id (or "
                    "GITHUB_APP_INSTALLATION_ID env)."
                )

            inline_pem = private_key or os.getenv("GITHUB_APP_PRIVATE_KEY")
            pem_path = private_key_path or os.getenv("GITHUB_APP_PRIVATE_KEY_PATH")
            if inline_pem and pem_path:
                raise GitToolkitError(
                    "auth_type='github_app': set EITHER private_key OR "
                    "private_key_path, not both."
                )
            if not inline_pem and not pem_path:
                raise GitToolkitError(
                    "auth_type='github_app' requires private_key or private_key_path "
                    "(or GITHUB_APP_PRIVATE_KEY[_PATH] env)."
                )
            if pem_path:
                try:
                    with open(pem_path, "r", encoding="utf-8") as fh:
                        inline_pem = fh.read()
                except OSError as exc:
                    raise GitToolkitError(
                        f"Could not read GitHub App private key from {pem_path}: {exc}"
                    ) from exc

            # Defensive: env-injected PEMs sometimes carry literal "\n" escape sequences.
            inline_pem = inline_pem.replace("\\n", "\n")  # type: ignore[union-attr]

            self._token_provider = _GitHubAppTokenProvider(
                app_id=self.app_id,
                installation_id=self.installation_id,
                private_key_pem=inline_pem,
            )

    # ------------------------------------------------------------------
    # Bearer token resolution
    # ------------------------------------------------------------------
    def _bearer_token(self) -> str:
        """Return the bearer token for the next GitHub API call.

        In ``pat`` mode, returns ``self.github_token`` and raises when it is
        absent. In ``github_app`` mode, delegates to the token provider which
        mints / caches installation access tokens transparently.

        Returns:
            A valid bearer token string.

        Raises:
            GitToolkitError: When no token is available (PAT mode with no token
                set) or when the App token provider fails to mint a token.
        """
        if self.auth_type == "github_app":
            if self._token_provider is None:
                raise GitToolkitError(
                    "BUG: _token_provider is None in github_app mode; this is an internal error."
                )
            return self._token_provider.get_token()
        # PAT mode
        if not self.github_token:
            raise GitToolkitError(
                "A GitHub personal access token is required via init argument or GITHUB_TOKEN."
            )
        return self.github_token

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
        repo = repository or self.default_repository
        if not repo:
            raise GitToolkitError(
                "A target repository is required (pass repository or configure default)."
            )

        token = self._bearer_token()

        branch = base_branch or self.default_branch
        return _GitHubContext(repository=repo, base_branch=branch, token=token)

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
    # Pull request read / review helpers (FEAT: github-pr-review-agent)
    # ------------------------------------------------------------------
    def _resolve_repository(self, repository: Optional[str]) -> str:
        repo = repository or self.default_repository
        if not repo:
            raise GitToolkitError(
                "A target repository is required (pass repository or set GIT_DEFAULT_REPOSITORY)."
            )
        return repo

    def _resolve_token(self) -> str:
        return self._bearer_token()

    def _get_pull_request_sync(self, repository: Optional[str], pr_number: int) -> Dict[str, Any]:
        repo = self._resolve_repository(repository)
        token = self._resolve_token()
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
        repo = self._resolve_repository(repository)
        token = self._resolve_token()
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
        repo = self._resolve_repository(repository)
        token = self._resolve_token()
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
        repo = self._resolve_repository(repository)
        token = self._resolve_token()
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
        repo = self._resolve_repository(repository)
        token = self._resolve_token()
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
        repo = self._resolve_repository(repository)
        token = self._resolve_token()
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
        repo = self._resolve_repository(repository)
        token = self._resolve_token()
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
        repo = self._resolve_repository(repository)
        token = self._resolve_token()
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
        repo = self._resolve_repository(repository)
        token = self._resolve_token()
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
]

