"""Unit coverage for the live opt-in gate and budget resolution (FEAT-581, M6).

Asserts the Scope contract directly against ``parrot.e2e.live``: missing
opt-in flags/credential or an unsupported ``E2E_MODEL``/``E2E_MAX_LLM_CALLS``
override must fail *before* any provider client is constructed -- these
tests monkeypatch ``LLMFactory.create`` to raise if it is ever called, so a
regression that constructs a client too early fails loudly rather than
silently passing.
"""

from __future__ import annotations

import pytest

from parrot.e2e import live as e2e_live
from parrot.e2e.errors import E2EConfigError, E2EPrerequisiteError
from parrot.e2e.models import LiveBudget

try:
    import parrot.clients.google.budget  # noqa: F401

    _has_google_budget = True
except (ImportError, ModuleNotFoundError):
    _has_google_budget = False

_skip_no_google_budget = pytest.mark.skipif(
    not _has_google_budget,
    reason="parrot.clients.google.budget not installed (ai-parrot-client-google satellite)",
)

_FULL_OPT_IN_ENV = {
    e2e_live.PARROT_TEST_E2E_ENV: "1",
    e2e_live.PARROT_TEST_REAL_LLM_ENV: "1",
    e2e_live.GOOGLE_API_KEY_ENV: "fixture-key",
}


def _forbid_client_construction(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict]]:
    """Patch ``LLMFactory.create`` to record any call instead of building a client.

    Returns:
        The list every recorded ``(llm, kwargs)`` call is appended to --
        assert it stays empty to prove zero client construction happened.
    """
    calls: list[tuple[str, dict]] = []

    def _fake_create(llm: str, **kwargs):
        calls.append((llm, kwargs))
        raise AssertionError(f"LLMFactory.create must not be called here (got llm={llm!r})")

    from parrot.clients.factory import LLMFactory

    monkeypatch.setattr(LLMFactory, "create", staticmethod(_fake_create))
    return calls


class TestRequireLiveOptIn:
    """``require_live_opt_in`` gating -- Scope: "Require E2E and real-LLM flags plus
    GOOGLE_API_KEY before constructing client"."""

    def test_missing_e2e_flag_blocks_before_client_construction(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = _forbid_client_construction(monkeypatch)
        env = {**_FULL_OPT_IN_ENV, e2e_live.PARROT_TEST_E2E_ENV: "0"}

        with pytest.raises(E2EPrerequisiteError) as excinfo:
            e2e_live.require_live_opt_in(env=env)

        assert excinfo.value.reason_code == "live_opt_in_missing"
        assert calls == []

    def test_missing_real_llm_flag_blocks_before_client_construction(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = _forbid_client_construction(monkeypatch)
        env = {**_FULL_OPT_IN_ENV, e2e_live.PARROT_TEST_REAL_LLM_ENV: "0"}

        with pytest.raises(E2EPrerequisiteError) as excinfo:
            e2e_live.require_live_opt_in(env=env)

        assert excinfo.value.reason_code == "live_opt_in_missing"
        assert calls == []

    def test_missing_google_api_key_blocks_before_client_construction(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = _forbid_client_construction(monkeypatch)
        env = {
            e2e_live.PARROT_TEST_E2E_ENV: "1",
            e2e_live.PARROT_TEST_REAL_LLM_ENV: "1",
        }

        with pytest.raises(E2EPrerequisiteError) as excinfo:
            e2e_live.require_live_opt_in(env=env)

        assert excinfo.value.reason_code == "live_credential_missing"
        assert calls == []

    def test_full_opt_in_resolves_plan_defaults(self) -> None:
        opt_in = e2e_live.require_live_opt_in(env=_FULL_OPT_IN_ENV)

        default_budget = LiveBudget()
        assert opt_in.model == default_budget.model
        assert opt_in.max_calls == default_budget.max_calls
        assert opt_in.env_overrides == {}

    def test_e2e_model_override_captured_and_applied(self) -> None:
        env = {**_FULL_OPT_IN_ENV, e2e_live.E2E_MODEL_ENV: "google:gemini-3.5-flash-lite"}

        opt_in = e2e_live.require_live_opt_in(env=env)

        assert opt_in.model == "google:gemini-3.5-flash-lite"
        assert opt_in.env_overrides == {e2e_live.E2E_MODEL_ENV: "google:gemini-3.5-flash-lite"}

    def test_e2e_model_override_unsupported_provider_is_config_error(self) -> None:
        env = {**_FULL_OPT_IN_ENV, e2e_live.E2E_MODEL_ENV: "openai:gpt-4o"}

        with pytest.raises(E2EConfigError) as excinfo:
            e2e_live.require_live_opt_in(env=env)

        assert excinfo.value.reason_code == "unsupported_provider"

    def test_e2e_max_llm_calls_override_captured_and_applied(self) -> None:
        env = {**_FULL_OPT_IN_ENV, e2e_live.E2E_MAX_LLM_CALLS_ENV: "2"}

        opt_in = e2e_live.require_live_opt_in(env=env)

        assert opt_in.max_calls == 2
        assert opt_in.env_overrides == {e2e_live.E2E_MAX_LLM_CALLS_ENV: "2"}

    @pytest.mark.parametrize("bad_value", ["not-a-number", "0", "-1"])
    def test_e2e_max_llm_calls_override_invalid_is_config_error(self, bad_value: str) -> None:
        env = {**_FULL_OPT_IN_ENV, e2e_live.E2E_MAX_LLM_CALLS_ENV: bad_value}

        with pytest.raises(E2EConfigError) as excinfo:
            e2e_live.require_live_opt_in(env=env)

        assert excinfo.value.reason_code == "invalid_override"


@_skip_no_google_budget
class TestBuildLiveGenerationBudget:
    """``build_live_generation_budget`` -- one shared budget per resolved opt-in."""

    def test_budget_uses_opt_in_max_calls_and_plan_ceilings(self) -> None:
        opt_in = e2e_live.require_live_opt_in(env={**_FULL_OPT_IN_ENV, e2e_live.E2E_MAX_LLM_CALLS_ENV: "3"})
        plan_budget = LiveBudget(max_output_tokens=256, max_request_bytes=8192, timeout_s=30)

        budget = e2e_live.build_live_generation_budget(opt_in, budget=plan_budget)

        assert budget.max_calls == 3
        assert budget.max_output_tokens == 256
        assert budget.max_request_bytes == 8192
        assert budget.timeout_s == 30
        assert budget.calls_used == 0


@_skip_no_google_budget
class TestBuildLiveClient:
    """``build_live_client`` -- resolves through ``LLMFactory`` only after opt-in succeeded."""

    def test_build_live_client_resolves_pinned_model_with_shared_budget(self, monkeypatch: pytest.MonkeyPatch) -> None:
        opt_in = e2e_live.require_live_opt_in(env=_FULL_OPT_IN_ENV)
        budget = e2e_live.build_live_generation_budget(opt_in)

        captured: dict[str, object] = {}
        sentinel = object()

        def _fake_create(llm: str, **kwargs):
            captured["llm"] = llm
            captured["kwargs"] = kwargs
            return sentinel

        from parrot.clients.factory import LLMFactory

        monkeypatch.setattr(LLMFactory, "create", staticmethod(_fake_create))

        client = e2e_live.build_live_client(opt_in, budget)

        assert client is sentinel
        assert captured["llm"] == opt_in.model
        assert captured["kwargs"] == {"generation_budget": budget}

    def test_build_live_client_constructs_a_real_google_client(self) -> None:
        opt_in = e2e_live.require_live_opt_in(env=_FULL_OPT_IN_ENV)
        budget = e2e_live.build_live_generation_budget(opt_in)

        client = e2e_live.build_live_client(opt_in, budget)

        from parrot.clients.google import GoogleGenAIClient

        assert isinstance(client, GoogleGenAIClient)
        assert client.generation_budget is budget
