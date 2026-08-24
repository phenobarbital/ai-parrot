"""Unit tests for parrot_tools.audio_note_capture.

Exercises the AudioNoteCaptureToolkit from its new standalone location in
ai-parrot-tools (extracted from agents/fireflies_wiki.py in FEAT-452).

No network, no real LLM, no real vault: every external collaborator is
mocked.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot_tools.audio_note_capture import (
    AudioNoteCaptureToolkit,
    AudioNoteResult,
    AudioNoteStructure,
    _build_note_structuring_prompt,
    _make_note_title,
    _parse_note_structure_response,
    _strip_bullet,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_STRUCTURED_RESPONSE = (
    "## Title\nBuy Milk\n\n"
    "## Tags\nshopping, reminder\n\n"
    "## Summary\nRecordar comprar leche.\n\n"
    "## Key Points\n- comprar leche en la tienda\n\n"
    "## Action Items\n- ir a la tienda hoy"
)


@pytest.fixture
def toolkit(tmp_path):
    """An AudioNoteCaptureToolkit with every collaborator mocked."""
    obsidian = MagicMock()
    obsidian.create_note = AsyncMock(return_value={"created": True, "file": {}})

    notes_wiki = MagicMock()
    notes_wiki.ingest_source = AsyncMock(return_value={})

    llm_call = AsyncMock(return_value=_STRUCTURED_RESPONSE)

    tk = AudioNoteCaptureToolkit(
        obsidian_toolkit=obsidian,
        notes_wiki_provider=lambda: notes_wiki,
        llm_call=llm_call,
        vault_path=tmp_path / "vault",
    )
    # Expose mocks for assertions.
    tk._test_obsidian = obsidian
    tk._test_notes_wiki = notes_wiki
    tk._test_llm_call = llm_call
    return tk


# ---------------------------------------------------------------------------
# Pure-function helpers
# ---------------------------------------------------------------------------


class TestStripBullet:
    def test_strips_dash(self):
        assert _strip_bullet("- hello") == "hello"

    def test_strips_asterisk(self):
        assert _strip_bullet("* world") == "world"

    def test_no_bullet(self):
        assert _strip_bullet("no bullet") == "no bullet"

    def test_whitespace_preserved(self):
        assert _strip_bullet("  - indented") == "indented"


class TestMakeNoteTitle:
    def test_basic_slug(self):
        assert _make_note_title("2026-08-23", "Buy Milk") == "2026-08-23-buy-milk"

    def test_collapses_hyphens(self):
        result = _make_note_title("2026-08-23", "one  /  two")
        assert "--" not in result

    def test_strips_non_alnum(self):
        result = _make_note_title("2026-08-23", "hello world!")
        assert "!" not in result
        assert result == "2026-08-23-hello-world"


class TestParseNoteStructure:
    def test_complete_response(self):
        s = _parse_note_structure_response(_STRUCTURED_RESPONSE)
        assert s.title == "Buy Milk"
        assert s.tags == ["shopping", "reminder"]
        assert "comprar leche" in s.summary.lower()
        assert len(s.key_points) == 1
        assert len(s.action_items) == 1

    def test_missing_title_raises(self):
        with pytest.raises(ValueError, match="Title"):
            _parse_note_structure_response("## Summary\nSome summary")

    def test_missing_summary_raises(self):
        with pytest.raises(ValueError, match="Summary"):
            _parse_note_structure_response("## Title\nHello")


class TestBuildPrompt:
    def test_with_language(self):
        prompt = _build_note_structuring_prompt("hola", "es")
        assert "'es'" in prompt
        assert "hola" in prompt

    def test_without_language(self):
        prompt = _build_note_structuring_prompt("hello", None)
        assert "Detect the language" in prompt


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class TestModels:
    def test_audio_note_structure_defaults(self):
        s = AudioNoteStructure(title="T", summary="S")
        assert s.tags == []
        assert s.key_points == []
        assert s.action_items == []

    def test_audio_note_result_round_trip(self):
        r = AudioNoteResult(
            note_title="2026-08-23-buy-milk",
            vault_path="audio-notes/2026-08-23-buy-milk.md",
            wiki_ingested=True,
            structured=True,
        )
        d = r.model_dump()
        assert d["wiki_reason"] is None
        assert d["wiki_ingested"] is True


# ---------------------------------------------------------------------------
# Toolkit integration
# ---------------------------------------------------------------------------


class TestAudioNoteCaptureToolkit:
    """The capture_audio_note tool: structure -> vault write -> wiki ingest."""

    @pytest.mark.asyncio
    async def test_note_path_and_transcript_preserved(self, toolkit):
        result = await toolkit.capture_audio_note("recordar comprar leche", language="es")
        assert result["vault_path"].startswith("audio-notes/")
        content = toolkit._test_obsidian.create_note.call_args.kwargs["content"]
        assert "## Transcript" in content
        assert "recordar comprar leche" in content

    @pytest.mark.asyncio
    async def test_language_split(self, toolkit):
        result = await toolkit.capture_audio_note("recordar comprar leche", language="es")
        assert result["structured"] is True
        content = toolkit._test_obsidian.create_note.call_args.kwargs["content"]
        assert "Recordar comprar leche." in content

    @pytest.mark.asyncio
    async def test_slug_collision_retries(self, toolkit):
        toolkit._test_obsidian.create_note = AsyncMock(
            side_effect=[FileExistsError(), {"created": True, "file": {}}]
        )
        result = await toolkit.capture_audio_note("recordar comprar leche", language="es")
        assert result["note_title"].endswith("-2")
        assert toolkit._test_obsidian.create_note.await_count == 2

    @pytest.mark.asyncio
    async def test_llm_failure_writes_verbatim(self, toolkit):
        toolkit._test_llm_call.side_effect = RuntimeError("llm down")
        result = await toolkit.capture_audio_note("just a raw thought", language="en")
        assert result["structured"] is False
        content = toolkit._test_obsidian.create_note.call_args.kwargs["content"]
        assert "just a raw thought" in content

    @pytest.mark.asyncio
    async def test_wiki_unavailable_keeps_note(self, toolkit, tmp_path):
        tk = AudioNoteCaptureToolkit(
            obsidian_toolkit=toolkit._test_obsidian,
            notes_wiki_provider=lambda: None,
            llm_call=toolkit._test_llm_call,
            vault_path=tmp_path / "vault",
        )
        result = await tk.capture_audio_note("recordar comprar leche", language="es")
        assert result["wiki_ingested"] is False
        assert result["wiki_reason"]

    @pytest.mark.asyncio
    async def test_ingest_error_keeps_note(self, toolkit):
        toolkit._test_notes_wiki.ingest_source = AsyncMock(side_effect=RuntimeError("wiki down"))
        result = await toolkit.capture_audio_note("recordar comprar leche", language="es")
        assert result["wiki_ingested"] is False
        assert "wiki down" in result["wiki_reason"]
        toolkit._test_obsidian.create_note.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_vault_failure_surfaces(self, toolkit):
        toolkit._test_obsidian.create_note = AsyncMock(side_effect=OSError("disk full"))
        with pytest.raises(OSError):
            await toolkit.capture_audio_note("recordar comprar leche", language="es")

    @pytest.mark.asyncio
    async def test_ingest_source_receives_absolute_path(self, toolkit):
        await toolkit.capture_audio_note("recordar comprar leche", language="es")
        args, _kwargs = toolkit._test_notes_wiki.ingest_source.call_args
        assert Path(args[1]).is_absolute()

    @pytest.mark.asyncio
    async def test_exactly_one_llm_call(self, toolkit):
        await toolkit.capture_audio_note("recordar comprar leche", language="es")
        assert toolkit._test_llm_call.await_count == 1

    def test_toolkit_exposes_single_tool(self, toolkit):
        assert [t.name for t in toolkit.get_tools()] == ["capture_audio_note"]

    @pytest.mark.asyncio
    async def test_typed_input_without_language(self, toolkit):
        result = await toolkit.capture_audio_note("remember to buy milk")
        assert result["structured"] is True
        assert toolkit._test_llm_call.await_count == 1
