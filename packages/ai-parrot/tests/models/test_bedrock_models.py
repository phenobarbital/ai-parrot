"""Unit tests for the Nova / multi-provider extensions to
``parrot.clients.amazon.models`` (FEAT-302, TASK-1744).

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
from parrot.clients.amazon.models import (
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
        with caplog.at_level("WARNING", logger="parrot.clients.amazon.models"):
            result = translate("minimax.minimax-m2.5", region_prefix="us")
        assert result == "minimax.minimax-m2.5"
        assert any("prefix" in r.message.lower() for r in caplog.records)

    @pytest.mark.parametrize(
        "already_prefixed_id",
        [
            # The two no-tools Nova seats' current default (FEAT-405 follow-up:
            # migrated off us.anthropic.* — those need a per-account Bedrock
            # Anthropic use-case form; native Nova ids do not).
            "us.amazon.nova-2-lite-v1:0",
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
        with caplog.at_level("WARNING", logger="parrot.clients.amazon.models"):
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
        with caplog.at_level("WARNING", logger="parrot.clients.amazon.models"):
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
        with caplog.at_level("WARNING", logger="parrot.clients.amazon.models"):
            assert translate("totally-made-up-model") == "totally-made-up-model"
        assert any(r.levelname == "WARNING" for r in caplog.records)


class TestUnprefixedIdRepair:
    """A Bedrock-shaped ID that is not usable as written must be repaired.

    Both spellings below were rejected by the Converse API with
    ``ValidationException: The provided model identifier is invalid`` when the
    pass-through branch returned them verbatim — the failure that broke the
    ``bedrock-converse`` sample agents.
    """

    def test_namespaced_public_id_is_resolved(self):
        """``anthropic.<public-id>`` gains its version suffix AND prefix."""
        assert (
            translate("anthropic.claude-haiku-4-5")
            == "us.anthropic.claude-haiku-4-5-20251001-v1:0"
        )

    def test_namespaced_public_id_honours_explicit_prefix(self):
        assert (
            translate("anthropic.claude-haiku-4-5", region_prefix="eu")
            == "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
        )

    def test_bare_base_id_gains_required_prefix(self):
        """A base ID whose model has no in-region access gets its prefix."""
        assert translate("anthropic.claude-opus-5") == "us.anthropic.claude-opus-5"
        assert (
            translate("anthropic.claude-fable-5") == "global.anthropic.claude-fable-5"
        )

    def test_complete_base_id_still_passes_through(self):
        """A valid, prefix-free base ID must NOT be rewritten."""
        bid = "anthropic.claude-sonnet-4-5-20250929-v1:0"
        assert translate(bid) == bid

    def test_already_prefixed_id_untouched(self):
        for bid in (
            "us.anthropic.claude-opus-5",
            "us.anthropic.claude-haiku-4-5-20251001-v1:0",
            "global.anthropic.claude-fable-5",
        ):
            assert translate(bid) == bid

    def test_vendor_namespace_never_repaired(self):
        for bid in ("minimax.minimax-m2.5", "zai.glm-5", "moonshotai.kimi-k2.5"):
            assert translate(bid) == bid

    def test_amazon_namespaced_public_id_is_resolved(self):
        assert translate("amazon.nova-2-lite") == "amazon.nova-2-lite-v1:0"

    def test_arn_never_repaired(self):
        arn = "arn:aws:bedrock:us-east-1::inference-profile/us.anthropic.claude-x"
        assert translate(arn) == arn

    def test_no_version_suffix_is_ever_guessed(self, caplog):
        """An unknown model is passed through, never string-munged."""
        with caplog.at_level("WARNING", logger="parrot.clients.amazon.models"):
            assert (
                translate("anthropic.claude-not-a-real-model")
                == "anthropic.claude-not-a-real-model"
            )


class TestThirdPartyBedrockModels:
    """Qwen3 Coder / GLM 5 / Kimi K2.5 / Llama 4 Maverick map entries.

    Each has a different prefixing rule, and the two Bedrock endpoints do not
    always agree on the ID — the sample agents in ``examples/agents/aws/``
    depend on the first three resolving correctly. Llama 4 Maverick is
    map-only (no sample ships: Meta geo-restricts it by caller location).
    """

    def test_llama4_maverick_is_geo_only(self):
        """No in-region access exists — the ``us.`` profile is mandatory."""
        assert REQUIRES_REGION_PREFIX["llama4-maverick-17b-instruct"] == "us"
        assert (
            translate("llama4-maverick-17b-instruct")
            == "us.meta.llama4-maverick-17b-instruct-v1:0"
        )

    @pytest.mark.parametrize("spelling", [
        "meta.llama4-maverick-17b-instruct",
        "meta.llama4-maverick-17b-instruct-v1:0",
    ])
    def test_llama4_namespaced_spellings_gain_the_prefix(self, spelling):
        """``meta.`` is prefixable, so a bare id must be repaired, not passed."""
        assert translate(spelling) == "us.meta.llama4-maverick-17b-instruct-v1:0"

    def test_llama4_already_prefixed_id_untouched(self):
        bid = "us.meta.llama4-maverick-17b-instruct-v1:0"
        assert translate(bid) == bid

    def test_qwen3_coder_runtime_id(self):
        """The public id maps to the bedrock-runtime (Converse) id."""
        assert (
            translate("qwen3-coder-480b-a35b") == "qwen.qwen3-coder-480b-a35b-v1:0"
        )

    def test_qwen3_coder_is_never_prefixed(self):
        """In-region only — no geo/global profile, so no prefix is added."""
        assert "qwen3-coder-480b-a35b" not in REQUIRES_REGION_PREFIX
        bid = "qwen.qwen3-coder-480b-a35b-v1:0"
        assert translate(bid) == bid

    def test_qwen3_coder_mantle_id_passes_through_verbatim(self, caplog):
        """The Mantle id differs from the runtime id and must NOT be rewritten."""
        mantle_id = "qwen.qwen3-coder-480b-a35b-instruct"
        with caplog.at_level("WARNING", logger="parrot.clients.amazon.models"):
            assert translate(mantle_id) == mantle_id
        assert not [r for r in caplog.records if r.levelname == "WARNING"]

    def test_glm5_same_id_on_both_endpoints(self):
        assert PUBLIC_TO_BEDROCK["glm-5"] == "zai.glm-5"
        assert translate("glm-5") == "zai.glm-5"
        assert translate("zai.glm-5") == "zai.glm-5"

    def test_glm5_is_never_prefixed(self):
        assert "glm-5" not in REQUIRES_REGION_PREFIX
        assert translate("zai.glm-5", region_prefix="us") == "zai.glm-5"

    def test_kimi_k25_same_id_on_both_endpoints(self):
        assert PUBLIC_TO_BEDROCK["kimi-k2.5"] == "moonshotai.kimi-k2.5"
        assert translate("kimi-k2.5") == "moonshotai.kimi-k2.5"
        assert translate("moonshotai.kimi-k2.5") == "moonshotai.kimi-k2.5"

    def test_kimi_k25_is_never_prefixed(self):
        assert "kimi-k2.5" not in REQUIRES_REGION_PREFIX
        assert translate("moonshotai.kimi-k2.5", region_prefix="us") == (
            "moonshotai.kimi-k2.5"
        )

    def test_qwen_namespace_recognised_as_bedrock_shaped(self):
        assert _is_bedrock_id("qwen.qwen3-coder-480b-a35b-v1:0") is True
        assert _is_bedrock_id("meta.llama4-maverick-17b-instruct-v1:0") is True
