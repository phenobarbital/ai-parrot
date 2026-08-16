"""Provider conformance kit — parametrized drop-in parity suite (FEAT-418,
TASK-2176 — spec §3 Module 9).

Turns "drop-in" from a claim into a test that fails when it regresses.
Parametrized over every declared VoiceCapable implementation
(conftest.py's PROVIDERS) — adding a provider costs exactly one entry
there plus a scenario-event builder pair, not new test bodies.

Mocks at the provider-SDK boundary (see conftest.py) so each client's own
translation logic is actually exercised.
"""
import pytest
from parrot.models.voice import VoiceStreamOptions

from .conftest import build_client, collect_responses, nova_session_start_config

# ---------------------------------------------------------------------
# Cross-provider config extraction (adapts each SDK's own representation
# to a canonical comparable value — NOT a behavioral branch; the
# assertions below never branch on provider).
# ---------------------------------------------------------------------

def _captured_temperature(client, provider_name: str) -> float:
    if provider_name == "gemini":
        return client.captured_configs[-1].temperature
    return nova_session_start_config(client)["temperature"]


def _captured_max_tokens(client, provider_name: str) -> int:
    if provider_name == "gemini":
        return client.captured_configs[-1].max_output_tokens
    return nova_session_start_config(client)["maxTokens"]


def _captured_top_p(client, provider_name: str) -> float:
    if provider_name == "gemini":
        return client.captured_configs[-1].top_p
    return nova_session_start_config(client)["topP"]


class TestOptionsHonored:
    @pytest.mark.asyncio
    async def test_inference_params_reach_provider(self, provider, monkeypatch):
        client = build_client(monkeypatch, provider)
        options = VoiceStreamOptions(temperature=0.33, max_tokens=2048, top_p=0.55)
        await collect_responses(client, options=options)

        assert _captured_temperature(client, provider) == 0.33
        assert _captured_max_tokens(client, provider) == 2048
        assert _captured_top_p(client, provider) == 0.55

    @pytest.mark.asyncio
    async def test_explicit_kwarg_wins_over_options(self, provider, monkeypatch):
        client = build_client(monkeypatch, provider)
        options = VoiceStreamOptions(temperature=0.33)
        await collect_responses(client, options=options, temperature=0.9)

        assert _captured_temperature(client, provider) == 0.9


class TestCanonicalEnvelope:
    @pytest.mark.asyncio
    async def test_roles_are_canonical(self, provider, monkeypatch):
        client = build_client(monkeypatch, provider)
        responses = await collect_responses(client)
        assert {r.role for r in responses if r.role} <= {"user", "assistant"}

    @pytest.mark.asyncio
    async def test_no_legacy_metadata_key(self, provider, monkeypatch):
        client = build_client(monkeypatch, provider)
        responses = await collect_responses(client)
        assert all("user_transcription" not in r.metadata for r in responses)
        assert all("assistant_transcription" not in r.metadata for r in responses)

    @pytest.mark.asyncio
    async def test_user_and_assistant_both_present(self, provider, monkeypatch):
        """Both providers' basic_turn scenario carries one user utterance
        and one assistant reply — both must surface with canonical role."""
        client = build_client(monkeypatch, provider)
        responses = await collect_responses(client)
        roles = {r.role for r in responses if r.text}
        assert roles == {"user", "assistant"}


class TestReconnectSignal:
    @pytest.mark.asyncio
    async def test_limit_emits_reconnect_required(self, provider, monkeypatch):
        client = build_client(monkeypatch, provider, scenario="reconnect")
        responses = await collect_responses(client)
        assert any(r.metadata.get("reconnect_required") for r in responses)


class TestDescriptorHonesty:
    """A descriptor that lies is worse than no descriptor — every declared
    capability must be demonstrated present or absent by actual behavior."""

    @pytest.mark.asyncio
    async def test_supports_per_call_inference_demonstrated(self, provider, monkeypatch):
        caps = build_client(monkeypatch, provider).voice_capabilities
        if not caps.supports_per_call_inference:
            pytest.skip(f"{provider} declares supports_per_call_inference=False")
        client = build_client(monkeypatch, provider)
        await collect_responses(client, temperature=0.11)
        assert _captured_temperature(client, provider) == 0.11

    @pytest.mark.asyncio
    async def test_supports_top_p_demonstrated(self, provider, monkeypatch):
        caps = build_client(monkeypatch, provider).voice_capabilities
        if not caps.supports_top_p:
            pytest.skip(f"{provider} declares supports_top_p=False")
        client = build_client(monkeypatch, provider)
        await collect_responses(client, top_p=0.13)
        assert _captured_top_p(client, provider) == 0.13

    @pytest.mark.asyncio
    async def test_emits_reconnect_signal_demonstrated(self, provider, monkeypatch):
        caps = build_client(monkeypatch, provider).voice_capabilities
        client = build_client(monkeypatch, provider, scenario="reconnect")
        responses = await collect_responses(client)
        emitted = any(r.metadata.get("reconnect_required") for r in responses)
        assert emitted == caps.emits_reconnect_signal

    def test_native_stt_only_matches_provider_reality(self, provider, monkeypatch):
        """Both providers today: Gemini natively suppresses generation
        (native_stt_only=True); Nova always generates
        (native_stt_only=False) — this is a structural fact of each
        provider's API, not exercised via a mocked stream. Asserted
        directly against the known-true value per provider so a future
        accidental flip is caught."""
        caps = build_client(monkeypatch, provider).voice_capabilities
        expected = {"gemini": True, "nova": False}[provider]
        assert caps.native_stt_only is expected

    def test_audio_format_sets_populated(self, provider, monkeypatch):
        caps = build_client(monkeypatch, provider).voice_capabilities
        assert caps.input_formats
        assert caps.output_formats
        assert caps.input_sample_rates
        assert caps.output_sample_rates

    def test_voice_catalog_populated(self, provider, monkeypatch):
        caps = build_client(monkeypatch, provider).voice_capabilities
        assert caps.voice_catalog
        assert caps.default_voice in caps.voice_catalog


class TestDropInEquivalence:
    """Same mocked audio + same VoiceConfig (provider aside) -> same frame
    types in the same order. Payloads may differ (audio bytes, token
    counts); structure may not (spec §4)."""

    @pytest.mark.asyncio
    async def test_role_sequence_structurally_identical(self, monkeypatch):
        gemini_client = build_client(monkeypatch, "gemini")
        nova_client = build_client(monkeypatch, "nova")

        gemini_responses = await collect_responses(gemini_client)
        nova_responses = await collect_responses(nova_client)

        gemini_roles = [r.role for r in gemini_responses if r.text]
        nova_roles = [r.role for r in nova_responses if r.text]

        # Both scenarios script one user utterance followed by one
        # assistant reply — structure (role sequence), not payload bytes,
        # must match.
        assert gemini_roles == ["user", "assistant"]
        assert nova_roles == ["user", "assistant"]
        assert gemini_roles == nova_roles

    @pytest.mark.asyncio
    async def test_metadata_never_carries_legacy_keys_either_provider(self, monkeypatch):
        gemini_client = build_client(monkeypatch, "gemini")
        nova_client = build_client(monkeypatch, "nova")

        for client in (gemini_client, nova_client):
            responses = await collect_responses(client)
            for r in responses:
                assert "user_transcription" not in r.metadata
                assert "assistant_transcription" not in r.metadata
