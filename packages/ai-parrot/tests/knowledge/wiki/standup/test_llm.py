"""Regression cases for FEAT-627 optional model resolution and synthesis."""

import asyncio
import logging
import sys
import types
from datetime import date
from pathlib import Path

import pytest

import parrot.knowledge.wiki.llm_resolve as resolve
import parrot.knowledge.wiki.standup.llm as subject
from parrot.knowledge.wiki.standup.models import BriefItem


def _item(i: int, **kw: object) -> BriefItem:
    base: dict[str, object] = {
        "id": f"ticket:{i:03d}",
        "kind": "ticket",
        "title": f"Title {i}",
        "source": "jira",
        "owner": "secret-owner",
        "url": "https://example.test/secret",
    }
    base.update(kw)
    return BriefItem(**base)  # type: ignore[arg-type]


class FakeAdapter:
    """Records prompts; returns or raises as configured."""

    def __init__(self, result: object = "- a\n- b", exc: Exception | None = None, delay: float = 0.0) -> None:
        self.result, self.exc, self.delay = result, exc, delay
        self.prompts: list[str] = []
        self.temperatures: list[float] = []

    async def ask(self, prompt: str, temperature: float = 0.5, **_: object) -> object:
        self.prompts.append(prompt)
        self.temperatures.append(temperature)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.exc:
            raise self.exc
        return self.result


def test_bounded_projection_and_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Projection is whitelisted/bounded and fallback is urgent-first, <=3."""
    monkeypatch.setenv("PARROT_HOME", str(tmp_path))
    items = [_item(i, title="x" * 300, project_hint="P") for i in range(60)]
    items.append(_item(99, urgent=True, title="Fire", date=date(2026, 1, 1)))
    proj = subject.project_items(items, period="day", language="en")
    assert len(proj.items) == 40
    assert all(set(r) == {"kind", "title", "status", "project", "age_days", "urgent"} for r in proj.items)
    assert all(len(r["title"]) <= 120 for r in proj.items)  # type: ignore[arg-type]
    assert proj.items[0]["title"] == "Fire"
    blob = str(proj.model_dump())
    assert "secret" not in blob and "ticket:" not in blob
    bullets = subject.fallback_bullets(items, language="en")
    assert len(bullets) == 3 and bullets[0].startswith("Urgent: Fire")
    assert bullets == subject.fallback_bullets(list(reversed(items)), language="en")
    assert subject.fallback_bullets([], language="es") == []


def test_model_resolution_and_imports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Absent/disabled/failing detection yields None; explicit spec builds adapter."""
    monkeypatch.setenv("HOME", str(tmp_path))
    log = logging.getLogger("t")
    settings: dict[str, str] = {}
    monkeypatch.setattr(resolve, "_env_setting", lambda n: settings.get(n))
    det = types.ModuleType("parrot.clients.detection")
    calls: list[int] = []

    def detect() -> str | None:
        calls.append(1)
        return None

    det.detect_coding_agent_llm = detect  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "parrot.clients.detection", det)
    assert resolve.resolve_optional_llm(["X"], purpose="t", logger=log) is None
    assert calls
    calls.clear()
    settings["PARROT_NO_AUTO_LLM"] = "1"
    assert resolve.resolve_optional_llm(["X"], purpose="t", logger=log) is None
    assert not calls
    del settings["PARROT_NO_AUTO_LLM"]

    def boom() -> str:
        raise RuntimeError("sk-secret")

    det.detect_coding_agent_llm = boom  # type: ignore[attr-defined]
    assert resolve.resolve_optional_llm(["X"], purpose="t", logger=log) is None

    fac = types.ModuleType("parrot.clients.factory")

    class LLMFactory:
        @staticmethod
        def parse_llm_string(spec: str) -> tuple[str, str]:
            return tuple(spec.split(":", 1))  # type: ignore[return-value]

        @staticmethod
        def create(spec: str, model_args: dict | None = None) -> object:
            assert model_args == {"temperature": 0.0}
            return types.SimpleNamespace(default_model="m")

    fac.LLMFactory = LLMFactory  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "parrot.clients.factory", fac)
    settings["B"] = "prov:model-x"
    adapter = resolve.resolve_optional_llm(["A", "B"], purpose="t", logger=log)
    assert adapter is not None and adapter.model == "model-x"
    LLMFactory.create = staticmethod(lambda *a, **k: (_ for _ in ()).throw(RuntimeError("sk-secret")))  # type: ignore
    assert resolve.resolve_optional_llm(["B"], purpose="t", logger=log) is None


@pytest.mark.asyncio
async def test_timeout_and_invalid_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Adapter sees only projected facts; bad outputs/timeouts/errors give None without leaks."""
    monkeypatch.setenv("HOME", str(tmp_path))
    proj = subject.project_items([_item(1, title="Ship it")], period="week", language="en")
    ok = FakeAdapter("- one\n* two\n3. three")
    assert await subject.summarize(proj, language="en", adapter=ok) == ["one", "two", "three"]  # type: ignore[arg-type]
    assert ok.temperatures == [0]
    assert "Ship it" in ok.prompts[0] and "secret" not in ok.prompts[0] and "ticket:001" not in ok.prompts[0]
    for bad in ("", "   ", None, "- a\n- b\n- c\n- d", 42):
        assert await subject.summarize(proj, language="en", adapter=FakeAdapter(bad)) is None  # type: ignore[arg-type]
    slow = FakeAdapter(delay=1.0)
    assert await subject.summarize(proj, language="en", adapter=slow, timeout_s=0.05) is None  # type: ignore[arg-type]
    with caplog.at_level(logging.WARNING):
        raising = FakeAdapter(exc=RuntimeError("api_key=sk-LEAK"))
        assert await subject.summarize(proj, language="en", adapter=raising) is None  # type: ignore[arg-type]
    assert "sk-LEAK" not in caplog.text
