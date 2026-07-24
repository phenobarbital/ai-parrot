"""InfographicAuthoringMixin — tier-1 infographic authoring for agents (FEAT-326).

A **cooperative mixin** (same pattern as
:class:`~parrot.bots.mixins.model_switching.ModelSwitchingMixin`) composable
onto :class:`~parrot.bots.data.PandasAgent` — or any ``DatasetManager``-bearing
agent — that wires a pre-configured :class:`InfographicToolkit` into the agent
and adds the tier-1 authoring API::

    class MyAgent(InfographicAuthoringMixin, PandasAgent):
        ...

    agent = MyAgent(name="reporter", artifact_store=store, template_dirs=[...])

Tier 1 (``generate_infographic``) builds a one-shot infographic from ad-hoc data
and returns a :class:`ProvenanceDescriptor` that records datasets/params/section
mapping and snapshot timestamps — but **never** the python code used to build it
(resolved brainstorm decision; spec §2 / §5). Tier 2 (``publish_recipe``) is
added by TASK-1885.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

from parrot.tools.infographic_sections import (
    GapReport,
    ProvenanceDescriptor,
    SectionDescriptor,
    SectionSpec,
    TransformerGap,
    validate_descriptor_datasets,
)
from parrot.tools.infographic_toolkit import (
    InfographicRenderResult,
    InfographicToolkit,
)
from parrot.outputs.a2ui.recipes.models import (
    DataSourceSpec,
    InfographicRecipe,
    LayoutSpec,
    RenderSpec,
    TransformStep,
)
from parrot.outputs.a2ui.recipes.store import RecipeNotFoundError
from parrot.outputs.a2ui.recipes.transformers import transformer_registry

logger = logging.getLogger(__name__)


class InfographicAuthoringMixin:
    """Cooperative mixin adding infographic authoring to a data agent.

    Mix in **before** the agent class so the MRO reaches this class first::

        class MyAgent(InfographicAuthoringMixin, PandasAgent): ...

    Constructor kwargs (all optional; popped before the cooperative
    ``super().__init__`` chain):
        infographic_toolkit: A pre-built :class:`InfographicToolkit` to wire in.
        artifact_store: Used to build an :class:`InfographicToolkit` when
            ``infographic_toolkit`` is not supplied.
        recipe_store: Optional recipe store forwarded to the built toolkit
            (enables tier-2 ``publish_recipe`` + the toolkit's recipe tools).
        template_dirs: Optional template directory(ies) forwarded to the built
            toolkit (the data-splice template registry).
    """

    def __init__(
        self,
        *args: Any,
        infographic_toolkit: Optional[InfographicToolkit] = None,
        artifact_store: Optional[Any] = None,
        recipe_store: Optional[Any] = None,
        template_dirs: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        """Build/accept the toolkit, register its tools, then chain ``__init__``."""
        if infographic_toolkit is None and artifact_store is not None:
            infographic_toolkit = InfographicToolkit(
                artifact_store=artifact_store,
                recipe_store=recipe_store,
                template_dirs=template_dirs,
            )
        self._infographic_toolkit: Optional[InfographicToolkit] = infographic_toolkit

        # Register the toolkit through the standard tools= path so its tools land
        # in the agent's ToolManager (``_initialize_tools`` accepts a toolkit
        # instance directly — see parrot/interfaces/tools.py).
        if infographic_toolkit is not None:
            tools = list(kwargs.pop("tools", None) or [])
            tools.append(infographic_toolkit)
            kwargs["tools"] = tools

        super().__init__(*args, **kwargs)

        # Bind the toolkit to this agent (enables scope resolution for renders
        # and prompt-guidance injection). Idempotent; re-run in configure().
        if self._infographic_toolkit is not None:
            self._infographic_toolkit.set_bot(self)

    async def configure(self, *args: Any, **kwargs: Any) -> None:
        """Re-bind the toolkit (prompt guidance) before base configuration.

        ``InfographicToolkit.set_bot`` appends its usage guidance to the bot's
        ``system_prompt_template``; it must run BEFORE the base ``configure()``
        finalises the prompt. Cooperative: chains ``super().configure()``.
        """
        if self._infographic_toolkit is not None:
            self._infographic_toolkit.set_bot(self)
        await super().configure(*args, **kwargs)

    # ── Tier 1 — one-shot authoring ─────────────────────────────────────────

    async def generate_infographic(
        self,
        template: str,
        descriptor: "SectionDescriptor | str",
        params: Optional[dict] = None,
    ) -> Tuple[InfographicRenderResult, ProvenanceDescriptor]:
        """Build a one-shot (tier-1) infographic from the section descriptor.

        Flow (spec §2): coerce descriptor → **fail-fast validation gate** →
        build per-section data → render via the toolkit (data-splice or Jinja
        per ``descriptor.mode``) → persist → return the render result plus a
        :class:`ProvenanceDescriptor` (datasets/params/mapping + snapshot
        timestamps — NO python code).

        Args:
            template: Registered template name to render (should match
                ``descriptor.template``).
            descriptor: A :class:`SectionDescriptor` or its JSON string.
            params: Optional parameters (e.g. ``{"title": "...", ...}``).

        Returns:
            ``(InfographicRenderResult, ProvenanceDescriptor)``.

        Raises:
            InfographicValidationError: When the descriptor's datasets/columns
                are unmet — raised BEFORE any build/render/persist.
            RuntimeError: When no toolkit or DatasetManager is wired.
        """
        descriptor = self._coerce_descriptor(descriptor)
        params = dict(params or {})
        toolkit = self._require_toolkit()
        dm = self._require_dm()

        # Fail-fast: never build/render/persist with unmet datasets/columns.
        validate_descriptor_datasets(descriptor, dm)

        payload, snapshots = await self._build_section_payload(descriptor, params)

        if descriptor.mode == "data-splice":
            result = await toolkit.render_data_template(
                template,
                payload,
                descriptor=descriptor,
                title=params.get("title"),
            )
        else:
            result = await toolkit.render_template(
                template,
                data=payload,
                title=params.get("title"),
            )

        provenance = ProvenanceDescriptor(
            descriptor=descriptor,
            dataset_snapshots=snapshots,
            artifact_id=result.artifact_id,
            tier="one-shot",
            recipe_ref=None,
        )
        self.logger.info(
            "Generated tier-1 infographic: artifact=%s template=%s mode=%s",
            result.artifact_id, template, descriptor.mode,
        )
        return result, provenance

    async def _build_section_payload(
        self,
        descriptor: SectionDescriptor,
        params: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], Dict[str, str]]:
        """Assemble the payload and dataset snapshot timestamps for a descriptor.

        This is the programmatic (deterministic) build seam: each section's
        declared datasets/columns are shaped per ``SectionSpec.shape`` and placed
        under the section's ``target`` key. Conversational authoring instead
        drives the agent's pandas REPL tools; subclasses/tests may override this
        hook. NEVER records the code used to build the data.

        Args:
            descriptor: The validated descriptor.
            params: Author-supplied parameters (unused by the default build).

        Returns:
            ``(payload, dataset_snapshots)``.
        """
        dm = self._require_dm()
        payload: Dict[str, Any] = {}
        snapshots: Dict[str, str] = {}
        now_iso = datetime.now(timezone.utc).isoformat()
        for section in descriptor.sections:
            frames: Dict[str, Any] = {}
            for alias in section.datasets:
                entry = dm.get_dataset_entry(alias)
                df = getattr(entry, "df", None) if entry is not None else None
                if df is None and entry is not None and hasattr(dm, "fetch_dataset"):
                    df = await dm.fetch_dataset(alias)
                frames[alias] = df
                snapshots[alias] = now_iso
            key = section.target.lstrip("/")
            payload[key] = self._assemble_section(section, frames)
        return payload, snapshots

    @staticmethod
    def _assemble_section(section: SectionSpec, frames: Dict[str, Any]) -> Any:
        """Shape a section's dataset(s) into its declared ``shape``.

        Uses the first non-empty declared dataset. Column projection is applied
        when the section declares required columns for that alias.
        """
        df = None
        primary_alias = section.datasets[0] if section.datasets else None
        if primary_alias is not None:
            df = frames.get(primary_alias)
        if df is None:
            if section.shape in ("records", "table"):
                return []
            if section.shape == "mapping":
                return {}
            return None
        cols = section.columns.get(primary_alias or "", None)
        if cols:
            df = df[cols]
        if section.shape == "records":
            return df.to_dict("records")
        if section.shape == "table":
            return df.values.tolist()
        if section.shape == "mapping":
            return df.to_dict()
        # scalar
        return df.iloc[0, 0] if not df.empty else None

    # ── Tier 2 — publication ────────────────────────────────────────────────

    async def publish_recipe(
        self,
        name: str,
        descriptor: "SectionDescriptor | str",
        owner: Optional[str] = None,
        delivery: Optional[dict] = None,
        overwrite: bool = False,
    ) -> Union[InfographicRecipe, GapReport]:
        """Publish a descriptor as a deterministic FEAT-324 recipe (tier 2).

        Maps each descriptor section onto a **registered** transformer as a
        :class:`TransformStep`. Full coverage → build and save an
        :class:`InfographicRecipe` carrying the ``section_descriptor`` and a
        :class:`RenderSpec` with the supplied ``delivery`` config. ANY unmapped
        section → return a :class:`GapReport` (with a human-registerable
        ``suggested_source`` per gap) and save **nothing** (spec G1: never store
        or execute code).

        Section → transformer resolution uses the section's name, normalised to
        a Python identifier, as the registry key.

        Args:
            name: Recipe name (scoped by ``owner``).
            descriptor: A :class:`SectionDescriptor` or its JSON string.
            owner: Recipe owner scope.
            delivery: Optional delivery config → ``RenderSpec.delivery``.
            overwrite: Replace an existing ``(name, owner)`` recipe. When False,
                a collision raises.

        Returns:
            The saved :class:`InfographicRecipe`, or a :class:`GapReport` when
            coverage is partial.

        Raises:
            ValueError: On a ``(name, owner)`` collision when ``overwrite`` is
                False.
            RuntimeError: When no recipe store is wired.
        """
        descriptor = self._coerce_descriptor(descriptor)
        store = self._require_recipe_store()

        if not overwrite:
            try:
                await store.get(name, owner)
            except RecipeNotFoundError:
                pass
            else:
                raise ValueError(
                    f"Recipe (name={name!r}, owner={owner!r}) already exists; "
                    f"pass overwrite=True to replace it."
                )

        transforms: List[TransformStep] = []
        gaps: List[TransformerGap] = []
        covered: List[str] = []
        for section in descriptor.sections:
            tname = self._transformer_name(section)
            try:
                transformer_registry.get(tname)
            except KeyError:
                gaps.append(
                    TransformerGap(
                        section=section.name,
                        proposed_name=tname,
                        suggested_source=self._suggest_transformer_source(section, tname),
                    )
                )
                continue
            transforms.append(
                TransformStep(
                    transformer=tname,
                    inputs=list(section.datasets),
                    params=dict(descriptor.params),
                    output_key=section.target.lstrip("/"),
                )
            )
            covered.append(section.name)

        if gaps:
            self.logger.info(
                "publish_recipe(%s): partial coverage — %d gap(s); recipe NOT saved.",
                name, len(gaps),
            )
            return GapReport(gaps=gaps, covered=covered)

        # Full coverage → build + persist the recipe.
        aliases: List[str] = []
        for section in descriptor.sections:
            for alias in section.datasets:
                if alias not in aliases:
                    aliases.append(alias)
        data_sources = [DataSourceSpec(dataset=alias, alias=alias) for alias in aliases]

        recipe = InfographicRecipe(
            name=name,
            title=name,
            owner=owner,
            data_sources=data_sources,
            transforms=transforms,
            layout=LayoutSpec(
                component="Infographic",
                properties={"template": descriptor.template},
            ),
            render=RenderSpec(delivery=delivery),
            section_descriptor=descriptor,
            updated_at=datetime.now(timezone.utc),
        )
        await store.save(recipe)
        self.logger.info(
            "publish_recipe(%s): saved with %d transform(s), delivery=%s.",
            name, len(transforms), bool(delivery),
        )
        return recipe

    @staticmethod
    def _transformer_name(section: SectionSpec) -> str:
        """Normalise a section name into a transformer-registry key/identifier."""
        return re.sub(r"\W+", "_", section.name).strip("_")

    @staticmethod
    def _suggest_transformer_source(section: SectionSpec, fn_name: str) -> str:
        """Return a human-registerable transformer skeleton (NEVER executed).

        Derived from the section's declared inputs/output shape — text only, for
        a developer to review and register with ``@infographic_transformer``.
        """
        inputs = ", ".join(section.datasets) or "<dataset aliases>"
        return (
            f"# Suggested transformer for section '{section.name}'.\n"
            f"# FOR HUMAN REVIEW + REGISTRATION ONLY — this text is never executed.\n"
            f"from parrot.outputs.a2ui.recipes.transformers import infographic_transformer\n\n"
            f"@infographic_transformer({fn_name!r})\n"
            f"def {fn_name}(inputs: dict, params: dict) -> dict:\n"
            f"    # Required input aliases: {inputs}\n"
            f"    # Expected output shape: {section.shape} (target {section.target!r})\n"
            f"    raise NotImplementedError('Implement the {section.name!r} transform')\n"
        )

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _coerce_descriptor(descriptor: "SectionDescriptor | str") -> SectionDescriptor:
        """Return a :class:`SectionDescriptor`, parsing a JSON string if needed."""
        if isinstance(descriptor, SectionDescriptor):
            return descriptor
        if isinstance(descriptor, str):
            return SectionDescriptor.model_validate_json(descriptor)
        raise TypeError(
            f"descriptor must be a SectionDescriptor or JSON string, got "
            f"{type(descriptor).__name__}"
        )

    def _require_toolkit(self) -> InfographicToolkit:
        """Return the wired toolkit or raise a clear error."""
        toolkit = getattr(self, "_infographic_toolkit", None)
        if toolkit is None:
            raise RuntimeError(
                "InfographicAuthoringMixin: no InfographicToolkit is wired. "
                "Pass infographic_toolkit= or artifact_store= to the agent."
            )
        return toolkit

    def _require_dm(self) -> Any:
        """Return the agent's DatasetManager or raise a clear error."""
        dm = getattr(self, "_dataset_manager", None)
        if dm is None:
            raise RuntimeError(
                "InfographicAuthoringMixin: no DatasetManager found on the agent "
                "(compose onto PandasAgent or a DatasetManager-bearing agent)."
            )
        return dm

    def _require_recipe_store(self) -> Any:
        """Return the wired recipe store or raise a clear error."""
        toolkit = self._require_toolkit()
        store = getattr(toolkit, "_recipe_store", None)
        if store is None:
            raise RuntimeError(
                "InfographicAuthoringMixin.publish_recipe requires a recipe store; "
                "pass recipe_store= (or a toolkit configured with one)."
            )
        return store
