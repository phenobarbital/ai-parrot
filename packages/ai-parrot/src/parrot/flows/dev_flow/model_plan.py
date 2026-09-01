"""Per-seat LLM configuration for a dev-flow run (FEAT-486, Module 1).

``dev_flow`` drives four distinct LLM-facing *seats* — the ideation
(research) primary, an optional complementary research partner
(FEAT-482), the development sub-agent pool, and the adversarial review
pair — and until now every one of them was a hardcoded Claude model. This
module is the single configuration object that makes all four selectable:

* :class:`ResearchPartnerPlan` — the FEAT-482 partner selection (a pure
  passthrough; this module never builds a partner).
* :class:`ReviewPairPlan` — the primary reviewer + Mantle-hosted
  counter-reviewer that ride ``ParallelPerspectiveReviewDispatcher``.
* :class:`DevFlowModelPlan` — the four seat groups together, plus
  :meth:`DevFlowModelPlan.to_pool_config` which materialises the
  development pool as the ``DevAgentPoolConfig`` ``DevelopmentNode``
  already accepts.
* :func:`resolve_model_plan` — applies the ``DEV_FLOW_*`` env-key
  defaults, with the precedence *explicit argument > env > built-in*.

Deliberately **pure configuration**: no I/O, no client construction, no
dispatcher assembly (that is TASK-2652/2654/2655's job). The only
enforcement here is fail-fast backend validation — an unknown
``dev_pool`` backend raises :class:`ValueError` naming the supported set
*before* any dispatch is attempted. Model strings are never validated:
per the catalog's standing policy (``dev_loop/catalog.py:22-24``) model
ids are free text and an empty model means "use the backend default".

See ``sdd/specs/refactor-dev-flow.spec.md`` §2 (Data Models) / §3
(Module 1).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, get_args

from pydantic import BaseModel, Field, field_validator

from parrot import conf
from parrot.flows.dev_loop.catalog import resolve_research_partner_backend
from parrot.flows.dev_loop.models.base import (
    DevAgentBackend,
    DevAgentPoolConfig,
    DevAgentSpec,
)

__all__ = [
    "DevFlowModelPlan",
    "ResearchPartnerPlan",
    "ReviewPairPlan",
    "resolve_model_plan",
    "supported_dev_pool_backends",
]

# ─────────────────────────────────────────────────────────────────────
# Built-in defaults (spec §2 Data Models)
# ─────────────────────────────────────────────────────────────────────

#: Ideation primary seat — replaces the ``claude-sonnet-4-6`` literal
#: that ``dev_flow/nodes/ideation.py`` hardcoded (TASK-2656).
DEFAULT_RESEARCH_PRIMARY: str = "claude-opus-5"

#: FEAT-482 partner selector (``"gpt"`` ⇒ Mantle-hosted, ``"nova"`` ⇒
#: Bedrock Nova). Validated by FEAT-482's own
#: ``resolve_research_partner_backend()``, never here.
DEFAULT_PARTNER_BACKEND: str = "gpt"
#: Default model for the ``"gpt"`` backend. FEAT-487: the model default is
#: now chosen AFTER the backend is known, so a ``"nova"`` partner no longer
#: inherits a ``gpt-*`` default (the latent mismatch FEAT-486 shipped).
DEFAULT_PARTNER_MODEL: str = "gpt-5.6-sol"
DEFAULT_PARTNER_NOVA_MODEL: str = "us.amazon.nova-2-lite-v1:0"

#: Adversarial review pair (spec G5): Claude Opus 5 primary + Bedrock
#: Mantle ``gpt-5.6-sol`` read-only counter-reviewer.
DEFAULT_REVIEW_PRIMARY_BACKEND: str = "claude-code"
DEFAULT_REVIEW_PRIMARY_MODEL: str = "claude-opus-5"
DEFAULT_REVIEW_COUNTER_MODEL: str = "gpt-5.6-sol"

# ─────────────────────────────────────────────────────────────────────
# Env keys (spec §8: "settle at task decomposition")
# ─────────────────────────────────────────────────────────────────────

#: Shared with FEAT-482 — the ideation primary seat's model.
ENV_RESEARCH_PRIMARY: str = "DEV_FLOW_IDEATION_MODEL"
#: FEAT-487: the research-partner seat has NO enable/backend key of its
#: own. FEAT-486 originally invented ``DEV_FLOW_RESEARCH_PARTNER_ENABLED``
#: / ``_BACKEND`` / ``_MODEL`` here, written against a predicted FEAT-482
#: API before that feature merged. FEAT-482 shipped a different, better
#: shape — ``DEV_FLOW_RESEARCH_PARTNER`` ("" = disabled, else the backend
#: id) plus a PER-BACKEND model key — so the duplicates were retired and
#: this resolver now reads FEAT-482's keys through
#: ``catalog.resolve_research_partner_backend()``: one key set, one parse,
#: one place where the Anthropic family guard lives.
ENV_PARTNER_GPT_MODEL: str = "DEV_FLOW_RESEARCH_PARTNER_GPT_MODEL"
ENV_PARTNER_NOVA_MODEL: str = "DEV_FLOW_RESEARCH_PARTNER_NOVA_MODEL"
#: JSON list of ``{"agent": ..., "model": ..., "count": ...}`` rows.
ENV_DEV_POOL: str = "DEV_FLOW_DEV_POOL"
ENV_REVIEW_PRIMARY_BACKEND: str = "DEV_FLOW_REVIEW_PRIMARY_BACKEND"
ENV_REVIEW_PRIMARY_MODEL: str = "DEV_FLOW_REVIEW_PRIMARY_MODEL"
ENV_REVIEW_COUNTER_MODEL: str = "DEV_FLOW_REVIEW_COUNTER_MODEL"

#: ``(key, fallback=...) -> Any`` — mirrors ``dev_loop.catalog.ConfigGetter``.
ConfigGetter = Callable[..., Any]

_TRUE_VALUES: frozenset[str] = frozenset({"1", "true", "t", "yes", "y", "on"})
_FALSE_VALUES: frozenset[str] = frozenset({"0", "false", "f", "no", "n", "off", ""})


def supported_dev_pool_backends() -> tuple[str, ...]:
    """Return every backend a ``dev_pool`` entry may name.

    Read off the ``DevAgentBackend`` Literal rather than re-listed, so a
    new backend in ``dev_loop`` is automatically accepted here.

    Returns:
        The supported backend ids, in declaration order.
    """
    return tuple(get_args(DevAgentBackend))


class ResearchPartnerPlan(BaseModel):
    """Complementary research partner selection (FEAT-482 passthrough).

    Disabled by default — FEAT-482's own shipping default (spec G6). When
    enabled, ``backend``/``model`` are handed to FEAT-482's
    ``resolve_research_partner_backend()``; this model neither validates
    nor constructs the partner itself.
    """

    enabled: bool = Field(
        default=False,
        description="Whether the FEAT-482 complementary partner seat runs at all.",
    )
    backend: str = Field(
        default=DEFAULT_PARTNER_BACKEND,
        description="FEAT-482 partner selector: 'gpt' (Bedrock Mantle) or 'nova'.",
    )
    model: str = Field(
        default=DEFAULT_PARTNER_MODEL,
        description="Partner model id; '' ⇒ let FEAT-482's env selector decide.",
    )


class ReviewPairPlan(BaseModel):
    """Adversarial review pair riding ``ParallelPerspectiveReviewDispatcher``.

    ``primary`` is the write-enabled reviewer; ``counter_model`` names the
    Bedrock-Mantle-hosted, advisory/read-only counter-reviewer built by
    ``MantleAdversarialReviewDispatcher`` (TASK-2654). ``JudgeSpec`` and
    the judge panel are untouched by this feature.
    """

    primary: DevAgentSpec = Field(
        default_factory=lambda: DevAgentSpec(
            agent=DEFAULT_REVIEW_PRIMARY_BACKEND,
            model=DEFAULT_REVIEW_PRIMARY_MODEL,
        ),
        description="Write-enabled primary reviewer seat.",
    )
    counter_model: str = Field(
        default=DEFAULT_REVIEW_COUNTER_MODEL,
        description="Mantle-hosted read-only counter-reviewer model.",
    )


class DevFlowModelPlan(BaseModel):
    """Per-seat LLM configuration for a dev-flow run (FEAT-486).

    Passed to ``build_dev_flow(model_plan=...)`` (TASK-2652). Omitting it
    entirely leaves today's wiring byte-identical; supplying it selects
    the model for each seat independently.

    Attributes:
        research_primary: Model for the ``IdeationNode`` primary seat.
        research_partner: FEAT-482 complementary partner selection.
        dev_pool: Explicit development sub-agent specs. Empty (default)
            ⇒ today's single-agent claude-code path; N entries ⇒ an
            N-seat ``DevAgentPool``.
        review: The adversarial review pair.
    """

    research_primary: str = Field(
        default=DEFAULT_RESEARCH_PRIMARY,
        description="IdeationNode primary seat model.",
    )
    research_partner: ResearchPartnerPlan = Field(
        default_factory=ResearchPartnerPlan,
        description="FEAT-482 complementary research partner selection.",
    )
    dev_pool: list[DevAgentSpec] = Field(
        default_factory=list,
        description="Development sub-agent specs; empty ⇒ single-agent path.",
    )
    review: ReviewPairPlan = Field(
        default_factory=ReviewPairPlan,
        description="Adversarial review pair (primary + counter-reviewer).",
    )

    @field_validator("dev_pool", mode="before")
    @classmethod
    def _validate_pool_backends(cls, value: Any) -> Any:
        """Reject an unknown ``dev_pool`` backend with a clear message.

        Runs in ``before`` mode so the error names the supported set
        instead of Pydantic's raw ``Literal`` complaint, and so it fires
        at plan-construction time — long before any dispatch.

        Args:
            value: The raw ``dev_pool`` input (list of dicts or specs).

        Returns:
            ``value`` unchanged; validation is the only side effect.

        Raises:
            ValueError: If a row names a backend ``build_dispatcher``
                cannot build, listing every supported backend.
        """
        if not isinstance(value, list):
            return value
        supported = supported_dev_pool_backends()
        for row in value:
            if isinstance(row, DevAgentSpec):
                continue
            if not isinstance(row, dict):
                continue
            agent = row.get("agent")
            if agent is None:
                continue
            if str(agent) not in supported:
                raise ValueError(f"unknown dev agent backend {str(agent)!r} — supported: " f"{', '.join(supported)}")
        return value

    def to_pool_config(self) -> DevAgentPoolConfig | None:
        """Materialise ``dev_pool`` as a ``DevAgentPoolConfig``.

        Returns:
            A shared-worktree pool config wrapping every configured spec,
            or ``None`` when ``dev_pool`` is empty — which leaves
            ``DevelopmentNode``'s existing brief → env → single-agent
            cascade untouched.
        """
        if not self.dev_pool:
            return None
        return DevAgentPoolConfig(agents=list(self.dev_pool), isolation_mode="shared")


def _as_bool(value: Any, fallback: bool) -> bool:
    """Coerce a config value to ``bool``, tolerating string forms.

    Args:
        value: Raw config value (``bool``, ``str``, ``int`` or ``None``).
        fallback: Returned when ``value`` is ``None`` or unrecognised.

    Returns:
        The coerced boolean.
    """
    if value is None:
        return fallback
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in _TRUE_VALUES:
        return True
    if text in _FALSE_VALUES:
        return False
    return fallback


def _partner_model_default(backend: str, getter: ConfigGetter) -> str:
    """Return the configured default model for the partner ``backend``.

    FEAT-487: mirrors FEAT-482's per-backend mapping
    (``research_partner.resolve_backend_model``) but reads through the
    injected ``getter``, with the built-in as fallback — the shape every
    other default in this module uses, and what keeps tests hermetic.
    Deliberately NOT an import of ``resolve_backend_model``: that reads
    ``conf.*`` module attributes directly and would ignore ``getter``.

    Args:
        backend: ``"gpt"`` or ``"nova"``. Anything else falls back to the
            gpt key — an invalid backend has already raised by this point,
            inside ``resolve_research_partner_backend``.
        getter: ``(key, fallback=...) -> Any`` config accessor.

    Returns:
        The model id for that backend.
    """
    if backend == "nova":
        key, fallback = ENV_PARTNER_NOVA_MODEL, DEFAULT_PARTNER_NOVA_MODEL
    else:
        key, fallback = ENV_PARTNER_GPT_MODEL, DEFAULT_PARTNER_MODEL
    return str(getter(key, fallback=fallback) or "").strip() or fallback


def _pool_from_env(raw: Any) -> list[dict[str, Any]] | None:
    """Parse the ``DEV_FLOW_DEV_POOL`` JSON list into raw spec rows.

    Args:
        raw: The config value — a JSON array string, an already-decoded
            list, or anything falsy (meaning "not configured").

    Returns:
        The decoded rows, or ``None`` when nothing usable was configured.

    Raises:
        ValueError: If the value is a string that is not a JSON array.
    """
    if raw is None:
        return None
    if isinstance(raw, list):
        return list(raw) or None
    text = str(raw).strip()
    if not text:
        return None
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{ENV_DEV_POOL} must be a JSON array of dev-agent rows, e.g. "
            '[{"agent": "nova", "model": "zai.glm-5"}] — got invalid JSON: '
            f"{exc}"
        ) from exc
    if not isinstance(decoded, list):
        # ValueError, not TypeError: this is a *config value* the operator
        # got wrong, and `resolve_model_plan`'s documented contract raises
        # ValueError for every bad plan input.
        raise ValueError(  # noqa: TRY004
            f"{ENV_DEV_POOL} must be a JSON *array* of dev-agent rows, got " f"{type(decoded).__name__}."
        )
    return decoded or None


def resolve_model_plan(
    plan: DevFlowModelPlan | None = None,
    *,
    config_getter: ConfigGetter | None = None,
) -> DevFlowModelPlan:
    """Return ``plan`` with ``DEV_FLOW_*`` env defaults filled in.

    Precedence is *explicit argument > env > built-in default*, decided
    per field: a field the caller actually set (tracked by Pydantic's
    ``model_fields_set``) is never overwritten by config, while an
    unset field falls through to its env key and then to the built-in
    default. Mirrors ``dev_loop.catalog.resolve_adversarial_backend``'s
    injectable-getter shape so tests need no monkeypatching of ``conf``.

    Args:
        plan: The operator's partial plan, or ``None`` for "nothing
            explicit" (every field resolves from env/built-ins).
        config_getter: ``(key, fallback=...) -> Any``; defaults to
            ``conf.config.get``.

    Returns:
        A fully-resolved :class:`DevFlowModelPlan`.

    Raises:
        ValueError: If a configured ``dev_pool`` row names an unsupported
            backend, or ``DEV_FLOW_DEV_POOL`` is not a JSON array.
    """
    getter = config_getter or (lambda key, fallback="": conf.config.get(key, fallback=fallback))
    base = plan if plan is not None else DevFlowModelPlan()
    explicit = base.model_fields_set

    # ── research primary ────────────────────────────────────────────
    research_primary = base.research_primary
    if "research_primary" not in explicit:
        research_primary = (
            str(getter(ENV_RESEARCH_PRIMARY, fallback=DEFAULT_RESEARCH_PRIMARY) or "").strip()
            or DEFAULT_RESEARCH_PRIMARY
        )

    # ── research partner (FEAT-482 passthrough) ─────────────────────
    partner_explicit = base.research_partner.model_fields_set if "research_partner" in explicit else frozenset()
    partner = base.research_partner
    partner_kwargs: dict[str, Any] = {}
    # FEAT-487: `enabled` and `backend` come from ONE key,
    # `DEV_FLOW_RESEARCH_PARTNER` ("" = disabled, else the backend id),
    # resolved through FEAT-482's own `resolve_research_partner_backend()`.
    # Delegating rather than re-parsing keeps the enable/backend semantics
    # AND the Anthropic family guard in a single place — with two separate
    # key sets the two could disagree.
    configured_backend = resolve_research_partner_backend(getter)
    if "enabled" in partner_explicit:
        partner_kwargs["enabled"] = partner.enabled
    else:
        partner_kwargs["enabled"] = bool(configured_backend)
    if "backend" in partner_explicit:
        partner_kwargs["backend"] = partner.backend
    else:
        partner_kwargs["backend"] = configured_backend or DEFAULT_PARTNER_BACKEND
    if "model" in partner_explicit:
        partner_kwargs["model"] = partner.model
    else:
        # Resolved AFTER the backend, from that backend's own key — the
        # whole point of the FEAT-487 dedup.
        partner_kwargs["model"] = _partner_model_default(partner_kwargs["backend"], getter)

    # ── development pool ────────────────────────────────────────────
    dev_pool: list[Any] = list(base.dev_pool)
    if "dev_pool" not in explicit:
        from_env = _pool_from_env(getter(ENV_DEV_POOL, fallback=""))
        dev_pool = from_env if from_env is not None else []

    # ── review pair ─────────────────────────────────────────────────
    review_explicit = base.review.model_fields_set if "review" in explicit else frozenset()
    review = base.review
    if "primary" in review_explicit:
        review_primary = review.primary
    else:
        review_primary = DevAgentSpec(
            agent=str(
                getter(ENV_REVIEW_PRIMARY_BACKEND, fallback=DEFAULT_REVIEW_PRIMARY_BACKEND)
                or DEFAULT_REVIEW_PRIMARY_BACKEND
            ).strip()
            or DEFAULT_REVIEW_PRIMARY_BACKEND,
            model=str(
                getter(ENV_REVIEW_PRIMARY_MODEL, fallback=DEFAULT_REVIEW_PRIMARY_MODEL) or DEFAULT_REVIEW_PRIMARY_MODEL
            ).strip()
            or DEFAULT_REVIEW_PRIMARY_MODEL,
        )
    if "counter_model" in review_explicit:
        counter_model = review.counter_model
    else:
        counter_model = (
            str(getter(ENV_REVIEW_COUNTER_MODEL, fallback=DEFAULT_REVIEW_COUNTER_MODEL) or "").strip()
            or DEFAULT_REVIEW_COUNTER_MODEL
        )

    return DevFlowModelPlan(
        research_primary=research_primary,
        research_partner=ResearchPartnerPlan(**partner_kwargs),
        dev_pool=dev_pool,
        review=ReviewPairPlan(primary=review_primary, counter_model=counter_model),
    )
