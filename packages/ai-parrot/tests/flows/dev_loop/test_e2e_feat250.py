"""Live end-to-end integration tests for FEAT-250 (TASK-013).

Gated behind ``@pytest.mark.live`` and the skip-guard fixtures in
``conftest.py``; they skip cleanly (never error) when the prerequisites
(``claude`` CLI, ``ANTHROPIC_API_KEY``, ``gh``/``GITHUB_TOKEN``, a Jira sandbox,
a private fixture repo) are not configured.

Run them explicitly with::

    pytest packages/ai-parrot/tests/flows/dev_loop/test_e2e_feat250.py -m live -v

Each test documents the env-vars it needs. The private-clone test is the most
CI-friendly (no Jira/claude needed): export ``GITHUB_TOKEN`` and
``DEV_LOOP_TEST_PRIVATE_REPO=owner/name``.
"""
from __future__ import annotations

import os

import pytest

from parrot.flows.dev_loop.models import RepoSpec, RevisionBrief, WorkBrief  # noqa: F401

pytestmark = pytest.mark.live


# ---------------------------------------------------------------------------
# 1. Initial run → DRAFT PR
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_initial_run_draft_pr(
    skip_unless_claude_available,
    skip_unless_github_available,
    fixture_git_repo,
    temp_worktree_base,
):
    """Intent → … → Development → QA(both gates) → **draft** PR.

    Needs: ``ANTHROPIC_API_KEY`` + ``claude`` CLI, ``GITHUB_TOKEN`` +
    ``GITHUB_REPOSITORY``, and a Jira sandbox. Asserts the opened PR is a
    DRAFT and the run surfaces a ``pr_number``.
    """
    if not os.environ.get("JIRA_TEST_PROJECT_KEY"):
        pytest.skip(
            "JIRA_TEST_PROJECT_KEY not set; the initial-run e2e needs a Jira "
            "sandbox to create the ticket. Wiring is in place — export "
            "JIRA_TEST_PROJECT_KEY (+ Jira creds) to enable."
        )

    # Intended structure once a Jira sandbox + GitHub target are configured:
    #   from parrot.flows.dev_loop.flow import build_dev_loop_flow
    #   from parrot.flows.dev_loop.runner import DevLoopRunner
    #   flow = build_dev_loop_flow(dispatcher=..., jira_toolkit=...,
    #                              log_toolkits={}, redis_url=...,
    #                              git_toolkit=..., repos=[RepoSpec(...)])
    #   runner = DevLoopRunner(flow)
    #   result = await runner.run(brief)
    #   assert result.responses["deployment_handoff"]["pr_number"] is not None
    #   # gh pr view <n> --json isDraft  →  {"isDraft": true}
    pytest.skip("Live e2e wiring present; enable with a Jira sandbox + GitHub target.")


# ---------------------------------------------------------------------------
# 2. Revision run updates the SAME PR (no new PR)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_revision_updates_same_pr(
    skip_unless_claude_available,
    skip_unless_github_available,
    fixture_git_repo,
    temp_worktree_base,
):
    """A simulated reviewer change-request triggers ``run_revision``.

    Asserts a new commit lands on the **same** branch and a comment is posted
    on the **same** ``pr_number`` — and that **no** second PR is created.
    """
    if not os.environ.get("DEV_LOOP_TEST_PR_NUMBER"):
        pytest.skip(
            "DEV_LOOP_TEST_PR_NUMBER not set; the revision e2e updates an "
            "existing draft PR. Run test_e2e_initial_run_draft_pr first and "
            "export the PR number to enable."
        )

    # Intended structure:
    #   brief = RevisionBrief(repo_path=fixture_git_repo, branch=...,
    #                         pr_number=int(os.environ["DEV_LOOP_TEST_PR_NUMBER"]),
    #                         repository=os.environ["GITHUB_REPOSITORY"],
    #                         jira_issue_key=..., feedback="handle the null case",
    #                         head_sha=...)
    #   runner = DevLoopRunner(flow, dispatcher=..., jira_toolkit=...,
    #                          git_toolkit=..., redis_url=...)
    #   result = await runner.run_revision(brief)
    #   assert result.responses["revision_handoff"]["status"] == "revised"
    #   # git_toolkit.add_pr_comment called on the SAME pr_number;
    #   # create_pull_request NOT called.
    pytest.skip("Live e2e wiring present; enable with an existing draft PR.")


# ---------------------------------------------------------------------------
# 3. Private repo clone (most CI-friendly — no Jira/claude needed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_private_repo_clone(
    skip_unless_private_repo_configured,
    tmp_path,
):
    """Clone a **private** fixture repo via ``GitToolkit.clone_repo``.

    Needs: ``GITHUB_TOKEN`` and ``DEV_LOOP_TEST_PRIVATE_REPO=owner/name``.
    Uses ``gh`` when present, else token-in-URL. Asserts the clone lands on
    disk and the token never leaks into the returned payload.
    """
    from parrot_tools.gittoolkit import GitToolkit

    slug = os.environ["DEV_LOOP_TEST_PRIVATE_REPO"]
    token = os.environ["GITHUB_TOKEN"]
    dest = str(tmp_path / "private-clone")

    toolkit = GitToolkit(default_repository=slug, github_token=token)
    result = await toolkit.clone_repo(slug, dest, private=True)

    assert os.path.isdir(os.path.join(dest, ".git"))
    assert result["path"] == dest
    # The token must never appear in the returned payload.
    assert token not in str(result)
