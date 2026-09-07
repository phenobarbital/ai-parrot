"""The two Community Manager nodes that call a model.

Nothing here touches the network. A fake agent returns whatever the test asks
for — a parsed model, raw text, an exception, a call that never finishes — and
the assertions are about what the node does with each.

Three properties matter more than the rest, and each corresponds to a way this
feature was found to be broken before it was written:

* **No model failure reaches the guest.** Every path — no agent, a raised
  exception, a timeout, a response that did not parse — ends in a reply, not
  in an unanswered review.
* **The repair loop converges.** A rejected draft comes back with its reasons
  in the prompt and a *different* draft comes out. Before T15 the node ignored
  ``guardrail.reasons`` entirely, so a second round reproduced the first one
  verbatim and the loop could only ever end in ``blocked``.
* **No cross-review contamination.** The agents are per tenant and shared
  across every review that tenant receives, so a call that used conversation
  history would make one review's verdict depend on the ones before it.
"""
from __future__ import annotations

import asyncio
import logging

import pytest

from parrot_saas.flows.community_manager import prompts
from parrot_saas.flows.community_manager.models import (
    GuardrailStatus,
    GuardrailVerdict,
    ReviewIntake,
    ReviewTriage,
    Sentiment,
    Severity,
    TriageAction,
)
from parrot_saas.flows.community_manager.nodes.reply import (
    ReplyDraftNode,
    TriageNode,
)
from parrot_saas.tenancy.context import TenantContext


def _review(**overrides) -> ReviewIntake:
    """Build a normalised review."""
    payload = {
        "review_id": "11111111-1111-1111-1111-111111111111",
        "tenant_id": "bar-pepe",
        "source": "mock",
        "external_id": "ext-1",
        "rating": 1,
        "text": "The food arrived cold and we waited forty minutes.",
    }
    payload.update(overrides)
    return ReviewIntake(**payload)


class _Usage:
    """Stand-in for ``AIMessage.usage``."""

    prompt_tokens = 120
    completion_tokens = 40
    total_tokens = 160


class _Message:
    """Stand-in for ``AIMessage``.

    ``output`` mirrors ``structured_output or content``, which is what the real
    model does — and why the nodes read ``output`` for text and
    ``structured_output`` for a parsed model.
    """

    def __init__(self, output, *, structured=None, usage=_Usage()) -> None:
        self.output = output
        self.structured_output = structured if structured is not None else output
        self.usage = usage
        self.model = "test-model"
        self.provider = "test-provider"


class _Agent:
    """Fake agent recording every call it receives.

    Args:
        responses: Returned in order; the last one repeats once exhausted.
            Callables are invoked with the task, so a test can make the reply
            depend on the prompt it was given.
        raises: Raised instead of answering.
        delay: Seconds to sleep before answering, for the timeout test.
    """

    def __init__(self, *responses, raises=None, delay: float = 0.0) -> None:
        self.responses = list(responses)
        self.raises = raises
        self.delay = delay
        self.calls: list[dict] = []

    async def invoke(self, task: str, **kwargs):
        self.calls.append({"task": task, **kwargs})
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.raises is not None:
            raise self.raises
        response = (
            self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        )
        return response(task) if callable(response) else response


# ---------------------------------------------------------------------------
# Triage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_triage_uses_structured_output():
    """A parsed verdict is used as-is, and its usage is recorded."""
    verdict = ReviewTriage(
        action=TriageAction.REPLY,
        sentiment=Sentiment.NEGATIVE,
        severity=Severity.HIGH,
        language="en",
        topics=["wait time", "food temperature"],
        rationale="two specific complaints",
    )
    agent = _Agent(_Message("ignored", structured=verdict))
    node = TriageNode(node_id="triage", agent=agent)
    shared = {"review": _review()}

    result = await node.execute(shared, {})

    assert result.action == TriageAction.REPLY.value
    assert result.topics == ["wait time", "food temperature"]
    assert shared["triage"] is result
    assert shared["usage"]["triage"]["total_tokens"] == 160
    assert shared["usage"]["triage"]["model"] == "test-model"


@pytest.mark.asyncio
async def test_triage_call_is_isolated_from_other_reviews():
    """History is off and the session is the review's own.

    The agents are built once per tenant and shared across every review it
    receives. With history on, the same review text would be classified
    differently depending on what arrived before it.
    """
    review = _review()
    agent = _Agent(_Message("x", structured=ReviewTriage()))
    node = TriageNode(node_id="triage", agent=agent)

    await node.execute({"review": review}, {})

    call = agent.calls[0]
    assert call["use_conversation_history"] is False
    assert call["session_id"] == review.review_id
    assert call["response_model"] is ReviewTriage


@pytest.mark.asyncio
async def test_triage_falls_back_when_the_model_returns_raw_text(caplog):
    """A failed parse arrives as a string, not as an exception.

    The client swallows the parse error and hands back the raw text, so
    ``structured_output`` can be a ``str``. Trusting it would put a string
    where the flow expects a verdict and break the run several nodes later.
    """
    agent = _Agent(_Message("Sure! Here is the classification: negative."))
    node = TriageNode(node_id="triage", agent=agent)

    with caplog.at_level(logging.WARNING):
        result = await node.execute({"review": _review(rating=1)}, {})

    assert isinstance(result, ReviewTriage)
    assert result.action == TriageAction.REPLY.value
    assert result.rationale == "rating-based fallback triage"
    assert "rather than a verdict" in caplog.text


@pytest.mark.asyncio
async def test_triage_falls_back_when_the_agent_raises():
    """A provider outage still produces a verdict."""
    agent = _Agent(raises=RuntimeError("401 unauthorized"))
    node = TriageNode(node_id="triage", agent=agent)

    result = await node.execute({"review": _review(rating=5)}, {})

    assert result.sentiment == Sentiment.POSITIVE.value
    assert result.rationale == "rating-based fallback triage"


@pytest.mark.asyncio
async def test_triage_falls_back_when_the_call_exceeds_its_timeout():
    """The scheduler enforces no timeout, so the node must."""
    agent = _Agent(_Message("x", structured=ReviewTriage()), delay=0.5)
    node = TriageNode(node_id="triage", agent=agent, timeout=0.05)

    result = await node.execute({"review": _review()}, {})

    assert result.rationale == "rating-based fallback triage"


@pytest.mark.asyncio
async def test_triage_without_an_agent_uses_the_heuristic():
    """A tenant with no Google key still gets its reviews triaged."""
    node = TriageNode(node_id="triage")
    shared = {"review": _review(rating=1)}

    result = await node.execute(shared, {})

    assert result.action == TriageAction.REPLY.value
    assert result.severity == Severity.HIGH.value
    assert "usage" not in shared


# ---------------------------------------------------------------------------
# Reply drafting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reply_draft_uses_the_model_and_records_usage():
    """The model's text becomes the draft."""
    text = (
        "We are genuinely sorry about the wait and the cold food — that is "
        "not the evening we want anyone to have. We have raised it with the "
        "kitchen team who were on that night."
    )
    agent = _Agent(_Message(text, structured=text))
    node = ReplyDraftNode(node_id="reply_draft", agent=agent)
    shared = {"review": _review()}

    draft = await node.execute(shared, {})

    assert draft.text == text
    assert draft.attempt == 1
    assert draft.tone == "apologetic"
    assert shared["usage"]["reply_draft"]["prompt_tokens"] == 120
    assert agent.calls[0]["use_conversation_history"] is False


@pytest.mark.asyncio
async def test_reply_draft_falls_back_on_failure():
    """A failed call still answers the guest."""
    agent = _Agent(raises=TimeoutError("boom"))
    node = ReplyDraftNode(node_id="reply_draft", agent=agent)

    draft = await node.execute({"review": _review()}, {})

    assert "sorry" in draft.text.lower()


@pytest.mark.asyncio
async def test_repair_round_carries_the_reasons_and_changes_the_draft():
    """The loop converges rather than resubmitting the same text.

    This is the regression that T15 exists for: the node used to build its
    prompt from the review alone, so a second round produced an identical
    draft and the guardrail could only block it.
    """
    first = "Sorry about that, here is a discount for you."
    second = (
        "We are sorry about the wait and the cold food, and we have raised "
        "it with the team who were on that evening."
    )
    agent = _Agent(
        _Message(first, structured=first), _Message(second, structured=second)
    )
    node = ReplyDraftNode(node_id="reply_draft", agent=agent)
    shared = {"review": _review()}

    draft_one = await node.execute(shared, {})
    shared["guardrail"] = GuardrailVerdict(
        status=GuardrailStatus.REVISE,
        attempt=draft_one.attempt,
        reasons=["contains banned phrase: 'discount'"],
    )
    draft_two = await node.execute(shared, {})

    assert draft_two.attempt == 2
    assert draft_two.text != draft_one.text

    repair_prompt = agent.calls[1]["task"]
    assert first in repair_prompt
    assert "contains banned phrase: 'discount'" in repair_prompt
    assert "Do not repeat the previous draft." in repair_prompt


@pytest.mark.asyncio
async def test_repair_round_without_an_agent_still_changes_the_text():
    """Even the template must differ, or the loop cannot terminate early."""
    node = ReplyDraftNode(node_id="reply_draft")
    shared = {"review": _review()}

    first = await node.execute(shared, {})
    shared["guardrail"] = GuardrailVerdict(
        status=GuardrailStatus.REVISE,
        attempt=first.attempt,
        reasons=["reply is shorter than 40 characters"],
    )
    second = await node.execute(shared, {})

    assert second.text != first.text
    assert len(second.text) > len(first.text)


@pytest.mark.asyncio
async def test_triage_verdict_reaches_the_drafting_prompt():
    """What triage concluded is context the drafter should have."""
    agent = _Agent(_Message("ok", structured="ok"))
    node = ReplyDraftNode(node_id="reply_draft", agent=agent)
    shared = {
        "review": _review(),
        "triage": ReviewTriage(
            action=TriageAction.REPLY,
            sentiment=Sentiment.NEGATIVE,
            severity=Severity.CRITICAL,
            topics=["food safety"],
        ),
    }

    await node.execute(shared, {})

    task = agent.calls[0]["task"]
    assert "negative" in task
    assert "critical" in task
    assert "food safety" in task


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


def test_system_prompt_carries_the_tenant_voice_and_name():
    """Brand voice is a tenant setting, applied at agent construction."""
    tenant = TenantContext(
        tenant_id="bar-pepe",
        name="Bar Pepe",
        mode="shared",
        locale="es",
        settings={"brand_voice": "cercano, directo y con algo de guasa"},
    )

    system = prompts.build_reply_prompt(tenant)

    assert "Bar Pepe" in system
    assert "cercano, directo y con algo de guasa" in system
    assert "Write in es" in system
    assert "Bar Pepe" in prompts.build_triage_prompt(tenant)


def test_reply_prompt_states_the_guardrail_prohibitions():
    """The guardrail is the net, not the instruction.

    A model never told about these rules writes a draft that violates them,
    gets rejected, and spends a second call rediscovering a constraint it
    could have been given for free.
    """
    tenant = TenantContext(tenant_id="venue", name="The Venue", mode="shared")

    system = prompts.build_reply_prompt(tenant)

    lowered = system.lower()
    for forbidden in (
        "discount",
        "coupon",
        "compensation",
        "refund",
        "being an ai",
        "never invent facts",
    ):
        assert forbidden in lowered


def test_reply_prompt_falls_back_to_a_default_voice():
    """A tenant that never set a voice still gets a usable one."""
    tenant = TenantContext(tenant_id="venue", name="The Venue", mode="shared")

    assert prompts.DEFAULT_BRAND_VOICE in prompts.build_reply_prompt(tenant)


def test_first_round_prompt_has_no_repair_scaffolding():
    """The repair wording appears only on a repair round."""
    task = prompts.render_reply_task(_review())

    assert "previous draft" not in task.lower()
