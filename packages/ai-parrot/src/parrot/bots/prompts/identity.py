"""File-based identity loader (FEAT-321 — PromptBuilder Identity Capability).

Loads the five composable identity fields (``role``, ``goal``,
``capabilities``, ``backstory``, ``rationale``) from per-field Markdown files
in an agent-local ``identity/`` directory, mirroring the whole-blob
convention already used by :func:`parrot.bots.prompts.agent_context.load_agent_context`.

Missing or empty files fall through silently (field ``None``, debug log
only) so agents that only define a subset of the five files keep working.
File content is injected **verbatim** (no ``$``-escaping) so dynamic
variable pre-resolution (``$current_date``, etc.) keeps working exactly as
it does for inline identity — see
``sdd/specs/promptbuilder-identity-capability.spec.md`` §7.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Union

from pydantic import BaseModel, Field

from .agent_context import read_text_cached

_logger = logging.getLogger(__name__)

IDENTITY_FILES: tuple[str, ...] = (
    "role", "goal", "capabilities", "backstory", "rationale",
)


class IdentityFields(BaseModel):
    """The five composable identity fields, loaded from Markdown."""

    role: Optional[str] = Field(default=None)
    goal: Optional[str] = Field(default=None)
    capabilities: Optional[str] = Field(default=None)
    backstory: Optional[str] = Field(default=None)
    rationale: Optional[str] = Field(default=None)

    def as_kwargs(self) -> dict[str, str]:
        """Non-empty fields only, for injection as instance attributes.

        Returns:
            A dict mapping field name to value, excluding any field whose
            value is ``None`` (empty/missing files never reach here).
        """
        return {k: v for k, v in self.model_dump().items() if v}


def load_identity(
    directory: Union[str, Path],
    *,
    escape_placeholders: bool = False,
) -> IdentityFields:
    """Read ``{role,goal,capabilities,backstory,rationale}.md`` from a directory.

    Each file is read via :func:`read_text_cached` (mtime-keyed, near-free on
    repeated calls) and stripped. A missing directory, missing file, empty
    file, whitespace-only file, or unreadable file all resolve that field to
    ``None`` silently (debug log only) — the same fallthrough discipline as
    :func:`parrot.bots.prompts.agent_context.load_agent_context`.

    Content is injected **verbatim** by default — no ``$``-escaping — so
    dynamic variables (``$current_date``, etc.) pre-resolve exactly as they
    do for inline identity (``abstract.py`` lines 1200-1214). Pass
    ``escape_placeholders=True`` to double any ``$`` for locked-down
    personas that must not participate in dynamic-variable substitution.

    Args:
        directory: The ``identity/`` directory to read from.
        escape_placeholders: When ``True``, replace ``$`` with ``$$`` in
            every loaded field so ``string.Template`` treats them literally.

    Returns:
        An :class:`IdentityFields` instance with non-empty fields populated.
    """
    directory = Path(directory)
    values: dict[str, str] = {}
    for name in IDENTITY_FILES:
        file_path = directory / f"{name}.md"
        try:
            raw = read_text_cached(file_path)
        except Exception as exc:  # noqa: BLE001 - decode/permission errors, not "missing"
            _logger.warning("Could not read identity file %s: %s", file_path, exc)
            raw = ""
        content = raw.strip()
        if not content:
            _logger.debug("Identity field '%s' missing/empty at %s", name, file_path)
            continue
        if escape_placeholders:
            content = content.replace("$", "$$")
        values[name] = content
    return IdentityFields(**values)
