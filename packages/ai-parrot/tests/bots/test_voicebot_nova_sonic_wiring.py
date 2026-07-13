"""Tests for VoiceBot provider-aware voice-client wiring (FEAT-302, code
review follow-up).

Prior to this fix, ``VoiceBot._resolve_llm_config()``/``_create_llm_client()``
were hardcoded to ``GeminiLiveClient`` regardless of any provider selection
— Nova Sonic's voice-provider registration (TASK-1749) was enum+resolver
only, never wired into the real bot voice-session pipeline. This is now
fixed via ``VoiceConfig.provider`` (``"google_live"`` default,
``"nova_sonic"`` opt-in) — see ``tests/models/test_voice_config.py`` for
direct ``VoiceConfig`` coverage.

``parrot.bots`` cannot be imported directly in this environment (the
Cython extension ``parrot.utils.types`` is not built here — a
pre-existing, unrelated environment limitation reproduced independently:
``import parrot.bots`` raises ``ModuleNotFoundError: No module named
'parrot.utils.types'`` regardless of this feature), so the wiring is
verified via source inspection instead of live instantiation — same
strategy already used by
``tests/bots/prompts/test_voicebot_prompt.py`` for the same reason. This
file intentionally lives at ``tests/bots/`` (not
``tests/bots/prompts/``), whose ``conftest.py`` force-imports
``parrot.bots.prompts.layers`` and would poison collection for every test
in that directory regardless of what any individual test file imports.
"""
import ast
from pathlib import Path

VOICE_BOT_SOURCE = (
    Path(__file__).resolve().parents[2] / "src" / "parrot" / "bots" / "voice.py"
)


class TestVoiceBotResolvesNovaSonicProvider:
    def _get_method_source(self, method_name: str) -> str:
        source = VOICE_BOT_SOURCE.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "VoiceBot":
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == method_name:
                        return ast.get_source_segment(source, item)
        raise AssertionError(f"Method {method_name} not found in VoiceBot")

    def test_resolve_llm_config_branches_on_provider(self):
        method_source = self._get_method_source("_resolve_llm_config")
        assert "self.voice_config.provider" in method_source
        assert "nova_sonic" in method_source
        assert "NovaSonicClient" in method_source

    def test_resolve_llm_config_default_branch_unchanged(self):
        """The existing GeminiLiveClient branch must still be present and
        still be the fallback/default (no regression for the only
        currently-fully-wired voice provider)."""
        method_source = self._get_method_source("_resolve_llm_config")
        assert "GeminiLiveClient" in method_source
        assert "gemini_live" in method_source

    def test_create_llm_client_branches_on_provider(self):
        method_source = self._get_method_source("_create_llm_client")
        assert "config.provider" in method_source
        assert "nova_sonic" in method_source
        assert "NovaSonicClient" in method_source

    def test_create_llm_client_default_branch_unchanged(self):
        method_source = self._get_method_source("_create_llm_client")
        assert "GeminiLiveClient" in method_source
