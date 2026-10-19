"""FEAT-707 — SkillRegistryMixin tenant core (TASK-4499)."""
import logging
from pathlib import Path

import pytest

from parrot.skills.mixin import SkillRegistryMixin
from parrot.skills.tenancy import bind_skill_tenant, current_skill_tenant, reset_skill_tenant
from parrot.utils.helpers import RequestContext


def _skill(path: Path, name: str, trigger: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nname: {name}\ndescription: {name} desc\ntriggers:\n  - /{trigger}\n---\n\nBody of {name}\n"
    )


@pytest.fixture
def agent_tree(tmp_path):
    root = tmp_path / "troc_finance"
    _skill(root / "skills" / "glob.md", "glob", "glob")
    _skill(root / "tenants" / "pokemon" / "skills" / "poke.md", "poke", "poke")
    _skill(root / "tenants" / "pokemon" / "skills" / "learned" / "x.md", "lx", "lx")
    _skill(root / "tenants" / "epson" / "skills" / "eps.md", "eps", "eps")
    _skill(root / "tenants" / "skills" / "skills" / "bad.md", "bad", "bad")
    return tmp_path


def make_host(tmp_path, **kw):
    class Host(SkillRegistryMixin):
        name = "troc_finance"
        enable_skill_registry = False

    host = Host(**kw)
    host._agents_dir = tmp_path
    return host


@pytest.mark.asyncio
async def test_tenant_based_false_no_scan(agent_tree):
    host = make_host(agent_tree)
    await host._configure_skill_file_registry()
    assert host.known_tenants() == frozenset()
    assert host.current_skill_view() is host._global_view
    assert host._global_view.get("/glob") is not None


@pytest.mark.asyncio
async def test_configure_loads_tenant_trees_eagerly(agent_tree, caplog):
    host = make_host(agent_tree, tenant_based=True)
    with caplog.at_level(logging.INFO):
        await host._configure_skill_file_registry()
    assert host.known_tenants() == frozenset({"pokemon", "epson"})
    msgs = [r.getMessage() for r in caplog.records]
    assert any(m.startswith("tenant=pokemon skills=1") for m in msgs)
    assert any(m.startswith("tenant=epson skills=1") for m in msgs)
    assert host.current_skill_view("pokemon").get("/poke") is not None
    assert host.current_skill_view("pokemon").get("/eps") is None


@pytest.mark.asyncio
async def test_reserved_tenant_dir_skipped(agent_tree):
    host = make_host(agent_tree, tenant_based=True)
    await host._configure_skill_file_registry()
    assert "skills" not in host.known_tenants()


@pytest.mark.asyncio
async def test_tenant_learned_dir_ignored_with_warning(agent_tree, caplog):
    host = make_host(agent_tree, tenant_based=True)
    with caplog.at_level(logging.WARNING):
        await host._configure_skill_file_registry()
    assert host.current_skill_view("pokemon").get("/lx") is None
    assert any("learned/" in r.getMessage() for r in caplog.records)


def test_resolve_tenant_precedence():
    host = make_host(Path("."), tenant_based=True, tenant_id="dflt")
    assert host._resolve_tenant() == "dflt"
    token = bind_skill_tenant("ctxvar")
    try:
        assert host._resolve_tenant() == "ctxvar"
        ctx = RequestContext(tenant="fromctx")
        assert host._resolve_tenant(ctx=ctx) == "fromctx"
        assert host._resolve_tenant("explicit", ctx) == "explicit"
    finally:
        reset_skill_tenant(token)
    assert make_host(Path("."), tenant_based=True)._resolve_tenant() is None


def test_constructor_kwargs_tenant_based_and_tenant_id():
    host = make_host(Path("."), tenant_based=True, tenant_id="pokemon")
    assert host.tenant_based is True
    assert host._tenant_id == "pokemon"
    assert make_host(Path(".")).tenant_based is False
    assert not hasattr(make_host(Path(".")), "_tenant_id")


@pytest.mark.asyncio
async def test_unresolved_tenant_global_view_debug(agent_tree, caplog):
    host = make_host(agent_tree, tenant_based=True)
    await host._configure_skill_file_registry()
    with caplog.at_level(logging.DEBUG):
        assert host.current_skill_view() is host._global_view


@pytest.mark.asyncio
async def test_unknown_tenant_warns_once_per_instance(agent_tree, caplog):
    host = make_host(agent_tree, tenant_based=True)
    await host._configure_skill_file_registry()
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        assert host.current_skill_view("nope") is host._global_view
        assert host.current_skill_view("nope") is host._global_view
    assert len([r for r in caplog.records if "Unknown skill tenant" in r.getMessage()]) == 1


def test_invalid_tenant_raises():
    host = make_host(Path("."), tenant_based=True)
    with pytest.raises(ValueError):
        host._resolve_tenant("../etc")
    with pytest.raises(ValueError):
        host._resolve_tenant("skills")


def test_enter_exit_hooks_bind_and_reset():
    host = make_host(Path("."), tenant_based=True)
    token = host._enter_skill_tenant("pokemon", None)
    assert current_skill_tenant() == "pokemon"
    host._exit_skill_tenant(token)
    assert current_skill_tenant() is None
    assert make_host(Path("."))._enter_skill_tenant("pokemon", None) is None


@pytest.mark.asyncio
async def test_reload_tenant_skills_adds_new_tenant(agent_tree):
    host = make_host(agent_tree, tenant_based=True)
    await host._configure_skill_file_registry()
    _skill(agent_tree / "troc_finance" / "tenants" / "acme" / "skills" / "a.md", "acme_s", "acme")
    reports = await host.reload_tenant_skills()
    assert "acme" in reports
    assert "acme" in host.known_tenants()
    assert host.current_skill_view("acme").get("/acme") is not None
    reports = await host.reload_tenant_skills("acme")
    assert reports["acme"].loaded == 1


@pytest.mark.asyncio
async def test_skill_paths_only_agent_tenant_based_warns(tmp_path, caplog):
    sp = tmp_path / "sp"
    _skill(sp / "p.md", "pskill", "pskill")

    class Host(SkillRegistryMixin):
        name = "a"
        enable_skill_registry = False
        skill_paths = [sp]

    host = Host(tenant_based=True)
    host._resolve_agents_dir = lambda: None
    with caplog.at_level(logging.WARNING):
        await host._configure_skill_file_registry()
    assert any("global skills only" in r.getMessage() for r in caplog.records)
    assert host.current_skill_view("x").get("/pskill") is not None
