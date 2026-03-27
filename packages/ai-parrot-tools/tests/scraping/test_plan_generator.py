"""Tests for PlanGenerator — TASK-052."""
import json

import pytest
from unittest.mock import AsyncMock

from parrot.tools.scraping.plan import ScrapingPlan
from parrot.tools.scraping.plan_generator import (
    PageSnapshot,
    PlanGenerator,
    _extract_json_object,
    _strip_code_fences,
)


VALID_PLAN_DICT = {
    "url": "https://example.com/products",
    "objective": "Extract products",
    "steps": [
        {"action": "navigate", "url": "https://example.com/products"},
        {"action": "wait", "condition": ".products", "condition_type": "selector"},
    ],
}


@pytest.fixture
def valid_plan_json():
    return json.dumps(VALID_PLAN_DICT)


@pytest.fixture
def mock_client(valid_plan_json):
    client = AsyncMock()
    client.complete = AsyncMock(return_value=valid_plan_json)
    return client


class TestStripCodeFences:
    def test_strips_json_fence(self, valid_plan_json):
        wrapped = f"```json\n{valid_plan_json}\n```"
        assert _strip_code_fences(wrapped) == valid_plan_json

    def test_strips_plain_fence(self, valid_plan_json):
        wrapped = f"```\n{valid_plan_json}\n```"
        assert _strip_code_fences(wrapped) == valid_plan_json

    def test_returns_plain_text_unchanged(self, valid_plan_json):
        assert _strip_code_fences(valid_plan_json) == valid_plan_json

    def test_handles_whitespace(self, valid_plan_json):
        wrapped = f"```json\n  {valid_plan_json}  \n```"
        result = _strip_code_fences(wrapped)
        assert result.startswith("{")


class TestExtractJsonObject:
    def test_extracts_from_plain_json(self):
        result = _extract_json_object('{"key": "value"}')
        assert json.loads(result) == {"key": "value"}

    def test_extracts_from_surrounded_text(self):
        text = 'Here is the plan: {"key": "value"} end.'
        result = _extract_json_object(text)
        assert json.loads(result) == {"key": "value"}

    def test_handles_nested_braces(self):
        text = '{"a": {"b": 1}}'
        result = _extract_json_object(text)
        assert json.loads(result) == {"a": {"b": 1}}

    def test_raises_on_no_json(self):
        with pytest.raises(ValueError, match="No JSON object found"):
            _extract_json_object("no json here")

    def test_raises_on_unterminated(self):
        with pytest.raises(ValueError, match="Unterminated JSON"):
            _extract_json_object('{"key": "value"')


class TestPlanGenerator:
    @pytest.mark.asyncio
    async def test_generate_returns_plan(self, mock_client):
        gen = PlanGenerator(mock_client)
        plan = await gen.generate(
            "https://example.com/products", "Extract products"
        )
        assert isinstance(plan, ScrapingPlan)
        assert plan.url == "https://example.com/products"
        assert plan.objective == "Extract products"
        assert len(plan.steps) == 2
        assert plan.source == "llm"

    @pytest.mark.asyncio
    async def test_prompt_includes_schema(self, mock_client):
        gen = PlanGenerator(mock_client)
        await gen.generate("https://example.com", "test")
        prompt = mock_client.complete.call_args[0][0]
        assert "properties" in prompt  # JSON schema present
        assert "https://example.com" in prompt
        assert "test" in prompt

    @pytest.mark.asyncio
    async def test_prompt_includes_snapshot(self, mock_client):
        gen = PlanGenerator(mock_client)
        snapshot = PageSnapshot(
            title="My Page",
            text_excerpt="Hello world",
            element_hints="div.main, h1#title",
            links="/about, /contact",
        )
        await gen.generate("https://example.com", "test", snapshot=snapshot)
        prompt = mock_client.complete.call_args[0][0]
        assert "My Page" in prompt
        assert "Hello world" in prompt
        assert "div.main" in prompt

    @pytest.mark.asyncio
    async def test_prompt_includes_hints(self, mock_client):
        gen = PlanGenerator(mock_client)
        hints = {"auth_required": True, "pagination": "infinite_scroll"}
        await gen.generate("https://example.com", "test", hints=hints)
        prompt = mock_client.complete.call_args[0][0]
        assert "auth_required" in prompt
        assert "infinite_scroll" in prompt

    @pytest.mark.asyncio
    async def test_handles_markdown_code_fence(self, mock_client, valid_plan_json):
        mock_client.complete.return_value = f"```json\n{valid_plan_json}\n```"
        gen = PlanGenerator(mock_client)
        plan = await gen.generate(
            "https://example.com/products", "Extract products"
        )
        assert isinstance(plan, ScrapingPlan)
        assert plan.url == "https://example.com/products"

    @pytest.mark.asyncio
    async def test_handles_extra_text_around_json(self, mock_client, valid_plan_json):
        mock_client.complete.return_value = (
            f"Here is the plan:\n{valid_plan_json}\nLet me know if you need changes."
        )
        gen = PlanGenerator(mock_client)
        plan = await gen.generate(
            "https://example.com/products", "Extract products"
        )
        assert isinstance(plan, ScrapingPlan)

    @pytest.mark.asyncio
    async def test_invalid_json_raises(self, mock_client):
        mock_client.complete.return_value = "This is not JSON at all"
        gen = PlanGenerator(mock_client)
        with pytest.raises(ValueError, match="Failed to parse"):
            await gen.generate("https://example.com", "test")

    @pytest.mark.asyncio
    async def test_missing_steps_raises(self, mock_client):
        mock_client.complete.return_value = json.dumps(
            {"url": "https://example.com", "objective": "test"}
        )
        gen = PlanGenerator(mock_client)
        with pytest.raises(ValueError, match="missing required 'steps'"):
            await gen.generate("https://example.com", "test")

    @pytest.mark.asyncio
    async def test_fills_missing_url_and_objective(self, mock_client):
        mock_client.complete.return_value = json.dumps(
            {
                "steps": [
                    {"action": "navigate", "url": "https://example.com"}
                ],
            }
        )
        gen = PlanGenerator(mock_client)
        plan = await gen.generate("https://example.com", "My objective")
        assert plan.url == "https://example.com"
        assert plan.objective == "My objective"

    def test_build_prompt_includes_url_and_objective(self, mock_client):
        gen = PlanGenerator(mock_client)
        prompt = gen._build_prompt(
            "https://example.com",
            "Extract data",
            PageSnapshot(title="Example"),
            None,
        )
        assert "https://example.com" in prompt
        assert "Extract data" in prompt
        assert "Example" in prompt

    def test_build_prompt_with_no_snapshot(self, mock_client):
        gen = PlanGenerator(mock_client)
        prompt = gen._build_prompt("https://example.com", "test", None, None)
        assert "https://example.com" in prompt
        # Empty snapshot fields are present but empty
        assert "Title:" in prompt

    @pytest.mark.asyncio
    async def test_source_is_llm(self, mock_client):
        gen = PlanGenerator(mock_client)
        plan = await gen.generate(
            "https://example.com/products", "Extract products"
        )
        assert plan.source == "llm"
