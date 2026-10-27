"""FEAT-761 TASK-4826 — registry names + security preset."""
import os
import subprocess
import sys
from typing import Any, ClassVar

import pytest

from parrot.bots.guardrails import registry
from parrot.bots.guardrails.base import Guardrail, GuardrailStage
from parrot.bots.guardrails.config import build_pipelines_from_config
from parrot.bots.guardrails.registry import GUARDRAIL_PRESETS, build_guardrails, expand_presets


class StubGuardrail(Guardrail):
    """Minimal guardrail used to exercise preset construction."""

    stages: ClassVar[set[GuardrailStage]] = {GuardrailStage.INPUT}
    priority = 50

    def __init__(self, name: str, kwargs: dict[str, Any]) -> None:
        self.name = name
        self.kwargs = kwargs

    async def check(self, content: str, ctx: Any) -> Any:
        """Return no verdict because these tests never execute a pipeline."""
        return None


@pytest.fixture
def stub_factories(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[dict[str, Any]]]:
    """Replace security-member factories with recording test doubles."""
    calls: dict[str, list[dict[str, Any]]] = {
        "prompt_injection": [],
        "jailbreak": [],
        "prompt_leakage": [],
    }

    for name in calls:

        def factory(*, _name: str = name, **kwargs: Any) -> Guardrail:
            calls[_name].append(kwargs)
            return StubGuardrail(_name, kwargs)

        monkeypatch.setitem(registry._GUARDRAIL_FACTORIES, name, factory)

    return calls


def test_security_preset_members() -> None:
    """The security preset expands to all v1 security guardrails in order."""
    assert GUARDRAIL_PRESETS["security"] == (
        "prompt_injection",
        "jailbreak",
        "prompt_leakage",
    )
    assert expand_presets(["security"]) == [
        "prompt_injection",
        "jailbreak",
        "prompt_leakage",
    ]


def test_explicit_member_wins_without_duplicates() -> None:
    """Explicit member policy replaces the corresponding preset default."""
    configured_jailbreak = {"name": "jailbreak", "threshold": 0.75}
    expanded = expand_presets(["security", configured_jailbreak, "secrets"])

    assert expanded == [
        "prompt_injection",
        "prompt_leakage",
        configured_jailbreak,
        "secrets",
    ]
    assert expand_presets(expanded) == expanded


def test_dict_form_preset_is_rejected() -> None:
    """Preset-level policy is rejected in favor of member-level policy."""
    with pytest.raises(ValueError, match="preset 'security'.*members explicitly"):
        expand_presets([{"name": "security", "threshold": 0.5}])


def test_build_guardrails_constructs_all_security_members(
    stub_factories: dict[str, list[dict[str, Any]]],
) -> None:
    """Building the preset constructs each member exactly once."""
    built = build_guardrails(["security"])

    assert [guardrail.name for guardrail in built] == [
        "prompt_injection",
        "jailbreak",
        "prompt_leakage",
    ]
    assert stub_factories == {
        "prompt_injection": [{}],
        "jailbreak": [{}],
        "prompt_leakage": [{}],
    }


def test_security_preset_deduplicates_legacy_injection_flag(
    stub_factories: dict[str, list[dict[str, Any]]],
) -> None:
    """Legacy injection detection does not add a second prompt guardrail."""
    pipelines = build_pipelines_from_config(
        guardrails=["security"],
        legacy_flags={"injection_detection": True},
    )

    assert len(stub_factories["prompt_injection"]) == 1
    assert [guardrail.name for guardrail in pipelines[GuardrailStage.INPUT]._guardrails] == [
        "prompt_injection",
        "jailbreak",
        "prompt_leakage",
    ]


def test_new_names_are_registered_without_importing_plugins() -> None:
    """Registry import exposes lazy names without importing plugin modules."""
    script = """
import sys
from parrot.bots.guardrails import registry

assert "jailbreak" in registry._GUARDRAIL_FACTORIES
assert "prompt_leakage" in registry._GUARDRAIL_FACTORIES
assert "parrot.bots.guardrails.builtin.jailbreak" not in sys.modules
assert "parrot.bots.guardrails.builtin.prompt_leakage" not in sys.modules
print("lazy-registration-ok")
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(sys.path)
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    assert "lazy-registration-ok" in completed.stdout.splitlines()
