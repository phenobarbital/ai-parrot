"""FEAT-707 — tenant-aware narrate() (TASK-4502)."""

import logging
from pathlib import Path

import pytest

from parrot.bots.mixins.narrative import NarrativeMixin
from parrot.skills.tenancy import bind_skill_tenant, reset_skill_tenant

FACTS = {"n": 3}


def _skill(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nname: revenue\ndescription: revenue desc\ntriggers:\n  - /revenue\n---\n\n{body}\n")


class _Host(NarrativeMixin):
    name = "troc_finance"
    enable_skill_registry = False

    def __init__(self, **kw):
        super().__init__(**kw)
        self.logger = logging.getLogger("test")
        self.prompts = []

    async def _configure_skill_registry(self):
        # File-registry only: skip the DB-backed registry, which is out of scope here.
        await self._configure_skill_file_registry()

    async def _call_llm_for_narrative(self, prompt):
        self.prompts.append(prompt)
        return "Three items."


@pytest.fixture
def host(tmp_path):
    root = tmp_path / "troc_finance"
    _skill(root / "skills" / "revenue.md", "GLOBAL-BODY")
    _skill(root / "tenants" / "pokemon" / "skills" / "revenue.md", "POKEMON-BODY")
    h = _Host(tenant_based=True)
    h._agents_dir = tmp_path
    return h


@pytest.mark.asyncio
async def test_narrate_tenant_variant(host):
    await host.narrate(FACTS, "revenue", tenant="pokemon")
    assert "POKEMON-BODY" in host.prompts[0]


@pytest.mark.asyncio
async def test_narrate_without_tenant_uses_global(host):
    await host.narrate(FACTS, "revenue")
    assert "GLOBAL-BODY" in host.prompts[0]
    assert "POKEMON-BODY" not in host.prompts[0]


@pytest.mark.asyncio
async def test_narrate_uses_bound_contextvar(host):
    token = bind_skill_tenant("pokemon")
    try:
        await host.narrate(FACTS, "revenue")
    finally:
        reset_skill_tenant(token)
    assert "POKEMON-BODY" in host.prompts[0]


@pytest.mark.asyncio
async def test_narrate_invalid_tenant_returns_none(host):
    assert await host.narrate(FACTS, "revenue", tenant="../evil") is None
    assert host.prompts == []
