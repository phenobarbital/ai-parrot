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

Only standard library modules (plus :mod:`requests` and :mod:`pydantic`, which
are already dependencies of Parrot) are required.
"""

from __future__ import annotations

import asyncio
import base64
import datetime as _dt
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

import difflib

import requests
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


@dataclass
class _GitHubContext:
    """Simple container with prepared GitHub configuration."""

    repository: str
    base_branch: str
    token: str


class GitToolkit(AbstractToolkit):
    """Toolkit dedicated to Git patch generation and GitHub pull requests."""

    input_class = GitToolkitInput

    def __init__(
        self,
        default_repository: Optional[str] = None,
        default_branch: str = "main",
        github_token: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
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

        token = self.github_token
        if not token:
            raise GitToolkitError(
                "A GitHub personal access token is required via init argument or GITHUB_TOKEN."
            )

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
    def _encode_content(change: GitHubFileChange) -> Optional[str]:
        if change.change_type == "delete":
            return None
        if change.encoding == "base64":
            return change.content or ""
        assert change.encoding == "utf-8"
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

        branch_name = head_branch or f"parrot/{_dt.datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
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


__all__ = [
    "GitToolkit",
    "GitToolkitInput",
    "GitPatchFile",
    "GitHubFileChange",
    "GeneratePatchInput",
    "CreatePullRequestInput",
    "GitToolkitError",
]

