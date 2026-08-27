"""Tests for ``Skill.owner_user_id`` and its plumbing through
``SkillRegistry.upload_skill`` (FEAT-467 TASK-2515).

Covers:
  - ``Skill.to_dict()``/``from_dict()`` round-trip the new field.
  - Backward compatibility: a dict WITHOUT ``owner_user_id`` (as written
    by any pre-TASK-2515 persisted skill) still loads, defaulting to "".
  - ``upload_skill(..., owner_user_id=..., skill_id=<preset>)`` stamps
    the owner AND mirrors the given ``skill_id`` on a NEW skill (needed
    so the Postgres skills-catalog row and the registry's Skill share
    one id — spec §2 Data Models: "skill_id ... mirrors SkillRegistry
    skill_id").
"""

from __future__ import annotations

import pytest
from parrot.skills.models import Skill, SkillCategory, SkillMetadata, SkillStatus
from parrot.skills.store import SkillRegistry

# ---------------------------------------------------------------------------
# Skill.owner_user_id — dataclass round-trip
# ---------------------------------------------------------------------------


class TestSkillOwnerUserIdRoundtrip:
    def test_to_dict_includes_owner_user_id(self):
        skill = Skill(
            namespace="org1/_shared",
            owner_agent_id="agent-1",
            owner_user_id="user-42",
            metadata=SkillMetadata(name="My Skill", description="desc"),
            status=SkillStatus.ACTIVE,
        )
        data = skill.to_dict()
        assert data["owner_user_id"] == "user-42"

    def test_from_dict_restores_owner_user_id(self):
        skill = Skill(
            namespace="org1/_shared",
            owner_agent_id="agent-1",
            owner_user_id="user-42",
            metadata=SkillMetadata(name="My Skill", description="desc"),
            status=SkillStatus.ACTIVE,
        )
        restored = Skill.from_dict(skill.to_dict())
        assert restored.owner_user_id == "user-42"
        assert restored.owner_agent_id == "agent-1"
        assert restored.skill_id == skill.skill_id

    def test_owner_user_id_defaults_empty(self):
        skill = Skill(
            metadata=SkillMetadata(name="No Owner", description="desc"),
        )
        assert skill.owner_user_id == ""

    def test_from_dict_backward_compatible_without_owner_user_id(self):
        """A dict written by pre-TASK-2515 code (no owner_user_id key)
        must still load, defaulting the field to ""."""
        skill = Skill(
            namespace="default",
            owner_agent_id="agent-1",
            metadata=SkillMetadata(name="Legacy Skill", description="desc"),
        )
        data = skill.to_dict()
        del data["owner_user_id"]  # simulate a pre-existing persisted record

        restored = Skill.from_dict(data)
        assert restored.owner_user_id == ""
        assert restored.owner_agent_id == "agent-1"


# ---------------------------------------------------------------------------
# SkillRegistry.upload_skill — owner_user_id + skill_id passthrough
# ---------------------------------------------------------------------------


async def _fake_embed(_text: str):
    """Lightweight stand-in for a real sentence-transformers model —
    dimension must match the registry's ``dimension=`` constructor arg."""
    return [0.0] * 8


@pytest.fixture
async def registry(tmp_path) -> SkillRegistry:
    reg = SkillRegistry(
        namespace="org1/_shared",
        dimension=8,
        persistence_path=tmp_path,
    )
    await reg.configure(embedding_model=_fake_embed)
    return reg


class TestUploadSkillOwnerAndIdPassthrough:
    @pytest.mark.asyncio
    async def test_upload_skill_stamps_owner_user_id(self, registry):
        skill, _version = await registry.upload_skill(
            name="my-skill",
            content="Skill body.",
            agent_id="studio-catalog",
            description="A shared skill.",
            category=SkillCategory.GENERAL,
            owner_user_id="user-42",
        )
        assert skill.owner_user_id == "user-42"
        assert skill.owner_agent_id == "studio-catalog"
        assert skill.namespace == "org1/_shared"

    @pytest.mark.asyncio
    async def test_upload_skill_mirrors_preset_skill_id_for_new_skill(self, registry):
        """A skill_id that does NOT yet exist in the registry is used AS
        the new skill's id (not silently discarded) — this is what lets
        the Postgres catalog row and the registry Skill share one id."""
        preset_id = "11111111-1111-1111-1111-111111111111"
        skill, version = await registry.upload_skill(
            name="mirrored-skill",
            content="Body.",
            agent_id="studio-catalog",
            skill_id=preset_id,
        )
        assert skill.skill_id == preset_id
        assert version.skill_id == preset_id

    @pytest.mark.asyncio
    async def test_upload_skill_without_skill_id_auto_generates(self, registry):
        skill, _version = await registry.upload_skill(
            name="auto-id-skill",
            content="Body.",
            agent_id="studio-catalog",
        )
        assert skill.skill_id  # non-empty, auto-generated uuid4 string

    @pytest.mark.asyncio
    async def test_upload_skill_update_preserves_owner_user_id(self, registry):
        """Updating an EXISTING skill (skill_id already in the registry)
        goes through _create_new_version, which never touches ownership —
        the original owner_user_id survives a content update."""
        skill, _ = await registry.upload_skill(
            name="owned-skill",
            content="v0 content that is reasonably long for a diff check.",
            agent_id="studio-catalog",
            owner_user_id="original-owner",
        )
        updated_skill, _ = await registry.upload_skill(
            name="owned-skill",
            content="v1 content that is meaningfully different from v0 to force a new version.",
            agent_id="studio-catalog",
            skill_id=skill.skill_id,
            owner_user_id="ignored-on-update",
        )
        assert updated_skill.skill_id == skill.skill_id
        assert updated_skill.owner_user_id == "original-owner"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
