"""Unit tests for ScrapingPlan and PlanRegistryEntry models."""
import pytest
from datetime import datetime, timezone

from parrot.tools.scraping.plan import ScrapingPlan, PlanRegistryEntry


@pytest.fixture
def sample_plan():
    return ScrapingPlan(
        url="https://example.com/products",
        objective="Extract product listings",
        steps=[
            {"action": "navigate", "url": "https://example.com/products"},
            {"action": "wait", "condition": ".product-list", "condition_type": "selector"},
            {"action": "get_html", "selector": ".product-list"},
        ],
        tags=["ecommerce", "products"],
    )


class TestScrapingPlan:
    def test_auto_populate_domain(self, sample_plan):
        """Domain auto-derived from URL."""
        assert sample_plan.domain == "example.com"

    def test_auto_populate_name(self, sample_plan):
        """Name defaults to sanitized domain when not provided."""
        assert sample_plan.name is not None
        assert sample_plan.name == "example-com"

    def test_explicit_name_preserved(self):
        """Explicit name is not overwritten."""
        plan = ScrapingPlan(
            url="https://example.com/page",
            objective="test",
            steps=[],
            name="my-custom-plan",
        )
        assert plan.name == "my-custom-plan"

    def test_fingerprint_stability(self):
        """Same URL with different query params produces same fingerprint."""
        plan1 = ScrapingPlan(
            url="https://example.com/page?utm_source=google",
            objective="test",
            steps=[],
        )
        plan2 = ScrapingPlan(
            url="https://example.com/page?ref=twitter&v=2",
            objective="test",
            steps=[],
        )
        assert plan1.fingerprint == plan2.fingerprint
        assert len(plan1.fingerprint) == 16

    def test_fingerprint_differs_for_different_paths(self):
        """Different URL paths produce different fingerprints."""
        plan1 = ScrapingPlan(
            url="https://example.com/products",
            objective="test",
            steps=[],
        )
        plan2 = ScrapingPlan(
            url="https://example.com/about",
            objective="test",
            steps=[],
        )
        assert plan1.fingerprint != plan2.fingerprint

    def test_normalized_url_strips_params(self):
        """Normalized URL has no query params or fragments."""
        plan = ScrapingPlan(
            url="https://example.com/page?q=1#section",
            objective="test",
            steps=[],
        )
        assert plan.normalized_url == "https://example.com/page"

    def test_normalized_url_preserves_path(self, sample_plan):
        """Normalized URL preserves scheme, netloc, and path."""
        assert sample_plan.normalized_url == "https://example.com/products"

    def test_json_roundtrip(self, sample_plan):
        """model_dump_json -> model_validate_json preserves all fields."""
        json_str = sample_plan.model_dump_json()
        restored = ScrapingPlan.model_validate_json(json_str)
        assert restored.url == sample_plan.url
        assert restored.fingerprint == sample_plan.fingerprint
        assert restored.domain == sample_plan.domain
        assert restored.name == sample_plan.name
        assert restored.steps == sample_plan.steps
        assert restored.tags == sample_plan.tags
        assert restored.version == sample_plan.version
        assert restored.source == sample_plan.source

    def test_default_created_at(self, sample_plan):
        """created_at defaults to a UTC datetime."""
        assert sample_plan.created_at is not None
        assert sample_plan.created_at.tzinfo is not None

    def test_default_source(self, sample_plan):
        """Default source is 'llm'."""
        assert sample_plan.source == "llm"

    def test_default_version(self, sample_plan):
        """Default version is '1.0'."""
        assert sample_plan.version == "1.0"

    def test_fingerprint_length(self, sample_plan):
        """Fingerprint is exactly 16 hex characters."""
        assert len(sample_plan.fingerprint) == 16
        assert all(c in "0123456789abcdef" for c in sample_plan.fingerprint)

    def test_url_with_fragment_only(self):
        """URL with only a fragment is normalized correctly."""
        plan = ScrapingPlan(
            url="https://example.com/docs#intro",
            objective="test",
            steps=[],
        )
        assert plan.normalized_url == "https://example.com/docs"


class TestPlanRegistryEntry:
    def test_entry_creation(self):
        """PlanRegistryEntry validates with required fields."""
        entry = PlanRegistryEntry(
            name="example-com",
            plan_version="1.0",
            url="https://example.com/products",
            domain="example.com",
            fingerprint="abcdef0123456789",
            path="example.com/example-com_v1.0_abcdef0123456789.json",
            created_at=datetime.now(timezone.utc),
        )
        assert entry.use_count == 0
        assert entry.last_used_at is None
        assert entry.tags == []

    def test_entry_with_usage(self):
        """PlanRegistryEntry tracks usage stats."""
        now = datetime.now(timezone.utc)
        entry = PlanRegistryEntry(
            name="example-com",
            plan_version="1.0",
            url="https://example.com/products",
            domain="example.com",
            fingerprint="abcdef0123456789",
            path="example.com/example-com_v1.0_abcdef0123456789.json",
            created_at=now,
            last_used_at=now,
            use_count=5,
            tags=["ecommerce"],
        )
        assert entry.use_count == 5
        assert entry.last_used_at == now
        assert entry.tags == ["ecommerce"]

    def test_entry_json_roundtrip(self):
        """PlanRegistryEntry survives JSON serialization."""
        entry = PlanRegistryEntry(
            name="test",
            plan_version="1.0",
            url="https://test.com",
            domain="test.com",
            fingerprint="1234567890abcdef",
            path="test.com/test_v1.0_1234567890abcdef.json",
            created_at=datetime.now(timezone.utc),
        )
        json_str = entry.model_dump_json()
        restored = PlanRegistryEntry.model_validate_json(json_str)
        assert restored.name == entry.name
        assert restored.path == entry.path
        assert restored.fingerprint == entry.fingerprint
