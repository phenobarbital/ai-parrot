"""
Skill trigger middleware for the prompt pipeline.

Factory function that creates a PromptMiddleware detecting /trigger patterns
at the start of user messages, stripping the prefix, setting the activated
SkillDefinition on the bot instance, and handling reserved /skills and /help
triggers.
"""
from typing import Any, Dict

from parrot.bots.middleware import PromptMiddleware

from .file_registry import SkillFileRegistry


def create_skill_trigger_middleware(
    registry: SkillFileRegistry,
    bot: "AbstractBot",
    priority: int = -10,
) -> PromptMiddleware:
    """Create a PromptMiddleware that detects /trigger patterns.

    The middleware intercepts user messages starting with ``/``, looks up the
    trigger in the registry, and if found:
    - Sets ``bot._active_skill`` to the matching SkillDefinition
    - Returns the remaining text after the trigger

    Reserved triggers ``/skills`` and ``/help`` return a formatted listing
    of available skills.

    Args:
        registry: The SkillFileRegistry to look up triggers in.
        bot: The bot instance — used to set ``_active_skill`` via closure.
        priority: Middleware priority (lower runs first). Default ``-10``.

    Returns:
        A configured PromptMiddleware instance.
    """

    async def transform(query: str, context: Dict[str, Any]) -> str:
        if not query or not query.startswith("/"):
            return query

        # Split trigger from remaining text
        parts = query.split(None, 1)  # maxsplit=1
        trigger = parts[0]
        remaining = parts[1] if len(parts) > 1 else ""

        # Reserved triggers
        if trigger in ("/skills", "/help"):
            skills = registry.list_skills()
            if not skills:
                return "No skills available."
            listing = "\n".join(
                f"- {', '.join(s.triggers)}: {s.description}"
                for s in skills
            )
            return f"Available skills:\n{listing}"

        # Skill lookup
        skill = registry.get(trigger)
        if skill is not None:
            bot._active_skill = skill  # Set via closure reference
            return remaining

        # Unknown trigger — pass through unchanged
        return query

    return PromptMiddleware(
        name="skill_trigger",
        priority=priority,
        transform=transform,
    )
