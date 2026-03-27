"""Unit tests for Plan File I/O helpers."""
import pytest
from pathlib import Path

from parrot.tools.scraping.plan import ScrapingPlan
from parrot.tools.scraping.plan_io import save_plan_to_disk, load_plan_from_disk


@pytest.fixture
def sample_plan():
    return ScrapingPlan(
        url="https://example.com/products",
        objective="Extract product listings",
        steps=[
            {"action": "navigate", "url": "https://example.com/products"},
            {"action": "get_html", "selector": ".product-list"},
        ],
        tags=["ecommerce"],
    )


@pytest.fixture
def tmp_plans_dir(tmp_path):
    return tmp_path / "plans"


class TestPlanFileIO:
    @pytest.mark.asyncio
    async def test_save_and_load_plan(self, sample_plan, tmp_plans_dir):
        """Save plan to disk, reload, verify field equality."""
        saved_path = await save_plan_to_disk(sample_plan, tmp_plans_dir)
        loaded = await load_plan_from_disk(saved_path)
        assert loaded.url == sample_plan.url
        assert loaded.fingerprint == sample_plan.fingerprint
        assert loaded.steps == sample_plan.steps
        assert loaded.domain == sample_plan.domain
        assert loaded.name == sample_plan.name
        assert loaded.version == sample_plan.version
        assert loaded.tags == sample_plan.tags

    @pytest.mark.asyncio
    async def test_save_creates_domain_dir(self, sample_plan, tmp_plans_dir):
        """Domain subdirectory created automatically."""
        await save_plan_to_disk(sample_plan, tmp_plans_dir)
        domain_dir = tmp_plans_dir / sample_plan.domain
        assert domain_dir.is_dir()

    @pytest.mark.asyncio
    async def test_save_creates_plans_dir(self, sample_plan, tmp_plans_dir):
        """Plans root directory created automatically via parents=True."""
        assert not tmp_plans_dir.exists()
        await save_plan_to_disk(sample_plan, tmp_plans_dir)
        assert tmp_plans_dir.exists()

    @pytest.mark.asyncio
    async def test_file_naming_convention(self, sample_plan, tmp_plans_dir):
        """File follows {name}_v{version}_{fingerprint}.json convention."""
        saved_path = await save_plan_to_disk(sample_plan, tmp_plans_dir)
        expected_name = f"{sample_plan.name}_v{sample_plan.version}_{sample_plan.fingerprint}.json"
        assert saved_path.name == expected_name
        assert saved_path.parent.name == sample_plan.domain

    @pytest.mark.asyncio
    async def test_file_is_valid_json(self, sample_plan, tmp_plans_dir):
        """Saved file contains valid JSON."""
        import json
        saved_path = await save_plan_to_disk(sample_plan, tmp_plans_dir)
        content = saved_path.read_text()
        data = json.loads(content)
        assert data["url"] == sample_plan.url
        assert data["fingerprint"] == sample_plan.fingerprint

    @pytest.mark.asyncio
    async def test_load_nonexistent_file(self, tmp_path):
        """Loading a nonexistent file raises an error."""
        with pytest.raises((FileNotFoundError, OSError)):
            await load_plan_from_disk(tmp_path / "nonexistent.json")

    @pytest.mark.asyncio
    async def test_multiple_plans_same_domain(self, tmp_plans_dir):
        """Multiple plans for the same domain coexist in the same directory."""
        plan1 = ScrapingPlan(
            url="https://example.com/products",
            objective="Products",
            steps=[],
            name="products-plan",
        )
        plan2 = ScrapingPlan(
            url="https://example.com/about",
            objective="About page",
            steps=[],
            name="about-plan",
        )
        path1 = await save_plan_to_disk(plan1, tmp_plans_dir)
        path2 = await save_plan_to_disk(plan2, tmp_plans_dir)

        assert path1.parent == path2.parent  # same domain dir
        assert path1 != path2  # different files

        loaded1 = await load_plan_from_disk(path1)
        loaded2 = await load_plan_from_disk(path2)
        assert loaded1.name == "products-plan"
        assert loaded2.name == "about-plan"

    @pytest.mark.asyncio
    async def test_save_returns_absolute_path(self, sample_plan, tmp_plans_dir):
        """save_plan_to_disk returns a Path that exists on disk."""
        saved_path = await save_plan_to_disk(sample_plan, tmp_plans_dir)
        assert saved_path.exists()
        assert saved_path.is_file()
