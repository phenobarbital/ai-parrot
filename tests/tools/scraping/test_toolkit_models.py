"""Tests for toolkit data models — TASK-049."""
from datetime import datetime, timezone

from parrot.tools.scraping.toolkit_models import (
    DriverConfig,
    PlanSaveResult,
    PlanSummary,
)
from parrot.tools.scraping.plan import PlanRegistryEntry


class TestDriverConfig:
    def test_defaults(self):
        """DriverConfig initializes with correct defaults."""
        config = DriverConfig()
        assert config.driver_type == "selenium"
        assert config.browser == "chrome"
        assert config.headless is True
        assert config.mobile is False
        assert config.auto_install is True
        assert config.default_timeout == 10
        assert config.retry_attempts == 3
        assert config.delay_between_actions == 1.0
        assert config.overlay_housekeeping is True
        assert config.disable_images is False
        assert config.custom_user_agent is None

    def test_merge_applies_overrides(self):
        """merge() applies overrides without mutating original."""
        config = DriverConfig()
        merged = config.merge({"headless": False, "browser": "firefox"})
        assert merged.headless is False
        assert merged.browser == "firefox"
        # Original unchanged
        assert config.headless is True
        assert config.browser == "chrome"

    def test_merge_none_returns_copy(self):
        """merge(None) returns a copy, not the same instance."""
        config = DriverConfig(browser="edge")
        merged = config.merge(None)
        assert merged.browser == "edge"
        assert merged is not config

    def test_merge_empty_dict_returns_copy(self):
        """merge({}) returns a copy, not the same instance."""
        config = DriverConfig(browser="safari")
        merged = config.merge({})
        assert merged.browser == "safari"
        assert merged is not config

    def test_merge_preserves_non_overridden_fields(self):
        """merge() keeps fields that aren't in the overrides dict."""
        config = DriverConfig(
            browser="firefox", headless=False, retry_attempts=5
        )
        merged = config.merge({"browser": "chrome"})
        assert merged.browser == "chrome"
        assert merged.headless is False
        assert merged.retry_attempts == 5

    def test_custom_values(self):
        """DriverConfig accepts custom values for all fields."""
        config = DriverConfig(
            driver_type="playwright",
            browser="webkit",
            headless=False,
            mobile=True,
            mobile_device="iPhone 12",
            auto_install=False,
            default_timeout=30,
            retry_attempts=5,
            delay_between_actions=2.5,
            overlay_housekeeping=False,
            disable_images=True,
            custom_user_agent="MyBot/1.0",
        )
        assert config.driver_type == "playwright"
        assert config.browser == "webkit"
        assert config.mobile_device == "iPhone 12"
        assert config.default_timeout == 30


class TestPlanSummary:
    def test_from_registry_entry(self):
        """from_registry_entry() correctly maps all fields."""
        now = datetime.now(timezone.utc)
        entry = PlanRegistryEntry(
            name="example-com",
            plan_version="1.0",
            url="https://example.com",
            domain="example.com",
            fingerprint="abc123def456",
            path="example.com/plan.json",
            created_at=now,
            last_used_at=now,
            use_count=5,
            tags=["test", "demo"],
        )
        summary = PlanSummary.from_registry_entry(entry)
        assert summary.name == "example-com"
        assert summary.version == "1.0"
        assert summary.url == "https://example.com"
        assert summary.domain == "example.com"
        assert summary.created_at == now
        assert summary.last_used_at == now
        assert summary.use_count == 5
        assert summary.tags == ["test", "demo"]

    def test_from_registry_entry_minimal(self):
        """from_registry_entry() works with minimal entry (no optional fields)."""
        entry = PlanRegistryEntry(
            name="minimal",
            plan_version="0.1",
            url="https://minimal.com",
            domain="minimal.com",
            fingerprint="abc",
            path="minimal.com/plan.json",
            created_at=datetime.now(timezone.utc),
        )
        summary = PlanSummary.from_registry_entry(entry)
        assert summary.name == "minimal"
        assert summary.last_used_at is None
        assert summary.use_count == 0
        assert summary.tags == []

    def test_defaults(self):
        """PlanSummary has correct defaults for optional fields."""
        summary = PlanSummary(
            name="test",
            version="1.0",
            url="https://test.com",
            domain="test.com",
            created_at=datetime.now(timezone.utc),
        )
        assert summary.last_used_at is None
        assert summary.use_count == 0
        assert summary.tags == []


class TestPlanSaveResult:
    def test_creation(self):
        """PlanSaveResult initializes with all required fields."""
        result = PlanSaveResult(
            success=True,
            path="plans/example.com/plan_v1.0.json",
            name="example-com",
            version="1.0",
            registered=True,
            message="Plan saved successfully",
        )
        assert result.success is True
        assert result.path == "plans/example.com/plan_v1.0.json"
        assert result.name == "example-com"
        assert result.version == "1.0"
        assert result.registered is True
        assert result.message == "Plan saved successfully"

    def test_failure_result(self):
        """PlanSaveResult can represent a failed save."""
        result = PlanSaveResult(
            success=False,
            path="",
            name="failed-plan",
            version="1.0",
            registered=False,
            message="Disk write failed: permission denied",
        )
        assert result.success is False
        assert result.registered is False

    def test_json_roundtrip(self):
        """PlanSaveResult survives JSON serialization round-trip."""
        original = PlanSaveResult(
            success=True,
            path="plans/x.json",
            name="test",
            version="2.0",
            registered=True,
            message="OK",
        )
        raw = original.model_dump_json()
        restored = PlanSaveResult.model_validate_json(raw)
        assert restored == original
