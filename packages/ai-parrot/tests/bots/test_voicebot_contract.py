"""VoiceBot projection + memory-from-role regression tests (FEAT-418,
TASK-2173 — spec §3 Module 7).

Covers: ask_stream() using VoiceConfig.to_stream_options() instead of an
ad-hoc kwargs dict, Nova no longer receiving a Gemini voice name via
_resolve_llm_config(), and conversation memory accumulating from the
canonical role attribute instead of the removed
metadata["user_transcription"] key.
"""
from parrot.bots import VoiceBot
from parrot.clients.live import LiveVoiceResponse
from parrot.models.voice import VoiceConfig


class _RecordingClient:
    """VoiceCapable double that records the options it was handed and
    yields role-tagged responses for one turn."""

    def __init__(self, responses=None):
        self.calls = []
        self._responses = responses or [
            LiveVoiceResponse(
                text="what's the weather", role="user",
                turn_id="turn-1", is_complete=False,
            ),
            LiveVoiceResponse(
                text="It's sunny.", role="assistant",
                turn_id="turn-1", is_complete=True,
            ),
        ]

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return False

    async def stream_voice(self, audio_iterator=None, system_prompt=None,
                            session_id=None, user_id=None, stt_only=False,
                            options=None, **kwargs):
        self.calls.append(options)
        for resp in self._responses:
            yield resp


class _FakeConversationMemory:
    """Minimal conversation-memory double recording every saved turn."""

    def __init__(self):
        self.turns = []

    async def add_turn(self, user_id, session_id, turn, chatbot_id=None):
        self.turns.append(turn)

    async def get_history(self, user_id, session_id, chatbot_id=None):
        """No prior history — ask_stream() only uses this to build an
        optional conversation_context string, harmless when None."""
        return

    async def last_turn(self):
        return self.turns[-1]


async def _drain(async_gen):
    return [r async for r in async_gen]


class TestProjection:
    async def test_uses_to_stream_options(self):
        bot = VoiceBot(voice_config=VoiceConfig(max_tokens=4096))
        bot._llm = _RecordingClient()
        await _drain(bot.ask_stream(b""))
        assert bot._llm.calls[0].max_tokens == 4096

    async def test_explicit_kwargs_win(self):
        bot = VoiceBot(voice_config=VoiceConfig(temperature=0.7))
        bot._llm = _RecordingClient()
        await _drain(bot.ask_stream(b"", temperature=0.1))
        assert bot._llm.calls[0].temperature == 0.1

    async def test_options_is_projected_from_voice_config(self):
        bot = VoiceBot(voice_config=VoiceConfig(top_p=0.42, voice_name="Charon"))
        bot._llm = _RecordingClient()
        await _drain(bot.ask_stream(b""))
        opts = bot._llm.calls[0]
        assert opts.top_p == 0.42
        assert opts.voice == "Charon"

    async def test_stt_only_still_reaches_client(self):
        """stt_only travels as its own stream_voice() kwarg, not through
        the options object — verified via the call being made without error
        and stt_only=True not raising."""
        bot = VoiceBot(voice_config=VoiceConfig())
        client = _RecordingClient()
        bot._llm = client
        await _drain(bot.ask_stream(b"", stt_only=True))
        assert len(client.calls) == 1

    async def test_arbitrary_extra_kwargs_do_not_raise(self):
        """initial_context/use_vectors/ctx (consumed earlier in ask_stream)
        must not be forwarded to to_stream_options(), which would raise on
        an unrecognized field name."""
        bot = VoiceBot(voice_config=VoiceConfig())
        bot._llm = _RecordingClient()
        await _drain(bot.ask_stream(b"", initial_context="hi", use_vectors=False))


class TestVoicePassthrough:
    def test_nova_does_not_receive_puck(self):
        """Regression for bots/voice.py:198 (pre-TASK-2173)."""
        bot = VoiceBot(voice_config=VoiceConfig(provider="nova"))
        cfg = bot._resolve_llm_config()
        assert cfg.extra.get("voice_id") != "Puck"

    def test_nova_extra_has_no_voice_id_key_by_default(self):
        """The native voice now flows through per-call VoiceStreamOptions,
        not the constructor-level extra['voice_id'] — NovaClient's own
        constructor default ("matthew") applies unless explicitly
        overridden via a voice_id kwarg."""
        bot = VoiceBot(voice_config=VoiceConfig(provider="nova"))
        cfg = bot._resolve_llm_config()
        assert "voice_id" not in cfg.extra

    def test_explicit_voice_id_kwarg_still_flows_through(self):
        bot = VoiceBot(voice_config=VoiceConfig(provider="nova"))
        cfg = bot._resolve_llm_config(voice_id="tiffany")
        assert cfg.extra.get("voice_id") == "tiffany"

    async def test_native_voice_flows_through_options(self):
        """The native Gemini voice_name still reaches the per-call
        options object (VoiceStreamOptions.voice), regardless of
        provider — the client validates/normalizes it."""
        bot = VoiceBot(voice_config=VoiceConfig(provider="nova", voice_name="matthew"))
        bot._llm = _RecordingClient()
        await _drain(bot.ask_stream(b""))
        assert bot._llm.calls[0].voice == "matthew"


class TestMemoryFromRole:
    async def test_user_turn_persisted_from_role(self):
        """CRITICAL regression: bots/voice.py:583-584 read a key that no
        longer exists after TASK-2167. Without this migration, user turns
        persist EMPTY — silent data loss, no crash, no error log."""
        bot = VoiceBot(voice_config=VoiceConfig())
        bot._llm = _RecordingClient()
        bot.conversation_memory = _FakeConversationMemory()
        await _drain(bot.ask_stream(b""))
        turn = await bot.conversation_memory.last_turn()
        assert turn.user_message == "what's the weather"

    async def test_assistant_turn_persisted_from_role(self):
        bot = VoiceBot(voice_config=VoiceConfig())
        bot._llm = _RecordingClient()
        bot.conversation_memory = _FakeConversationMemory()
        await _drain(bot.ask_stream(b""))
        turn = await bot.conversation_memory.last_turn()
        assert turn.assistant_response == "It's sunny."

    async def test_no_metadata_transcription_keys_needed(self):
        """Responses carrying NO metadata at all still persist correctly
        — role/text alone drive memory now, not metadata."""
        responses = [
            LiveVoiceResponse(text="hello", role="user", turn_id="t1", metadata={}),
            LiveVoiceResponse(text="hi there", role="assistant", turn_id="t1",
                               is_complete=True, metadata={}),
        ]
        bot = VoiceBot(voice_config=VoiceConfig())
        bot._llm = _RecordingClient(responses=responses)
        bot.conversation_memory = _FakeConversationMemory()
        await _drain(bot.ask_stream(b""))
        turn = await bot.conversation_memory.last_turn()
        assert turn.user_message == "hello"
        assert turn.assistant_response == "hi there"

    async def test_role_none_frames_ignored(self):
        """A frame with role=None (e.g. a tool_call or turn_complete
        marker) contributes nothing to either transcript."""
        responses = [
            LiveVoiceResponse(text="hello", role="user", turn_id="t1"),
            LiveVoiceResponse(text="", role=None, turn_id="t1", is_complete=True),
        ]
        bot = VoiceBot(voice_config=VoiceConfig())
        bot._llm = _RecordingClient(responses=responses)
        bot.conversation_memory = _FakeConversationMemory()
        await _drain(bot.ask_stream(b""))
        turn = await bot.conversation_memory.last_turn()
        assert turn.user_message == "hello"
        assert turn.assistant_response == ""
