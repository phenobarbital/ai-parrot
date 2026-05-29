"""
Unit tests for parrot.skills.tools.SkillRegistryToolkit.

The DB-backed skill tools (search/read/list/document/update) are now methods
of a single toolkit sharing one SkillRegistry store. These tests use a
lightweight fake registry to exercise each tool method and the toolkit's
tool-generation / write-tool exclusion behaviour.
"""
from types import SimpleNamespace

import pytest

from parrot.skills.models import SkillCategory
from parrot.skills.tools import SkillRegistryToolkit


def _make_skill(skill_id="s1", name="Query Pattern", version=1):
    """Build a fake Skill object shaped like store.SkillRegistry results."""
    metadata = SimpleNamespace(
        name=name,
        description="How to query efficiently",
        category=SkillCategory.GENERAL,
        triggers=["/query"],
    )
    return SimpleNamespace(
        skill_id=skill_id,
        metadata=metadata,
        current_version=version,
    )


class FakeRegistry:
    """Minimal async stand-in for SkillRegistry recording calls."""

    def __init__(self, *, skills=None, search_results=None):
        self._skills = skills if skills is not None else [{
            "skill_id": "s1", "name": "Query Pattern", "category": "general",
            "current_version": 1, "description": "How to query", "tags": [],
        }]
        self._search_results = search_results
        self.calls = {}

    async def search_skills(self, query, category=None, tags=None,
                            include_deprecated=False, max_results=5):
        self.calls["search"] = dict(
            query=query, category=category, tags=tags,
            include_deprecated=include_deprecated, max_results=max_results,
        )
        if self._search_results is not None:
            return self._search_results
        return [SimpleNamespace(skill=_make_skill(), relevance_score=0.91)]

    async def read_skill(self, skill_id, version=None):
        self.calls["read"] = dict(skill_id=skill_id, version=version)
        if skill_id == "missing":
            raise KeyError(skill_id)
        return "# Skill body content"

    async def list_skills(self):
        return self._skills

    async def upload_skill(self, **kwargs):
        self.calls["upload"] = kwargs
        skill = SimpleNamespace(
            skill_id=kwargs.get("skill_id") or "new1",
            metadata=SimpleNamespace(name=kwargs["name"]),
        )
        version = SimpleNamespace(version_number=2)
        return skill, version


@pytest.fixture
def registry():
    return FakeRegistry()


@pytest.fixture
def toolkit(registry):
    return SkillRegistryToolkit(registry=registry, agent_id="agent-x")


# --- tool generation / exclusion -------------------------------------------

def test_tool_names_include_write(registry):
    """With write tools enabled, all five tools are exposed by their names."""
    tk = SkillRegistryToolkit(registry=registry, agent_id="a")
    names = {t.name for t in tk.get_tools()}
    assert names == {
        "search_skills", "read_skill", "list_skills",
        "document_skill", "update_skill",
    }


def test_write_tools_excluded(registry):
    """include_write_tools=False hides document_skill and update_skill."""
    tk = SkillRegistryToolkit(registry=registry, agent_id="a", include_write_tools=False)
    names = {t.name for t in tk.get_tools()}
    assert names == {"search_skills", "read_skill", "list_skills"}


def test_format_summary_not_a_tool(registry):
    """The internal _format_summary helper is not exposed as a tool."""
    tk = SkillRegistryToolkit(registry=registry, agent_id="a")
    assert "_format_summary" not in {t.name for t in tk.get_tools()}


# --- search_skills ----------------------------------------------------------

@pytest.mark.asyncio
async def test_search_skills_found(toolkit, registry):
    """search_skills returns a summary + structured metadata; args are wired."""
    result = await toolkit.search_skills(
        query="how to query", category="general",
        tags=["db"], include_deprecated=True, max_results=3,
    )
    assert result.status == "done"
    assert result.metadata["skills_found"] == 1
    assert result.metadata["skills"][0]["name"] == "Query Pattern"
    # tags + include_deprecated flow through to the store (richer schema wired)
    assert registry.calls["search"]["tags"] == ["db"]
    assert registry.calls["search"]["include_deprecated"] is True
    assert registry.calls["search"]["max_results"] == 3


@pytest.mark.asyncio
async def test_search_skills_empty():
    """No results returns a friendly message and skills_found=0."""
    tk = SkillRegistryToolkit(registry=FakeRegistry(search_results=[]), agent_id="a")
    result = await tk.search_skills(query="nothing")
    assert result.status == "done"
    assert result.metadata["skills_found"] == 0


# --- read_skill -------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_skill_found(toolkit):
    result = await toolkit.read_skill(skill_id="s1")
    assert result.status == "done"
    assert "Skill body" in result.result
    assert result.metadata["skill_id"] == "s1"


@pytest.mark.asyncio
async def test_read_skill_missing(toolkit):
    """A KeyError from the store maps to a not-found error result."""
    result = await toolkit.read_skill(skill_id="missing")
    assert result.status == "error"
    assert "not found" in result.error.lower()


# --- list_skills (no-arg tool) ---------------------------------------------

@pytest.mark.asyncio
async def test_list_skills(toolkit):
    result = await toolkit.list_skills()
    assert result.status == "done"
    assert result.metadata["count"] == 1


@pytest.mark.asyncio
async def test_list_skills_empty():
    tk = SkillRegistryToolkit(registry=FakeRegistry(skills=[]), agent_id="a")
    result = await tk.list_skills()
    assert result.status == "done"
    assert result.metadata["count"] == 0


def test_list_skills_has_empty_schema(toolkit):
    """The no-arg list_skills tool generates an empty args schema."""
    tool = next(t for t in toolkit.get_tools() if t.name == "list_skills")
    assert list(tool.args_schema.model_fields) == []


# --- document_skill / update_skill -----------------------------------------

@pytest.mark.asyncio
async def test_document_skill(toolkit, registry):
    result = await toolkit.document_skill(
        name="New Skill", description="desc", content="# body",
    )
    assert result.status == "done"
    assert registry.calls["upload"]["agent_id"] == "agent-x"
    assert result.metadata["version"] == 2


@pytest.mark.asyncio
async def test_update_skill_found(toolkit, registry):
    result = await toolkit.update_skill(skill_id="s1", content="# updated")
    assert result.status == "done"
    assert registry.calls["upload"]["skill_id"] == "s1"


@pytest.mark.asyncio
async def test_update_skill_not_found(toolkit):
    result = await toolkit.update_skill(skill_id="ghost", content="x")
    assert result.status == "error"
    assert "not found" in result.error.lower()


# --- create_skill_tools factory --------------------------------------------

def test_create_skill_tools_db_only(registry):
    """Without a file_registry, the factory returns just the DB-backed tools."""
    from parrot.skills.tools import create_skill_tools
    names = {t.name for t in create_skill_tools(registry=registry, agent_id="a")}
    assert names == {
        "search_skills", "read_skill", "list_skills",
        "document_skill", "update_skill",
    }


def test_create_skill_tools_with_file_registry(registry, tmp_path):
    """With a file_registry + learned_dir, file-based tools are unioned in."""
    from parrot.skills.tools import create_skill_tools
    from parrot.skills.file_registry import SkillFileRegistry
    file_reg = SkillFileRegistry(skills_dir=tmp_path, learned_dir=tmp_path / "learned")
    names = {
        t.name for t in create_skill_tools(
            registry=registry, agent_id="a",
            file_registry=file_reg, learned_dir=tmp_path / "learned",
        )
    }
    assert {"search_skills", "read_skill", "list_skills",
            "document_skill", "update_skill"} <= names
    assert {"load_skill", "read_skill_asset", "save_learned_skill"} <= names


def test_create_skill_tools_read_only(registry):
    """include_write_tools=False drops the write tools from the factory output."""
    from parrot.skills.tools import create_skill_tools
    names = {
        t.name for t in create_skill_tools(
            registry=registry, agent_id="a", include_write_tools=False
        )
    }
    assert "document_skill" not in names and "update_skill" not in names
