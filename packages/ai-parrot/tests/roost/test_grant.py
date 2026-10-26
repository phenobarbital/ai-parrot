"""Tests for the Roost inter-agent grant policy (TASK-4717)."""

from parrot.roost.directory import InterAgentGrant, RoostAgentConfig
from parrot.roost.grant import GrantDenied, GrantPolicy


def test_allows():
    gp = GrantPolicy()
    cfg = RoostAgentConfig(grant=InterAgentGrant(scopes=["hr.*"]))
    assert gp.allows(cfg, "hr.people.salary") and not gp.allows(cfg, "fin.x")
    assert not gp.allows(RoostAgentConfig(), "hr.people.salary") and not gp.allows(None, "x")


def test_star_and_empty_scopes():
    gp = GrantPolicy()
    assert gp.allows(RoostAgentConfig(grant=InterAgentGrant(scopes=["*"])), "anything.at.all")
    assert not gp.allows(RoostAgentConfig(grant=InterAgentGrant(scopes=[])), "hr.x")


def test_attenuate():
    g = GrantPolicy().attenuate(InterAgentGrant(scopes=["hr.*"]), InterAgentGrant(scopes=["hr.people.*", "fin.*"]))
    assert g.scopes == ["hr.people.*"]


def test_attenuate_star_and_none():
    gp = GrantPolicy()
    assert gp.attenuate(InterAgentGrant(scopes=["*"]), InterAgentGrant(scopes=["a.*", "b"])).scopes == ["a.*", "b"]
    assert gp.attenuate(None, InterAgentGrant(scopes=["a.*"])).scopes == []


def test_grant_denied_is_exception():
    assert issubclass(GrantDenied, Exception)
