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
