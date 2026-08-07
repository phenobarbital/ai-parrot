"""``NarrativeMixin`` — a reusable ``Narrator`` implementation over skills (FEAT-420).

Renders deterministic facts as prose by resolving a named skill (body +
assets), building a prompt, calling the composing agent's configured LLM,
and applying the figure guard so no invented figure ever reaches a rendered
artifact (spec criterion G-H). Carries NO domain vocabulary (criterion G-I):
any facts dict and any skill name work, so a second reporting agent can
compose this mixin unchanged.

Satisfies :class:`~parrot.tools.infographic_recipes.narrator.Narrator`.
Every failure path — missing skill, LLM error, guard rejection — logs a
warning and returns ``None`` rather than raising (spec criterion G-E): the
runner's best-effort narrative step relies on this contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from parrot.skills.mixin import SkillRegistryMixin
from parrot.skills.models import SkillDefinition
from parrot.tools.infographic_recipes.figure_guard import figures_are_derivable

__all__ = ["NarrativeMixin"]


class NarrativeMixin(SkillRegistryMixin):
    """Implements ``Narrator`` over :class:`SkillRegistryMixin`.

    Cooperative mixin — mix in BEFORE the agent class::

        class MyAgent(NarrativeMixin, InfographicAuthoringMixin, PandasAgent): ...

    Inherits :class:`~parrot.skills.mixin.SkillRegistryMixin` directly (rather
    than requiring every composing agent to add it separately) so the
    ``narrate()`` capability is self-sufficient wherever this mixin is used —
    consistent with criterion G-I (no one-off wiring per agent).
    """

    #: Agent-level default skill name, used when a caller of :meth:`narrate`
    #: passes an empty/``None`` ``skill``. The runner's narrative step always
    #: passes the recipe's declared skill explicitly; this is the fallback
    #: for direct calls.
    narrative_skill: Optional[str] = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

    async def configure(self, *args: Any, **kwargs: Any) -> None:
        await super().configure(*args, **kwargs)

    async def narrate(self, facts: dict[str, Any], skill: str) -> Optional[str]:
        """Render ``facts`` as prose using the named skill, or ``None`` on failure.

        Args:
            facts: The deterministic facts to render.
            skill: Registered skill name; falls back to
                :attr:`narrative_skill` when falsy.

        Returns:
            The generated, guard-verified prose, or ``None`` on ANY failure
            (missing skill, LLM error, empty output, or a non-derivable
            figure — spec criterion G-H discards the WHOLE narrative, never
            just the offending sentence).
        """
        name = skill or self.narrative_skill
        if not name:
            self.logger.warning("narrate() called with no skill name; skipping.")
            return None
        try:
            definition = await self._load_narrative_skill(name)
            if definition is None:
                self.logger.warning("Narrative skill %r not found; skipping.", name)
                return None
            prompt = self._build_narrative_prompt(definition, facts)
            prose = await self._call_llm_for_narrative(prompt)
        except Exception as exc:  # noqa: BLE001 — narrative is never fatal
            self.logger.warning("Narrative generation failed (%s); skipping.", exc)
            return None
        if not prose or not prose.strip():
            return None
        ok, offending = figures_are_derivable(prose, facts)
        if not ok:
            self.logger.warning(
                "Discarding narrative: %d non-derivable figure(s) %r.",
                len(offending),
                offending,
            )
            return None
        return prose.strip()

    async def _load_narrative_skill(self, name: str) -> Optional[SkillDefinition]:
        """Resolve a skill by name via the file-based skill registry.

        Lazily configures the registry (idempotent — `_configure_skill_registry`
        returns early once already configured) so narration works even for an
        agent that never explicitly called it during its own `configure()`.

        Args:
            name: Skill name as declared in its frontmatter `name:` field.

        Returns:
            The matching :class:`SkillDefinition`, or ``None`` if not found
            or no file registry is available.
        """
        await self._configure_skill_registry()
        registry = getattr(self, "_skill_file_registry", None)
        if registry is None:
            return None
        return registry.get_by_name(name)

    def _build_narrative_prompt(
        self, definition: SkillDefinition, facts: dict[str, Any]
    ) -> str:
        """Build the LLM prompt from the skill body, its assets, and the facts.

        Reads `definition.assets_dir` directly as a plain `Path` (the
        internal path — `read_skill_asset` is a sandboxed *tool* meant for
        LLM-facing tool-call dispatch, not for code calling a skill's own
        content internally).

        Args:
            definition: The resolved skill definition. Accessed via
                `getattr` (duck-typed) rather than assumed to be a real
                `SkillDefinition`, so a minimal test double works too.
            facts: The deterministic facts to render.

        Returns:
            The composed prompt text.
        """
        sections = [getattr(definition, "template_body", "") or ""]
        assets_text = self._read_narrative_assets(definition)
        if assets_text:
            sections.append(assets_text)
        sections.append(f"Facts (JSON):\n{json.dumps(facts, indent=2, default=str)}")
        return "\n\n".join(sections)

    def _read_narrative_assets(self, definition: SkillDefinition) -> str:
        """Read a composite skill's Markdown assets (never `SKILL.md` itself).

        Args:
            definition: The resolved skill definition (duck-typed via
                `getattr`, see :meth:`_build_narrative_prompt`).

        Returns:
            The concatenated asset contents, or an empty string when the
            skill is single-file (no `assets_dir`) or has no assets.
        """
        assets_dir_value = getattr(definition, "assets_dir", None)
        if not assets_dir_value:
            return ""
        assets_dir = Path(assets_dir_value)
        if not assets_dir.is_dir():
            return ""
        parts = []
        for path in sorted(assets_dir.glob("*.md")):
            if path.name == "SKILL.md":
                continue
            parts.append(f"### {path.name}\n\n{path.read_text()}")
        return "\n\n".join(parts)

    async def _call_llm_for_narrative(self, prompt: str) -> Optional[str]:
        """Call the agent's configured LLM through the standard bot seam.

        Routes through `self.get_client()` / `self.execute_llm_call()` —
        the SAME cooperative seam `ModelSwitchingMixin` builds on — never a
        provider SDK directly. Provider-agnostic: works identically whether
        the agent is configured with a Google, Amazon, or any other client.

        Args:
            prompt: The composed prompt text.

        Returns:
            The model's textual response, or ``None`` if the client returned
            no textual content.
        """
        client = self.get_client()
        async with client as entered:
            response = await self.execute_llm_call(entered, "ask", prompt=prompt)
        return getattr(response, "response", None) or getattr(response, "output", None)
