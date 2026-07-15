---
type: Wiki Entity
title: GitToolkit
id: class:parrot_tools.gittoolkit.GitToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Toolkit dedicated to Git patch generation and GitHub pull requests.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# GitToolkit

Defined in [`parrot_tools.gittoolkit`](../summaries/mod:parrot_tools.gittoolkit.md).

```python
class GitToolkit(AbstractToolkit)
```

Toolkit dedicated to Git patch generation and GitHub pull requests.

## Methods

- `async def generate_git_apply_patch(self, files: List[GitPatchFile], context_lines: int=3, include_apply_snippet: bool=True) -> Dict[str, Any]` — Create a unified diff (and optional ``git apply`` snippet) from code blocks.
- `async def create_pull_request(self, repository: Optional[str], title: str, body: Optional[str], base_branch: Optional[str], head_branch: Optional[str], commit_message: Optional[str], files: List[GitHubFileChange], draft: bool=False, labels: Optional[List[str]]=None) -> Dict[str, Any]` — Create a GitHub pull request with the supplied file updates.
- `async def clone_repo(self, repository: str, dest_dir: str, branch: Optional[str]=None, *, private: bool=False, depth: Optional[int]=None) -> Dict[str, Any]` — Clone ``repository`` to ``dest_dir``.
- `async def pull_repo(self, repo_path: str, branch: Optional[str]=None) -> Dict[str, Any]` — Fast-forward an existing clone at ``repo_path`` to ``branch``.
- `async def get_pull_request(self, pr_number: int, repository: Optional[str]=None) -> Dict[str, Any]` — Fetch metadata for a GitHub pull request by number.
- `async def list_pull_requests(self, repository: Optional[str]=None, state: Literal['open', 'closed', 'all']='open', per_page: int=100) -> List[Dict[str, Any]]` — List pull requests on a repository, defaulting to open ones.
- `async def get_pull_request_diff(self, pr_number: int, repository: Optional[str]=None, max_bytes: int=50000) -> Dict[str, Any]` — Return the raw unified diff of a pull request, truncated to ``max_bytes``.
- `async def add_pr_comment(self, pr_number: int, body: str, repository: Optional[str]=None) -> Dict[str, Any]` — Add an issue-style comment to a pull request.
- `async def submit_pr_review(self, pr_number: int, event: Literal['APPROVE', 'REQUEST_CHANGES', 'COMMENT'], body: str, repository: Optional[str]=None) -> Dict[str, Any]` — Submit a pull-request review (approve, request-changes or comment).
- `async def ensure_webhook(self, webhook_url: str, repository: Optional[str]=None, secret: Optional[str]=None, events: Optional[List[str]]=None) -> Dict[str, Any]` — Ensure a GitHub webhook pointing at ``webhook_url`` exists on the repo.
- `async def get_file_content_at_ref(self, path: str, ref: str, repository: Optional[str]=None, start_line: Optional[int]=None, end_line: Optional[int]=None) -> 'FileContentResult'` — Return the full or sliced contents of a file at a given git ref.
- `async def compare_pr_versions(self, pr_number: int, path: str, repository: Optional[str]=None) -> 'CompareVersionsResult'` — Return the base and head versions of a single file in a pull request.
- `async def search_repo_code(self, query: str, repository: Optional[str]=None, max_results: int=20) -> 'SearchCodeResult'` — Search code in the PR's repository via the GitHub Code Search API.
- `async def get_contributor_stats(self, repository: Optional[str]=None) -> List[ContributorStats]` — Return per-contributor weekly stats for the repository.
- `async def get_weekly_commit_activity(self, repository: Optional[str]=None) -> List[Dict[str, Any]]` — Return the last 52 weeks of repo-wide commits broken down by day-of-week.
- `async def get_code_frequency(self, repository: Optional[str]=None) -> List[WeeklyCodeFrequency]` — Return per-week additions/deletions for the whole repository since inception.
