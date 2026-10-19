"""
Skill trigger middleware for the prompt pipeline.

Factory function that creates a PromptMiddleware detecting /trigger patterns
at the start of user messages, stripping the prefix, setting the activated
SkillDefinition on the bot instance, and handling reserved /skills and /help
triggers.
"""

from typing import Any, Callable, Dict, Optional

from parrot.bots.middleware import PromptMiddleware

from .file_registry import SkillFileRegistry
from .tenancy import set_active_skill


def create_skill_trigger_middleware(
    registry: SkillFileRegistry,
    bot: "AbstractBot",
    priority: int = -10,
    *,
    view_provider: Optional[Callable[[], Any]] = None,
) -> PromptMiddleware:
    """Create a PromptMiddleware that detects /trigger patterns.

    The middleware intercepts user messages starting with ``/``, looks up the
    trigger in the registry, and if found:
    - Sets the request-local active skill to the matching SkillDefinition
    - Preserves ``bot._active_skill`` for legacy bot implementations
    - Returns the remaining text after the trigger

    Reserved triggers ``/skills`` and ``/help`` return a formatted listing
    of available skills.

    Args:
        registry: The SkillFileRegistry to look up triggers in.
        bot: The bot instance — used to set ``_active_skill`` via closure.
        priority: Middleware priority (lower runs first). Default ``-10``.
        view_provider: Optional callable returning the current per-request
            SkillView (FEAT-707). The constructor registry is used when it
            returns ``None`` or is not provided.

    Returns:
        A configured PromptMiddleware instance.
    """

    def _reg() -> Any:
        current = view_provider() if view_provider is not None else None
        return current if current is not None else registry

    async def transform(query: str, context: Dict[str, Any]) -> str:
        if not query or not query.startswith("/"):
            return query

        # Split trigger from remaining text
        parts = query.split(None, 1)  # maxsplit=1
        trigger = parts[0]
        remaining = parts[1] if len(parts) > 1 else ""

        # Reserved triggers
        if trigger in ("/skills", "/help"):
            skills = _reg().list_skills()
            if not skills:
                return "No skills available."
            listing = "\n".join(
                f"- {', '.join(s.triggers)}: {s.description}"
                for s in skills
                if s.triggers  # skip skills with no triggers (loaded via load_skill, not /trigger)
            )
            return f"Available skills:\n{listing}"

        # Skill lookup
        skill = _reg().get(trigger)
        if skill is not None:
            set_active_skill(skill)  # request-local (FEAT-707, S5)
            bot._active_skill = skill  # Set via closure reference
            return remaining

        # Unknown trigger — pass through unchanged
        return query

    return PromptMiddleware(
        name="skill_trigger",
        priority=priority,
        transform=transform,
    )
