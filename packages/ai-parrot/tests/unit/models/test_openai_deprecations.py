"""Unit tests for OpenAIModel catalog refresh and deprecation registry.

Spec: sdd/specs/openai-model-deprecation.spec.md §4
Implements: TASK-942
"""
from datetime import date
import inspect
import warnings

import pytest

from parrot.models.openai import (
    OpenAIModel,
    DeprecationInfo,
    DEPRECATIONS,
    is_deprecated,
    get_shutoff_date,
    resolve_alias,
)


class TestCatalog:
    """Tests for the refreshed OpenAIModel enum."""

    def test_enum_contains_only_current_models(self):
        """Every OpenAIModel value must not appear as a direct DEPRECATIONS key.

        A current member CAN legitimately be the alias target of a deprecated
        dated source (e.g. ``gpt-4.1-nano-2025-04-14`` aliases the still-alive
        ``gpt-4.1-nano``); see spec §7. The is_deprecated() helper handles
        this by skipping alias-matches that resolve to a current enum value.
        """
        for member in OpenAIModel:
            assert member.value not in DEPRECATIONS, (
                f"{member.name} ({member.value}) is a direct key in DEPRECATIONS"
            )

    def test_enum_matches_upstream_catalog_snapshot(self, upstream_current_models):
        """The enum values must exactly equal the upstream catalog snapshot."""
        assert {m.value for m in OpenAIModel} == upstream_current_models

    def test_enum_has_26_members(self):
        """Catalog snapshot has exactly 26 models."""
        assert len(list(OpenAIModel)) == 26


class TestDeprecationsDict:
    """Tests for the DEPRECATIONS registry."""

    def test_deprecations_dict_shape(self):
        """Every DEPRECATIONS value must be a valid DeprecationInfo."""
        for key, info in DEPRECATIONS.items():
            assert isinstance(info, DeprecationInfo), (
                f"DEPRECATIONS[{key!r}] is not a DeprecationInfo"
            )
            assert isinstance(info.shutoff, date), (
                f"DEPRECATIONS[{key!r}].shutoff is not a date"
            )
            if info.alias is not None:
                assert isinstance(info.alias, str), (
                    f"DEPRECATIONS[{key!r}].alias is not a str"
                )

    def test_deprecations_has_50_entries(self):
        """Registry must contain exactly 50 entries."""
        assert len(DEPRECATIONS) == 50, (
            f"Expected 50 DEPRECATIONS entries, got {len(DEPRECATIONS)}"
        )


class TestHelpers:
    """Tests for is_deprecated, get_shutoff_date, resolve_alias."""

    @pytest.mark.parametrize("model", [
        "gpt-4-turbo-2024-04-09",   # direct key
        "gpt-4-turbo",              # alias of above
        "gpt-3.5-turbo-0125",       # direct key
        "gpt-3.5-turbo",            # direct key (bare alias entry)
    ])
    def test_is_deprecated_true(self, model):
        assert is_deprecated(model) is True

    @pytest.mark.parametrize("model", [
        "gpt-5-mini",
        "gpt-4.1",
        "o3",
        "gpt-4o-mini",
    ])
    def test_is_deprecated_false(self, model):
        assert is_deprecated(model) is False

    def test_is_deprecated_recognises_dated_id(self):
        assert is_deprecated("gpt-4-turbo-2024-04-09") is True

    def test_is_deprecated_recognises_alias(self):
        assert is_deprecated("gpt-4-turbo") is True

    def test_is_deprecated_passes_current_id(self):
        assert is_deprecated("gpt-5-mini") is False

    def test_is_deprecated_skips_alive_alias(self):
        """An alias that is itself a current enum member must not be flagged.

        gpt-4.1-nano is the alias of the deprecated dated source
        gpt-4.1-nano-2025-04-14, but the alias remains alive upstream
        (spec §7). is_deprecated must return False for it.
        """
        assert "gpt-4.1-nano" in {m.value for m in OpenAIModel}
        assert is_deprecated("gpt-4.1-nano") is False

    def test_is_deprecated_accepts_enum_member(self):
        assert is_deprecated(OpenAIModel.GPT5_MINI) is False

    def test_get_shutoff_date_returns_iso_date(self):
        assert get_shutoff_date("gpt-3.5-turbo-0125") == date(2026, 10, 23)

    def test_get_shutoff_date_returns_none_for_current(self):
        assert get_shutoff_date("gpt-5-mini") is None

    def test_get_shutoff_date_alias_path(self):
        """get_shutoff_date should work for alias strings too."""
        assert get_shutoff_date("gpt-4-turbo") == date(2026, 10, 23)

    def test_resolve_alias_returns_migration_target(self):
        """resolve_alias uses interpretation (b): deprecated → gpt-5-mini."""
        assert resolve_alias("gpt-4-turbo") == "gpt-5-mini"

    def test_resolve_alias_pass_through_for_current(self):
        assert resolve_alias("gpt-5-mini") == "gpt-5-mini"
        assert resolve_alias("gpt-4.1") == "gpt-4.1"

    def test_resolve_alias_accepts_enum_member(self):
        assert resolve_alias(OpenAIModel.GPT5_MINI) == "gpt-5-mini"


class TestNormalizeModel:
    """Tests for OpenAIClient._normalize_model warning behaviour."""

    def test_emits_warning_once(self):
        """Calling _normalize_model with a deprecated ID emits exactly one warning."""
        from parrot.clients import gpt as gpt_mod
        gpt_mod._warned.clear()

        client = gpt_mod.OpenAIClient(api_key="dummy")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = client._normalize_model("gpt-4-turbo")
            assert result == "gpt-4-turbo"
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
            # second call — must be silent
            client._normalize_model("gpt-4-turbo")
            assert len(w) == 1, "Second call should not emit another warning"

    def test_silent_for_current_id(self):
        """_normalize_model must emit no warning for a current model."""
        from parrot.clients import gpt as gpt_mod
        gpt_mod._warned.clear()

        client = gpt_mod.OpenAIClient(api_key="dummy")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            client._normalize_model("gpt-5-mini")
            assert len(w) == 0


class TestDefaults:
    """Tests for migrated default values."""

    def test_openaiclient_default_is_gpt5_mini(self):
        """OpenAIClient class-level defaults must be gpt-5-mini."""
        from parrot.clients.gpt import OpenAIClient
        assert OpenAIClient.model == "gpt-5-mini"
        assert OpenAIClient._default_model == "gpt-5-mini"

    def test_chat_handler_no_gpt4_turbo_literal(self):
        """The chat handler module source must not contain 'gpt-4-turbo' literals."""
        from parrot.handlers import chat
        src = inspect.getsource(chat)
        assert '"gpt-4-turbo"' not in src, (
            "Found deprecated literal 'gpt-4-turbo' in handlers/chat.py"
        )

    def test_loaders_abstract_default_model_name(self):
        """The token-splitter default must be gpt-4.1-mini."""
        from parrot.loaders.abstract import AbstractLoader
        sig = inspect.signature(AbstractLoader._get_token_splitter)
        default = sig.parameters["model_name"].default
        assert default == "gpt-4.1-mini", (
            f"Expected 'gpt-4.1-mini', got {default!r}"
        )


class TestPartitionedListing:
    """Tests for LLMClient._get_supported_models partitioned return."""

    def test_llm_handler_active_deprecated_partition(self):
        """_get_supported_models('openai') must return a partitioned dict."""
        from parrot.handlers.llm import LLMClient
        inst = LLMClient.__new__(LLMClient)
        out = inst._get_supported_models("openai")
        assert isinstance(out, dict), f"Expected dict, got {type(out)}"
        assert set(out.keys()) == {"active", "deprecated"}
        assert "gpt-5-mini" in out["active"]
        assert "gpt-3.5-turbo-0125" in out["deprecated"]

    def test_llm_handler_azure_partition(self):
        """azure provider also returns partitioned dict."""
        from parrot.handlers.llm import LLMClient
        inst = LLMClient.__new__(LLMClient)
        out = inst._get_supported_models("azure")
        assert isinstance(out, dict)
        assert set(out.keys()) == {"active", "deprecated"}

    def test_llm_handler_groq_flat_list(self):
        """groq provider still returns a flat list."""
        from parrot.handlers.llm import LLMClient
        inst = LLMClient.__new__(LLMClient)
        out = inst._get_supported_models("groq")
        assert isinstance(out, list)

    def test_llm_handler_unknown_returns_empty(self):
        """Unknown provider returns empty list."""
        from parrot.handlers.llm import LLMClient
        inst = LLMClient.__new__(LLMClient)
        out = inst._get_supported_models("unknown")
        assert out == []
