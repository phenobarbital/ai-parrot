"""Rule base classes: the two-phase fits/evaluate contract.

``fits()`` is the cheap synchronous pre-filter; ``evaluate()`` is the real
(possibly I/O-bound) async evaluation. This is the exact contract nav-rewards
production rules already implement, extended with ``priority`` (FIRST_MATCH
ordering) and ``result`` (typed payload a matching rule yields, e.g. a
payrate).
"""
from __future__ import annotations

import logging
import uuid
from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any, Callable, Optional

from .conditions import ConditionSet, make_resolver
from .context import EvalContext
from .environment import Environment
from .operators import OperatorRegistry


class AbstractRule(ABC):
    """Base class for all rules.

    Attributes:
        name: Rule name (class name unless overridden).
        id: Unique instance id.
        priority: FIRST_MATCH ordering key — higher evaluates first.
        result: Payload returned when this rule matches (e.g. a payrate dict).
        conditions: Declarative condition spec attached to the rule.
        attributes: Every extra kwarg, also set as instance attributes.
    """

    #: Declarative rules (pure CPU-bound condition matching) set this True;
    #: they are the only ones eligible for the Rust backend.
    is_declarative: bool = False

    def __init__(
        self,
        conditions: Optional[dict] = None,
        *,
        name: Optional[str] = None,
        priority: int = 0,
        result: Any = None,
        **kwargs: Any,
    ):
        self.name = name or self.__class__.__name__
        self.id = uuid.uuid4().hex
        self.priority = priority
        self.result = result
        self.conditions: dict = conditions if isinstance(conditions, dict) else {}
        self.logger = logging.getLogger(f"navrules.{self.__class__.__name__}")
        for key, arg in kwargs.items():
            setattr(self, key, arg)
        self.attributes = kwargs

    def __str__(self) -> str:
        return f"<{self.name}:{self.priority}>"

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r} priority={self.priority}>"

    @abstractmethod
    def fits(self, ctx: EvalContext, env: Environment) -> bool:
        """Cheap synchronous pre-filter.

        Args:
            ctx: Evaluation context (subject/session information).
            env: Ambient/temporal environment.

        Returns:
            True when this rule is applicable to the given context.
        """

    @abstractmethod
    async def evaluate(self, ctx: EvalContext, env: Environment) -> bool:
        """Full (possibly I/O-bound) evaluation.

        Args:
            ctx: Evaluation context (subject/session information).
            env: Ambient/temporal environment.

        Returns:
            True when the rule matches. Implementations may also return a
            ``RuleResult`` for richer payloads; plain ``True`` is normalized
            by the RuleSet to ``RuleResult(matched=True, value=self.result)``.
        """


class ConditionRule(AbstractRule):
    """Fully declarative rule: a condition spec evaluated CPU-bound.

    This is the only rule family compilable to the Rust backend, and the one
    payrate/first-match consumers should use::

        ConditionRule(
            name="ot_weekend", priority=100,
            conditions={"env.is_weekend": True, "ctx.worked_hours": {"gt": 8}},
            result={"payrate": 33.75, "code": "OT-WKND"},
        )
    """

    is_declarative = True

    def __init__(
        self,
        conditions: Optional[dict] = None,
        *,
        operators: Optional[OperatorRegistry] = None,
        **kwargs: Any,
    ):
        super().__init__(conditions, **kwargs)
        self.condition_set = ConditionSet.from_dict(self.conditions, operators)

    def match(self, ctx: EvalContext, env: Environment) -> bool:
        """Synchronous full evaluation (fits and evaluate are the same)."""
        return self.condition_set.match(make_resolver(ctx, env))

    def match_flat(self, flat: dict[str, Any]) -> bool:
        """Evaluate against a pre-flattened context (batch/Rust parity path)."""
        return self.condition_set.match_flat(flat)

    def fits(self, ctx: EvalContext, env: Environment) -> bool:
        return self.match(ctx, env)

    async def evaluate(self, ctx: EvalContext, env: Environment) -> bool:
        return self.match(ctx, env)


class ComputedRule(AbstractRule):
    """Pull-style rule: it finds its own candidate subjects.

    Instead of answering "does this subject match?", a ComputedRule queries a
    data source for the set of matching subjects (e.g. everyone whose
    birthday is today). Port of the rewards pattern with the domain-specific
    pieces injected:

    Args:
        user_resolver: ``async (conn, **{key: id}) -> subject`` — turns a
            candidate row into a full subject object.
        context_factory: ``(subject) -> EvalContext`` — builds the evaluation
            context for a resolved subject (defaults to
            ``EvalContext.from_user``).
        candidate_keys: Column names probed (in order) to identify a
            candidate row.
    """

    def __init__(
        self,
        conditions: Optional[dict] = None,
        *,
        user_resolver: Optional[Callable] = None,
        context_factory: Optional[Callable[..., EvalContext]] = None,
        candidate_keys: tuple[str, ...] = ("user_id", "associate_id"),
        **kwargs: Any,
    ):
        super().__init__(conditions, **kwargs)
        self.user_resolver = user_resolver
        self.context_factory = context_factory or EvalContext.from_user
        self.candidate_keys = candidate_keys

    def fits(self, ctx: EvalContext, env: Environment) -> bool:
        return True

    async def evaluate(self, ctx: EvalContext, env: Environment) -> bool:
        return True

    def fits_computed(self, env: Environment) -> bool:
        """Ambient pre-filter for the whole computed evaluation."""
        return True

    def get_dataframe(self, data: Iterable) -> Any:
        """Convert an iterable of records to a pandas DataFrame.

        Requires the ``navrules[pandas]`` extra; returns None on failure.
        """
        try:
            import pandas as pd  # noqa: PLC0415 - optional dependency
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "pandas is required for get_dataframe(); "
                "install with: pip install navrules[pandas]"
            ) from exc
        try:
            df = pd.DataFrame([dict(r) for r in data], dtype=str)
            df.infer_objects()
            return df.convert_dtypes(convert_string=True)
        except Exception:
            return None

    @abstractmethod
    async def _get_candidates(
        self,
        env: Environment,
        dataset: Optional[Iterable] = None,
    ) -> Any:
        """Produce the candidate rows (DataFrame or iterable of mappings)."""

    def _iter_candidates(self, candidates: Any):
        """Yield (index, row_dict) pairs from a DataFrame or an iterable."""
        if candidates is None:
            return
        if hasattr(candidates, "iterrows"):
            for idx, row in candidates.iterrows():
                yield idx, row.to_dict()
        else:
            for idx, row in enumerate(candidates):
                yield idx, dict(row)

    async def evaluate_dataset(
        self,
        env: Environment,
        dataset: Any = None,
    ) -> list[EvalContext]:
        """Evaluate the rule against a dataset; return matching contexts."""
        candidates = await self._get_candidates(env, dataset)
        potential: list[EvalContext] = []
        if self.user_resolver is None:
            raise RuntimeError(
                f"{self.name}: a user_resolver is required to materialize "
                "candidates into evaluation contexts"
            )
        conn_manager = (
            await env.connection.acquire() if env.connection else None
        )
        try:
            conn = await conn_manager.__aenter__() if conn_manager else None
            for position, (idx, candidate) in enumerate(
                self._iter_candidates(candidates)
            ):
                key = next(
                    (k for k in self.candidate_keys if k in candidate), None
                )
                if key is None:
                    continue
                args = {key: candidate[key]}
                try:
                    subject = await self.user_resolver(conn, **args)
                    ctx = self.context_factory(subject)
                    ctx.args = {
                        "position": position + 1,
                        "index": idx,
                        **candidate,
                    }
                    potential.append(ctx)
                except Exception as err:
                    self.logger.warning(
                        "Error resolving candidate %s: %s", args, err
                    )
                    continue
        finally:
            if conn_manager:
                await conn_manager.__aexit__(None, None, None)
        return potential
