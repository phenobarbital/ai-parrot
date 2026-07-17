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
