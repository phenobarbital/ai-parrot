"""Redis-backed per-user toolkit overrides (FEAT-878, TASK-5503)."""

import pytest

from parrot.handlers import toolkit_persistence
from parrot.handlers.toolkit_persistence import ToolkitConfigService, UserToolkitOverride
from parrot.userstore.testing import redis_test_settings


@pytest.fixture
async def redis_overrides(monkeypatch):
    monkeypatch.delenv("TOOLKIT_OVERRIDES_STORE", raising=False)
    monkeypatch.delenv("PARROT_USER_STORE", raising=False)
    monkeypatch.setattr(toolkit_persistence, "_PG_OVERRIDES", None)
    monkeypatch.setattr(toolkit_persistence, "_REDIS_OVERRIDES", None)
    async with redis_test_settings(monkeypatch):
        yield ToolkitConfigService()


async def test_overrides_redis_store(redis_overrides):
    svc = redis_overrides
    await svc.save(UserToolkitOverride(user_id="35", agent_id="a1", slug="jira", params={"x": 1}))
    loaded = await svc.load("35", "a1")
    assert [o.slug for o in loaded] == ["jira"]
    assert loaded[0].params == {"x": 1}
    assert await svc.revision("35", "a1")
    assert await svc.remove("35", "a1", "jira") is True
    assert await svc.remove("35", "a1", "jira") is False
    assert await svc.load("35", "a1") == []
    assert await svc.revision("35", "a1") == ""


async def test_purge_agent_returns_deleted(redis_overrides):
    svc = redis_overrides
    await svc.save(UserToolkitOverride(user_id="1", agent_id="a1", slug="jira", secret_refs={"token": "ref1"}))
    await svc.save(UserToolkitOverride(user_id="2", agent_id="a1", slug="git"))
    await svc.save(UserToolkitOverride(user_id="1", agent_id="a2", slug="jira"))
    purged = await svc.purge_agent("a1")
    assert sorted((o.user_id, o.slug) for o in purged) == [("1", "jira"), ("2", "git")]
    assert {o.user_id: o.secret_refs for o in purged}["1"] == {"token": "ref1"}
    assert await svc.load("1", "a1") == []
    assert [o.slug for o in await svc.load("1", "a2")] == ["jira"]


async def test_postgres_unregistered_fails_closed(monkeypatch):
    monkeypatch.setenv("TOOLKIT_OVERRIDES_STORE", "postgres")
    monkeypatch.setattr(toolkit_persistence, "_PG_OVERRIDES", None)
    with pytest.raises(RuntimeError):
        await ToolkitConfigService().load("1", "a1")


async def test_registered_store_wins(monkeypatch):
    class Fake:
        async def load(self, user_id, agent_id):
            return ["fake"]

    monkeypatch.setenv("TOOLKIT_OVERRIDES_STORE", "postgres")
    monkeypatch.setattr(toolkit_persistence, "_PG_OVERRIDES", Fake())
    assert await ToolkitConfigService().load("1", "a1") == ["fake"]
