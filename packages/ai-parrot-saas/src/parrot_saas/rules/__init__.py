"""Per-tenant eligibility rules, built on navrules.

Exports are resolved lazily (PEP 562), matching the parent package: the
repository pulls in ``asyncdb``, which is a heavy import to pay for naming the
vocabulary.
"""
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - import only for type checkers
    from .builder import (
        DEFAULT_ELIGIBILITY_RULES,
        DEFAULT_RULESET,
        RULE_TYPE,
        RuleValidationError,
        build_ruleset,
        validate_rule,
    )
    from .context import (
        ELIGIBILITY_FIELDS,
        build_environment,
        build_eval_context,
        describe_vocabulary,
    )
    from .models import Rule, RuleCreate, RuleUpdate
    from .repository import PostgresRuleStorage, RuleAlreadyExists, RuleRepository

__all__ = (
    "DEFAULT_ELIGIBILITY_RULES",
    "DEFAULT_RULESET",
    "ELIGIBILITY_FIELDS",
    "RULE_TYPE",
    "PostgresRuleStorage",
    "Rule",
    "RuleAlreadyExists",
    "RuleCreate",
    "RuleRepository",
    "RuleUpdate",
    "RuleValidationError",
    "build_environment",
    "build_eval_context",
    "build_ruleset",
    "describe_vocabulary",
    "validate_rule",
)

_LAZY_EXPORTS = {
    "DEFAULT_ELIGIBILITY_RULES": ("parrot_saas.rules.builder", "DEFAULT_ELIGIBILITY_RULES"),
    "DEFAULT_RULESET": ("parrot_saas.rules.builder", "DEFAULT_RULESET"),
    "RULE_TYPE": ("parrot_saas.rules.builder", "RULE_TYPE"),
    "RuleValidationError": ("parrot_saas.rules.builder", "RuleValidationError"),
    "build_ruleset": ("parrot_saas.rules.builder", "build_ruleset"),
    "validate_rule": ("parrot_saas.rules.builder", "validate_rule"),
    "ELIGIBILITY_FIELDS": ("parrot_saas.rules.context", "ELIGIBILITY_FIELDS"),
    "build_environment": ("parrot_saas.rules.context", "build_environment"),
    "build_eval_context": ("parrot_saas.rules.context", "build_eval_context"),
    "describe_vocabulary": ("parrot_saas.rules.context", "describe_vocabulary"),
    "Rule": ("parrot_saas.rules.models", "Rule"),
    "RuleCreate": ("parrot_saas.rules.models", "RuleCreate"),
    "RuleUpdate": ("parrot_saas.rules.models", "RuleUpdate"),
    "PostgresRuleStorage": ("parrot_saas.rules.repository", "PostgresRuleStorage"),
    "RuleAlreadyExists": ("parrot_saas.rules.repository", "RuleAlreadyExists"),
    "RuleRepository": ("parrot_saas.rules.repository", "RuleRepository"),
}


def __getattr__(name: str) -> Any:
    """Resolve lazily-exported names on first access (PEP 562).

    Args:
        name: Attribute being looked up on the package.

    Returns:
        The resolved object.

    Raises:
        AttributeError: If ``name`` is not a known lazy export.
    """
    try:
        module_path, attr = _LAZY_EXPORTS[name]
    except KeyError:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        ) from None
    from importlib import import_module

    return getattr(import_module(module_path), attr)


def __dir__() -> list[str]:
    """Expose lazy exports to ``dir()`` and tab-completion."""
    return sorted(__all__)
