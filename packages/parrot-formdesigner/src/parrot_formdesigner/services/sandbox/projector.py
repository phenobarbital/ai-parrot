"""Live FormEventContext -> serialisable SandboxContext (FEAT-459 / M7).

Resolves OQ-5: token/headers NEVER cross the sandbox boundary at any tier
(structurally — SandboxContext has no such field to populate). Tier 1
receives no identity at all. Tiers 2-4 receive an identical projected
identity set — the governing invariant is that MORE TIER NEVER MEANS MORE
SECRETS, only more brokered actions (enforced elsewhere, by the host
broker, TASK-3171).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

from parrot_formdesigner.core.events import FormEventContext
from parrot_formdesigner.core.snippets import CapabilityTier, SandboxContext, SnippetBundle
from parrot_formdesigner.services.auth_context import AuthContext

logger = logging.getLogger(__name__)

# Fixed maximum safe-claim set (spec §2 OQ-5). A manifest's `auth_claims`
# may only narrow this set, never extend it.
SAFE_CLAIM_KEYS: frozenset[str] = frozenset({"sub", "tenant", "roles", "scope", "email", "preferred_username"})

# FILL IN (resolves the SandboxContext.scheme gap noted in the Codebase
# Contract): this key folds AuthContext.scheme into SandboxContext.claims
# for tiers >= 2, since SandboxContext has no dedicated scheme field.
# Leading underscore signals "projector-injected metadata, not a real
# claim" to a snippet author reading their own ctx.claims. If a reviewer
# prefers adding `scheme: str | None = None` to SandboxContext instead
# (TASK-3161), do that there and drop this constant — record the choice
# in the Completion Note either way, since it is a genuine spec gap, not
# an oversight in this task.
_SCHEME_CLAIM_KEY = "_scheme"


def _assert_json_serialisable(value: Mapping[str, Any] | None, *, field_name: str) -> None:
    """Raise loudly if `value` cannot round-trip through json.dumps/loads."""
    if value is None:
        return
    try:
        json.dumps(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(
            f"{field_name} is not JSON-serialisable and cannot cross the " f"sandbox boundary: {exc}"
        ) from exc


class ContextProjector:
    """Converts a live FormEventContext into a serialisable SandboxContext."""

    def __init__(self) -> None:
        self.logger = logger

    async def project(self, ctx: FormEventContext, bundle: SnippetBundle) -> SandboxContext:
        """Project `ctx` down to exactly what `bundle`'s tier is allowed to see.

        Args:
            ctx: The live dispatch-time context. `ctx.auth_context` is
                read ONLY for `.scheme` and `.claims` (never `.token`,
                never `.headers`) and only at tier >= 2.
            bundle: Supplies the tier (via `bundle.manifest.tier`) and the
                declared `auth_claims` allowlist.

        Returns:
            A SandboxContext safe to serialise across the worker boundary.

        Raises:
            TypeError: `ctx.payload` or `ctx.schema_dump` is not JSON-serialisable.
        """
        _assert_json_serialisable(ctx.payload, field_name="payload")
        _assert_json_serialisable(ctx.schema_dump, field_name="schema_dump")

        claims: dict[str, Any] = {}
        if bundle.manifest.tier != CapabilityTier.PURE:
            auth = ctx.auth_context
            if isinstance(auth, AuthContext):
                claims[_SCHEME_CLAIM_KEY] = auth.scheme
                allowed_keys = set(bundle.manifest.auth_claims) & SAFE_CLAIM_KEYS
                for key in allowed_keys:
                    if key in auth.claims:
                        claims[key] = auth.claims[key]
            else:
                # FILL IN: decide behavior when ctx.auth_context is not an
                #   AuthContext instance (e.g. None in a test harness) —
                #   bounded by "tier 1 has no identity" NOT applying here
                #   (tier is already known to be >= 2 in this branch); the
                #   safest default is an empty claims dict with a debug
                #   log, never raising, since a missing auth_context is a
                #   caller/test setup issue, not a security violation.
                self.logger.debug(
                    "ContextProjector: auth_context is not an AuthContext " "instance (%r) — projecting empty claims",
                    type(auth),
                )

        return SandboxContext(
            event=ctx.event,
            form_id=ctx.form_id,
            tenant=ctx.tenant,
            claims=claims,
            payload=ctx.payload,
            schema_dump=ctx.schema_dump,
            user_message=ctx.user_message,
            extra=ctx.extra,
        )
