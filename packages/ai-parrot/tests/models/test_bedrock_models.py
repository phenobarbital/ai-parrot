"""Unit tests for the Nova / multi-provider extensions to
``parrot.models.bedrock_models`` (FEAT-302, TASK-1744).

Complements the existing Claude-focused suite at
``packages/ai-parrot/tests/test_bedrock_models.py`` (TASK-1514) with
coverage for Amazon Nova model IDs and the ``amazon.`` pass-through prefix.

Also covers Module 1 of FEAT-405 (TASK-2083): the 2026-generation model-ID
translation — ``au.``/``global.`` prefixes, ``minimax.``/``zai.``/
``moonshotai.`` vendor-namespace pass-through, the suffix-less Claude Opus 5
/ Fable 5 map entries, and the ``REQUIRES_REGION_PREFIX`` allowlist
inversion that keeps ``region_prefix`` from leaking onto prefix-less vendor
models (the day-one bug, [R6]).
"""
import pytest
from parrot.models.bedrock_models import (
    PUBLIC_TO_BEDROCK,
    REQUIRES_REGION_PREFIX,
    _is_bedrock_id,
    translate,
)


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


class TestPrefixPolicy:
    """FEAT-405 [R6]: REQUIRES_REGION_PREFIX is an ALLOWLIST inversion."""

    def test_unmapped_model_never_prefixed(self):
        """THE day-one bug: region_prefix must not leak onto MiniMax."""
        assert translate("minimax.minimax-m2.5", region_prefix="us") == "minimax.minimax-m2.5"

    @pytest.mark.parametrize("model_id", ["moonshotai.kimi-k2.5", "zai.glm-5"])
    def test_other_prefixless_models(self, model_id):
        assert translate(model_id, region_prefix="us") == model_id

    def test_mapped_model_uses_caller_prefix(self):
        assert translate("claude-opus-5", region_prefix="eu").startswith("eu.")

    def test_mapped_model_falls_back_to_map_default(self):
        assert "claude-opus-5" in REQUIRES_REGION_PREFIX
        assert translate("claude-opus-5").startswith(
            f"{REQUIRES_REGION_PREFIX['claude-opus-5']}."
        )

    def test_explicit_prefix_on_unmapped_model_warns(self, caplog):
        with caplog.at_level("WARNING", logger="parrot.models.bedrock_models"):
            result = translate("minimax.minimax-m2.5", region_prefix="us")
        assert result == "minimax.minimax-m2.5"
        assert any("prefix" in r.message.lower() for r in caplog.records)

    @pytest.mark.parametrize(
        "already_prefixed_id",
        [
            "us.anthropic.claude-opus-5",
            "us.anthropic.claude-haiku-4-5-20251001-v1:0",
            "global.anthropic.claude-fable-5",
        ],
    )
    def test_explicit_prefix_on_already_prefixed_id_does_not_warn(
        self, already_prefixed_id, caplog
    ):
        """Code-review fix: a model's OWN verified default id (already
        region-prefixed, e.g. NovaAdversarialReviewProfile/
        NovaMechanicalProfile's defaults) must not spam a false-positive
        'ignoring the prefix' warning just because a caller (e.g.
        NovaClient's own region_prefix="us" default) also happens to pass
        region_prefix="us" redundantly — the id is already fully resolved."""
        with caplog.at_level("WARNING", logger="parrot.models.bedrock_models"):
            result = translate(already_prefixed_id, region_prefix="us")
        assert result == already_prefixed_id
        assert not [r for r in caplog.records if r.levelname == "WARNING"]


class TestPassThrough:
    """Recognised region prefixes and vendor namespaces."""

    @pytest.mark.parametrize("prefix", ["us.", "eu.", "apac.", "au.", "global."])
    def test_known_prefixes_pass_through(self, prefix):
        already = f"{prefix}anthropic.claude-opus-5"
        assert translate(already) == already

    @pytest.mark.parametrize("model_id", [
        "minimax.minimax-m2.5", "zai.glm-5", "moonshotai.kimi-k2.5",
    ])
    def test_vendor_namespaces_no_warning(self, model_id, caplog):
        with caplog.at_level("WARNING", logger="parrot.models.bedrock_models"):
            assert translate(model_id) == model_id
        assert not [r for r in caplog.records if r.levelname == "WARNING"]


class TestNewMapEntries:
    """Claude Opus 5 / Fable 5 — 2026 generation, no ``-vN:0`` suffix."""

    def test_opus5_bedrock_id_has_no_version_suffix(self):
        assert PUBLIC_TO_BEDROCK["claude-opus-5"] == "anthropic.claude-opus-5"

    def test_fable5_bedrock_id_has_no_version_suffix(self):
        assert PUBLIC_TO_BEDROCK["claude-fable-5"] == "anthropic.claude-fable-5"

    def test_opus5_default_prefix_applied(self):
        # No explicit region_prefix -> REQUIRES_REGION_PREFIX default kicks
        # in ("us" for Opus 5), and the suffix-less base id is preserved.
        assert translate("claude-opus-5") == "us.anthropic.claude-opus-5"

    def test_fable5_default_prefix_applied(self):
        assert translate("claude-fable-5") == "global.anthropic.claude-fable-5"
        assert "-v1:0" not in translate("claude-fable-5")

    def test_unknown_id_warns_and_passes_through(self, caplog):
        with caplog.at_level("WARNING", logger="parrot.models.bedrock_models"):
            assert translate("totally-made-up-model") == "totally-made-up-model"
        assert any(r.levelname == "WARNING" for r in caplog.records)
