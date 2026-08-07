"""navrules — generic, low-latency rule evaluation engine.

Two-phase rule contract (sync ``fits`` pre-filter + async ``evaluate``),
declarative condition DSL, priority-ordered first-match with typed results,
and an optional Rust backend for the CPU-bound hot path.
"""
from .abstract import AbstractRule, ComputedRule, ConditionRule
from .availability import AvailabilityWindow
from .conditions import Condition, ConditionError, ConditionSet
from .context import EvalContext
from .environment import Environment
from .loader import RuleLoader, RuleLoadError
from .operators import MISSING, OperatorRegistry, default_operators
from .policies import Policy, RuleResult, RuleSetResult
from .registry import FunctionRegistry, default_registry, register_function
from .ruleset import RuleSet
from ._native import HAS_RUST

__version__ = "0.1.4"

__all__ = (
    "AbstractRule",
    "ConditionRule",
    "ComputedRule",
    "AvailabilityWindow",
    "Condition",
    "ConditionError",
    "ConditionSet",
    "EvalContext",
    "Environment",
    "RuleLoader",
    "RuleLoadError",
    "MISSING",
    "OperatorRegistry",
    "default_operators",
    "Policy",
    "RuleResult",
    "RuleSetResult",
    "FunctionRegistry",
    "default_registry",
    "register_function",
    "RuleSet",
    "HAS_RUST",
    "__version__",
)
