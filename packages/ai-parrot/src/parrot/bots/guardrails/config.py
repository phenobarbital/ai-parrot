"""Guardrail configuration coercion — legacy-flag mapping + pipeline building.

Builds the four stage-keyed ``GuardrailPipeline`` instances a bot uses from
two sources: the explicit ``guardrails=[...]`` kwarg and the legacy ctor
flags (``strict_mode``, ``block_on_threat``, ``injection_detection``,
``injection_probability_threshold``, ``enable_redaction``). See
``sdd/specs/guardrails-infrastructure.spec.md`` §2/§3 Module 1 (FEAT-396).
"""
from collections.abc import Callable
from typing import Any

from .base import Guardrail, GuardrailStage
from .pipeline import GuardrailPipeline, GuardrailTelemetryEntry
from .registry import build_guardrails


def _requested_name(item: str | dict[str, Any] | Guardrail) -> str | None:
    """Best-effort extraction of the guardrail name an explicit spec entry requests.

    Used only to avoid double-registering a guardrail the caller already
    requested explicitly via ``guardrails=[...]`` when a legacy flag would
    otherwise add an equivalent one.

    Args:
        item: One entry from the ``guardrails=[...]`` spec list.

    Returns:
        The guardrail name if it can be determined, else ``None``.
    """
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return item.get("name")
    if isinstance(item, Guardrail):
        return getattr(item, "name", None)
    return None


def build_pipelines_from_config(
    guardrails: list[str | dict[str, Any] | Guardrail] | None = None,
    legacy_flags: dict[str, Any] | None = None,
    on_telemetry: Callable[[GuardrailTelemetryEntry], None] | None = None,
) -> dict[GuardrailStage, GuardrailPipeline]:
    """Build one ``GuardrailPipeline`` per stage from bot configuration.

    Legacy-flag mapping:
        - ``injection_detection`` truthy -> registers ``"prompt_injection"``
          (unless already requested explicitly), forwarding ``strict_mode``,
          ``block_on_threat``, and ``injection_probability_threshold`` as
          its policy kwargs.
        - ``enable_redaction`` truthy -> registers ``"secrets"`` (unless
          already requested explicitly).

    The explicit ``guardrails`` kwarg does NOT disable legacy flags — both
    are combined. If a guardrail name is present in both, it is registered
    only once (the explicit entry wins; the legacy mapping is skipped for
    that name).

    Args:
        guardrails: Explicit guardrail spec list (names / config dicts /
            ``Guardrail`` instances), or ``None``.
        legacy_flags: Mapping of the legacy ctor flag names to their
            current values, or ``None`` (treated as all-falsy/defaults).
        on_telemetry: Optional callback forwarded to every constructed
            ``GuardrailPipeline`` (see `GuardrailPipeline.__init__`) — e.g.
            a bot's `_on_guardrail_telemetry` forwarding each
            `GuardrailTelemetryEntry` to a FEAT-176 observer.

    Returns:
        A dict with exactly one ``GuardrailPipeline`` per ``GuardrailStage``,
        containing every guardrail routed to that stage (a guardrail
        registered for multiple stages is added to each pipeline it
        declares).

    Raises:
        NotImplementedError: A reserved guardrail name was requested.
        ValueError: An unknown guardrail name was requested.
    """
    legacy_flags = legacy_flags or {}
    explicit_spec: list[str | dict[str, Any] | Guardrail] = list(guardrails or [])
    requested_names = {
        name for name in (_requested_name(item) for item in explicit_spec) if name is not None
    }

    legacy_spec: list[str | dict[str, Any]] = []
    if legacy_flags.get("injection_detection") and "prompt_injection" not in requested_names:
        legacy_spec.append({
            "name": "prompt_injection",
            "strict_mode": legacy_flags.get("strict_mode", True),
            "block_on_threat": legacy_flags.get("block_on_threat", False),
            "injection_probability_threshold": legacy_flags.get(
                "injection_probability_threshold", 0.98
            ),
        })
    if legacy_flags.get("enable_redaction") and "secrets" not in requested_names:
        legacy_spec.append("secrets")

    all_guardrails = build_guardrails(explicit_spec + legacy_spec)

    pipelines: dict[GuardrailStage, GuardrailPipeline] = {
        stage: GuardrailPipeline(on_telemetry=on_telemetry) for stage in GuardrailStage
    }
    for guardrail in all_guardrails:
        for stage in guardrail.stages:
            pipelines[stage].add(guardrail)

    return pipelines
