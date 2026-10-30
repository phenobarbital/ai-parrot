"""Tests for the LLM suggestion provider (FEAT-752, TASK-4799)."""

from parrot.bots.suggestions import SuggestionContext
from parrot.bots.suggestions.llm import LLMSuggestionProvider
from parrot.models import AIMessage, Suggestion, SuggestionBatch
from parrot.models.basic import CompletionUsage
from parrot.models.outputs import OutputMode
from parrot.models.responses import InvokeResult


class FakeClient:
    def __init__(self, output=None, exc=None):
        self.calls, self._output, self._exc = [], output, exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def invoke(self, prompt, **kw):
        self.calls.append((prompt, kw))
        if self._exc:
            raise self._exc
        return InvokeResult(
            output=self._output, output_type=SuggestionBatch, model="fake-lite", usage=CompletionUsage()
        )

    async def ask(self, *a, **k):
        raise AssertionError("ask must not be called")


class FakeBot:
    def __init__(self, client):
        self._client = client

    def get_client(self):
        return self._client


def _ctx(bot):
    msg = AIMessage(input="q", output="answer", model="m", provider="p", usage=CompletionUsage())
    return SuggestionContext(question="q", response=msg, output_mode=OutputMode.DEFAULT, bot=bot)


async def test_llm_provider_uses_invoke_not_ask():
    batch = SuggestionBatch(suggestions=[Suggestion(label="Why?", prompt="Why did it change?")])
    client = FakeClient(output=batch)
    chips = await LLMSuggestionProvider(FakeBot(client)).suggest(_ctx(FakeBot(client)))
    assert len(client.calls) == 1 and client.calls[0][1]["output_type"] is SuggestionBatch
    assert chips[0].source == "llm"
    kwargs = client.calls[0][1]
    assert kwargs["max_tokens"] == 256 and kwargs["temperature"] == 0.3
    assert "Question: q" in client.calls[0][0] and "answer" in client.calls[0][0]


async def test_llm_provider_model_override():
    batch = SuggestionBatch(suggestions=[Suggestion(label="Why?", prompt="Why?")])

    default_client = FakeClient(output=batch)
    await LLMSuggestionProvider(FakeBot(default_client)).suggest(_ctx(None))
    assert default_client.calls[0][1]["model"] is None

    cheap_client = FakeClient(output=batch)
    await LLMSuggestionProvider(FakeBot(cheap_client), model="cheap-model").suggest(_ctx(None))
    assert cheap_client.calls[0][1]["model"] == "cheap-model"


async def test_llm_provider_cost_recorded_and_capped():
    batch = SuggestionBatch(
        suggestions=[
            Suggestion(label="A", prompt="a", kind="presentation", output_mode="card"),
            Suggestion(label="B", prompt="b"),
            Suggestion(label="C", prompt="c"),
            Suggestion(label="D", prompt="d"),
        ]
    )
    provider = LLMSuggestionProvider(FakeBot(FakeClient(output=batch)), max_items=2)
    chips = await provider.suggest(_ctx(None))
    assert [c.label for c in chips] == ["A", "B"]
    for chip in chips:
        assert chip.source == "llm" and chip.kind == "followup"
        assert chip.output_mode is None and chip.action is None
    cost = provider.last_cost
    assert cost is not None
    assert cost["model"] == "fake-lite"
    assert isinstance(cost["usage"], dict)
    assert cost["elapsed_ms"] >= 0


async def test_llm_provider_accepts_dict_output():
    client = FakeClient(output={"suggestions": [{"label": "X", "prompt": "x"}]})
    chips = await LLMSuggestionProvider(FakeBot(client)).suggest(_ctx(None))
    assert [c.label for c in chips] == ["X"]


async def test_llm_provider_malformed_output_is_silent():
    provider = LLMSuggestionProvider(FakeBot(FakeClient(output={"suggestions": "nope"})))
    assert await provider.suggest(_ctx(None)) == []
    assert provider.last_cost is None


async def test_llm_provider_failure_is_silent():
    provider = LLMSuggestionProvider(FakeBot(FakeClient(exc=RuntimeError("boom"))))
    assert await provider.suggest(_ctx(None)) == []
    assert provider.last_cost is None


async def test_llm_provider_cost_reset_between_calls():
    good = FakeClient(output=SuggestionBatch(suggestions=[Suggestion(label="A", prompt="a")]))
    bot = FakeBot(good)
    provider = LLMSuggestionProvider(bot)
    await provider.suggest(_ctx(None))
    assert provider.last_cost is not None
    bot._client = FakeClient(exc=RuntimeError("boom"))
    await provider.suggest(_ctx(None))
    assert provider.last_cost is None


class _SlowEchoClient:
    """invoke() reports a question-dependent model after a fixed delay."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def invoke(self, prompt, **kw):
        import asyncio

        tag = "A" if "Question: qA" in prompt else "B"
        # Equal delays: both calls complete in the same loop iteration, so with instance-level cost state the second
        # writer would be visible to the first turn's engine read.
        await asyncio.sleep(0.02)
        batch = SuggestionBatch(suggestions=[Suggestion(label=f"chip {tag}", prompt=f"p {tag}")])
        return InvokeResult(output=batch, output_type=SuggestionBatch, model=f"model-{tag}", usage=CompletionUsage())


async def test_concurrent_turns_on_a_shared_engine_keep_their_own_cost():
    import asyncio

    from parrot.bots.suggestions import SuggestionEngine

    engine = SuggestionEngine(timeout_s=2.0)
    engine.register(LLMSuggestionProvider(FakeBot(_SlowEchoClient())))  # one provider shared by every request

    def ctx_for(question):
        msg = AIMessage(input=question, output="answer", model="m", provider="p", usage=CompletionUsage())
        return SuggestionContext(question=question, response=msg, output_mode=OutputMode.DEFAULT, bot=None)

    (chips_a, meta_a), (chips_b, meta_b) = await asyncio.gather(
        engine.collect(ctx_for("qA"), lanes=frozenset({"llm"})),
        engine.collect(ctx_for("qB"), lanes=frozenset({"llm"})),
    )

    assert [c.label for c in chips_a] == ["chip A"] and meta_a["llm"]["model"] == "model-A"
    assert [c.label for c in chips_b] == ["chip B"] and meta_b["llm"]["model"] == "model-B"


async def test_failed_call_leaves_no_cost_in_the_context():
    from parrot.bots.suggestions import SuggestionEngine

    engine = SuggestionEngine(timeout_s=2.0)
    engine.register(LLMSuggestionProvider(FakeBot(FakeClient(exc=RuntimeError("boom")))))
    msg = AIMessage(input="q", output="a", model="m", provider="p", usage=CompletionUsage())
    ctx = SuggestionContext(question="q", response=msg, output_mode=OutputMode.DEFAULT, bot=None)
    chips, meta = await engine.collect(ctx, lanes=frozenset({"llm"}))
    assert chips == [] and meta["llm"] is None and "llm_cost" not in ctx.scratch
