"""Tests for composite-action expansion (composer)."""
import pytest

from parrot_tools.browsing.catalog import ActionCatalog
from parrot_tools.browsing.composer import expand_action, expand_sequence
from parrot_tools.browsing.models import (
    ActionParam,
    ComposedRef,
    SiteAction,
    SiteInfo,
)

pytestmark = pytest.mark.asyncio

NAV = [{"action": "navigate", "url": "https://hooba.es/x"}]


@pytest.fixture
async def catalog(tmp_path):
    cat = ActionCatalog(tmp_path / "catalog")
    await cat.register_site(
        SiteInfo(base_url="https://hooba.es", aliases=["hooba"])
    )
    await cat.save_action(
        "hooba",
        SiteAction(name="login", description="Log in", steps=NAV),
    )
    await cat.save_action(
        "hooba",
        SiteAction(
            name="goto-dashboard",
            description="Open the dashboard",
            kind="navigation",
            steps=NAV,
            requires=["login"],
        ),
    )
    await cat.save_action(
        "hooba",
        SiteAction(
            name="search-customer",
            description="Search a customer in CRM",
            steps=[
                {"action": "fill", "selector": "#q", "value": "{{customer}}"},
            ],
            params={"customer": ActionParam(description="Customer name")},
            requires=["goto-dashboard"],
        ),
    )
    await cat.save_action(
        "hooba",
        SiteAction(
            name="invoice-draft",
            description="Create an invoice draft for a customer",
            kind="composite",
            compose=[
                ComposedRef(
                    action="search-customer",
                    params={"customer": "{{customer}}"},
                ),
                ComposedRef(action="goto-dashboard"),
            ],
            params={"customer": ActionParam(description="Customer name")},
        ),
    )
    return cat


class TestExpandAction:
    async def test_requires_injected_recursively(self, catalog):
        seq = await expand_action(
            catalog, "hooba", "search-customer", {"customer": "ACME"}
        )
        names = [r.action.name for r in seq]
        assert names == ["login", "goto-dashboard", "search-customer"]
        assert [r.injected for r in seq] == [True, True, False]

    async def test_requires_skipped_when_disabled(self, catalog):
        seq = await expand_action(
            catalog,
            "hooba",
            "search-customer",
            {"customer": "ACME"},
            include_requires=False,
        )
        assert [r.action.name for r in seq] == ["search-customer"]

    async def test_composite_expansion_binds_params(self, catalog):
        seq = await expand_action(
            catalog, "hooba", "invoice-draft", {"customer": "ACME"}
        )
        names = [r.action.name for r in seq]
        # login/goto-dashboard injected once; goto-dashboard from compose
        # NOT re-injected as prerequisite but still runs as explicit entry.
        assert names == [
            "login",
            "goto-dashboard",
            "search-customer",
            "goto-dashboard",
        ]
        search = next(r for r in seq if r.action.name == "search-customer")
        assert search.params["customer"] == "ACME"

    async def test_missing_required_param_raises(self, catalog):
        with pytest.raises(ValueError, match="customer"):
            await expand_action(catalog, "hooba", "search-customer", {})

    async def test_cycle_detection(self, catalog):
        await catalog.save_action(
            "hooba",
            SiteAction(
                name="a-flow",
                description="cycle a",
                kind="composite",
                compose=[ComposedRef(action="b-flow")],
            ),
        )
        await catalog.save_action(
            "hooba",
            SiteAction(
                name="b-flow",
                description="cycle b",
                kind="composite",
                compose=[ComposedRef(action="a-flow")],
            ),
        )
        with pytest.raises(ValueError, match="cycle"):
            await expand_action(catalog, "hooba", "a-flow")


class TestExpandSequence:
    async def test_prerequisites_deduplicated_across_plan(self, catalog):
        seq = await expand_sequence(
            catalog,
            "hooba",
            [
                "goto-dashboard",
                {"action": "search-customer", "params": {"customer": "ACME"}},
            ],
        )
        names = [r.action.name for r in seq]
        # login injected once; goto-dashboard not re-injected before
        # search-customer because the plan already satisfied it.
        assert names == ["login", "goto-dashboard", "search-customer"]

    async def test_shared_params_flow_to_entries(self, catalog):
        seq = await expand_sequence(
            catalog,
            "hooba",
            ["search-customer"],
            shared_params={"customer": "Globex"},
        )
        search = next(r for r in seq if r.action.name == "search-customer")
        assert search.params["customer"] == "Globex"

    async def test_malformed_entry_raises(self, catalog):
        with pytest.raises(ValueError, match="plan\\[0\\]"):
            await expand_sequence(catalog, "hooba", [{"params": {}}])
