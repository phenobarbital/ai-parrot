"""Tests for VoiceBot refinements (FEAT-416, TASK-2151 — spec §3 Module 7):
export from `parrot.bots`, `stt_only` passthrough, and the `VoiceCapable`
runtime check in `_create_llm_client()`.

``TestVoiceBotSttOnly``/``TestVoiceBotVoiceCapableCheck`` use AST source
inspection rather than live instantiation — same strategy as
``test_voicebot_nova_wiring.py``/``test_voicebot_provider_switch.py`` in
this directory, for the same reason: the Cython ``parrot.utils.types``
extension is not built in this environment, so ``parrot.bots`` (and
therefore ``VoiceBot``) cannot be imported directly here. In a
fully-provisioned environment, `from parrot.bots import VoiceBot` (used by
``TestVoiceBotExport`` below, per the task's own Test Specification) works
normally.
"""
import ast
from pathlib import Path

VOICE_BOT_SOURCE = (
    Path(__file__).resolve().parents[2] / "src" / "parrot" / "bots" / "voice.py"
)


def _get_method_source(method_name: str) -> str:
    source = VOICE_BOT_SOURCE.read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "VoiceBot":
            for item in node.body:
                if (
                    isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and item.name == method_name
                ):
                    return ast.get_source_segment(source, item)
    raise AssertionError(f"Method {method_name} not found in VoiceBot")


class TestVoiceBotExport:
    def test_import_from_bots(self):
        from parrot.bots import VoiceBot
        assert VoiceBot is not None

    def test_voicebot_in_all(self):
        import parrot.bots
        assert "VoiceBot" in parrot.bots.__all__


class TestVoiceBotLazyExport:
    """The export must not be EAGER (regression guard).

    An eager `from .voice import VoiceBot` in `parrot/bots/__init__.py`
    drags `parrot.clients.live` -> `from google import genai` into every
    importer of `parrot.bots`, turning the optional `google-genai` dep into
    a hard requirement of the agent REPL and the agentd daemon. AST-based
    for the same reason as the rest of this module.
    """

    BOTS_INIT = (
        Path(__file__).resolve().parents[2]
        / "src" / "parrot" / "bots" / "__init__.py"
    )

    def _tree(self) -> ast.Module:
        return ast.parse(self.BOTS_INIT.read_text())

    def test_no_module_level_voice_import(self):
        for node in self._tree().body:
            if isinstance(node, ast.ImportFrom):
                assert node.module != "voice", (
                    "parrot/bots/__init__.py imports .voice at module level; "
                    "that makes google-genai a hard dependency of parrot.bots"
                )

    def test_defines_module_getattr(self):
        names = {
            node.name
            for node in self._tree().body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert "__getattr__" in names, (
            "lazy exports require a PEP 562 module-level __getattr__"
        )


class TestVoiceBotSttOnly:
    def test_ask_stream_has_stt_only_param(self):
        src = _get_method_source("ask_stream")
        assert "stt_only: bool = False" in src

    def test_stt_only_passed_to_client(self):
        """ask_stream(stt_only=True) passes through to stream_voice."""
        src = _get_method_source("ask_stream")
        assert "stt_only=stt_only" in src
        assert "client.stream_voice(" in src

    def test_inference_params_threaded_from_voice_config(self):
        """VoiceConfig temperature/max_tokens/top_p/parallel_tool_execution
        are threaded to stream_voice() via the single VoiceStreamOptions
        projection (FEAT-418, TASK-2173 — spec §3 Module 7), overridable
        via **kwargs. Was an ad-hoc voice_stream_kwargs dict with four
        explicit VoiceConfig reads before TASK-2173; to_stream_options()
        now covers ALL nine VoiceStreamOptions fields (including
        temperature/max_tokens/top_p/parallel_tool_execution) internally."""
        src = _get_method_source("ask_stream")
        assert "self.voice_config.to_stream_options(" in src
        assert "options=options" in src


class TestVoiceBotVoiceCapableCheck:
    def test_non_voice_client_raises(self):
        """_create_llm_client raises TypeError for non-VoiceCapable."""
        src = _get_method_source("_create_llm_client")
        assert "isinstance(client, VoiceCapable)" in src
        assert "raise TypeError(" in src

    def test_return_type_annotated_voice_capable(self):
        src = _get_method_source("_create_llm_client")
        assert "-> VoiceCapable:" in src

    def test_both_provider_branches_still_present(self):
        """Regression guard: restructuring to a shared isinstance check
        must not drop either provider branch."""
        src = _get_method_source("_create_llm_client")
        assert "config.provider == 'nova'" in src
        assert "NovaClient" in src
        assert "GeminiLiveClient" in src


class TestVoiceBotUnifiedVoiceConfig:
    def test_imports_voice_capable_protocol(self):
        source = VOICE_BOT_SOURCE.read_text()
        assert "from ..clients.protocols import VoiceCapable" in source

    def test_resolved_model_uses_truthiness_not_stale_default(self):
        """Code-review fix: VoiceConfig.model now defaults to None
        (TASK-2146), so the Nova branch's fallback must use a truthiness
        check, not a `!= GoogleVoiceModel.DEFAULT` comparison (which would
        always be True for None, breaking the "nova-2-sonic" fallback)."""
        src = _get_method_source("_resolve_llm_config")
        # The old comparison is mentioned in an explanatory comment (with
        # markdown backticks) but must not appear as executable code.
        assert "self.voice_config.model != GoogleVoiceModel.DEFAULT" not in src
        assert 'self.voice_config.model or "nova-2-sonic"' in src
