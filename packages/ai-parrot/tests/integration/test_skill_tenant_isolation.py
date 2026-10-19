"""FEAT-707 — tenant isolation on a singleton agent (TASK-4505)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable

import pytest

from parrot.bots.base import BaseBot
from parrot.bots.middleware import PromptPipeline
from parrot.bots.prompts.builder import PromptBuilder
from parrot.clients.base import AbstractClient
from parrot.skills.tools import SkillFileToolkit
from parrot.models.basic import CompletionUsage, ToolCall
from parrot.models.responses import AIMessage
from parrot.skills.mixin import SkillRegistryMixin
from parrot.skills.tenancy import current_skill_tenant


def _write_skill(path: Path, name: str, description: str, trigger: str, body: str, **metadata: Any) -> None:
    """Write a small deterministic markdown skill fixture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [f"name: {name}", f"description: {description}", "triggers:", f"  - /{trigger}"]
    fields.extend(f"{key}: {value}" for key, value in metadata.items())
    path.write_text("---\n" + "\n".join(fields) + f"\n---\n\n{body}\n")


class _FakeClient(AbstractClient):
    """Offline client that records prompts and optionally synchronizes calls."""

    client_type = "stub"

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("model", "stub")
        super().__init__(**kwargs)
        self.calls: list[dict[str, Any]] = []
        self.ready = asyncio.Event()
        self.call_count = 0
        self.probe: Callable[[], Any] | None = None
        self.block_calls = False
        self.tool_call: ToolCall | None = None

    async def get_client(self) -> "_FakeClient":
        """Return this in-process client."""
        return self

    async def ask(self, prompt: Any, **kwargs: Any) -> AIMessage:
        """Record one request and return a deterministic answer."""
        self._record(prompt, kwargs, method="ask")
        if self.block_calls:
            self.call_count += 1
            if self.call_count == 2:
                self.ready.set()
            await self.ready.wait()
        response = AIMessage(
            input=str(prompt),
            output="ok",
            response="ok",
            model="stub",
            provider="stub",
            usage=CompletionUsage(),
        )
        if self.tool_call is not None:
            response.tool_calls.append(self.tool_call)
        return response

    async def ask_stream(self, prompt: Any, **kwargs: Any):
        """Record a streaming request and execute the optional mid-stream probe."""
        self._record(prompt, kwargs, method="ask_stream")
        if self.probe is not None:
            self.probe()
        yield "ok"

    async def resume(self, session_id: str, user_input: str, state: Any) -> AIMessage:
        """Satisfy the abstract client contract for this test double."""
        return await self.ask(user_input)

    async def invoke(self, prompt: Any, **kwargs: Any) -> AIMessage:
        """Satisfy the abstract client contract for this test double."""
        return await self.ask(prompt, **kwargs)

    def _record(self, prompt: Any, kwargs: dict[str, Any], method: str) -> None:
        system_prompt = kwargs.get("system_prompt", "")
        self.calls.append(
            {
                "tenant": current_skill_tenant(),
                "method": method,
                "prompt": f"{system_prompt}\n{prompt}",
            }
        )


class _TenantBot(SkillRegistryMixin, BaseBot):
    """Real BaseBot ask binding with the feature's mixin enabled."""

    name = "troc_finance"
    enable_skill_registry = False


@pytest.fixture
def agent_tree(tmp_path: Path) -> Path:
    """Create the global, pokemon, and epson skill trees from spec §4."""
    root = tmp_path / "troc_finance"
    _write_skill(root / "skills" / "revenue.md", "revenue", "Global revenue", "revenue", "GLOBAL REVENUE")
    _write_skill(
        root / "skills" / "ebitda.md",
        "ebitda",
        "Global EBITDA",
        "ebitda",
        "GLOBAL EBITDA",
        global_only="true",
    )
    (root / "skills" / "learned").mkdir(parents=True)

    pokemon = root / "tenants" / "pokemon" / "skills"
    _write_skill(pokemon / "revenue" / "SKILL.md", "revenue", "Pokemon revenue", "revenue", "POKEMON REVENUE")
    (pokemon / "revenue" / "accounts.csv").write_text("pokemon-account\n")
    _write_skill(pokemon / "ebitda.md", "ebitda", "Pokemon EBITDA", "ebitda", "POKEMON EBITDA")

    _write_skill(
        root / "tenants" / "epson" / "skills" / "revenue.md",
        "revenue",
        "Epson revenue",
        "revenue",
        "EPSON REVENUE",
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "tenants").mkdir(parents=True, exist_ok=True)
    (root / "tenants" / "evil").symlink_to(outside, target_is_directory=True)
    _write_skill(root / "tenants" / "skills" / "skills" / "bad.md", "bad", "Reserved", "bad", "BAD")
    return tmp_path


@pytest.fixture
async def tenant_bot(agent_tree: Path) -> _TenantBot:
    """Configure one singleton bot and its tenant-aware file registry."""
    client = _FakeClient()
    bot = _TenantBot(
        name="troc_finance",
        llm=client,
        prompt_builder=PromptBuilder.default(),
        injection_detection=False,
        memory_type="memory",
        tenant_based=True,
        enable_tools=False,
    )
    bot._agents_dir = agent_tree
    bot._prompt_pipeline = PromptPipeline()
    bot._llm = client
    await bot._configure_skill_file_registry()
    await bot._configure_prompt_builder()
    bot.fake_client = client
    return bot


async def _ask(bot: _TenantBot, question: str, tenant: str) -> AIMessage:
    """Run the real BaseBot ask path with only offline context providers."""
    return await bot.ask(
        question,
        tenant=tenant,
        use_vector_context=False,
        use_conversation_history=False,
        use_tools=True,
    )


async def test_two_tenants_concurrent_on_singleton(tenant_bot: _TenantBot) -> None:
    """AC-V1/AC-V3: each concurrent ask sees only its own view and trigger."""
    tenant_bot.fake_client.block_calls = True
    await asyncio.gather(_ask(tenant_bot, "list skills", "pokemon"), _ask(tenant_bot, "list skills", "epson"))

    by_tenant = {call["tenant"]: call["prompt"] for call in tenant_bot.fake_client.calls}
    assert "Pokemon revenue" in by_tenant["pokemon"]
    assert "Epson revenue" in by_tenant["epson"]
    assert "Epson revenue" not in by_tenant["pokemon"]
    assert "Pokemon revenue" not in by_tenant["epson"]

    toolkit = SkillFileToolkit(
        tenant_bot._skill_file_registry,
        view_provider=tenant_bot.current_skill_view,
    )
    token = tenant_bot._enter_skill_tenant("pokemon", None)
    try:
        pokemon_listing = await toolkit.list_skill_commands()
    finally:
        tenant_bot._exit_skill_tenant(token)
    assert "revenue" in pokemon_listing.result
    assert "ebitda" in pokemon_listing.result


async def test_trigger_isolation_concurrent(tenant_bot: _TenantBot) -> None:
    """AC-A1: concurrent ``/revenue`` asks render only their tenant body."""
    await asyncio.gather(
        _ask(tenant_bot, "/revenue quarterly", "pokemon"), _ask(tenant_bot, "/revenue quarterly", "epson")
    )
    by_tenant = {call["tenant"]: call["prompt"] for call in tenant_bot.fake_client.calls}
    assert "POKEMON REVENUE" in by_tenant["pokemon"]
    assert "EPSON REVENUE" in by_tenant["epson"]
    assert "EPSON REVENUE" not in by_tenant["pokemon"]
    assert "POKEMON REVENUE" not in by_tenant["epson"]


async def test_fixed_tenant_instance(agent_tree: Path) -> None:
    """A class-level ``tenant_id='pokemon'`` supplies the default view."""

    class FixedTenantBot(_TenantBot):
        tenant_id = "pokemon"

    bot = FixedTenantBot(
        name="troc_finance",
        llm=_FakeClient(),
        prompt_builder=PromptBuilder.default(),
        injection_detection=False,
        memory_type="memory",
        tenant_based=True,
        enable_tools=False,
    )
    bot._agents_dir = agent_tree
    bot._prompt_pipeline = PromptPipeline()
    bot._llm = bot._llm_raw
    await bot._configure_skill_file_registry()
    assert bot.current_skill_view().get_by_name("revenue").template_body == "POKEMON REVENUE"


async def test_global_only_end_to_end(tenant_bot: _TenantBot, caplog: pytest.LogCaptureFixture) -> None:
    """AC-V4: a tenant cannot shadow a global-only skill."""
    view = tenant_bot.current_skill_view("pokemon")
    assert view.get_by_name("ebitda").template_body == "GLOBAL EBITDA"
    assert "ebitda" in view.report.dropped
    assert any("global_only" in record.getMessage() for record in caplog.records) or view.report.dropped == ("ebitda",)


async def test_read_skill_asset_tenant_composite(tenant_bot: _TenantBot) -> None:
    """AC-V1: the composite asset is read from the active tenant."""
    toolkit = SkillFileToolkit(tenant_bot._skill_file_registry, view_provider=tenant_bot.current_skill_view)
    token = tenant_bot._enter_skill_tenant("pokemon", None)
    try:
        result = await toolkit.read_skill_asset("revenue", "accounts.csv")
    finally:
        tenant_bot._exit_skill_tenant(token)
    assert result.result == "pokemon-account\n"
    assert "epson" not in result.result.lower()


async def test_ask_stream_mid_stream_tool_sees_tenant(tenant_bot: _TenantBot) -> None:
    """AC-V3: a callback invoked by the streaming client sees the bound tenant."""
    seen: list[str | None] = []
    tenant_bot.fake_client.probe = lambda: seen.append(current_skill_tenant())
    chunks = [
        chunk
        async for chunk in tenant_bot.ask_stream(
            "stream", tenant="epson", use_vector_context=False, use_conversation_history=False, use_tools=False
        )
    ]
    assert chunks[0] == "ok"
    assert seen == ["epson"]
    assert current_skill_tenant() is None
