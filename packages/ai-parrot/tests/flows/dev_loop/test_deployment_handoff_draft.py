"""DeploymentHandoffNode draft-PR behaviour (FEAT-250 TASK-007).

Verifies the PR is opened as a DRAFT on both the ``gh`` and the REST paths,
and that the node surfaces the PR ``number``.
"""
from __future__ import annotations

from parrot.flows.dev_loop.nodes.deployment_handoff import DeploymentHandoffNode


def _node() -> DeploymentHandoffNode:
    # jira_toolkit is unused by the helpers under test.
    return DeploymentHandoffNode(
        jira_toolkit=object(),
        target_repo="owner/repo",
        base_branch="dev",
    )


# ── gh path ────────────────────────────────────────────────────────────


async def test_create_pr_with_gh_is_draft(monkeypatch):
    captured: dict = {}

    class _Proc:
        returncode = 0

        async def communicate(self):
            return (b"https://github.com/owner/repo/pull/7\n", b"")

    async def _fake_exec(*argv, **kwargs):
        captured["argv"] = argv
        return _Proc()

    monkeypatch.setattr(
        "parrot.flows.dev_loop.nodes.deployment_handoff.asyncio.create_subprocess_exec",
        _fake_exec,
    )
    node = _node()
    pr_url = await node._create_pr_with_gh("feat-x", "title", "body")
    assert "--draft" in captured["argv"]
    assert captured["argv"][:3] == ("gh", "pr", "create")
    assert pr_url == "https://github.com/owner/repo/pull/7"
    assert node._parse_pr_number(pr_url) == 7


# ── REST path ──────────────────────────────────────────────────────────


async def test_create_pr_via_rest_is_draft(monkeypatch):
    captured: dict = {}

    class _Resp:
        status = 201

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def json(self):
            return {
                "html_url": "https://github.com/owner/repo/pull/9",
                "number": 9,
            }

    class _Session:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def post(self, url, json=None, headers=None):
            captured["payload"] = json
            return _Resp()

    import aiohttp

    monkeypatch.setattr(aiohttp, "ClientSession", _Session)
    monkeypatch.setenv("GITHUB_TOKEN", "tok")

    node = _node()
    pr_url = await node._create_pr_via_rest("feat-x", "title", "body")
    assert captured["payload"]["draft"] is True
    assert pr_url == "https://github.com/owner/repo/pull/9"
    assert node._parse_pr_number(pr_url) == 9


# ── number parsing ─────────────────────────────────────────────────────


def test_parse_pr_number_handles_non_url():
    node = _node()
    assert node._parse_pr_number("") is None
    assert node._parse_pr_number("not-a-pr") is None
    assert node._parse_pr_number("https://github.com/o/r/pull/123") == 123
