import asyncio

import pytest

from parrot_formdesigner.audio.commands import VoiceCommand, classify_command, command_option_collisions
from parrot_formdesigner.audio.models import Phase
from parrot_formdesigner.audio.narration.lexicon import load_lexicon
from parrot_formdesigner.audio.option_refiner import LLMOptionRefiner, RefinedOption


class _FakeClient:
    def __init__(self, result=None, exc=None, delay=0.0):
        self.calls, self.result, self.exc, self.delay = [], result, exc, delay

    async def ask(self, prompt, **kw):
        self.calls.append((prompt, kw))
        await asyncio.sleep(self.delay)
        if self.exc:
            raise self.exc
        return type("R", (), {"structured_output": self.result})()


OPTS = [{"value": "r", "label": "Rojo"}, {"value": "a", "label": "Azul", "disabled": True}]


def test_classify_command_phase_gating_and_precedence():
    es = load_lexicon("es")
    assert classify_command("repetir", lexicon=es, phase=Phase.ASKING) is VoiceCommand.REPEAT
    assert classify_command("atrás", lexicon=es, phase=Phase.ASKING) is VoiceCommand.BACK
    assert classify_command("saltar", lexicon=es, phase=Phase.ASKING) is VoiceCommand.SKIP
    assert classify_command("ayuda", lexicon=es, phase=Phase.ASKING) is VoiceCommand.HELP
    assert classify_command("parar", lexicon=es, phase=Phase.ASKING) is VoiceCommand.STOP
    assert classify_command("siguiente", lexicon=es, phase=Phase.ASKING) is VoiceCommand.NEXT
    assert classify_command("sí", lexicon=es, phase=Phase.ASKING) is None
    assert classify_command("enviar", lexicon=es, phase=Phase.ASKING) is None
    assert classify_command("sí", lexicon=es, phase=Phase.REVIEW) is VoiceCommand.YES
    assert classify_command("no", lexicon=es, phase=Phase.CONFIRMING) is VoiceCommand.NO
    assert classify_command("enviar", lexicon=es, phase=Phase.REVIEW) is VoiceCommand.SEND
    assert classify_command("cambiar la 2", lexicon=es, phase=Phase.REVIEW) is VoiceCommand.CHANGE


def test_classify_command_limits_fuzzy_and_dead_phases():
    es = load_lexicon("es")
    assert classify_command("quiero repetir el color rojo", lexicon=es, phase=Phase.ASKING) is None
    assert classify_command("repetirr", lexicon=es, phase=Phase.ASKING) is VoiceCommand.REPEAT
    assert classify_command("rep", lexicon=es, phase=Phase.ASKING) is None
    assert classify_command("repetir", lexicon=es, phase=Phase.SUBMITTING) is None
    assert classify_command("", lexicon=es, phase=Phase.ASKING) is None


def test_command_option_collisions_enumerated():
    es = load_lexicon("es")
    got = command_option_collisions([{"label": "Saltar", "value": "s"}, {"label": "Rojo", "value": "r"}], es)
    assert ("Saltar", VoiceCommand.SKIP) in got
    assert all(label != "Rojo" for label, _ in got)


async def test_refiner_returns_llm_match_and_none_on_failure():
    client = _FakeClient(RefinedOption(value="r", confidence=0.8))
    m = await LLMOptionRefiner(client).refine("rojito", OPTS, locale="es")
    assert m is not None and m.method == "llm" and m.value == "r" and m.score == 0.8
    assert len(client.calls) == 1
    assert await LLMOptionRefiner(_FakeClient({"value": "r", "confidence": 0.5})).refine("x", OPTS, locale="es")
    assert await LLMOptionRefiner(_FakeClient(RefinedOption(value="zz", confidence=1))).refine("x", OPTS, locale="es") is None
    assert await LLMOptionRefiner(_FakeClient(RefinedOption(value="a", confidence=1))).refine("x", OPTS, locale="es") is None
    assert await LLMOptionRefiner(_FakeClient(exc=RuntimeError("boom"))).refine("x", OPTS, locale="es") is None
    slow = LLMOptionRefiner(_FakeClient(RefinedOption(value="r"), delay=0.5), timeout_s=0.05)
    assert await slow.refine("x", OPTS, locale="es") is None
