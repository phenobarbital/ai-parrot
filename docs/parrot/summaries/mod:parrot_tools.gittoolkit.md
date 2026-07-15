---
type: Wiki Summary
title: parrot_tools.gittoolkit
id: mod:parrot_tools.gittoolkit
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Git/GitHub toolkit inspired by :mod:`parrot.tools.jiratoolkit`.
relates_to:
- concept: class:parrot_tools.gittoolkit.AddPRCommentInput
  rel: defines
- concept: class:parrot_tools.gittoolkit.ComparePRVersionsInput
  rel: defines
- concept: class:parrot_tools.gittoolkit.CompareVersionsResult
  rel: defines
- concept: class:parrot_tools.gittoolkit.ContributorStats
  rel: defines
- concept: class:parrot_tools.gittoolkit.ContributorWeek
  rel: defines
- concept: class:parrot_tools.gittoolkit.CreatePullRequestInput
  rel: defines
- concept: class:parrot_tools.gittoolkit.FileContentResult
  rel: defines
- concept: class:parrot_tools.gittoolkit.GeneratePatchInput
  rel: defines
- concept: class:parrot_tools.gittoolkit.GetCodeFrequencyInput
  rel: defines
- concept: class:parrot_tools.gittoolkit.GetCommitActivityInput
  rel: defines
- concept: class:parrot_tools.gittoolkit.GetContributorStatsInput
  rel: defines
- concept: class:parrot_tools.gittoolkit.GetFileContentInput
  rel: defines
- concept: class:parrot_tools.gittoolkit.GetPullRequestDiffInput
  rel: defines
- concept: class:parrot_tools.gittoolkit.GetPullRequestInput
  rel: defines
- concept: class:parrot_tools.gittoolkit.GitHubFileChange
  rel: defines
- concept: class:parrot_tools.gittoolkit.GitPatchFile
  rel: defines
- concept: class:parrot_tools.gittoolkit.GitToolkit
  rel: defines
- concept: class:parrot_tools.gittoolkit.GitToolkitError
  rel: defines
- concept: class:parrot_tools.gittoolkit.GitToolkitInput
  rel: defines
- concept: class:parrot_tools.gittoolkit.ListPullRequestsInput
  rel: defines
- concept: class:parrot_tools.gittoolkit.RepositoryCredential
  rel: defines
- concept: class:parrot_tools.gittoolkit.SearchCodeResult
  rel: defines
- concept: class:parrot_tools.gittoolkit.SearchRepoCodeInput
  rel: defines
- concept: class:parrot_tools.gittoolkit.SubmitPRReviewInput
  rel: defines
- concept: class:parrot_tools.gittoolkit.WeeklyCodeFrequency
  rel: defines
- concept: mod:parrot_tools.decorators
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.gittoolkit`

Git/GitHub toolkit inspired by :mod:`parrot.tools.jiratoolkit`.

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

## Classes

- **`GitToolkitError(RuntimeError)`** — Raised when the toolkit cannot satisfy a request.
- **`RepositoryCredential(BaseModel)`** — Credentials + defaults for a single named repository in a registry.
- **`GitToolkitInput(BaseModel)`** — Default configuration shared by all tools in the toolkit.
- **`GitPatchFile(BaseModel)`** — Represents a single file change for patch generation.
- **`GeneratePatchInput(BaseModel)`** — Input payload for ``generate_git_apply_patch``.
- **`GitHubFileChange(BaseModel)`** — Description of a file mutation when creating a pull request.
- **`CreatePullRequestInput(BaseModel)`** — Input payload for ``create_pull_request``.
- **`GetPullRequestInput(BaseModel)`** — Input payload for ``get_pull_request``.
- **`ListPullRequestsInput(BaseModel)`** — Input payload for ``list_pull_requests``.
- **`GetPullRequestDiffInput(BaseModel)`** — Input payload for ``get_pull_request_diff``.
- **`AddPRCommentInput(BaseModel)`** — Input payload for ``add_pr_comment``.
- **`SubmitPRReviewInput(BaseModel)`** — Input payload for ``submit_pr_review``.
- **`GetFileContentInput(BaseModel)`** — Input payload for ``get_file_content_at_ref``.
- **`ComparePRVersionsInput(BaseModel)`** — Input payload for ``compare_pr_versions``.
- **`SearchRepoCodeInput(BaseModel)`** — Input payload for ``search_repo_code``.
- **`FileContentResult(BaseModel)`** — Return payload for ``get_file_content_at_ref``.
- **`CompareVersionsResult(BaseModel)`** — Return payload for ``compare_pr_versions``.
- **`SearchCodeResult(BaseModel)`** — Return payload for ``search_repo_code``.
- **`ContributorWeek(BaseModel)`** — One week's slice of a contributor's activity.
- **`ContributorStats(BaseModel)`** — Aggregated stats for a single contributor across the repository's history.
- **`WeeklyCodeFrequency(BaseModel)`** — Repo-wide weekly additions/deletions totals.
- **`GetContributorStatsInput(BaseModel)`** — Input payload for ``get_contributor_stats``.
- **`GetCommitActivityInput(BaseModel)`** — Input payload for ``get_weekly_commit_activity``.
- **`GetCodeFrequencyInput(BaseModel)`** — Input payload for ``get_code_frequency``.
- **`GitToolkit(AbstractToolkit)`** — Toolkit dedicated to Git patch generation and GitHub pull requests.
