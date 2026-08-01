"""Named registry for guardrail factories.

Maps short names (``"prompt_injection"``, ``"secrets"``, ...) to factory
callables so bot configuration can reference guardrails by name (or by a
``{"name": ..., "policy": {...}}`` dict, or by passing a ``Guardrail``
instance directly). See ``sdd/specs/guardrails-infrastructure.spec.md``
§2/§3 Module 1 (FEAT-396).

Built-in factory registrations are lazy: they defer importing the concrete
plugin module (``parrot.bots.guardrails.builtin.*``) until the factory is
actually called, mirroring the lazy-``pytector``-import constraint on
``PromptInjectionGuardrail`` itself (spec §3 Module 2) — registering a name
here never pulls in a plugin's heavy dependencies (or the plugin module at
all) unless that guardrail is actually requested.
"""
import importlib
import logging
from collections.abc import Callable
from typing import Any

from .base import Guardrail

logger = logging.getLogger(__name__)

# name -> factory(**kwargs) -> Guardrail
_GUARDRAIL_FACTORIES: dict[str, Callable[..., Guardrail]] = {}

# Reserved names for guardrails whose engines are separate, not-yet-landed
# features (spec §1 Non-Goals / §6 "Does NOT Exist"). Requesting one raises
# a clear NotImplementedError instead of a confusing ImportError/KeyError.
_RESERVED_NAMES: dict[str, str] = {
    "pii": "FEAT-324 (pii-detection-redaction)",
    "pseudonymize": "FEAT-324 (pii-detection-redaction)",
    "groundedness": "FEAT-398 (deterministic-groundedness-scoring)",
}


def register_guardrail(name: str, factory: Callable[..., Guardrail]) -> None:
    """Register (or replace) a named guardrail factory.

    Args:
        name: The short name used in ``guardrails=[...]`` config entries.
        factory: A callable accepting arbitrary keyword arguments (the
            guardrail's policy) and returning a ``Guardrail`` instance.
    """
    _GUARDRAIL_FACTORIES[name] = factory


def _make_lazy_factory(module_path: str, class_name: str) -> Callable[..., Guardrail]:
    """Build a factory that imports ``module_path`` only when called.

    Args:
        module_path: Dotted path of the module defining the guardrail class.
        class_name: Name of the ``Guardrail`` subclass within that module.

    Returns:
        A factory suitable for `register_guardrail`.
    """
    def _factory(**kwargs: Any) -> Guardrail:
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        return cls(**kwargs)
    return _factory


def _build_by_name(name: str, **kwargs: Any) -> Guardrail:
    """Resolve a single guardrail by its registered name.

    Args:
        name: The registered guardrail name.
        **kwargs: Policy keyword arguments forwarded to the factory.

    Returns:
        A constructed ``Guardrail`` instance.

    Raises:
        NotImplementedError: ``name`` is reserved for a not-yet-landed
            feature (e.g. ``"pii"``, ``"groundedness"``).
        ValueError: ``name`` is not registered.
    """
    if name in _RESERVED_NAMES:
        raise NotImplementedError(
            f"Guardrail {name!r} is not yet implemented — requires "
            f"{_RESERVED_NAMES[name]}."
        )
    factory = _GUARDRAIL_FACTORIES.get(name)
    if factory is None:
        raise ValueError(f"Unknown guardrail: {name!r}")
    return factory(**kwargs)


def build_guardrails(spec: list[str | dict[str, Any] | Guardrail]) -> list[Guardrail]:
    """Coerce a mixed guardrail spec list into concrete ``Guardrail`` instances.

    Each entry may be:
        - a ``str`` — a registered guardrail name, built with no policy args.
        - a ``dict`` — ``{"name": <str>, **policy_kwargs}``, forwarded to
          the named factory as keyword arguments.
        - a ``Guardrail`` instance — used as-is.

    Args:
        spec: The mixed list of guardrail references.

    Returns:
        The list of constructed (or passed-through) ``Guardrail`` instances,
        in the same order as ``spec``.

    Raises:
        NotImplementedError: A reserved name was requested.
        ValueError: An unknown name was requested, or a dict entry is
            missing ``"name"``.
        TypeError: An entry is not a ``str``, ``dict``, or ``Guardrail``.
    """
    result: list[Guardrail] = []
    for item in spec:
        if isinstance(item, Guardrail):
            result.append(item)
        elif isinstance(item, str):
            result.append(_build_by_name(item))
        elif isinstance(item, dict):
            kwargs = dict(item)
            try:
                name = kwargs.pop("name")
            except KeyError as exc:
                raise ValueError(
                    f"Guardrail config dict missing required 'name' key: {item!r}"
                ) from exc
            result.append(_build_by_name(name, **kwargs))
        else:
            raise TypeError(
                f"Guardrail spec entries must be str, dict, or Guardrail; got {type(item)!r}"
            )
    return result


# --- Built-in name reservations -------------------------------------------
# Concrete plugin classes land in later tasks of this feature
# (TASK-2027 PromptInjectionGuardrail, TASK-2029 SecretsGuardrail,
# TASK-2030 ModerationGuardrail); registering their names here now, via
# lazy factories, lets config/registry code (and this task's own tests)
# reference them by name immediately, while the actual plugin module is
# only imported the first time one is actually built.
register_guardrail(
    "prompt_injection",
    _make_lazy_factory("parrot.bots.guardrails.builtin.prompt_injection", "PromptInjectionGuardrail"),
)
register_guardrail(
    "secrets",
    _make_lazy_factory("parrot.bots.guardrails.builtin.secrets", "SecretsGuardrail"),
)
register_guardrail(
    "moderation",
    _make_lazy_factory("parrot.bots.guardrails.builtin.moderation", "ModerationGuardrail"),
)
