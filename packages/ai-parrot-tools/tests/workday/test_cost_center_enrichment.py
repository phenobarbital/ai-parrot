"""TASK-2139: Cost-centre organisation-hierarchy enrichment."""
from __future__ import annotations

import logging

import pandas as pd
from parrot_tools.interfaces.workday.handlers.cost_centers import CostCenterType


class _FakeService:
    """Minimal stand-in providing call_operation + logger for the handler base."""

    def __init__(self):
        self.calls: list = []
        self._logger = logging.getLogger("test.workday.cost_centers")

    async def call_operation(self, operation, **kwargs):
        self.calls.append((operation, kwargs))
        return {}

    def serialize_object(self, obj):
        return obj


class TestHierarchyChain:
    async def test_builds_chain_from_container_orgs(self):
        """Container ids resolve into an ordered hierarchy chain."""
        handler = CostCenterType(_FakeService())
        cache = {
            "ORG-A": {"name": "Region A", "type": "Cost_Center_Hierarchy", "superior_id": "ORG-ROOT"},
            "ORG-ROOT": {"name": "Root", "type": "Cost_Center_Hierarchy", "superior_id": None},
        }
        chain = await handler._build_hierarchy_chain("ORG-A", cache)
        assert chain == [
            {"id": "ORG-A", "name": "Region A"},
            {"id": "ORG-ROOT", "name": "Root"},
        ]

    async def test_handles_missing_parent(self):
        """An absent parent link terminates the walk without raising."""
        handler = CostCenterType(_FakeService())

        async def fake_fetch(_org_id):
            raise RuntimeError("not found")

        handler._fetch_container_org_info = fake_fetch
        chain = await handler._build_hierarchy_chain("ORG-MISSING", {})
        assert chain == [{"id": "ORG-MISSING", "name": None}]

    async def test_cycle_does_not_loop_forever(self):
        """A self-referential/cyclic parent chain terminates."""
        handler = CostCenterType(_FakeService())
        cache = {
            "ORG-A": {"name": "A", "type": None, "superior_id": "ORG-B"},
            "ORG-B": {"name": "B", "type": None, "superior_id": "ORG-A"},  # cycle
        }
        chain = await handler._build_hierarchy_chain("ORG-A", cache)
        assert len(chain) == 2
        assert [c["id"] for c in chain] == ["ORG-A", "ORG-B"]

    async def test_cache_avoids_refetching_same_org(self):
        """A repeated organization_id is served from cache, not refetched."""
        handler = CostCenterType(_FakeService())
        calls = {"n": 0}

        async def fake_fetch(org_id):
            calls["n"] += 1
            return {"name": f"Org-{org_id}", "type": None, "superior_id": None}

        handler._fetch_container_org_info = fake_fetch
        cache: dict = {}
        await handler._build_hierarchy_chain("ORG-A", cache)
        await handler._build_hierarchy_chain("ORG-A", cache)
        assert calls["n"] == 1

    async def test_max_depth_cap(self):
        """A very long (non-cyclic) chain is capped at 10 levels."""
        handler = CostCenterType(_FakeService())
        cache = {}
        for i in range(20):
            cache[f"ORG-{i}"] = {
                "name": f"Org {i}",
                "type": None,
                "superior_id": f"ORG-{i + 1}" if i < 19 else None,
            }
        chain = await handler._build_hierarchy_chain("ORG-0", cache)
        assert len(chain) == 10


class TestResolveContainerOrgs:
    async def test_resolves_each_container_once(self):
        handler = CostCenterType(_FakeService())
        calls = {"n": 0}

        async def fake_fetch(org_id):
            calls["n"] += 1
            return {"name": f"Org-{org_id}", "type": "T", "superior_id": None}

        handler._fetch_container_org_info = fake_fetch
        cache = await handler._resolve_container_orgs({"ORG-A", "ORG-B"})
        assert calls["n"] == 2
        assert cache["ORG-A"]["name"] == "Org-ORG-A"
        assert cache["ORG-B"]["name"] == "Org-ORG-B"

    async def test_resolve_failure_is_graceful(self):
        handler = CostCenterType(_FakeService())

        async def fake_fetch(_org_id):
            raise RuntimeError("boom")

        handler._fetch_container_org_info = fake_fetch
        cache = await handler._resolve_container_orgs({"ORG-A"})
        assert cache["ORG-A"] == {"name": None, "type": None, "superior_id": None}


class TestEnrichmentOrchestration:
    async def test_enrich_merges_org_columns(self):
        handler = CostCenterType(_FakeService())

        org_df = pd.DataFrame(
            [
                {
                    "organization_id": "CC-001",
                    "parent_organization_id": "ORG-PARENT",
                    "roles": [],
                    "external_ids": [],
                    "last_updated_datetime": "2026-01-01",
                }
            ]
        )

        async def fake_fetch_org_enrichment(include_inactive=True):
            return org_df

        async def fake_resolve_container_orgs(_container_ids):
            return {
                "ORG-PARENT": {
                    "name": "Parent Org",
                    "type": "Cost_Center_Hierarchy",
                    "superior_id": None,
                }
            }

        handler._fetch_org_enrichment = fake_fetch_org_enrichment
        handler._resolve_container_orgs = fake_resolve_container_orgs

        rows = [{"cost_center_id": "CC-001", "cost_center_name": "Alpha"}]
        result = await handler._enrich_with_organizations(
            rows, cost_center_id=None, include_hierarchy_chain=True
        )

        assert result[0]["org_parent_organization_id"] == "ORG-PARENT"
        assert result[0]["org_parent_organization_name"] == "Parent Org"
        assert result[0]["org_parent_organization_type"] == "Cost_Center_Hierarchy"
        assert result[0]["org_hierarchy_chain"] == '[{"id": "ORG-PARENT", "name": "Parent Org"}]'

    async def test_enrich_missing_match_leaves_org_columns_none(self):
        handler = CostCenterType(_FakeService())

        async def fake_fetch_org_enrichment(include_inactive=True):
            return pd.DataFrame()

        handler._fetch_org_enrichment = fake_fetch_org_enrichment

        rows = [{"cost_center_id": "CC-002", "cost_center_name": "Beta"}]
        result = await handler._enrich_with_organizations(
            rows, cost_center_id=None, include_hierarchy_chain=False
        )
        assert result[0]["org_parent_organization_id"] is None
        assert result[0]["org_hierarchy_chain"] is None

    async def test_enrichment_failure_returns_rows_unchanged(self):
        handler = CostCenterType(_FakeService())

        async def fake_fetch_org_enrichment(include_inactive=True):
            raise RuntimeError("SOAP down")

        handler._fetch_org_enrichment = fake_fetch_org_enrichment

        rows = [{"cost_center_id": "CC-003", "cost_center_name": "Gamma"}]
        result = await handler._enrich_with_organizations(
            rows, cost_center_id=None, include_hierarchy_chain=False
        )
        assert result == rows


class TestEnrichmentIntegration:
    async def test_execute_wires_enrichment_into_dataframe(self):
        """execute() still returns a DataFrame, now carrying hierarchy columns."""
        cc_payload = {
            "Response_Data": {
                "Cost_Center": {
                    "Cost_Center_Reference": {
                        "ID": [{"type": "Cost_Center_Reference_ID", "_value_1": "CC-001"}],
                        "Descriptor": "Alpha",
                    },
                    "Cost_Center_Data": {},
                }
            }
        }

        class _CCService(_FakeService):
            async def call_operation(self, operation, **kwargs):
                self.calls.append((operation, kwargs))
                return cc_payload

        handler = CostCenterType(_CCService())

        async def fake_enrich(rows, cost_center_id=None, include_hierarchy_chain=False):
            for row in rows:
                row["org_hierarchy_chain"] = '[{"id": "ORG-PARENT", "name": "Parent"}]'
            return rows

        handler._enrich_with_organizations = fake_enrich

        df = await handler.execute(cost_center_id="CC-001")
        assert isinstance(df, pd.DataFrame)
        assert "org_hierarchy_chain" in df.columns
        assert df.iloc[0]["org_hierarchy_chain"] == '[{"id": "ORG-PARENT", "name": "Parent"}]'
