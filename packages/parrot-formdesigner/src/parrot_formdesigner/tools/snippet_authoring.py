"""LLM authoring surface for snippet bundles (FEAT-459 / M16).

Generates conformant bundles (Python + TS + manifest + OQ-8 equivalence
fixtures) from a natural-language rule description, gates every draft
through TASK-3175's run_gate() BEFORE returning it, and produces a
plain-language capability summary for whoever approves it (PR reviewer
for git snippets, tenant admin for DB snippets via TASK-3166).

C4 (human approval, always) is enforced structurally here: no method in
this toolkit ever calls SnippetApprovalService.publish() or otherwise
causes generated code to become executable. Only draft()-ing (DB) or
returning files ready to be PR'd (git) are in scope.

Codebase-contract note: unlike the task blueprint's draft, methods here
are NOT decorated with ``@tool`` — that decorator (parrot.tools.tool)
marks a *standalone function* as a tool; ``AbstractToolkit`` instead
auto-converts every public **async** method into a tool (see
``tools/edit_toolkit.py`` for the verified convention in this package).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from parrot.tools import AbstractToolkit
from parrot_formdesigner.core.snippets import CapabilityManifest, CapabilityTier, SnippetSource
from parrot_formdesigner.services.snippets.approval import SnippetApprovalService
from scripts.check_snippet_conformance import EquivalenceFixture, run_gate

logger = logging.getLogger(__name__)


@dataclass
class GeneratedBundle:
    """One LLM-generation attempt: a candidate bundle plus its fixtures."""

    bundle: Any  # SnippetBundle — Any to avoid a hard import-time cycle here
    fixtures: list[EquivalenceFixture]


# Injected — the actual LLM call. Kept as a Callable so this toolkit has
# no hard dependency on a specific AbstractClient/model choice; the
# caller (an Agent using this toolkit) wires a real generator.
BundleGeneratorFn = Callable[[str], Awaitable[GeneratedBundle]]

_TIER_PLAIN_LANGUAGE: dict[CapabilityTier, str] = {
    CapabilityTier.PURE: "cannot read any account information and cannot access the network",
    CapabilityTier.HELPERS: (
        "can read basic account info (like your email or role) but cannot make " "network calls or access other systems"
    ),
    CapabilityTier.BROKERED: (
        "can make a small number of pre-approved network calls or database "
        "lookups, but only to hosts/tables explicitly listed below"
    ),
    CapabilityTier.TOOLKIT: (
        "can use pre-approved automated tools/agents in addition to everything " "the tier above allows"
    ),
}


class SnippetAuthoringToolkit(AbstractToolkit):
    """Generates, gates, and summarizes snippet bundles. NEVER approves or executes one."""

    def __init__(self, generate_bundle: BundleGeneratorFn, **kwargs: Any) -> None:
        """
        Args:
            generate_bundle: Calls an LLM to produce a GeneratedBundle
                from a natural-language rule description. Injected —
                see module docstring.
            **kwargs: Forwarded to AbstractToolkit.__init__.
        """
        super().__init__(**kwargs)
        self._generate_bundle = generate_bundle
        self.logger = logger

    async def draft_from_description(self, rule_description: str) -> dict:
        """Generate a conformant snippet bundle from a natural-language rule.

        Runs the bundle through the tier-conformance and equivalence gate
        BEFORE returning it. Never approves or publishes the result —
        approval is always a separate human action (C4).

        Args:
            rule_description: Plain-language description of the desired
                behavior, e.g. "if total > 5000, require approver_email".

        Returns:
            A dict with keys: `ready` (bool — True only if the gate
            passed), `bundle` (the generated SnippetBundle, always
            returned even on failure so a caller can retry generation
            with the error context), `gate_errors` (list[str], empty if
            `ready`), `capability_summary` (str, plain language).
        """
        generated = await self._generate_bundle(rule_description)
        gate_result = await run_gate(generated.bundle, generated.fixtures)
        summary = await self.summarize_capabilities(generated.bundle.manifest)
        return {
            "ready": gate_result.passed,
            "bundle": generated.bundle,
            "gate_errors": gate_result.errors,
            "capability_summary": summary,
        }

    async def summarize_capabilities(self, manifest: CapabilityManifest) -> str:
        """Translate a CapabilityManifest into a plain-language summary for an approver.

        Args:
            manifest: The manifest to summarize.

        Returns:
            A short paragraph, never a JSON/field dump.
        """
        base = _TIER_PLAIN_LANGUAGE[manifest.tier]
        lines = [f"This code's declared tier is '{manifest.tier.value}' — it {base}."]
        if manifest.allowlist.http_hosts:
            lines.append(f"It may contact these external services: " f"{', '.join(manifest.allowlist.http_hosts)}.")
        if manifest.allowlist.query_tables:
            lines.append(f"It may read from these data tables: " f"{', '.join(manifest.allowlist.query_tables)}.")
        if manifest.auth_claims:
            lines.append(f"It may see these account details: {', '.join(manifest.auth_claims)}.")
        lines.append(
            f"It must finish within {manifest.timeout_ms} ms and use at most " f"{manifest.max_memory_mb} MB of memory."
        )
        return " ".join(lines)

    async def propose_for_tenant(
        self,
        rule_description: str,
        *,
        tenant: str,
        approval_service: SnippetApprovalService,
    ) -> dict:
        """Generate a bundle and insert it as a DB draft (NOT published — C4).

        Args:
            rule_description: See draft_from_description.
            tenant: The tenant this draft belongs to.
            approval_service: TASK-3166's service — draft() only, never publish().

        Returns:
            Same shape as draft_from_description()'s return, plus a
            `draft_version` key when `ready` is True (the version number
            SnippetApprovalService.draft() assigned).
        """
        result = await self.draft_from_description(rule_description)
        if not result["ready"]:
            return result
        # The generator (injected) produces a bundle whose `source` may
        # default to GIT; a DB-targeted draft requires source=DB and the
        # target tenant, so re-tag a copy before drafting — draft() raises
        # ValueError on a non-DB source (approval.py's own guard).
        retagged = result["bundle"].model_copy(update={"source": SnippetSource.DB, "tenant": tenant})
        drafted = await approval_service.draft(retagged, tenant=tenant)
        result["draft_version"] = drafted.version
        return result
