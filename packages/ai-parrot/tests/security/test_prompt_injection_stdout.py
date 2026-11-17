"""The injection-scorer resolver must never write to stdout (FEAT-844 / issue:70f18da2a8d5)."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.knowledge.pageindex.toolkit import PageIndexToolkit
from parrot.security.prompt_injection import get_injection_scoring_engine

BANNER = "Loading Hugging Face model from: protectai/deberta-v3-base-prompt-injection"
_RESOLVER = "parrot.bots.guardrails.builtin.prompt_injection._resolve_injection_engine"


def _printing_resolver(force_reresolve: bool = False):
    print(BANNER)  # noqa: T201 - simulates pytector's banner
    return None


def test_get_injection_scoring_engine_keeps_stdout_clean(monkeypatch, capsys) -> None:
    """AC-1: the banner lands on stderr, stdout stays empty, the result is passed through."""
    monkeypatch.setattr(_RESOLVER, _printing_resolver)
    assert get_injection_scoring_engine() is None
    captured = capsys.readouterr()
    assert captured.out == ""
    assert BANNER in captured.err


def test_get_injection_scoring_engine_passes_engine_through(monkeypatch, capsys) -> None:
    """AC-1: a resolved engine is returned unchanged; nothing is printed to stdout either way."""
    sentinel = object()
    monkeypatch.setattr(_RESOLVER, lambda force_reresolve=False: sentinel)
    assert get_injection_scoring_engine() is sentinel
    assert capsys.readouterr().out == ""


@pytest.mark.asyncio
async def test_scan_resolution_keeps_stdout_clean(monkeypatch, capsys, tmp_path: Path) -> None:
    """AC-1 via the toolkit path that the stdio server hits on first ingest."""
    monkeypatch.setattr(_RESOLVER, _printing_resolver)

    async def _no_scan(segments, *, detector, engine, threshold):
        return None

    monkeypatch.setattr("parrot.knowledge.pageindex.toolkit.scan_segments", _no_scan)
    toolkit = PageIndexToolkit(storage_dir=tmp_path)
    assert await toolkit._scan([object()]) is None
    captured = capsys.readouterr()
    assert captured.out == ""
    assert BANNER in captured.err
