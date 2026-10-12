"""Keep docs/audio-form-voice-modes.md and the navigator-svelte handoff in sync with audio/events.py (FEAT-649)."""

from __future__ import annotations

import re
import typing
from pathlib import Path

from parrot_formdesigner.audio import events

REPO = Path(__file__).resolve().parents[4]
DOC = REPO / "docs" / "audio-form-voice-modes.md"
HANDOFF = REPO / "sdd" / "proposals" / "audio-form-interaction-workflow.handoff-navigator-svelte.md"
SRC = REPO / "packages" / "parrot-formdesigner" / "src" / "parrot_formdesigner"
IO_REQUESTS = {
    "Synthesize",
    "Transcribe",
    "StoreBlob",
    "DeleteBlob",
    "SaveSnapshot",
    "RunPlausibility",
    "Submit",
    "Replan",
}


def _members(union: typing.Any) -> list[type]:
    args = typing.get_args(union)
    if args and typing.get_origin(union) is typing.Annotated:
        args = typing.get_args(args[0])
    return list(args)


def _wire_literals() -> set[str]:
    out: set[str] = set()
    for model in _members(events.InboundEvent) + _members(events.Outbound):
        if model.__name__ in IO_REQUESTS:
            continue
        for lit in typing.get_args(model.model_fields["type"].annotation):
            if not lit.startswith("_"):
                out.add(lit)
    return out


def _section(text: str, start: str, end: str) -> str:
    return text[text.index(start) : text.index(end)]


def test_wire_literals_found():
    assert {"audio_segment", "review_confirm", "start_session", "pong"} <= _wire_literals()


def test_docs_list_every_protocol_type():
    section7 = _section(DOC.read_text(), "## 7. WebSocket Protocol", "## 8. Flow Diagrams")
    missing = sorted(t for t in _wire_literals() if f"`{t}`" not in section7)
    assert not missing, f"undocumented message types: {missing}"


def test_handoff_tables_match_events():
    section3 = _section(HANDOFF.read_text(), "## 3. Backend contract", "## 4. Constraints")
    missing = sorted(t for t in _wire_literals() if f"`{t}" not in section3)
    assert not missing, f"types missing from handoff: {missing}"


def test_error_codes_documented():
    code_text = (SRC / "audio" / "engine.py").read_text() + (SRC / "api" / "audio_ws.py").read_text()
    codes = set(re.findall(r'code="([A-Z][A-Z_]+)"', code_text))
    codes |= set(re.findall(r'"([A-Z]{2,}(?:_[A-Z]+)+)"', code_text))
    assert "NO_MATCH" in codes and "RESUME_STALE" in codes
    section10 = _section(DOC.read_text(), "## 10. Error Codes", "## 11. Security")
    missing = sorted(c for c in codes if f"`{c}`" not in section10)
    assert not missing, f"undocumented error codes: {missing}"
