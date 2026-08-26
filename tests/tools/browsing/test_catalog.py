"""Tests for the disk-backed ActionCatalog."""
import pytest

from parrot_tools.browsing.catalog import ActionCatalog
from parrot_tools.browsing.models import ActionParam, SiteAction, SiteInfo

pytestmark = pytest.mark.asyncio


@pytest.fixture
def catalog(tmp_path):
    return ActionCatalog(tmp_path / "catalog")


def make_login(site: str = "") -> SiteAction:
    return SiteAction(
        site=site,
        name="login",
        description="Log in to the site",
        kind="operation",
        steps=[
            {"action": "navigate", "url": "https://hooba.es/login"},
            {"action": "fill", "selector": "#user", "value": "{{username}}"},
        ],
        params={"username": ActionParam(description="User")},
    )


async def register_hooba(catalog: ActionCatalog) -> SiteInfo:
    return await catalog.register_site(
        SiteInfo(
            base_url="https://www.hooba.es",
            title="Hooba",
            aliases=["hooba"],
        )
    )


class TestSites:
    async def test_register_creates_folder_and_file(self, catalog):
        info = await register_hooba(catalog)
        assert info.site == "www-hooba-es"
        site_dir = catalog.catalog_dir / info.site
        assert (site_dir / "_site.json").is_file()

    async def test_resolve_by_alias_domain_and_slug(self, catalog):
        info = await register_hooba(catalog)
        for query in ("hooba", "hooba.es", "www.hooba.es", info.site, "Hooba"):
            resolved = await catalog.resolve_site(query)
            assert resolved.site == info.site

    async def test_resolve_unknown_raises_keyerror(self, catalog):
        await register_hooba(catalog)
        with pytest.raises(KeyError, match="No catalogued site"):
            await catalog.resolve_site("desconocido")

    async def test_list_and_reload_from_disk(self, catalog, tmp_path):
        await register_hooba(catalog)
        # Fresh instance reads from disk
        fresh = ActionCatalog(tmp_path / "catalog")
        sites = await fresh.list_sites()
        assert [s.site for s in sites] == ["www-hooba-es"]

    async def test_delete_site(self, catalog):
        await register_hooba(catalog)
        await catalog.save_action("hooba", make_login())
        assert await catalog.delete_site("hooba") is True
        with pytest.raises(KeyError):
            await catalog.resolve_site("hooba")


class TestActions:
    async def test_save_and_get_roundtrip(self, catalog):
        await register_hooba(catalog)
        path = await catalog.save_action("hooba", make_login())
        assert path.name == "login.json"
        loaded = await catalog.get_action("hooba", "login")
        assert loaded.site == "www-hooba-es"
        assert loaded.steps[0]["action"] == "navigate"

    async def test_save_rejects_invalid_dsl(self, catalog):
        await register_hooba(catalog)
        bad = SiteAction(
            name="bad",
            description="x",
            steps=[{"action": "warp", "url": "https://x"}],
        )
        with pytest.raises(ValueError, match="invalid step"):
            await catalog.save_action("hooba", bad)
        assert not (catalog.catalog_dir / "www-hooba-es" / "bad.json").exists()

    async def test_save_no_overwrite_raises(self, catalog):
        await register_hooba(catalog)
        await catalog.save_action("hooba", make_login())
        with pytest.raises(FileExistsError):
            await catalog.save_action("hooba", make_login())
        # Explicit overwrite works
        await catalog.save_action("hooba", make_login(), overwrite=True)

    async def test_list_actions_excludes_site_file(self, catalog):
        await register_hooba(catalog)
        await catalog.save_action("hooba", make_login())
        actions = await catalog.list_actions("hooba")
        assert [a.name for a in actions] == ["login"]

    async def test_get_missing_action_lists_available(self, catalog):
        await register_hooba(catalog)
        await catalog.save_action("hooba", make_login())
        with pytest.raises(KeyError, match="login"):
            await catalog.get_action("hooba", "nope")

    async def test_delete_action(self, catalog):
        await register_hooba(catalog)
        await catalog.save_action("hooba", make_login())
        assert await catalog.delete_action("hooba", "login") is True
        assert await catalog.delete_action("hooba", "login") is False
