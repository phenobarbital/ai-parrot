"""RuleSet: policy-driven evaluation over an ordered collection of rules."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Generic, Literal, Optional, Sequence, TypeVar, Union

from .abstract import AbstractRule, ConditionRule
from .context import EvalContext
from .environment import Environment
from .loader import RuleLoader
from .policies import Policy, RuleResult, RuleSetResult
from ._native import HAS_RUST

T = TypeVar("T")

Backend = Literal["auto", "python", "rust"]


class RuleSet(Generic[T]):
    """An ordered, policy-driven set of rules.

    Args:
        rules: Initial rules (instances or loadable specs).
        policy: How rules combine (ALL_MATCH / ANY_MATCH / FIRST_MATCH).
        default: Value returned when no rule matches (FIRST_MATCH) or the
            payload attached to an aggregate match (ALL/ANY).
        backend: "rust" forces the native matcher (raises if unavailable),
            "python" forces the fallback, "auto" picks Rust when available
            and every rule is declarative with builtin operators.
        loader: RuleLoader used by :meth:`add_rule` for non-instance specs.
    """

    def __init__(
        self,
        rules: Sequence[Union[AbstractRule, dict, list, str]] = (),
        *,
        policy: Policy = Policy.ALL_MATCH,
        default: Optional[T] = None,
        backend: Backend = "auto",
        loader: Optional[RuleLoader] = None,
    ) -> None:
        self.policy = Policy(policy)
        self.default = default
        self.backend = backend
        self.loader = loader or RuleLoader()
        self.logger = logging.getLogger("navrules.RuleSet")
        self._rules: list[AbstractRule] = []
        self._compiled: Any = None  # native CompiledRuleSet (Phase 2)
        self._use_rust = False
        for rule in rules:
            self.add_rule(rule)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def add_rule(self, rule: Union[AbstractRule, dict, list, str]) -> None:
        """Add a rule instance or a loadable spec (dict/list/str)."""
        if not isinstance(rule, AbstractRule):
            rule = self.loader.load(rule)
        self._rules.append(rule)
        self._compiled = None  # invalidate compilation

    @property
    def rules(self) -> tuple[AbstractRule, ...]:
        return tuple(self._rules)

    @property
    def is_declarative(self) -> bool:
        """True when every rule is a pure CPU-bound ConditionRule."""
        return all(r.is_declarative for r in self._rules)

    @property
    def is_rust_compilable(self) -> bool:
        return self.is_declarative and all(
            isinstance(r, ConditionRule) and r.condition_set.is_rust_compilable
            for r in self._rules
        )

    def compile(self) -> None:
        """Sort rules by priority (descending, stable) and prepare backends.

        When the Rust backend is available and applicable, condition specs
        are serialized once into a native CompiledRuleSet.
        """
        self._rules.sort(key=lambda r: -r.priority)
        self._use_rust = False
        self._compiled = None
        if self.backend == "python":
            return
        if not self.is_rust_compilable:
            if self.backend == "rust":
                raise RuntimeError(
                    "backend='rust' requires all rules to be declarative "
                    "ConditionRules with builtin operators"
                )
            return
        if HAS_RUST:
            from . import _native

            import json

            spec = [
                {
                    "priority": rule.priority,
                    "conditions": rule.condition_set.to_spec(),
                }
                for rule in self._rules
            ]
            self._compiled = _native.compile_ruleset(json.dumps(spec))
            self._use_rust = True
        elif self.backend == "rust":
            raise RuntimeError(
                "backend='rust' requested but the native extension is not "
                "available (navrules._native failed to import)"
            )

    # ------------------------------------------------------------------
    # Sync evaluation (declarative-only hot path)
    # ------------------------------------------------------------------
    def evaluate_sync(
        self, ctx: EvalContext, env: Environment
    ) -> RuleSetResult[T]:
        """Synchronous evaluation; requires a fully declarative set.

        This is the low-latency path (payrate clock-out): no event loop, no
        I/O, optional GIL-released native matching.
        """
        if not self.is_declarative:
            raise RuntimeError(
                "evaluate_sync() requires all rules to be declarative; "
                "use `await evaluate()` for mixed sets"
            )
        if self._use_rust and self._compiled is not None:
            flat = ctx.flatten(env)
            return self._result_from_indices(
                self._native_indices(flat), total=len(self._rules)
            )
        return self._evaluate_sync_python(ctx, env)

    def evaluate_batch(
        self, contexts: Sequence[EvalContext], env: Environment
    ) -> list[RuleSetResult[T]]:
        """Evaluate many contexts against the same environment.

        Declarative sets use the native batch path (rayon) when available.
        """
        if not self.is_declarative:
            raise RuntimeError(
                "evaluate_batch() requires a fully declarative rule set"
            )
        if self._use_rust and self._compiled is not None:
            flats = [ctx.flatten(env) for ctx in contexts]
            return [
                self._result_from_indices(idx, total=len(self._rules))
                for idx in self._native_batch_indices(flats)
            ]
        return [self._evaluate_sync_python(ctx, env) for ctx in contexts]

    def fits_all(self, ctx: EvalContext, env: Environment) -> bool:
        """AND of every rule's fits() — the corrected rewards pre-filter."""
        return all(self._safe_fits(rule, ctx, env) for rule in self._rules)

    # ------------------------------------------------------------------
    # Async evaluation (general path, mixed rule sets)
    # ------------------------------------------------------------------
    async def evaluate(
        self, ctx: EvalContext, env: Environment
    ) -> RuleSetResult[T]:
        """Evaluate under the configured policy.

        ALL/ANY run rule evaluations concurrently (gather); FIRST_MATCH walks
        rules sequentially in priority order and short-circuits.
        """
        if not self._rules:
            matched = self.policy is not Policy.ANY_MATCH
            return RuleSetResult(
                matched=matched,
                value=self.default if matched else None,
                results=(),
                policy=self.policy,
            )
        if self.policy is Policy.FIRST_MATCH:
            return await self._evaluate_first_match(ctx, env)

        results = await asyncio.gather(
            *(self._evaluate_rule(rule, ctx, env) for rule in self._rules)
        )
        if self.policy is Policy.ALL_MATCH:
            matched = all(r.matched for r in results)
        else:
            matched = any(r.matched for r in results)
        return RuleSetResult(
            matched=matched,
            value=self.default if matched else None,
            results=tuple(results),
            policy=self.policy,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _safe_fits(
        self, rule: AbstractRule, ctx: EvalContext, env: Environment
    ) -> bool:
        try:
            return bool(rule.fits(ctx, env))
        except Exception as exc:
            self.logger.error("Error on rule %s fits(): %s", rule, exc)
            return False

    async def _evaluate_rule(
        self, rule: AbstractRule, ctx: EvalContext, env: Environment
    ) -> RuleResult[T]:
        """fits() pre-filter, then evaluate(), normalized to RuleResult."""
        if not self._safe_fits(rule, ctx, env):
            return RuleResult(matched=False, rule=rule)
        try:
            outcome = await rule.evaluate(ctx, env)
        except Exception as exc:
            self.logger.error("Error on rule %s evaluate(): %s", rule, exc)
            return RuleResult(matched=False, rule=rule, error=str(exc))
        if isinstance(outcome, RuleResult):
            return outcome
        matched = bool(outcome)
        return RuleResult(
            matched=matched,
            rule=rule,
            value=rule.result if matched else None,
        )

    async def _evaluate_first_match(
        self, ctx: EvalContext, env: Environment
    ) -> RuleSetResult[T]:
        rules = sorted(self._rules, key=lambda r: -r.priority)
        inspected: list[RuleResult] = []
        for rule in rules:
            result = await self._evaluate_rule(rule, ctx, env)
            inspected.append(result)
            if result.matched:
                value = result.value if result.value is not None else rule.result
                return RuleSetResult(
                    matched=True,
                    value=value,
                    results=tuple(inspected),
                    policy=self.policy,
                )
        return RuleSetResult(
            matched=False,
            value=self.default,
            results=tuple(inspected),
            policy=self.policy,
        )

    def _evaluate_sync_python(
        self, ctx: EvalContext, env: Environment
    ) -> RuleSetResult[T]:
        rules = self._rules
        if self._compiled is None:
            # Not compiled: still honor priority order for FIRST_MATCH.
            rules = sorted(self._rules, key=lambda r: -r.priority)
        if self.policy is Policy.FIRST_MATCH:
            inspected: list[RuleResult] = []
            for rule in rules:
                matched = self._safe_fits(rule, ctx, env)
                inspected.append(
                    RuleResult(
                        matched=matched,
                        rule=rule,
                        value=rule.result if matched else None,
                    )
                )
                if matched:
                    return RuleSetResult(
                        matched=True,
                        value=rule.result,
                        results=tuple(inspected),
                        policy=self.policy,
                    )
            return RuleSetResult(
                matched=False,
                value=self.default,
                results=tuple(inspected),
                policy=self.policy,
            )
        results = tuple(
            RuleResult(
                matched=self._safe_fits(rule, ctx, env),
                rule=rule,
            )
            for rule in rules
        )
        if self.policy is Policy.ALL_MATCH:
            matched = all(r.matched for r in results)
        else:
            matched = any(r.matched for r in results)
        return RuleSetResult(
            matched=matched,
            value=self.default if matched else None,
            results=results,
            policy=self.policy,
        )

    def _native_indices(self, flat: dict) -> Optional[int]:
        """Query the native backend for the winning rule index."""
        if self.policy is Policy.FIRST_MATCH:
            return self._compiled.evaluate_first_match(flat)
        raise RuntimeError(
            "native sync evaluation currently supports FIRST_MATCH; "
            "use evaluate()/fits_all() for other policies"
        )

    def _native_batch_indices(self, flats: list[dict]) -> list[Optional[int]]:
        if self.policy is Policy.FIRST_MATCH:
            return self._compiled.evaluate_batch_first_match(flats)
        raise RuntimeError(
            "native batch evaluation currently supports FIRST_MATCH"
        )

    def _result_from_indices(
        self, index: Optional[int], total: int
    ) -> RuleSetResult[T]:
        if index is None:
            return RuleSetResult(
                matched=False,
                value=self.default,
                results=(),
                policy=self.policy,
            )
        rule = self._rules[index]
        return RuleSetResult(
            matched=True,
            value=rule.result,
            results=(RuleResult(matched=True, rule=rule, value=rule.result),),
            policy=self.policy,
        )

    def __len__(self) -> int:
        return len(self._rules)

    def __repr__(self) -> str:
        return (
            f"<RuleSet policy={self.policy.value} rules={len(self._rules)} "
            f"backend={'rust' if self._use_rust else 'python'}>"
        )
