"""IdentityMixin — file-based identity injection + hot reload (FEAT-321).

Opt-in mixin that ties the file-based identity loader
(:mod:`parrot.bots.prompts.identity`) and the composable
:data:`~parrot.bots.prompts.domain_layers.CAPABILITIES_LAYER` together:

1. Loads ``{role,goal,capabilities,backstory,rationale}.md`` from an
   agent-local ``identity/`` directory and injects any non-empty value as an
   instance attribute *before* ``super().__init__()`` runs, so the existing
   ``kwargs.get(f) or getattr(self, f, None) or DEFAULT`` resolution chain in
   ``AbstractBot.__init__`` (abstract.py:432-452) keeps explicit kwargs
   winning while file values beat class attributes.
2. Adds ``CAPABILITIES_LAYER`` to a per-instance clone of the agent's
   effective prompt builder via :meth:`_configure_identity`, called
   explicitly by the adopting agent after ``await super().configure()`` —
   mirroring the ``SkillRegistryMixin`` / ``EpisodicMemoryMixin`` pattern
   (this mixin does NOT override ``configure()``).
3. Hot-reloads all five fields on every ``_build_prompt`` call (mtime-keyed,
   near-free) by re-cloning a pristine (never-configured) builder snapshot
   and swapping it in atomically, carrying over any transient REQUEST-phase
   layer (e.g. ``skill_active``) present on the outgoing builder.

See ``sdd/specs/promptbuilder-identity-capability.spec.md`` §2-3, §7.
"""
from __future__ import annotations

import inspect
import logging
from pathlib import Path
from string import Template
from typing import Any, Dict, Optional, Union

from ..prompts.domain_layers import CAPABILITIES_LAYER
from ..prompts.builder import PromptBuilder
from ..prompts.identity import IDENTITY_FILES, IdentityFields, load_identity

_logger = logging.getLogger(__name__)


class IdentityMixin:
    """Opt-in file-based identity injection + hot reload.

    Usage::

        class MyAgent(IdentityMixin, SomeAgentBase):
            enable_identity = True
            # identity_dir defaults to <module_dir>/identity

            async def configure(self, app=None):
                await super().configure(app)
                await self._configure_identity()

    When ``enable_identity`` is ``False`` (the default) the mixin is fully
    inert: plain ``super().__init__()`` passthrough, no file reads, no layer
    added, no ``_build_prompt`` override effects — non-adopters render a
    byte-for-byte unchanged prompt.
    """

    enable_identity: bool = False
    identity_dir: Union[str, Path, None] = None

    _identity_fields: Optional[IdentityFields] = None
    _identity_pristine: Optional[PromptBuilder] = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        if not self.enable_identity:
            super().__init__(*args, **kwargs)
            return

        directory = self._resolve_identity_dir()
        fields = load_identity(directory)
        self._identity_dir_resolved = directory
        self._identity_fields = fields
        # Inject non-empty file values as instance attributes BEFORE
        # super().__init__ runs, so AbstractBot's own
        # `kwargs.get(f) or getattr(self, f, None) or DEFAULT` resolution
        # (abstract.py:432-452) picks up the file value whenever no explicit
        # kwarg was given, while still beating any class attribute default.
        for name, value in fields.as_kwargs().items():
            setattr(self, name, value)

        # Capture the ORIGINAL caller's explicit `capabilities` kwarg (if
        # any) before super().__init__() runs — PandasAgent.__init__
        # declares its own `capabilities` named parameter and stores it as
        # self._capabilities instead of self.capabilities (data.py:550,586),
        # so by the time AbstractBot.__init__'s own
        # `kwargs.get('capabilities') or getattr(self, 'capabilities', None)
        # or DEFAULT` chain runs, the kwarg has already been stripped out of
        # **kwargs — the explicit value would otherwise be silently lost for
        # self.capabilities specifically (and therefore never reach
        # CAPABILITIES_LAYER).
        explicit_capabilities = kwargs.get("capabilities")

        super().__init__(*args, **kwargs)

        # Re-apply the ORIGINAL explicit kwarg (never the file value) when
        # one was given, so it wins over the file value on every base class
        # — including PandasAgent, where it would otherwise never reach
        # self.capabilities at all. Only fall back to the file value when no
        # explicit kwarg was passed (this is a no-op on non-swallowing base
        # classes, where AbstractBot.__init__ already resolved it via the
        # pre-super instance attribute set above).
        if explicit_capabilities:
            self.capabilities = explicit_capabilities
        elif fields.capabilities:
            self.capabilities = fields.capabilities

        # Snapshot the effective builder exactly as AbstractBot.__init__
        # left it (instance attr from `prompt_builder`/`prompt_preset`
        # kwarg, abstract.py:533-536, else the inherited class attr) BEFORE
        # configure() ever runs. __init__ and configure() are distinct
        # lifecycle phases, so this clone is guaranteed pristine
        # (never-configured, original $-templates intact) — required for
        # _build_prompt's hot reload to later re-render IDENTITY_LAYER /
        # BEHAVIOR_LAYER with fresh file content.
        if self._prompt_builder is not None:
            self._identity_init_snapshot = self._prompt_builder.clone()

    def _resolve_identity_dir(self) -> Path:
        """Resolve the ``identity/`` directory for this agent.

        Returns:
            ``self.identity_dir`` when explicitly set, else
            ``<dir of the concrete agent's module file>/identity``.
        """
        if self.identity_dir is not None:
            return Path(self.identity_dir)
        return Path(inspect.getfile(type(self))).parent / "identity"

    async def _configure_identity(self) -> None:
        """Add ``CAPABILITIES_LAYER`` to a per-instance builder clone.

        Guarded on :attr:`enable_identity`. Call explicitly after
        ``await super().configure()`` — this mixin does NOT override
        ``configure()`` (mirrors ``SkillRegistryMixin`` /
        ``EpisodicMemoryMixin``).

        Clones the pristine ``__init__``-time builder snapshot (never the
        current, possibly-already-configured ``self._prompt_builder`` —
        ``configure()`` destroys original CONFIGURE-phase templates,
        builder.py:234-241, so re-configuring an already-configured builder
        with new values is impossible), adds ``CAPABILITIES_LAYER``, stashes
        a never-configured copy as :attr:`_identity_pristine` for future hot
        reloads, then re-runs the inherited (async) ``_configure_prompt_builder``
        against the new clone — reusing the framework's own full context
        assembly (identity + security + tools + pre_instructions + dynamic
        values, abstract.py:1179-1240) instead of duplicating it.
        """
        if not self.enable_identity:
            return

        source = getattr(self, "_identity_init_snapshot", None)
        if source is None:
            if self._prompt_builder is None:
                self.logger.debug(
                    "IdentityMixin: no prompt builder to configure identity on"
                )
                return
            source = self._prompt_builder.clone()

        working = source.clone()
        working.add(CAPABILITIES_LAYER)
        # Stash BEFORE configuring: this is the reusable, never-configured
        # source cloned again on every future hot reload.
        self._identity_pristine = working.clone()

        self._prompt_builder = working
        await self._configure_prompt_builder()

        # Cache dynamic values (abstract.py:1185-1192) for reuse by the sync
        # hot-reload path (_identity_hot_reload_context), which cannot await.
        self._identity_dynamic_context = await self._resolve_dynamic_context()

        self.logger.debug(
            "IdentityMixin: configured prompt builder with CAPABILITIES_LAYER (dir=%s)",
            getattr(self, "_identity_dir_resolved", self.identity_dir),
        )

    async def _resolve_dynamic_context(self) -> Dict[str, str]:
        """Resolve every registered dynamic value (mirrors abstract.py:1185-1192).

        Cached on :attr:`_identity_dynamic_context` by :meth:`_configure_identity`
        so the synchronous hot-reload path can reuse the values without
        awaiting inside ``_build_prompt``.

        Returns:
            A mapping of dynamic-value name to its resolved string value.
        """
        from ..dynamic_values import dynamic_values

        context: Dict[str, str] = {}
        for name in dynamic_values.get_all_names():
            try:
                context[name] = await dynamic_values.get_value(name, {})
            except Exception as exc:  # noqa: BLE001 - mirror abstract.py's warning-and-continue
                self.logger.warning(
                    "IdentityMixin: error resolving dynamic value '%s': %s", name, exc
                )
                context[name] = ""
        return context

    def _build_prompt(self, *args: Any, **kwargs: Any):
        """Hot-reload seam: re-check identity files, then delegate to super().

        Re-runs :func:`load_identity` (near-free — mtime-keyed lru cache) on
        every call. When the loaded fields differ from the last-applied
        snapshot, re-clones the pristine builder, re-configures it with a
        minimal, synchronously-computable context, carries over any
        transient REQUEST-phase layer present on the outgoing builder
        (e.g. ``skill_active``), and atomically swaps ``self._prompt_builder``
        before delegating to ``super()._build_prompt(...)``.
        """
        if not self.enable_identity:
            return super()._build_prompt(*args, **kwargs)

        directory = getattr(self, "_identity_dir_resolved", None) or self._resolve_identity_dir()
        fields = load_identity(directory)
        if fields != self._identity_fields:
            self._reload_identity(fields)
        return super()._build_prompt(*args, **kwargs)

    def _reload_identity(self, fields: IdentityFields) -> None:
        """Apply newly-loaded identity fields and swap the prompt builder.

        Args:
            fields: The freshly-loaded :class:`IdentityFields` snapshot
                (already confirmed to differ from the last-applied one).
        """
        for name in IDENTITY_FILES:
            value = getattr(fields, name)
            if value:
                setattr(self, name, value)
        self._identity_fields = fields

        pristine = self._identity_pristine
        if pristine is None:
            self.logger.debug(
                "IdentityMixin: identity files changed but no pristine "
                "builder is stashed yet (configure() not called?)"
            )
            return

        old_builder = self._prompt_builder
        fresh = pristine.clone()
        fresh.configure(self._identity_hot_reload_context())

        # Carry over transient layers present on the old builder but absent
        # from the fresh clone (e.g. "skill_active", added by
        # create_system_prompt() at abstract.py:2772 before _build_prompt
        # runs and removed at 2786 after — remove() is a no-op on missing
        # names, builder.py:164-174, so cleanup on the new builder is safe).
        if old_builder is not None:
            carry_over = set(old_builder.layer_names) - set(fresh.layer_names)
            for name in carry_over:
                layer = old_builder.get(name)
                if layer is not None:
                    fresh.add(layer)

        self._prompt_builder = fresh  # single assignment = atomic swap
        self.logger.info("IdentityMixin: hot-reloaded identity/*.md changes")

    def _identity_hot_reload_context(self) -> Dict[str, Any]:
        """Minimal CONFIGURE-phase context for the synchronous hot-reload path.

        ``_build_prompt`` is synchronous (abstract.py:1242), so this
        replicates only the cheap, synchronously-computable subset of
        ``AbstractBot._configure_prompt_builder``'s configure context
        (abstract.py:1208-1227) — the five identity fields plus the static
        extras needed so unconditional CONFIGURE-phase layers already in
        the pristine stack (``security``, ``rag_grounding``, if present)
        don't bake in a literal, unresolved ``$placeholder``. The async
        ``dynamic_values`` expansion (abstract.py:1185-1192) is intentionally
        NOT recomputed here (would require blocking the running event loop);
        cached dynamic values from the last ``_configure_identity()`` run
        are reused instead so ``$current_date``-style tokens embedded in
        identity text still resolve rather than leaking as literal text.
        """
        dynamic_context = getattr(self, "_identity_dynamic_context", {})

        def _resolve(raw: str) -> str:
            return Template(raw).safe_substitute(dynamic_context) if raw else raw

        pre_instructions = getattr(self, "pre_instructions", [])
        pre_content = (
            "\n".join(f"- {inst}" for inst in pre_instructions)
            if pre_instructions else ""
        )
        has_tools = bool(
            getattr(self, "enable_tools", False)
            and self.tool_manager.tool_count() > 0
        )
        context: Dict[str, Any] = {
            "name": self.name,
            "role": _resolve(getattr(self, "role", "")),
            "goal": _resolve(getattr(self, "goal", "")),
            "capabilities": _resolve(getattr(self, "capabilities", "")),
            "backstory": _resolve(getattr(self, "backstory", "")),
            "rationale": _resolve(getattr(self, "rationale", "")),
            "pre_instructions_content": pre_content,
            "extra_security_rules": "",
            "has_tools": has_tools,
            "extra_tool_instructions": "",
            "extra_rag_rules": _resolve(getattr(self, "extra_rag_rules", "")),
            **dynamic_context,
        }

        # FEAT-181: when prompt_caching is on, AbstractBot.__init__ adds
        # AGENT_CONTEXT_LAYER to the pristine builder (abstract.py:538-541)
        # before this mixin ever ran, so it is present (and still
        # CONFIGURE-phase, gated on this key) in every pristine clone.
        # load_agent_context is a plain sync call (agent_context.py:57), so
        # it is safe to include here — omitting it would let the layer's
        # condition evaluate False on the first hot reload and silently gate
        # the layer off for the remaining lifetime of this instance (a
        # PromptLayer whose condition fails keeps its CONFIGURE phase,
        # builder.py/layers.py partial_render, but a subsequent build()
        # re-evaluates that same failing condition against REQUEST context,
        # which never carries this key either).
        if getattr(self, "_prompt_caching", False):
            from ..prompts.agent_context import load_agent_context

            context["agent_context_content"] = load_agent_context(self.name)

        return context
