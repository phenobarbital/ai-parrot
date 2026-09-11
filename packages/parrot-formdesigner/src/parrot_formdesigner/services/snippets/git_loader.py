"""Git-backed snippet loader (FEAT-459 / M4).

Bundle directory layout (one directory per snippet, under the configured
root)::

    <root>/<bundle-name>/
        manifest.json   # {"handler_ref": str, "event": FormEventName,
                         #  "manifest": CapabilityManifest-shaped dict}
        run.py           # Python source; sha256 verified against
                          #  manifest.json's "python_sha256" (which the
                          #  author/CI computes and commits alongside)
        client.js         # OPTIONAL — compiled JS, produced by
                          #  scripts/build_snippet_bundles.py (TASK-3174).
                          #  Read verbatim if present; never compiled here.

Approval for this source IS the merged PR: a bundle present on disk with a
matching hash is, by construction, approved (spec §2 point 2).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Callable
from pathlib import Path

from parrot_formdesigner.core.snippets import (
    CapabilityManifest,
    CapabilityTier,
    SnippetBundle,
    SnippetIntegrityError,
    SnippetSource,
    SnippetStatus,
    SnippetTierUnavailableError,
)
from parrot_formdesigner.services.snippets.base import (
    ContextProjectorFn,
    SandboxExecutorFn,
    register_resolver,
)

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = "manifest.json"
PYTHON_SOURCE_FILENAME = "run.py"
CLIENT_SOURCE_FILENAME = "client.js"


def _load_bundle_dir(bundle_dir: Path) -> SnippetBundle:
    """Parse and hash-verify one bundle directory into a SnippetBundle.

    Raises:
        SnippetIntegrityError: if the recomputed sha256 of run.py does not
            match manifest.json's declared "python_sha256".
        pydantic.ValidationError: if manifest.json is structurally invalid.
    """
    manifest_path = bundle_dir / MANIFEST_FILENAME
    source_path = bundle_dir / PYTHON_SOURCE_FILENAME
    raw = json.loads(manifest_path.read_text())
    python_source = source_path.read_text()
    actual_sha256 = hashlib.sha256(python_source.encode("utf-8")).hexdigest()
    declared_sha256 = raw.get("python_sha256")
    if actual_sha256 != declared_sha256:
        raise SnippetIntegrityError(
            f"{bundle_dir.name}: run.py sha256 mismatch — "
            f"declared {declared_sha256!r}, actual {actual_sha256!r}. "
            "Source was edited without updating manifest.json."
        )
    client_path = bundle_dir / CLIENT_SOURCE_FILENAME
    client_source = client_path.read_text() if client_path.exists() else None
    client_sha256 = hashlib.sha256(client_source.encode("utf-8")).hexdigest() if client_source is not None else None
    return SnippetBundle(
        source=SnippetSource.GIT,
        status=SnippetStatus.PUBLISHED,
        handler_ref=raw["handler_ref"],
        event=raw["event"],
        tenant=None,
        manifest=CapabilityManifest.model_validate(raw["manifest"]),
        python_source=python_source,
        python_sha256=actual_sha256,
        client_source=client_source,
        client_sha256=client_sha256,
    )


class GitSnippetLoader:
    """Discovers git-backed snippet bundles under `root` and registers them."""

    def __init__(self, root: Path, *, strict: bool = True) -> None:
        """
        Args:
            root: Directory containing one subdirectory per snippet bundle.
            strict: When True (default), any parse/hash failure aborts
                discover() entirely. When False, a failing bundle is
                logged and skipped rather than aborting the whole boot —
                deliberately rare/ops-only: G4/G5 treat an unverified
                source as unsafe to run at all, so `strict=False` should
                only be used to keep an otherwise-healthy platform
                snippet set booting while a single broken bundle is
                fixed out-of-band, never as a routine operating mode.
        """
        self._root = root
        self._strict = strict
        self._by_ref: dict[tuple[str | None, str], SnippetBundle] = {}
        self.logger = logger

    async def discover(self) -> list[SnippetBundle]:
        """Walk `root`, parse and hash-verify every bundle directory.

        Returns:
            All discovered bundles, in sorted directory-name order.

        Raises:
            SnippetIntegrityError: propagated from a failing bundle when
                `strict=True`.
        """

        def _walk() -> list[SnippetBundle]:
            bundles: list[SnippetBundle] = []
            for entry in sorted(self._root.iterdir()):
                if not entry.is_dir():
                    continue
                try:
                    bundles.append(_load_bundle_dir(entry))
                except Exception:
                    if self._strict:
                        raise
                    self.logger.error("skipping invalid bundle %s", entry, exc_info=True)
            return bundles

        bundles = await asyncio.to_thread(_walk)
        self._by_ref = {(b.tenant, b.handler_ref): b for b in bundles}
        return bundles

    async def resolve_current(self, *, tenant: str | None, handler_ref: str) -> SnippetBundle | None:
        """SnippetSourceProtocol implementation — plain dict lookup.

        Git bundles never change without a redeploy (which re-runs
        discover() at process boot), so no cache invalidation is needed.
        """
        return self._by_ref.get((tenant, handler_ref))

    async def register_all(
        self,
        *,
        project_context: ContextProjectorFn,
        execute: SandboxExecutorFn,
        gvisor_available: Callable[[], bool] = lambda: False,
    ) -> int:
        """Register every discovered bundle via register_resolver().

        Args:
            project_context: Passed through to register_resolver() —
                TASK-3167's ContextProjector.project, injected.
            execute: Passed through to register_resolver() — TASK-3172's
                TierRouter.execute, injected.
            gvisor_available: Returns True when the gVisor runtime is
                usable. Defaults to a fail-safe False so a caller that
                forgets to wire TASK-3170's real probe gets tier-3/4
                bundles refused rather than silently allowed to load
                without isolation (OQ-4: no silent degradation).

        Returns:
            Count of registered snippets.

        Raises:
            SnippetIntegrityError: source hash mismatch (from discover()).
            SnippetTierUnavailableError: bundle declares tier 3/4 but
                gVisor is unavailable.
            ValueError: propagated from register_form_event() on a
                duplicate (tenant, handler_ref).
        """
        bundles = await self.discover()
        registered = 0
        for bundle in bundles:
            if bundle.manifest.tier in (CapabilityTier.BROKERED, CapabilityTier.TOOLKIT):
                if not gvisor_available():
                    raise SnippetTierUnavailableError(
                        f"{bundle.handler_ref}: declares tier={bundle.manifest.tier!r} "
                        "but the gVisor (runsc) runtime is unavailable (OQ-4 hard "
                        "prerequisite — tiers 3-4 refuse to load, never silently downgrade)."
                    )
            register_resolver(
                bundle.handler_ref,
                tenant=bundle.tenant,
                source=self,
                project_context=project_context,
                execute=execute,
            )
            registered += 1
        return registered
