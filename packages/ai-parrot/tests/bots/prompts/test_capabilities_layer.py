"""Unit tests for CAPABILITIES_LAYER and the "identity" preset (FEAT-321)."""
from parrot.bots.prompts.builder import PromptBuilder
from parrot.bots.prompts.domain_layers import CAPABILITIES_LAYER, get_domain_layer
from parrot.bots.prompts.layers import LayerPriority, RenderPhase
from parrot.bots.prompts.presets import get_preset


class TestCapabilitiesLayer:
    def test_registered(self):
        assert get_domain_layer("capabilities") is CAPABILITIES_LAYER

    def test_layer_metadata(self):
        assert CAPABILITIES_LAYER.priority == LayerPriority.IDENTITY + 1
        assert CAPABILITIES_LAYER.phase is RenderPhase.CONFIGURE
        assert CAPABILITIES_LAYER.cacheable is True

    def test_renders_capabilities(self):
        out = CAPABILITIES_LAYER.render({"capabilities": "- do X"})
        assert out == "<capabilities>\n- do X\n</capabilities>"

    def test_empty_capabilities_skipped(self):
        assert CAPABILITIES_LAYER.render({"capabilities": "  "}) is None
        assert CAPABILITIES_LAYER.render({}) is None


class TestIdentityPreset:
    def test_identity_preset_stack(self):
        builder = get_preset("identity")
        assert builder.get("capabilities") is not None
        assert builder.get("identity") is not None  # default stack present

    def test_fresh_builder_per_call(self):
        assert get_preset("identity") is not get_preset("identity")

    def test_default_unchanged(self):
        assert PromptBuilder.default().get("capabilities") is None
