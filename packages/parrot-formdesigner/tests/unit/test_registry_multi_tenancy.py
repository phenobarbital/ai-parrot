"""Unit tests for FormRegistry multi-tenancy (FEAT-183).

Tests Modules 1 and 2 from spec §4:
- Nested-dict state, tenant resolution, constructor args (TASK-1239).
- load_from_directory tenant resolution (TASK-1240).
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from parrot_formdesigner.core.schema import FormSchema
from parrot_formdesigner.services import FormRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_form(form_id: str, tenant: str | None = None) -> FormSchema:
    """Build a minimal FormSchema with a configurable tenant."""
    return FormSchema(
        form_id=form_id,
        version="1.0",
        title={"en": form_id},
        sections=[],
        tenant=tenant,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def registry() -> FormRegistry:
    """Default-config: default_tenant='navigator', require_tenant=True."""
    return FormRegistry()


@pytest.fixture
def lax_registry() -> FormRegistry:
    """For tests that need the require_tenant=False seal-to-default behavior."""
    return FormRegistry(require_tenant=False)


# ---------------------------------------------------------------------------
# Module 1 tests (TASK-1239)
# ---------------------------------------------------------------------------


class TestRegistryMultiTenancy:
    """Core multi-tenancy behaviour for FormRegistry._forms nested dict."""

    async def test_register_isolates_same_form_id_across_tenants(
        self, registry: FormRegistry
    ) -> None:
        """Two tenants register the same form_id without collision."""
        await registry.register(_make_form("customer-intake", tenant="epson"))
        await registry.register(_make_form("customer-intake", tenant="pokemon"))

        form_epson = await registry.get_by_slug("customer-intake", tenant="epson")
        form_pokemon = await registry.get_by_slug("customer-intake", tenant="pokemon")

        assert form_epson is not None
        assert form_pokemon is not None
        assert form_epson is not form_pokemon

        forms_epson = await registry.list_forms(tenant="epson")
        forms_pokemon = await registry.list_forms(tenant="pokemon")
        assert {f.form_id for f in forms_epson} == {"customer-intake"}
        assert {f.form_id for f in forms_pokemon} == {"customer-intake"}
        # They are different objects
        assert forms_epson[0] is not forms_pokemon[0]

    async def test_get_strict_tenant_resolution(self, registry: FormRegistry) -> None:
        """get(form_uid, tenant='epson') returns None for a form under 'pokemon'."""
        form = _make_form("f", tenant="epson")
        await registry.register(form)
        assert await registry.get(form.form_uid, tenant="pokemon") is None

    async def test_get_none_tenant_resolves_to_default(
        self, registry: FormRegistry
    ) -> None:
        """get(form_uid) with no kwarg resolves to default_tenant='navigator'."""
        form = _make_form("f", tenant="navigator")
        await registry.register(form)
        assert await registry.get(form.form_uid) is not None  # None → "navigator"

    async def test_register_explicit_kwarg_overrides_form_tenant(
        self, registry: FormRegistry, caplog: pytest.LogCaptureFixture
    ) -> None:
        """register(form, tenant='y') overrides form.tenant='x'; logs WARNING."""
        caplog.set_level(logging.WARNING)
        form = _make_form("f", tenant="epson")
        await registry.register(form, tenant="pokemon")

        assert await registry.get(form.form_uid, tenant="pokemon") is not None
        assert await registry.get(form.form_uid, tenant="epson") is None

        # A warning mentioning tenant should have been emitted.
        assert any("tenant" in rec.message.lower() for rec in caplog.records)

    async def test_register_require_tenant_true_raises_on_missing(
        self, registry: FormRegistry
    ) -> None:
        """require_tenant=True, form.tenant=None, no kwarg → ValueError."""
        with pytest.raises(ValueError, match="tenant"):
            await registry.register(_make_form("f", tenant=None))

    async def test_register_require_tenant_false_seals_to_default(
        self, lax_registry: FormRegistry
    ) -> None:
        """require_tenant=False, form.tenant=None → form lands under default_tenant."""
        form = _make_form("f", tenant=None)
        await lax_registry.register(form)
        assert await lax_registry.get(form.form_uid, tenant="navigator") is not None

    async def test_unregister_tenant_scoped(self, registry: FormRegistry) -> None:
        """unregister(form_uid, tenant='epson') does not touch the form under 'pokemon'."""
        form_epson = _make_form("f", tenant="epson")
        form_pokemon = _make_form("f", tenant="pokemon")
        await registry.register(form_epson)
        await registry.register(form_pokemon)

        result = await registry.unregister(form_epson.form_uid, tenant="epson")
        assert result is True
        assert await registry.get(form_pokemon.form_uid, tenant="pokemon") is not None
        assert await registry.get(form_epson.form_uid, tenant="epson") is None

    async def test_unregister_deletes_empty_outer_key(
        self, registry: FormRegistry
    ) -> None:
        """After the last form under a tenant is removed, the tenant key is deleted."""
        form = _make_form("f", tenant="epson")
        await registry.register(form)
        await registry.unregister(form.form_uid, tenant="epson")
        assert "epson" not in await registry.list_tenants()

    async def test_list_forms_tenant_scoped(self, registry: FormRegistry) -> None:
        """list_forms(tenant='epson') returns only forms for 'epson'."""
        await registry.register(_make_form("a", tenant="epson"))
        await registry.register(_make_form("b", tenant="pokemon"))

        forms = await registry.list_forms(tenant="epson")
        assert {f.form_id for f in forms} == {"a"}

    async def test_clear_tenant_scoped(self, registry: FormRegistry) -> None:
        """clear(tenant='epson') empties only 'epson'; 'pokemon' survives."""
        await registry.register(_make_form("a", tenant="epson"))
        await registry.register(_make_form("b", tenant="pokemon"))

        await registry.clear(tenant="epson")

        assert (await registry.list_forms(tenant="epson")) == []
        assert len(await registry.list_forms(tenant="pokemon")) == 1
        # Outer key deleted for empty tenant.
        assert "epson" not in await registry.list_tenants()

    async def test_clear_all_drops_everything(self, registry: FormRegistry) -> None:
        """clear_all() empties every tenant."""
        await registry.register(_make_form("a", tenant="epson"))
        await registry.register(_make_form("b", tenant="pokemon"))

        await registry.clear_all()

        assert await registry.list_tenants() == []
        assert len(registry) == 0

    async def test_list_tenants_sorted(self, registry: FormRegistry) -> None:
        """list_tenants() returns alphabetically sorted keys."""
        await registry.register(_make_form("x", tenant="pokemon"))
        await registry.register(_make_form("x", tenant="epson"))
        assert await registry.list_tenants() == ["epson", "pokemon"]

    async def test_list_tenants_empty_when_no_forms(
        self, registry: FormRegistry
    ) -> None:
        """Empty registry → list_tenants() == []."""
        assert await registry.list_tenants() == []

    async def test_contains_tuple_only(self, registry: FormRegistry) -> None:
        """(tenant, form_id) in registry works; plain str raises TypeError."""
        await registry.register(_make_form("f", tenant="epson"))

        assert ("epson", "f") in registry
        assert ("pokemon", "f") not in registry

        with pytest.raises(TypeError):
            "f" in registry  # type: ignore[operator]  # plain str rejected

    async def test_len_total_across_tenants(self, registry: FormRegistry) -> None:
        """len(registry) returns the total count across all tenants."""
        await registry.register(_make_form("a", tenant="epson"))
        await registry.register(_make_form("b", tenant="pokemon"))
        assert len(registry) == 2

    async def test_aiter_deterministic_order(self, registry: FormRegistry) -> None:
        """__aiter__ yields forms in (tenant, form_id) sorted order."""
        await registry.register(_make_form("b", tenant="pokemon"))
        await registry.register(_make_form("a", tenant="pokemon"))
        await registry.register(_make_form("z", tenant="epson"))

        seen = [(f.tenant, f.form_id) async for f in registry]
        assert seen == [("epson", "z"), ("pokemon", "a"), ("pokemon", "b")]

    async def test_on_register_callback_receives_form(
        self, registry: FormRegistry
    ) -> None:
        """on_register callbacks receive the FormSchema with .tenant populated."""
        captured: list[FormSchema] = []

        async def cb(form: FormSchema) -> None:
            captured.append(form)

        registry.on_register(cb)
        await registry.register(_make_form("f", tenant="epson"))

        assert len(captured) == 1
        assert captured[0].form_id == "f"
        # The form's own .tenant is set (was already "epson" on the object).
        assert captured[0].tenant == "epson"

    async def test_on_unregister_callback_receives_tuple(
        self, registry: FormRegistry
    ) -> None:
        """on_unregister callbacks receive (form_uid, tenant) — FEAT-389 signature."""
        captured: list[tuple[str, str]] = []

        async def cb(form_uid: str, tenant: str) -> None:
            captured.append((form_uid, tenant))

        registry.on_unregister(cb)
        form = _make_form("f", tenant="epson")
        await registry.register(form)
        await registry.unregister(form.form_uid, tenant="epson")

        assert captured == [(form.form_uid, "epson")]

    async def test_on_unregister_async_mock_receives_tuple(
        self, registry: FormRegistry
    ) -> None:
        """AsyncMock-based variant: assert_awaited_once_with (form_uid, tenant)."""
        mock_cb = AsyncMock()
        registry.on_unregister(mock_cb)

        form = _make_form("f", tenant="epson")
        await registry.register(form)
        await registry.unregister(form.form_uid, tenant="epson")

        mock_cb.assert_awaited_once_with(form.form_uid, "epson")

    async def test_persist_routes_to_form_tenant(self) -> None:
        """register(form, persist=True) invokes storage.save(tenant=resolved)."""
        from unittest.mock import AsyncMock as AM

        mock_storage = AM()
        mock_storage.save = AM(return_value="f")

        registry = FormRegistry(storage=mock_storage)
        form = _make_form("f", tenant="epson")
        await registry.register(form, persist=True)

        mock_storage.save.assert_awaited_once()
        call_kwargs = mock_storage.save.call_args
        # The tenant kwarg should be the resolved tenant "epson".
        assert call_kwargs.kwargs.get("tenant") == "epson"

    async def test_load_from_storage_per_tenant_no_overwrite(self) -> None:
        """Sequential load_from_storage for different tenants populates both."""
        from unittest.mock import AsyncMock as AM

        epson_form = _make_form("f", tenant="epson")
        pokemon_form = _make_form("f", tenant="pokemon")

        mock_storage = AM()
        mock_storage.list_forms = AM(
            side_effect=[
                [{"form_id": "f"}],  # epson call
                [{"form_id": "f"}],  # pokemon call
            ]
        )
        mock_storage.load = AM(side_effect=[epson_form, pokemon_form])

        registry = FormRegistry(storage=mock_storage)
        await registry.load_from_storage(tenant="epson")
        await registry.load_from_storage(tenant="pokemon")

        # Both tenants should be populated. load_from_storage() registers
        # each hydrated FormSchema under ITS OWN form_uid (unaffected by
        # the form_id string returned in the storage list_forms() dict —
        # FEAT-389's re-keying happens inside register(), not here).
        assert await registry.get(epson_form.form_uid, tenant="epson") is not None
        assert await registry.get(pokemon_form.form_uid, tenant="pokemon") is not None
        assert sorted(await registry.list_tenants()) == ["epson", "pokemon"]


# ---------------------------------------------------------------------------
# Module 2 tests (TASK-1240) — load_from_directory tenant resolution
# ---------------------------------------------------------------------------


class TestLoadFromDirectoryTenant:
    """Tests for load_from_directory per-file tenant resolution."""

    @pytest.fixture
    def yaml_dir(self, tmp_path: Path) -> Path:
        """Directory with two YAML fixtures: one with tenant, one without."""
        d = tmp_path / "yaml_forms_mixed"
        d.mkdir()
        # File with explicit YAML tenant:
        (d / "with_tenant.yaml").write_text(
            "form_id: with-tenant\nversion: '1.0'\n"
            "title:\n  en: With Tenant\nsections: []\ntenant: epson\n"
        )
        # File without tenant:
        (d / "no_tenant.yaml").write_text(
            "form_id: no-tenant\nversion: '1.0'\n"
            "title:\n  en: No Tenant\nsections: []\n"
        )
        return d

    async def test_load_from_directory_yaml_tenant_wins(
        self, registry: FormRegistry, yaml_dir: Path
    ) -> None:
        """YAML tenant: epson wins over kwarg tenant='navigator'."""
        # kwarg says "navigator", YAML says "epson" — YAML wins for with-tenant.
        # no-tenant file gets kwarg "navigator".
        count = await registry.load_from_directory(yaml_dir, tenant="navigator")
        assert count == 2

        assert await registry.get_by_slug("with-tenant", tenant="epson") is not None
        assert await registry.get_by_slug("no-tenant", tenant="navigator") is not None
        # with-tenant is NOT under "navigator" (YAML won).
        assert await registry.get_by_slug("with-tenant", tenant="navigator") is None

    async def test_load_from_directory_kwarg_default_used(
        self, registry: FormRegistry, yaml_dir: Path
    ) -> None:
        """YAML without tenant gets kwarg tenant applied."""
        count = await registry.load_from_directory(yaml_dir, tenant="pokemon")
        # YAML's with-tenant still wins ("epson"); no-tenant gets "pokemon".
        assert await registry.get_by_slug("with-tenant", tenant="epson") is not None
        assert await registry.get_by_slug("no-tenant", tenant="pokemon") is not None
        assert count == 2

    async def test_load_from_directory_skip_with_warning_on_missing(
        self,
        registry: FormRegistry,
        yaml_dir: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """No kwarg + no YAML tenant + require_tenant=True → file skipped with WARNING."""
        caplog.set_level(logging.WARNING)
        # No kwarg supplied; require_tenant=True (default).
        count = await registry.load_from_directory(yaml_dir)  # no tenant= kwarg

        # Only with-tenant is loaded (has explicit tenant: epson).
        assert count == 1
        assert await registry.get_by_slug("with-tenant", tenant="epson") is not None
        assert await registry.get_by_slug("no-tenant", tenant="navigator") is None

        # Warning logged for the skipped file.
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any(
            "no_tenant" in r.message or "tenant" in r.message.lower()
            for r in warnings
        )

    async def test_load_from_directory_require_tenant_false_seals_to_default(
        self, lax_registry: FormRegistry, yaml_dir: Path
    ) -> None:
        """With require_tenant=False, files without tenant seal to default_tenant."""
        count = await lax_registry.load_from_directory(yaml_dir)
        # Both files should be loaded: with_tenant → epson, no_tenant → navigator.
        assert count == 2
        assert await lax_registry.get_by_slug("with-tenant", tenant="epson") is not None
        assert await lax_registry.get_by_slug("no-tenant", tenant="navigator") is not None


# ---------------------------------------------------------------------------
# Module 2 tests (TASK-1973) — stable UUID identity (form_uid)
# ---------------------------------------------------------------------------


class TestRegistryFormUid:
    """Tests for FormRegistry re-keyed on form_uid, with a tenant_form_slug
    secondary index (FEAT-389)."""

    @pytest.fixture
    def registry(self) -> FormRegistry:
        return FormRegistry(require_tenant=False, default_tenant="test")

    async def test_index_by_form_uid(self, registry: FormRegistry) -> None:
        """register() stores under form.form_uid; get(form_uid) retrieves it."""
        form = _make_form("test", tenant="test")
        await registry.register(form)
        result = await registry.get(form.form_uid)
        assert result is not None
        assert result.form_uid == form.form_uid

    async def test_get_by_slug(self, registry: FormRegistry) -> None:
        """get_by_slug(form_id) resolves via the tenant_form_slug index."""
        form = _make_form("my-slug", tenant="test")
        await registry.register(form)
        result = await registry.get_by_slug("my-slug")
        assert result is not None
        assert result.form_uid == form.form_uid

    async def test_slug_unique_per_tenant(self, registry: FormRegistry) -> None:
        """Registering a second, different form_uid under a taken slug
        (overwrite=False) raises ValueError."""
        f1 = _make_form("dup", tenant="test")
        f2 = _make_form("dup", tenant="test")
        await registry.register(f1)
        with pytest.raises(ValueError, match="already in use"):
            await registry.register(f2, overwrite=False)

    async def test_slug_allowed_across_tenants(self) -> None:
        """The same slug may be registered independently in different tenants."""
        reg = FormRegistry(require_tenant=False, default_tenant="t1")
        f1 = _make_form("same", tenant="t1")
        f2 = _make_form("same", tenant="t2")
        await reg.register(f1, tenant="t1")
        await reg.register(f2, tenant="t2")
        assert await reg.get_by_slug("same", tenant="t1") is not None
        assert await reg.get_by_slug("same", tenant="t2") is not None

    async def test_registry_tenant_form_slug_key(self) -> None:
        """_make_slug_key() produces '{tenant}_{form_id}'."""
        assert FormRegistry._make_slug_key("epson", "my-form") == "epson_my-form"

    async def test_unregister_cleans_both_indexes(
        self, registry: FormRegistry
    ) -> None:
        """unregister(form_uid) removes the form from both _forms and
        _slug_index."""
        form = _make_form("clean", tenant="test")
        await registry.register(form)
        await registry.unregister(form.form_uid)
        assert await registry.get(form.form_uid) is None
        assert await registry.get_by_slug("clean") is None

    async def test_clone_new_uid(self, registry: FormRegistry) -> None:
        """clone_form() generates a fresh form_uid; the source is untouched."""
        form = _make_form("original", tenant="test")
        await registry.register(form)
        clone = await registry.clone_form(form.form_uid, "clone-slug")
        assert clone.form_uid != form.form_uid
        assert clone.form_id == "clone-slug"
        # Source form is unchanged.
        source_reloaded = await registry.get(form.form_uid)
        assert source_reloaded is not None
        assert source_reloaded.form_id == "original"

    async def test_register_slug_change_updates_index(
        self, registry: FormRegistry
    ) -> None:
        """Re-registering the same form_uid with a changed form_id moves the
        slug index entry — the old slug no longer resolves, the new one does."""
        form = _make_form("old-slug", tenant="test")
        await registry.register(form)

        form.form_id = "new-slug"
        await registry.register(form)

        assert await registry.get_by_slug("old-slug") is None
        result = await registry.get_by_slug("new-slug")
        assert result is not None
        assert result.form_uid == form.form_uid

    async def test_list_form_uids(self, registry: FormRegistry) -> None:
        """list_form_uids() returns the form_uid values for the tenant."""
        f1 = _make_form("a", tenant="test")
        f2 = _make_form("b", tenant="test")
        await registry.register(f1)
        await registry.register(f2)
        uids = await registry.list_form_uids()
        assert sorted(uids) == sorted([f1.form_uid, f2.form_uid])

    async def test_list_form_ids_derived_from_values(
        self, registry: FormRegistry
    ) -> None:
        """list_form_ids() still returns slugs, now derived from the
        form_uid-keyed primary index's values."""
        f1 = _make_form("a", tenant="test")
        f2 = _make_form("b", tenant="test")
        await registry.register(f1)
        await registry.register(f2)
        assert sorted(await registry.list_form_ids()) == ["a", "b"]
