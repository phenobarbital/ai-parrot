"""Unit tests for JevClient (TypeSafe AI System One) and its wire models.

Covers the question primitives and their serialization, response parsing
(including forward-compat for unknown answer types), the Pydantic
output_type <-> questions mapping, client construction and env-var
fallback, LLMFactory registration, and the aiohttp transport against a
local ``aiohttp.web`` stub (auth header, body shape, retries, error
mapping). No live TypeSafe API calls are made.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Literal, Optional
from unittest.mock import MagicMock, patch

import pytest
from aiohttp import web
from pydantic import BaseModel, Field

from parrot.clients.factory import SUPPORTED_CLIENTS, LLMFactory
from parrot.clients.jev import (
    Choice,
    JevAuthenticationError,
    JevClient,
    JevConfigurationError,
    JevModel,
    MODEL_ALIASES,
    JevRateLimitError,
    JevSchemaError,
    JevServerError,
    Noul,
    NoulCriteria,
    Score,
    SystemOneResponse,
    answers_to_type,
    questions_from_type,
)
from parrot.clients.jev import client as jev_client_mod
from parrot.clients.jev.exceptions import api_error, parse_retry_after
from parrot.clients.jev.models import MAX_CHOICE_OPTIONS, normalize_questions, parse_question
from parrot.exceptions import InvokeError
from parrot.memory.render import HistoryMessage
from parrot.models import AIMessage
from parrot.models.responses import InvokeResult

# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #

SAMPLE_ANSWERS = {
    "category": {
        "type": "choice",
        "choice": "billing",
        "confidence": 0.91,
        "probabilities": {"billing": 0.91, "technical": 0.06, "other": 0.03},
    },
    "urgent": {"type": "noul", "noul": 0.82},
    "severity": {
        "type": "score",
        "score": 1.6,
        "confidence": 0.7,
        "legend": {"0": "Cosmetic", "1": "Degraded", "2": "Blocked"},
        "probabilities": {"0": 0.1, "1": 0.2, "2": 0.7},
    },
}


def _sample_response(**overrides):
    body = {"model": "jev-latest", "usage": {"input_tokens": 42, "output_tokens": None}, "answers": SAMPLE_ANSWERS}
    body.update(overrides)
    return body


class Category(str, Enum):
    BILLING = "billing"
    TECHNICAL = "technical"
    OTHER = "other"


class Triage(BaseModel):
    category: Literal["billing", "technical", "other"] = Field(description="What is this ticket about?")
    urgent: bool = Field(description="Does the customer need an answer today?")
    severity: int = Field(
        description="How badly is the customer affected?",
        json_schema_extra={"criteria": ["Cosmetic", "Degraded", "Blocked"]},
    )


@pytest.fixture
def stub_api(aiohttp_server):
    """Local stand-in for api.typesafe.ai recording every request it receives."""

    async def _make(handler=None, *, models_handler=None):
        calls: list[dict] = []

        async def default_handler(request: web.Request) -> web.Response:
            return web.json_response(_sample_response(), headers={"x-typesafe-request-id": "req-123"})

        async def systemone(request: web.Request) -> web.Response:
            body = await request.json()
            calls.append({"headers": dict(request.headers), "body": body})
            return await (handler or default_handler)(request)

        async def models(request: web.Request) -> web.Response:
            calls.append({"headers": dict(request.headers), "body": None})
            if models_handler:
                return await models_handler(request)
            return web.json_response(
                {"models": [{"name": "jev-latest", "description": "Jev", "release_date": "2026-09-16"}]}
            )

        app = web.Application()
        app.router.add_post("/v1/systemone", systemone)
        app.router.add_get("/v1/models", models)
        server = await aiohttp_server(app)
        return server, calls

    return _make


def _client(server, **kwargs) -> JevClient:
    kwargs.setdefault("api_key", "test-key")
    kwargs.setdefault("max_retries", 0)
    return JevClient(base_url=str(server.make_url("")), **kwargs)


# --------------------------------------------------------------------------- #
# Question primitives                                                         #
# --------------------------------------------------------------------------- #


def test_choice_to_wire_keeps_undescribed_labels_and_omits_instructions():
    wire = Choice(criteria={"billing": None, "technical": "Bugs and outages"}).to_wire()
    assert wire == {"type": "choice", "criteria": {"billing": None, "technical": "Bugs and outages"}}


def test_choice_rejects_empty_and_oversized_criteria():
    with pytest.raises(ValueError):
        Choice(criteria={})
    with pytest.raises(ValueError):
        Choice(criteria={str(i): None for i in range(MAX_CHOICE_OPTIONS + 1)})


def test_score_requires_levels_and_serializes_in_order():
    with pytest.raises(ValueError):
        Score(criteria=[])
    assert Score(instructions="How bad?", criteria=["lo", {"level": "hi"}]).to_wire() == {
        "type": "score",
        "instructions": "How bad?",
        "criteria": ["lo", {"level": "hi"}],
    }


def test_noul_to_wire_drops_absent_criteria_and_empty_outcomes():
    assert Noul(instructions="Refund?").to_wire() == {"type": "noul", "instructions": "Refund?"}
    assert Noul(criteria=NoulCriteria(true="asks for money back")).to_wire() == {
        "type": "noul",
        "criteria": {"true": "asks for money back"},
    }


def test_questions_pass_extra_fields_through():
    wire = Noul(instructions="x", future_flag=True).to_wire()  # type: ignore[call-arg]
    assert wire["future_flag"] is True


def test_normalize_questions_accepts_dicts_and_objects():
    wire = normalize_questions({"a": {"type": "noul", "instructions": "yes?"}, "b": Choice(criteria={"x": None})})
    assert wire == {"a": {"type": "noul", "instructions": "yes?"}, "b": {"type": "choice", "criteria": {"x": None}}}


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"type": "choice"},
        {"type": "score", "criteria": []},
        {"type": "mystery"},
        "not a question",
    ],
)
def test_parse_question_rejects_invalid_input(bad):
    with pytest.raises(JevConfigurationError):
        parse_question("q", bad)


def test_normalize_questions_requires_at_least_one():
    with pytest.raises(JevConfigurationError):
        normalize_questions({})


# --------------------------------------------------------------------------- #
# Response parsing                                                            #
# --------------------------------------------------------------------------- #


def test_system_one_response_parses_and_groups_answers():
    response = SystemOneResponse.model_validate(_sample_response())
    assert response.choices["category"].choice == "billing"
    assert response.nouls["urgent"].is_yes()
    assert not response.nouls["urgent"].is_yes(threshold=0.9)
    score = response.scores["severity"]
    assert score.legend == {0: "Cosmetic", 1: "Degraded", 2: "Blocked"}
    assert score.probabilities[2] == 0.7
    assert score.level == 2
    assert response.values() == {"category": "billing", "urgent": 0.82, "severity": 1.6}
    assert response["urgent"].noul == 0.82
    assert response.usage.input_tokens == 42


#: Verbatim request questions / response body from the TypeSafe quickstart
#: (https://docs.typesafe.ai/quickstart). Note the score answer carries no
#: ``probabilities`` key.
DOCS_STATE = (
    "Hi, I've been trying to connect my Stripe account for 3 days and it keeps failing. "
    "I'm losing sales. Please help ASAP."
)
DOCS_QUESTIONS = {
    "department": {
        "type": "choice",
        "instructions": "Which team should handle this",
        "criteria": {
            "billing": "Payment or subscription issues",
            "technical": "Bugs or integration problems",
            "sales": "Pricing or account questions",
        },
    },
    "frustration": {
        "type": "score",
        "instructions": "How frustrated the customer appears",
        "criteria": ["Calm, just stating facts", "Frustrated but civil", "Very angry, strong language"],
    },
    "is_urgent": {"type": "noul", "instructions": "The message conveys urgency or time-sensitivity"},
}
DOCS_RESPONSE = {
    "model": "jev-latest",
    "answers": {
        "department": {
            "type": "choice",
            "choice": "billing",
            "probabilities": {"billing": 0.84, "technical": 0.159, "sales": 0.001},
            "confidence": 0.596,
        },
        "frustration": {
            "type": "score",
            "score": 1.035,
            "legend": {
                "0": "Calm, just stating facts",
                "1": "Frustrated but civil",
                "2": "Very angry, strong language",
            },
            "confidence": 0.842,
        },
        "is_urgent": {"type": "noul", "noul": 0.999},
    },
    "usage": {"input_tokens": 312, "output_tokens": 48},
}


def test_quickstart_questions_serialize_exactly_as_documented():
    wire = normalize_questions(
        {
            "department": Choice(
                instructions="Which team should handle this",
                criteria={
                    "billing": "Payment or subscription issues",
                    "technical": "Bugs or integration problems",
                    "sales": "Pricing or account questions",
                },
            ),
            "frustration": Score(
                instructions="How frustrated the customer appears",
                criteria=["Calm, just stating facts", "Frustrated but civil", "Very angry, strong language"],
            ),
            "is_urgent": Noul(instructions="The message conveys urgency or time-sensitivity"),
        }
    )
    assert wire == DOCS_QUESTIONS


def test_quickstart_response_parses_including_score_without_probabilities():
    response = SystemOneResponse.model_validate(DOCS_RESPONSE)
    assert response.answers["department"].choice == "billing"
    assert response.answers["frustration"].score == 1.035
    assert response.answers["frustration"].probabilities == {}
    assert response.answers["frustration"].legend[1] == "Frustrated but civil"
    assert response.answers["is_urgent"].noul == 0.999
    assert response.usage.input_tokens == 312 and response.usage.output_tokens == 48


def test_model_enum_and_aliases_follow_the_models_page():
    assert JevModel.JEV_LATEST.value == "jev-latest"
    assert JevModel.JEV_PREVIEW.value == "jev-preview"
    assert JevModel.JEV_1_13.value == "jev-1.13.0"
    assert MODEL_ALIASES == {"jev-latest": "jev-1.13.0", "jev-preview": "jev-1.13.0"}
    assert JevClient(api_key="k", model=JevModel.JEV_1_13).model == "jev-1.13.0"


def test_system_one_response_skips_unknown_answer_types():
    body = _sample_response(answers={**SAMPLE_ANSWERS, "novel": {"type": "future", "payload": 1}})
    response = SystemOneResponse.model_validate(body)
    assert set(response.answers) == {"category", "urgent", "severity"}


# --------------------------------------------------------------------------- #
# Pydantic output_type mapping                                                #
# --------------------------------------------------------------------------- #


def test_questions_from_type_derives_each_primitive():
    questions = questions_from_type(Triage)
    assert isinstance(questions["category"], Choice)
    assert questions["category"].instructions == "What is this ticket about?"
    assert list(questions["category"].criteria) == ["billing", "technical", "other"]
    assert isinstance(questions["urgent"], Noul)
    assert isinstance(questions["severity"], Score)
    assert questions["severity"].criteria == ["Cosmetic", "Degraded", "Blocked"]


def test_questions_from_type_supports_enum_optional_descriptions_and_overrides():
    class Model(BaseModel):
        category: Optional[Category] = Field(
            default=None,
            description="Topic",
            json_schema_extra={"criteria": {"billing": "Money", "technical": "Bugs"}},
        )
        refund: bool = Field(json_schema_extra={"criteria": {"true": "wants money back", "false": "does not"}})
        custom: float = Field(json_schema_extra={"question": {"type": "score", "criteria": ["a", "b"]}})

    questions = questions_from_type(Model)
    assert questions["category"].criteria == {"billing": "Money", "technical": "Bugs", "other": None}
    assert questions["refund"].instructions == "refund"
    assert questions["refund"].criteria.true == "wants money back"
    assert questions["custom"] == Score(criteria=["a", "b"])


def test_questions_from_type_rejects_unmappable_fields():
    class NoLevels(BaseModel):
        rating: int

    class FreeText(BaseModel):
        summary: str

    with pytest.raises(JevSchemaError, match="score levels"):
        questions_from_type(NoLevels)
    with pytest.raises(JevSchemaError, match="no System One equivalent"):
        questions_from_type(FreeText)
    with pytest.raises(JevSchemaError):
        questions_from_type(dict)


def test_answers_to_type_round_trips_into_model():
    response = SystemOneResponse.model_validate(_sample_response())
    triage = answers_to_type(response, Triage)
    assert triage == Triage(category="billing", urgent=True, severity=2)
    assert answers_to_type(response, Triage, noul_threshold=0.9).urgent is False


def test_answers_to_type_handles_missing_and_enum_fields():
    class Model(BaseModel):
        category: Category
        maybe: Optional[bool] = None

    response = SystemOneResponse.model_validate(_sample_response())
    parsed = answers_to_type(response, Model)
    assert parsed.category is Category.BILLING
    assert parsed.maybe is None

    class Strict(BaseModel):
        missing: bool

    with pytest.raises(JevSchemaError, match="no answer"):
        answers_to_type(response, Strict)


# --------------------------------------------------------------------------- #
# Construction & registration                                                 #
# --------------------------------------------------------------------------- #


def test_init_defaults_and_overrides():
    client = JevClient(api_key="k")
    assert client.api_key == "k"
    assert client.base_url == "https://api.typesafe.ai"
    assert client.model == JevModel.JEV_LATEST.value
    assert client.timeout == 10.0
    assert client.max_retries == 2
    assert client.client_type == "jev"

    client = JevClient(
        api_key="k", base_url="https://proxy.example/", model=JevModel.JEV_LATEST, timeout=3, max_retries=5
    )
    assert client.base_url == "https://proxy.example"
    assert client.timeout == 3.0
    assert client.max_retries == 5


def test_init_falls_back_to_environment():
    env = {
        "TYPESAFE_API_KEY": "env-key",
        "TYPESAFE_BASE_URL": "https://env.example",
        "TYPESAFE_DEFAULT_MODEL": "jev-next",
    }
    fake_config = MagicMock()
    fake_config.get.side_effect = lambda key, default=None: env.get(key, default)
    with patch.object(jev_client_mod, "config", fake_config):
        client = JevClient()
    assert client.api_key == "env-key"
    assert client.base_url == "https://env.example"
    assert client.model == "jev-next"


def _resolve(entry):
    """Resolve a SUPPORTED_CLIENTS value the way LLMFactory.create() does.

    FEAT-523: providers register via `parrot.clients` entry points, so the
    registered value is the entry point's zero-arg loader, not the class.
    """
    if callable(entry) and not isinstance(entry, type):
        return entry()
    return entry


def test_factory_registration():
    assert _resolve(SUPPORTED_CLIENTS["jev"]) is JevClient
    assert _resolve(SUPPORTED_CLIENTS["typesafe"]) is JevClient
    client = LLMFactory.create("jev:jev-latest", api_key="k")
    assert isinstance(client, JevClient)
    assert client.model == "jev-latest"
    assert LLMFactory.list_models("jev")["active"] == ["jev-latest", "jev-preview", "jev-1.13.0"]


def test_session_headers_and_retry_helpers():
    client = JevClient(api_key="secret")
    headers = client._session_headers()
    assert headers["Authorization"] == "Bearer secret"
    assert headers["User-Agent"].startswith("ai-parrot-client-jev/")

    assert parse_retry_after({"retry-after-ms": "250"}) == 0.25
    assert parse_retry_after({"retry-after": "2"}) == 2.0
    assert parse_retry_after({}) is None

    err = api_error(429, {"error": {"message": "slow down"}}, {"retry-after-ms": "100", "x-typesafe-request-id": "r1"})
    assert isinstance(err, JevRateLimitError)
    assert err.retry_after == 0.1
    assert err.request_id == "r1"
    assert "slow down" in str(err)
    assert isinstance(api_error(401, None, {}), JevAuthenticationError)
    assert isinstance(api_error(503, "down", {}), JevServerError)
    detail = api_error(422, {"detail": [{"loc": ["body", "questions"], "msg": "field required"}]}, {})
    assert "questions: field required" in str(detail)

    state = MagicMock()
    state.outcome.exception.return_value = err
    state.attempt_number = 1
    assert JevClient._retry_wait(state) == 0.1
    state.outcome.exception.return_value = api_error(500, None, {})
    assert 0 < JevClient._retry_wait(state) <= 0.5
    assert JevClient._is_retryable(api_error(500, None, {}))
    assert not JevClient._is_retryable(api_error(400, None, {}))


# --------------------------------------------------------------------------- #
# Transport                                                                   #
# --------------------------------------------------------------------------- #


async def test_ask_posts_state_and_questions_and_builds_message(stub_api):
    server, calls = await stub_api()
    client = _client(server)
    try:
        message = await client.ask(
            "I was charged twice. Please fix this ASAP.",
            questions={
                "category": Choice(
                    instructions="What is this ticket about?",
                    criteria={"billing": None, "technical": None, "other": None},
                ),
                "urgent": {"type": "noul", "instructions": "Needs an answer today?"},
                "severity": Score(instructions="How bad?", criteria=["Cosmetic", "Degraded", "Blocked"]),
            },
        )
    finally:
        await client.close()

    assert len(calls) == 1
    sent = calls[0]
    assert sent["headers"]["Authorization"] == "Bearer test-key"
    assert sent["headers"]["Content-Type"] == "application/json"
    assert sent["body"]["state"] == "I was charged twice. Please fix this ASAP."
    assert sent["body"]["model"] == "jev-latest"
    assert sent["body"]["questions"]["category"] == {
        "type": "choice",
        "instructions": "What is this ticket about?",
        "criteria": {"billing": None, "technical": None, "other": None},
    }
    assert sent["body"]["questions"]["urgent"] == {"type": "noul", "instructions": "Needs an answer today?"}

    assert isinstance(message, AIMessage)
    assert message.provider == "typesafe"
    assert message.model == "jev-latest"
    assert message.is_structured
    assert isinstance(message.output, SystemOneResponse)
    assert message.output.request_id == "req-123"
    assert message.data == {"category": "billing", "urgent": 0.82, "severity": 1.6}
    assert json.loads(message.response) == message.data
    assert message.usage.prompt_tokens == 42
    assert message.usage.completion_tokens == 0
    assert message.metadata["request_id"] == "req-123"
    assert message.metadata["answers"]["category"]["probabilities"]["billing"] == 0.91
    assert message.finish_reason == "completed"


async def test_ask_round_trips_the_documented_quickstart_exchange(stub_api):
    async def quickstart(request):
        return web.json_response(DOCS_RESPONSE)

    server, calls = await stub_api(quickstart)
    client = _client(server)
    try:
        message = await client.ask(DOCS_STATE, questions=DOCS_QUESTIONS)
    finally:
        await client.close()
    assert calls[0]["body"] == {"state": DOCS_STATE, "model": "jev-latest", "questions": DOCS_QUESTIONS}
    assert message.data == {"department": "billing", "frustration": 1.035, "is_urgent": 0.999}
    assert message.usage.prompt_tokens == 312
    assert message.usage.completion_tokens == 48
    assert message.usage.total_tokens == 360


async def test_ask_builds_json_state_from_system_prompt_and_history(stub_api):
    server, calls = await stub_api()
    client = _client(server, questions={"urgent": Noul(instructions="Urgent?")})
    history = [HistoryMessage(role="user", content="hi"), HistoryMessage(role="assistant", content="hello")]
    try:
        message = await client.ask("still broken", system_prompt="You triage tickets.", history=history)
    finally:
        await client.close()
    assert calls[0]["body"]["state"] == {
        "context": "You triage tickets.",
        "conversation": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}],
        "input": "still broken",
    }
    assert message.used_conversation_history is True


async def test_ask_with_pydantic_structured_output_returns_typed_instance(stub_api):
    server, calls = await stub_api()
    client = _client(server)
    try:
        message = await client.ask("I was charged twice", structured_output=Triage)
    finally:
        await client.close()
    assert set(calls[0]["body"]["questions"]) == {"category", "urgent", "severity"}
    assert calls[0]["body"]["questions"]["severity"]["criteria"] == ["Cosmetic", "Degraded", "Blocked"]
    assert message.output == Triage(category="billing", urgent=True, severity=2)
    assert message.structured_output is message.output


async def test_ask_accepts_explicit_state_and_pydantic_state(stub_api):
    server, calls = await stub_api()

    class Ticket(BaseModel):
        subject: str
        body: str

    client = _client(server)
    try:
        await client.ask("ignored", state=Ticket(subject="Double charge", body="..."), questions={"u": Noul()})
        await client.ask("ignored", state=["a", "b"], questions={"u": Noul()})
    finally:
        await client.close()
    assert calls[0]["body"]["state"] == {"subject": "Double charge", "body": "..."}
    assert calls[1]["body"]["state"] == ["a", "b"]


async def test_ask_without_questions_raises_before_any_request(stub_api):
    server, calls = await stub_api()
    client = _client(server)
    try:
        with pytest.raises(JevConfigurationError, match="typed questions only"):
            await client.ask("hello")
    finally:
        await client.close()
    assert calls == []


async def test_missing_api_key_raises_configuration_error(stub_api):
    server, calls = await stub_api()
    fake_config = MagicMock()
    fake_config.get.return_value = None
    with patch.object(jev_client_mod, "config", fake_config):
        client = JevClient(base_url=str(server.make_url("")))
    try:
        with pytest.raises(JevConfigurationError, match="TYPESAFE_API_KEY"):
            await client.system_one("state", {"q": Noul()})
    finally:
        await client.close()
    assert calls == []


async def test_invoke_derives_questions_and_parses_output_type(stub_api):
    server, calls = await stub_api()
    client = _client(server)
    try:
        result = await client.invoke("I was charged twice", output_type=Triage, system_prompt="Triage tickets.")
    finally:
        await client.close()
    assert isinstance(result, InvokeResult)
    assert result.output == Triage(category="billing", urgent=True, severity=2)
    assert result.output_type is Triage
    assert result.model == "jev-latest"
    assert result.usage.prompt_tokens == 42
    assert result.raw_response["answers"]["category"]["confidence"] == 0.91
    assert calls[0]["body"]["state"] == {"context": "Triage tickets.", "input": "I was charged twice"}


async def test_invoke_without_output_type_returns_response_and_wraps_errors(stub_api):
    server, _ = await stub_api()
    client = _client(server, questions={"urgent": Noul(instructions="Urgent?")})
    try:
        result = await client.invoke("hello")
        assert isinstance(result.output, SystemOneResponse)
        assert result.output_type is None

        class FreeText(BaseModel):
            summary: str

        with pytest.raises(InvokeError) as excinfo:
            await client.invoke("hello", output_type=FreeText)
        assert isinstance(excinfo.value.original, JevSchemaError)
    finally:
        await client.close()


async def test_ask_stream_yields_text_then_message(stub_api):
    server, _ = await stub_api()
    client = _client(server)
    try:
        chunks = [chunk async for chunk in client.ask_stream("hi", questions={"urgent": Noul()})]
    finally:
        await client.close()
    assert len(chunks) == 2
    assert isinstance(chunks[0], str) and json.loads(chunks[0])["urgent"] == 0.82
    assert isinstance(chunks[1], AIMessage)


async def test_batch_ask_runs_requests_concurrently(stub_api):
    server, calls = await stub_api()
    client = _client(server)
    try:
        messages = await client.batch_ask(
            [{"prompt": "a", "questions": {"u": Noul()}}, {"prompt": "b", "questions": {"u": Noul()}}]
        )
    finally:
        await client.close()
    assert [m.input for m in messages] == ["a", "b"]
    assert sorted(c["body"]["state"] for c in calls) == ["a", "b"]


async def test_list_models(stub_api):
    server, calls = await stub_api()
    client = _client(server)
    try:
        models = await client.list_models()
    finally:
        await client.close()
    assert [m.name for m in models] == ["jev-latest"]
    assert calls[0]["headers"]["Authorization"] == "Bearer test-key"


async def test_non_retryable_error_maps_to_exception_without_retry(stub_api):
    async def unauthorized(request):
        return web.json_response({"error": "bad key"}, status=401, headers={"x-typesafe-request-id": "r-401"})

    server, calls = await stub_api(unauthorized)
    client = _client(server, max_retries=3)
    try:
        with pytest.raises(JevAuthenticationError) as excinfo:
            await client.ask("x", questions={"u": Noul()})
    finally:
        await client.close()
    assert excinfo.value.status == 401
    assert excinfo.value.request_id == "r-401"
    assert "bad key" in str(excinfo.value)
    assert len(calls) == 1


async def test_rate_limit_is_retried_honouring_retry_after(stub_api):
    attempts = {"n": 0}

    async def flaky(request):
        attempts["n"] += 1
        if attempts["n"] == 1:
            return web.json_response({"message": "slow down"}, status=429, headers={"retry-after-ms": "5"})
        return web.json_response(_sample_response())

    server, calls = await stub_api(flaky)
    client = _client(server, max_retries=1)
    try:
        message = await client.ask("x", questions={"u": Noul()})
    finally:
        await client.close()
    assert attempts["n"] == 2
    assert len(calls) == 2
    assert message.data["category"] == "billing"


async def test_server_error_exhausts_retries(stub_api):
    async def broken(request):
        return web.Response(status=503, text="down", headers={"retry-after-ms": "1"})

    server, calls = await stub_api(broken)
    client = _client(server, max_retries=2)
    try:
        with pytest.raises(JevServerError) as excinfo:
            await client.system_one("x", {"u": Noul()})
    finally:
        await client.close()
    assert excinfo.value.status == 503
    assert len(calls) == 3


async def test_resume_is_not_supported():
    client = JevClient(api_key="k")
    with pytest.raises(NotImplementedError):
        await client.resume("s", "input", {})


async def test_close_shuts_down_session(stub_api):
    server, _ = await stub_api()
    client = _client(server)
    await client.ask("x", questions={"u": Noul()})
    session = await client._ensure_client()
    assert not session.closed
    await client.close()
    assert session.closed
