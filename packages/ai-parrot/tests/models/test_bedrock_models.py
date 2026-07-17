"""Unit tests for the Nova / multi-provider extensions to
``parrot.models.bedrock_models`` (FEAT-302, TASK-1744).

Complements the existing Claude-focused suite at
``packages/ai-parrot/tests/test_bedrock_models.py`` (TASK-1514) with
coverage for Amazon Nova model IDs and the ``amazon.`` pass-through prefix.
"""
from parrot.models.bedrock_models import translate, _is_bedrock_id


class TestBedrockModelTranslateNova:
    def test_nova_sonic_v1(self):
        assert translate("nova-sonic") == "amazon.nova-sonic-v1:0"

    def test_nova_2_sonic(self):
        assert translate("nova-2-sonic") == "amazon.nova-2-sonic-v1:0"

    def test_nova_2_sonic_with_region(self):
        assert translate("nova-2-sonic", region_prefix="us") == "us.amazon.nova-2-sonic-v1:0"

    def test_passthrough_amazon_id(self):
        assert translate("amazon.nova-2-sonic-v1:0") == "amazon.nova-2-sonic-v1:0"

    def test_is_bedrock_id_amazon(self):
        assert _is_bedrock_id("amazon.nova-sonic-v1:0") is True

    def test_nova_pro(self):
        assert translate("nova-pro") == "amazon.nova-pro-v1:0"

    def test_nova_lite(self):
        assert translate("nova-lite") == "amazon.nova-lite-v1:0"

    def test_nova_micro(self):
        assert translate("nova-micro") == "amazon.nova-micro-v1:0"


class TestBedrockModelTranslateNovaFeat315:
    """New Nova Premier/Canvas/Reel entries (FEAT-315, TASK-1810)."""

    def test_nova_premier(self):
        assert translate("nova-premier") == "amazon.nova-premier-v1:0"

    def test_nova_premier_with_region(self):
        assert translate("nova-premier", region_prefix="us") == "us.amazon.nova-premier-v1:0"

    def test_nova_canvas(self):
        assert translate("nova-canvas") == "amazon.nova-canvas-v1:0"

    def test_nova_reel(self):
        assert translate("nova-reel") == "amazon.nova-reel-v1:0"

    def test_nova_canvas_with_region_still_prefixes(self):
        # Canvas/Reel are in-region only, but translate() itself has no
        # knowledge of that constraint — it is the caller's (NovaClient's)
        # responsibility not to pass a region_prefix for these models.
        assert translate("nova-canvas", region_prefix="us") == "us.amazon.nova-canvas-v1:0"
