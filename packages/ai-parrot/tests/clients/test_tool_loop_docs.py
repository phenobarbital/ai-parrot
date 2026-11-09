"""FEAT-848 AC-6 — the tool-loop documentation says the right thing."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
AGENTIC = ROOT / "wiki" / "knowledge" / "pageindex-agentic-retrieval.md"
CLIENT = ROOT / "wiki" / "clients" / "abstract-client.md"


def _section(text: str, heading: str) -> str:
    """Body of a markdown section, up to the next heading of the same or higher level."""
    level = heading.split(" ", 1)[0]
    start = text.index(heading) + len(heading)
    ends = [i for i in (text.find("\n" + "#" * n + " ", start) for n in range(1, len(level) + 1)) if i != -1]
    return text[start : min(ends)] if ends else text[start:]


def test_agentic_provider_table_is_corrected() -> None:
    """No inherited-loop provider is listed as unsupported; the three False classes are."""
    body = _section(AGENTIC.read_text(encoding="utf-8"), "### Provider support")
    # The flag is documented
    assert "supports_tool_loop" in body
    # OpenRouter is no longer called out as unverified
    assert "OpenRouter is not in the verified table" not in body
    # The three False classes are documented
    for name in ("TransformersClient", "JevClient", "GeminiLiveClient"):
        assert name in body
    # The old wrong list is gone
    assert "hf, meta, local, vllm, moonshot, nvidia, jev" not in body
    # Fail-fast and no_tool_calls semantics are documented
    assert "ValueError" in body
    assert "no_tool_calls" in body


def test_abstract_client_documents_the_flag() -> None:
    """The client page documents scope, bridges, the bot warning and the absence of a streaming flag."""
    text = CLIENT.read_text(encoding="utf-8")
    # The new subsection exists
    assert "### Tool-loop capability" in text
    # Gotchas document the flag
    gotchas = _section(text, "## Gotchas")
    assert "supports_tool_loop" in gotchas
    # The new subsection or Gotchas mention tool_manager, configure(), and ask_stream
    new_section = _section(text, "### Tool-loop capability")
    combined = new_section + gotchas
    assert "tool_manager" in combined
    assert "configure()" in combined
    assert "ask_stream" in combined