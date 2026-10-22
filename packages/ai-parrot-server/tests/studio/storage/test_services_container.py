"""build_studio_services wires every service with its real signature (review fix)."""
import pytest
from aiohttp import web

from parrot.handlers.studio.storage.models import (
    StudioAgentBundle,
    StudioAgentDefinition,
    StudioAssetInput,
    StudioPartition,
    StudioWriteGuard,
)
from parrot.handlers.studio.storage.repositories import build_studio_repositories
from parrot.handlers.studio.storage.services._common import build_studio_services
from parrot.handlers.studio.storage.testing import InMemoryStudioRepositories

GLOBAL = StudioPartition.GLOBAL


@pytest.fixture(params=["memory", "postgres"])
def repos(request):
    if request.param == "memory":
        return InMemoryStudioRepositories()
    return build_studio_repositories(request.getfixturevalue("studio_pool"))


async def test_container_builds_and_every_service_works(repos):
    services = build_studio_services(web.Application(), repos)
    for name in ("agents", "assets", "tooling", "drafts", "skills"):
        assert getattr(services, name) is not None
    await services.agents.create(GLOBAL, name="a1", owner="u1", definition=StudioAgentDefinition())
    await services.assets.put(GLOBAL, "a1", StudioAssetInput(kind="kb", name="k.md", content="x"), actor="u1",
                              guard=StudioWriteGuard())
    assert [a.name for a in await services.assets.list(GLOBAL, "a1")] == ["k.md"]
    assert (await services.tooling.load(GLOBAL, "a1")) is not None
    bundle = StudioAgentBundle(name="d1", definition=StudioAgentDefinition())
    await services.drafts.save_bundle(GLOBAL, owner="u1", bundle=bundle)
    assert (await services.drafts.activate(GLOBAL, "d1", owner="u1")).name == "d1"
    skill = await services.skills.publish(GLOBAL, owner="u1", name="s1", description="d", body="b")
    _, version = await services.skills.import_to_agent(GLOBAL, skill.skill_id, "a1", actor="u1",
                                                       guard=StudioWriteGuard())
    assert version >= 1 and [s.name for s in await services.skills.list(GLOBAL)] == ["s1"]
