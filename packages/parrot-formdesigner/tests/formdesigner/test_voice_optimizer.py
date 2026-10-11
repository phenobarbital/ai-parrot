"""Tests for the design-time VoiceOptimizer, EditToolkit.propose_voice_hints and the optimize endpoint (FEAT-649)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

from parrot_formdesigner.core.options import FieldOption
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType

pytest.importorskip("parrot.tools.toolkit")  # EditToolkit needs ai-parrot

_FORM_UID = "11111111-1111-1111-1111-111111111111"


def _form() -> FormSchema:
    pick = FormField(
        field_id="pick",
        field_type=FieldType.SELECT,
        label="Pick",
        options=[
            FieldOption(value="a", label="Saltar"),
            FieldOption(value="b", label="Rojo"),
            FieldOption(value="c", label="Rojos"),
        ],
    )
    return FormSchema(
        form_id="demo", title="Demo", tenant="acme", sections=[FormSection(section_id="s", fields=[pick])]
    )


class FakeClient:
    def __init__(self, output):
        self.calls, self._output = [], output

    async def ask(self, prompt, **kw):
        self.calls.append((prompt, kw))
        return type("Msg", (), {"output": self._output})()


def _batch(form: FormSchema, extra_uid=None, hint="Say the colour"):
    from parrot_formdesigner.tools.voice_optimizer import VoiceHintProposal, _ProposalBatch

    field = next(iter(form.iter_fields_recursive()))
    props = [VoiceHintProposal(field_uid=field.field_uid, hint={"en": hint}, rationale="r")]
    if extra_uid is not None:
        props.append(VoiceHintProposal(field_uid=extra_uid, hint={"en": "x"}))
    return _ProposalBatch(proposals=props)


def _optimizer(client):
    from parrot_formdesigner.audio.narration.engine import Narrator
    from parrot_formdesigner.tools.voice_optimizer import VoiceOptimizer

    return VoiceOptimizer(client, Narrator)


def test_self_test_without_client_reports_collisions():
    from parrot_formdesigner.audio.narration.lexicon import load_lexicon
    from parrot_formdesigner.tools.voice_optimizer import VoiceOptimizer

    findings = VoiceOptimizer(client=None, narrator_factory=lambda loc: None).self_test(_form(), load_lexicon("es"))
    assert any("sound alike" in f for f in findings)
    assert any("collides with command" in f for f in findings)


async def test_propose_single_call_and_no_mutation():
    form = _form()
    before = form.model_dump()
    client = FakeClient(_batch(form))
    proposals, preview = await _optimizer(client).propose(
        form, locale="en", fields=None, style="concise", max_hint_words=20
    )
    assert len(client.calls) == 1
    assert "structured_output" in client.calls[0][1]
    assert len(proposals) == 1
    assert "pick" in preview
    assert form.model_dump() == before


async def test_propose_drops_unknown_field_uid_and_warns_on_long_hint():
    import uuid

    form = _form()
    client = FakeClient(_batch(form, extra_uid=uuid.uuid4(), hint="one two three four five six"))
    proposals, _ = await _optimizer(client).propose(form, locale="en", fields=None, style="concise", max_hint_words=3)
    assert len(proposals) == 1
    assert proposals[0].warnings


async def test_toolkit_propose_voice_hints_does_not_mutate():
    from parrot_formdesigner.tools.edit_toolkit import EditToolkit

    form = _form()
    opt = _optimizer(FakeClient(_batch(form)))
    toolkit = EditToolkit(form, voice_optimizer=opt)
    before = toolkit._form.model_dump()
    result = await toolkit.propose_voice_hints(str(form.form_uid))
    assert result["proposals"]
    assert toolkit._form.model_dump() == before
    bad = await toolkit.propose_voice_hints(_FORM_UID)
    assert "error" in bad


def _handler(form, client):
    from parrot_formdesigner.api.handlers import FormAPIHandler
    from parrot_formdesigner.services.registry import FormRegistry

    registry = MagicMock(spec=FormRegistry)
    registry.get = AsyncMock(return_value=form)
    handler = FormAPIHandler(registry=registry)
    handler._client = client
    handler._get_llm_client = lambda: client
    return handler, registry


def _request(body=None):
    req = MagicMock(spec=web.Request)
    req.match_info = {"form_uid": _FORM_UID}
    req.json = AsyncMock(return_value=body or {})
    req.get = MagicMock(side_effect=lambda key, default=None: "acme" if key == "tenant" else default)
    req.session = {"session": {"programs": ["acme"]}}
    return req


async def test_optimize_voice_endpoint_503_without_client():
    handler, _ = _handler(_form(), None)
    resp = await handler.optimize_voice(_request())
    assert resp.status == 503


async def test_optimize_voice_endpoint_404_unknown_form():
    handler, registry = _handler(None, FakeClient(None))
    registry.get = AsyncMock(return_value=None)
    resp = await handler.optimize_voice(_request())
    assert resp.status == 404


async def test_optimize_voice_endpoint_never_writes():
    form = _form()
    handler, registry = _handler(form, FakeClient(_batch(form)))
    resp = await handler.optimize_voice(_request({"locale": "es"}))
    assert resp.status == 200
    data = json.loads(resp.body)
    assert set(data) == {"proposals", "narration_preview", "self_test"}
    assert data["self_test"]
    assert [c[0] for c in registry.method_calls] == ["get"]
