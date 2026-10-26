"""Caller-side inter-agent grant (FEAT-747 M4). Configuration, never model-visible."""
from __future__ import annotations

import fnmatch
import logging
from typing import Iterable, Optional

from .directory import CapabilityMatch, InterAgentGrant, RoostAgentConfig

logger = logging.getLogger(__name__)


class GrantDenied(Exception):
    """A lookup, mount or send targeted a capability outside the caller's grant."""


class GrantPolicy:
    """Deterministic scope check over ``RoostAgentConfig.grant``."""

    def __init__(self, *, default_deny: bool = True) -> None:
        self.default_deny = default_deny

    def allows(self, config: Optional[RoostAgentConfig], cap_id: str) -> bool:
        """True iff a scope of ``config.grant`` fnmatch-es *cap_id*; False when config/grant is missing.

        Args:
            config: The caller's Roost configuration (may be None).
            cap_id: Capability id being looked up, mounted or called.

        Returns:
            Whether the caller's grant covers *cap_id* (fail-closed).
        """
        if config is None or config.grant is None or not config.grant.scopes:
            logger.debug("Grant denied for %s: no grant configured", cap_id)
            return False
        return any(fnmatch.fnmatchcase(cap_id, scope) for scope in config.grant.scopes)

    def attenuate(self, requester: Optional[InterAgentGrant], awardee: Optional[InterAgentGrant]) -> InterAgentGrant:
        """Scopes the awardee may use for an awarded task (intersection, AC-14).

        Args:
            requester: The grant of the agent awarding the task.
            awardee: The awardee's own grant.

        Returns:
            A grant containing only awardee scopes covered by a requester scope.
        """
        if requester is None or awardee is None:
            return InterAgentGrant(scopes=[])
        kept: list[str] = []
        for scope in awardee.scopes:
            probe = scope.rstrip("*").rstrip(".") or scope
            if any(r == "*" or fnmatch.fnmatchcase(probe, r) for r in requester.scopes):
                kept.append(scope)
        return InterAgentGrant(scopes=kept)

    def filter_matches(self, config: Optional[RoostAgentConfig],
                       matches: Iterable[CapabilityMatch]) -> list[CapabilityMatch]:
        """Keep only matches the caller may call; order preserved."""
        return [m for m in matches if self.allows(config, m.cap_id)]
