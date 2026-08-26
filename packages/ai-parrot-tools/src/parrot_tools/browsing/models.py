"""
Catalog models for the Web Browsing subsystem.

A **site** groups a set of named, parameterized **actions** ("guiones"):
deterministic scripts expressed with the same BrowserAction DSL used by
``WebScrapingToolkit`` (``parrot_tools.scraping.models``). Actions are
stored on disk — one folder per site, one JSON file per action — so an
agent can resolve a natural-language request ("inicia sesión en Hooba")
to a concrete, replayable step sequence.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

#: Kinds of catalogued actions:
#: - ``navigation``: pure page movement (go to dashboard, open CRM tab).
#: - ``operation``: does something on the site (refresh a dashboard,
#:   download a report, create an invoice draft).
#: - ``composite``: no steps of its own — references other actions of the
#:   same site in order, forming a deterministic flow.
ActionKind = Literal["navigation", "operation", "composite"]

#: Placeholder names reserved by the Loop executor
#: (``{{index}}``/``{{index_1}}`` and the loop's ``value_name``, which
#: defaults to ``value``). Action parameters must not shadow them.
RESERVED_PLACEHOLDERS = frozenset({"index", "index_1", "value"})

_SLUG_RE = re.compile(r"[^a-z0-9-]+")


def slugify(value: str) -> str:
    """Convert an arbitrary name into a filesystem-safe slug.

    Args:
        value: Raw name (site or action).

    Returns:
        Lowercase slug containing only ``[a-z0-9-]``.

    Raises:
        ValueError: If nothing remains after sanitization.
    """
    slug = _SLUG_RE.sub("-", value.strip().lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        raise ValueError(f"Cannot derive a slug from {value!r}")
    return slug


class ActionParam(BaseModel):
    """Declared parameter of a :class:`SiteAction`.

    Parameters are substituted into step string fields via ``{{name}}``
    placeholders before execution (see
    :func:`parrot_tools.browsing.templating.render_steps`).

    Args:
        description: What the parameter means — shown to the LLM so it
            can map user intent ("factura al cliente X") to parameters.
        required: Whether the caller must provide a value.
        default: Value used when the caller omits the parameter.
        example: Example value, purely documentational.
    """

    description: str = ""
    required: bool = True
    default: Optional[Any] = None
    example: Optional[str] = None


class ComposedRef(BaseModel):
    """One entry of a composite action: a reference to a sibling action.

    Args:
        action: Name (slug) of the referenced action in the same site.
        params: Parameter bindings for the referenced action. String
            values may contain ``{{name}}`` placeholders resolved against
            the *parent* composite's parameters.
    """

    action: str
    params: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("action")
    @classmethod
    def _slug_action(cls, v: str) -> str:
        return slugify(v)


class SiteInfo(BaseModel):
    """Metadata of a catalogued site (one folder in the catalog).

    Args:
        site: Slug identifying the site folder (auto-derived from
            ``base_url`` domain when omitted).
        base_url: Root URL of the site (e.g. ``https://hooba.es``).
        title: Human-friendly name ("Hooba").
        description: What the site is — helps natural-language matching.
        aliases: Alternative names users may employ ("hooba", "hooba.es").
        created_at: Creation timestamp (UTC).
        updated_at: Last modification timestamp (UTC).
    """

    site: str = ""
    base_url: str
    title: str = ""
    description: str = ""
    aliases: List[str] = Field(default_factory=list)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: Optional[datetime] = None

    @property
    def domain(self) -> str:
        """Netloc of ``base_url`` (without credentials/port handling)."""
        return urlparse(self.base_url).netloc.lower()

    def model_post_init(self, __context: Any) -> None:
        """Auto-derive slug and title from the base URL when omitted."""
        if not self.site:
            self.site = slugify(self.domain or self.base_url)
        else:
            self.site = slugify(self.site)
        if not self.title:
            self.title = self.domain or self.site

    def matches(self, query: str) -> bool:
        """Check whether *query* plausibly refers to this site.

        Matches (case-insensitive) against slug, aliases, domain (with and
        without a ``www.`` prefix), base URL, and title.
        """
        q = query.strip().lower()
        if not q:
            return False
        domain = self.domain
        bare_domain = domain.removeprefix("www.")
        candidates = {
            self.site,
            domain,
            bare_domain,
            self.base_url.lower(),
            self.title.lower(),
            *(a.strip().lower() for a in self.aliases),
        }
        if q in candidates:
            return True
        try:
            return slugify(q) in {self.site, slugify(bare_domain) if bare_domain else ""}
        except ValueError:
            return False


class SiteAction(BaseModel):
    """A catalogued, deterministic script for one site.

    Non-composite actions carry ``steps`` — raw dicts in the BrowserAction
    DSL (the same shape ``ScrapingPlan.steps`` uses); call
    :meth:`validate_steps` to type-check them. Composite actions carry
    ``compose`` instead: an ordered list of references to sibling actions.

    Args:
        site: Site slug this action belongs to (set by the catalog).
        name: Action slug — unique within the site.
        title: Human-friendly name ("Iniciar sesión").
        description: Natural-language description of what the action does
            and when to use it. This is the LLM's matching material.
        kind: ``navigation`` / ``operation`` / ``composite``.
        params: Declared parameters keyed by name.
        steps: BrowserAction DSL steps (non-composite only).
        compose: Ordered references to sibling actions (composite only).
        requires: Names of prerequisite actions (e.g. ``["login"]``)
            executed beforehand unless already satisfied in the running
            sequence.
        tags: Free-form categorization tags.
        version: Script version string.
        source: Origin of the script (``user``, ``llm``, ``recorded``).
        created_at: Creation timestamp (UTC).
        updated_at: Last modification timestamp (UTC).
    """

    site: str = ""
    name: str
    title: str = ""
    description: str
    kind: ActionKind = "operation"
    params: Dict[str, ActionParam] = Field(default_factory=dict)
    steps: List[Dict[str, Any]] = Field(default_factory=list)
    compose: List[ComposedRef] = Field(default_factory=list)
    requires: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    version: str = "1.0"
    source: str = "user"
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: Optional[datetime] = None

    @field_validator("name")
    @classmethod
    def _slug_name(cls, v: str) -> str:
        return slugify(v)

    @field_validator("requires")
    @classmethod
    def _slug_requires(cls, v: List[str]) -> List[str]:
        return [slugify(item) for item in v]

    @field_validator("params")
    @classmethod
    def _reject_reserved_params(
        cls, v: Dict[str, ActionParam]
    ) -> Dict[str, ActionParam]:
        clashes = RESERVED_PLACEHOLDERS.intersection(v)
        if clashes:
            raise ValueError(
                f"Parameter name(s) {sorted(clashes)} are reserved by the "
                "Loop executor placeholders; rename them."
            )
        return v

    @model_validator(mode="after")
    def _check_shape(self) -> "SiteAction":
        if self.kind == "composite":
            if not self.compose:
                raise ValueError(
                    "composite action requires a non-empty 'compose' list"
                )
            if self.steps:
                raise ValueError(
                    "composite action must not carry 'steps' — put them in "
                    "the referenced actions instead"
                )
        else:
            if not self.steps:
                raise ValueError(
                    f"{self.kind} action requires a non-empty 'steps' list"
                )
            if self.compose:
                raise ValueError(
                    f"{self.kind} action must not carry 'compose' — use "
                    "kind='composite' for that"
                )
        return self

    def validate_steps(self) -> None:
        """Type-check ``steps`` against the BrowserAction DSL.

        Collects every step's validation error and raises once, so a
        malformed script fails at save time — before any browser opens.

        Raises:
            ValueError: One or more steps are invalid; the message names
                each offending step index.
        """
        if not self.steps:
            return
        from pydantic import ValidationError

        from parrot_tools.scraping.models import BrowserActionTypeAdapter

        errors: List[str] = []
        for idx, raw in enumerate(self.steps):
            try:
                BrowserActionTypeAdapter.validate_python(raw)
            except ValidationError as exc:
                errors.append(f"step {idx}: {exc}")
        if errors:
            raise ValueError(
                f"{len(errors)} invalid step(s):\n" + "\n".join(errors)
            )

    def summary(self) -> Dict[str, Any]:
        """Compact projection for catalog listings shown to the LLM."""
        return {
            "site": self.site,
            "name": self.name,
            "title": self.title,
            "kind": self.kind,
            "description": self.description,
            "params": {
                key: {
                    "description": p.description,
                    "required": p.required,
                    "default": p.default,
                    "example": p.example,
                }
                for key, p in self.params.items()
            },
            "requires": self.requires,
            "compose": [ref.action for ref in self.compose],
            "tags": self.tags,
            "version": self.version,
        }


class ActionRunSummary(BaseModel):
    """Outcome of executing ONE resolved action within a sequence.

    Args:
        action: Action name (slug).
        kind: Action kind executed.
        success: Whether every step completed.
        error: Error message when the action failed.
        extracted_data: Data produced by Extract/GetText/... steps.
        elapsed_ms: Wall-clock execution time in milliseconds.
        injected: True when the action was auto-injected as a
            prerequisite (``requires``) rather than requested explicitly.
    """

    action: str
    kind: ActionKind = "operation"
    success: bool
    error: Optional[str] = None
    extracted_data: Dict[str, Any] = Field(default_factory=dict)
    elapsed_ms: int = 0
    injected: bool = False


class SequenceRunResult(BaseModel):
    """Outcome of a full (possibly composite) action run.

    Args:
        success: True when every executed action succeeded.
        site: Site slug the sequence ran against.
        requested: What the caller asked for (action names, in order).
        executed: Per-action outcomes, in execution order.
        extracted_data: Merged extraction output (later actions win on
            key conflicts; keys are namespaced ``{action}.{key}`` when a
            conflict is detected).
        stopped_early: True when execution aborted on a failed action.
    """

    success: bool
    site: str
    requested: List[str] = Field(default_factory=list)
    executed: List[ActionRunSummary] = Field(default_factory=list)
    extracted_data: Dict[str, Any] = Field(default_factory=dict)
    stopped_early: bool = False
