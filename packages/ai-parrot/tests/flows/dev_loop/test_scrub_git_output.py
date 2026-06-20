"""Tests for scrub_git_output — git CLI output must never leak a token (R2)."""
from __future__ import annotations

from parrot.flows.dev_loop.nodes.base import scrub_git_output


def test_scrubs_token_in_remote_url():
    leaky = (
        "fatal: could not read from "
        "https://x-access-token:ghp_supersecret123@github.com/o/r.git"
    )
    out = scrub_git_output(leaky)
    assert "ghp_supersecret123" not in out
    assert "https://***@github.com/o/r.git" in out


def test_scrubs_github_token_env(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_envtoken999")
    out = scrub_git_output("remote rejected (token ghp_envtoken999 invalid)")
    assert "ghp_envtoken999" not in out
    assert "***" in out


def test_passes_through_clean_output():
    msg = "error: failed to push some refs to 'origin'"
    assert scrub_git_output(msg) == msg
