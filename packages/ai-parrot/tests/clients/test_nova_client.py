"""Unit tests for NovaClient composition (FEAT-315, TASK-1809).

Verifies the MRO/defaults, that text methods are inherited (not
delegated), and that voice/generation capabilities are present on
instances — no real AWS credentials or network access required.
"""
from parrot.clients.bedrock import BedrockConverseBase
from parrot.clients.nova import NovaClient
from parrot.clients.nova.audio import NovaAudio
from parrot.clients.nova.generation import NovaGeneration


class TestNovaClientComposition:
    def test_defaults(self):
        c = NovaClient()
        assert c.client_type == "nova"
        assert c._translate_model(None) == "us.amazon.nova-2-lite-v1:0"

    def test_region_prefix_opt_out(self):
        c = NovaClient(region_prefix=None)
        assert c._translate_model(None) == "amazon.nova-2-lite-v1:0"

    def test_text_methods_inherited_not_delegated(self):
        assert NovaClient.ask is BedrockConverseBase.ask
        assert NovaClient.ask_stream is BedrockConverseBase.ask_stream
        assert NovaClient.resume is BedrockConverseBase.resume
        assert NovaClient.invoke is BedrockConverseBase.invoke
        assert not hasattr(NovaClient(), "_text_client")
        assert not hasattr(NovaClient(), "_get_text_client")

    def test_capabilities_present(self):
        c = NovaClient()
        for m in ("stream_voice", "generate_image", "video_generation"):
            assert callable(getattr(c, m))

    def test_voice_id_stored(self):
        assert NovaClient(voice_id="tiffany").voice_id == "tiffany"

    def test_voice_id_default(self):
        assert NovaClient().voice_id == "matthew"

    def test_mro_order(self):
        mro = NovaClient.__mro__
        assert mro.index(NovaClient) < mro.index(BedrockConverseBase)
        assert mro.index(BedrockConverseBase) < mro.index(NovaAudio)
        assert NovaGeneration in mro

    def test_fallback_model_default(self):
        assert NovaClient()._fallback_model == "nova-lite"

    def test_client_name(self):
        assert NovaClient().client_name == "nova"


class TestInRegionModelsNeverGetRegionPrefix:
    """Code-review regression guard (FEAT-315): NovaClient's default
    region_prefix="us" (needed for the Nova 2 Lite/Premier TEXT models,
    which have no in-region access) must NOT leak into Nova Canvas / Nova
    Reel / Nova Sonic model-ID resolution — those three families are
    in-region only and have no cross-region inference profiles (spec §6
    "Verified AWS Facts"). Exercises the REAL (non-stubbed) NovaClient
    default, unlike test_nova_generation.py's Host stub (which hardcodes
    _translate_model to ignore region_prefix) and test_nova.py's
    stream_voice tests (which mock _open_stream, never asserting the
    resolved model_id argument)."""

    def test_generate_image_default_model_has_no_region_prefix(self):
        c = NovaClient()
        assert c._translate_in_region_model(
            c._default_image_model
        ) == "amazon.nova-canvas-v1:0"

    def test_video_generation_default_model_has_no_region_prefix(self):
        c = NovaClient()
        assert c._translate_in_region_model(
            c._default_video_model
        ) == "amazon.nova-reel-v1:0"

    def test_text_model_still_gets_region_prefix(self):
        """Sanity check: the fix must not remove the prefix from the TEXT
        path, which genuinely needs it (Nova 2 Lite has no in-region access)."""
        c = NovaClient()
        assert c._translate_model(None) == "us.amazon.nova-2-lite-v1:0"
