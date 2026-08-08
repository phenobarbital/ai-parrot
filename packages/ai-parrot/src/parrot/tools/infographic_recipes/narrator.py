"""``Narrator`` protocol — the LLM injection seam for narrative rendering (FEAT-420).

Lives under ``parrot.tools.infographic_recipes`` (never under
``parrot.outputs.a2ui``) because spec G8 forbids ``outputs/a2ui/**`` from
importing agents or LLM clients (``builders.py:11-12``).
``parrot.tools.infographic_recipes`` is the sanctioned side — it already
imports ``DatasetManager`` for the same reason.

This module is intentionally a pure typing module: it imports NOTHING from
``parrot`` so it can never become a G8 violation vector.
"""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

__all__ = ["Narrator"]


@runtime_checkable
class Narrator(Protocol):
    """Renders deterministic facts as prose. Implementations may call an LLM.

    Implementations MUST NOT raise into the caller: return ``None`` on any
    failure (missing skill, LLM error, figure-guard rejection, ...) so a
    replay degrades to facts-without-prose rather than aborting (spec
    criterion G-E). ``RecipeRunner``'s narrative step relies on this
    contract; :class:`~parrot.bots.mixins.narrative.NarrativeMixin`
    implements it.
    """

    async def narrate(self, facts: dict[str, Any], skill: str) -> Optional[str]:
        """Render ``facts`` as prose using the named skill.

        Args:
            facts: The deterministic facts to render (e.g. the
                ``narrative_facts`` transformer's output).
            skill: Registered skill name that teaches the LLM how to render
                ``facts`` as prose.

        Returns:
            The generated prose, or ``None`` on any failure.
        """
        ...
