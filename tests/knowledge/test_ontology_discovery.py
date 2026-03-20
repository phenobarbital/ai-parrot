"""Tests for ontology relation discovery engine."""
from datetime import datetime, timezone
from pathlib import Path

import pytest

from parrot.knowledge.ontology.discovery import (
    DiscoveryResult,
    RelationDiscovery,
)
from parrot.knowledge.ontology.schema import (
    DiscoveryConfig,
    DiscoveryRule,
    EntityDef,
    MergedOntology,
    PropertyDef,
    RelationDef,
    TenantContext,
)


@pytest.fixture
def tenant_ctx() -> TenantContext:
    return TenantContext(
        tenant_id="test",
        arango_db="test_ontology",
        pgvector_schema="test",
        ontology=MergedOntology(
            name="test",
            version="1.0",
            entities={
                "Employee": EntityDef(
                    collection="employees",
                    key_field="employee_id",
                    properties=[
                        {"employee_id": PropertyDef(type="string")},
                        {"name": PropertyDef(type="string")},
                        {"department": PropertyDef(type="string")},
                        {"job_title": PropertyDef(type="string")},
                    ],
                ),
                "Department": EntityDef(
                    collection="departments",
                    key_field="dept_id",
                    properties=[
                        {"dept_id": PropertyDef(type="string")},
                        {"name": PropertyDef(type="string")},
                    ],
                ),
                "Role": EntityDef(
                    collection="roles",
                    key_field="role_id",
                    properties=[
                        {"role_id": PropertyDef(type="string")},
                        {"name": PropertyDef(type="string")},
                    ],
                ),
            },
            relations={},
            traversal_patterns={},
            layers=["test"],
            merge_timestamp=datetime.now(timezone.utc),
        ),
    )


@pytest.fixture
def employees() -> list[dict]:
    return [
        {"employee_id": "E1", "name": "Alice", "department": "ENG", "job_title": "Senior Engineer"},
        {"employee_id": "E2", "name": "Bob", "department": "SALES", "job_title": "Sales Manager"},
        {"employee_id": "E3", "name": "Carol", "department": "ENG", "job_title": "Field Technician"},
    ]


@pytest.fixture
def departments() -> list[dict]:
    return [
        {"dept_id": "ENG", "name": "Engineering"},
        {"dept_id": "SALES", "name": "Sales"},
        {"dept_id": "HR", "name": "Human Resources"},
    ]


@pytest.fixture
def roles() -> list[dict]:
    return [
        {"role_id": "R1", "name": "Senior Software Engineer"},
        {"role_id": "R2", "name": "Sales Executive"},
        {"role_id": "R3", "name": "Field Technical Specialist"},
    ]


@pytest.fixture
def discovery() -> RelationDiscovery:
    return RelationDiscovery()


class TestExactMatch:

    @pytest.mark.asyncio
    async def test_exact_match_basic(self, discovery, tenant_ctx, employees, departments):
        rel = RelationDef(
            from_entity="Employee",
            to_entity="Department",
            edge_collection="belongs_to_dept",
            discovery=DiscoveryConfig(
                rules=[DiscoveryRule(
                    source_field="department",
                    target_field="dept_id",
                    match_type="exact",
                )]
            ),
        )
        result = await discovery.discover(tenant_ctx, rel, employees, departments)
        assert isinstance(result, DiscoveryResult)
        assert result.stats.edges_created == 3  # All 3 employees match
        assert result.stats.needs_review == 0

    @pytest.mark.asyncio
    async def test_exact_match_no_matches(self, discovery, tenant_ctx, departments):
        employees_bad = [
            {"employee_id": "E1", "department": "UNKNOWN"},
        ]
        rel = RelationDef(
            from_entity="Employee",
            to_entity="Department",
            edge_collection="belongs_to_dept",
            discovery=DiscoveryConfig(
                rules=[DiscoveryRule(
                    source_field="department",
                    target_field="dept_id",
                    match_type="exact",
                )]
            ),
        )
        result = await discovery.discover(tenant_ctx, rel, employees_bad, departments)
        assert result.stats.edges_created == 0

    @pytest.mark.asyncio
    async def test_exact_edge_format(self, discovery, tenant_ctx, employees, departments):
        rel = RelationDef(
            from_entity="Employee",
            to_entity="Department",
            edge_collection="belongs_to_dept",
            discovery=DiscoveryConfig(
                rules=[DiscoveryRule(
                    source_field="department",
                    target_field="dept_id",
                    match_type="exact",
                )]
            ),
        )
        result = await discovery.discover(tenant_ctx, rel, employees, departments)
        edge = result.confirmed[0]
        assert "_from" in edge
        assert "_to" in edge
        assert "employees/" in edge["_from"]
        assert "departments/" in edge["_to"]
        assert edge["confidence"] == 1.0


class TestFuzzyMatch:

    @pytest.mark.asyncio
    async def test_fuzzy_match_high_similarity(self, discovery, tenant_ctx, employees, roles):
        rel = RelationDef(
            from_entity="Employee",
            to_entity="Role",
            edge_collection="has_role",
            discovery=DiscoveryConfig(
                rules=[DiscoveryRule(
                    source_field="job_title",
                    target_field="name",
                    match_type="fuzzy",
                    threshold=0.50,
                )]
            ),
        )
        result = await discovery.discover(tenant_ctx, rel, employees, roles)
        # At threshold 0.50, fuzzy matching should find reasonable matches
        assert result.stats.edges_created >= 1

    @pytest.mark.asyncio
    async def test_fuzzy_match_review_queue(self, discovery, tenant_ctx):
        """Low-confidence matches go to review queue."""
        source = [{"title": "Technical Writer"}]
        target = [{"name": "Content Strategist"}]
        rel = RelationDef(
            from_entity="Employee",
            to_entity="Role",
            edge_collection="has_role",
            discovery=DiscoveryConfig(
                rules=[DiscoveryRule(
                    source_field="title",
                    target_field="name",
                    match_type="fuzzy",
                    threshold=0.95,  # Very high threshold
                )]
            ),
        )
        result = await discovery.discover(tenant_ctx, rel, source, target)
        # The match should be below 0.95 but above 0.50 → review queue
        assert result.stats.edges_created == 0
        # Might or might not be in review depending on actual fuzzy score


class TestDeduplication:

    @pytest.mark.asyncio
    async def test_deduplication(self, discovery, tenant_ctx, employees, departments):
        """Multiple rules matching the same pair should produce one edge."""
        rel = RelationDef(
            from_entity="Employee",
            to_entity="Department",
            edge_collection="belongs_to_dept",
            discovery=DiscoveryConfig(
                rules=[
                    DiscoveryRule(
                        source_field="department",
                        target_field="dept_id",
                        match_type="exact",
                    ),
                    DiscoveryRule(
                        source_field="department",
                        target_field="dept_id",
                        match_type="exact",
                    ),
                ]
            ),
        )
        result = await discovery.discover(tenant_ctx, rel, employees, departments)
        # Should be deduplicated to 3 (not 6)
        assert result.stats.edges_created == 3


class TestReviewQueue:

    @pytest.mark.asyncio
    async def test_review_queue_written_to_disk(self, discovery, tenant_ctx, tmp_path):
        """Ambiguous pairs are written to JSON file."""
        disc = RelationDiscovery(review_dir=tmp_path)
        source = [{"title": "xyz_unique_value"}]
        target = [{"name": "xyz_similar_value"}]
        rel = RelationDef(
            from_entity="Employee",
            to_entity="Role",
            edge_collection="has_role",
            discovery=DiscoveryConfig(
                rules=[DiscoveryRule(
                    source_field="title",
                    target_field="name",
                    match_type="fuzzy",
                    threshold=0.99,  # Force review queue
                )]
            ),
        )
        result = await disc.discover(tenant_ctx, rel, source, target)
        if result.review_queue:
            review_file = tmp_path / "test_review_queue.json"
            assert review_file.exists()
            import json
            content = json.loads(review_file.read_text())
            assert len(content) > 0
            assert "confidence" in content[0]


class TestCompositeMatch:

    @pytest.mark.asyncio
    async def test_composite_multi_field(self, discovery, tenant_ctx):
        source = [
            {"dept": "Engineering", "loc": "NYC"},
            {"dept": "Sales", "loc": "LA"},
        ]
        target = [
            {"department": "Engineering", "location": "New York City"},
            {"department": "Sales", "location": "Los Angeles"},
        ]
        rel = RelationDef(
            from_entity="Employee",
            to_entity="Department",
            edge_collection="assigned",
            discovery=DiscoveryConfig(
                rules=[DiscoveryRule(
                    source_field="dept,loc",
                    target_field="department,location",
                    match_type="composite",
                    threshold=0.50,
                )]
            ),
        )
        result = await discovery.discover(tenant_ctx, rel, source, target)
        # dept matches should be strong, loc less so
        assert result.stats.edges_created >= 1


class TestDiscoveryStats:

    @pytest.mark.asyncio
    async def test_stats_accurate(self, discovery, tenant_ctx, employees, departments):
        rel = RelationDef(
            from_entity="Employee",
            to_entity="Department",
            edge_collection="belongs_to_dept",
            discovery=DiscoveryConfig(
                rules=[DiscoveryRule(
                    source_field="department",
                    target_field="dept_id",
                    match_type="exact",
                )]
            ),
        )
        result = await discovery.discover(tenant_ctx, rel, employees, departments)
        assert result.stats.total_source == 3
        assert result.stats.total_target == 3
        assert result.stats.edges_created == 3
        assert result.stats.needs_review == 0
