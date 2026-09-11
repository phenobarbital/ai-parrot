# TASK-3164: Git snippet loader — `services/snippets/git_loader.py`

**Feature**: FEAT-459 — Form Builder: Sandboxed Custom Code on Lifecycle Events
**Spec**: `sdd/specs/formbuilder-custom-code.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3161, TASK-3163
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4. This loader is the platform-wide half of the hybrid
dual-source model (OQ-1): it walks a directory of git-committed snippet
bundles, verifies each one's declared SHA-256 against its actual Python
source (catching "edited without a manifest bump" at **boot**, not at
request time — spec §7 risk table), and registers each bundle through
TASK-3163's `register_resolver()` under `tenant=None`.

Because the approval gate for this source IS the merged PR (spec §2 point
2), this loader performs no approval logic itself — a bundle that exists
on disk in the configured root, with a matching hash, is by definition
approved.

---

## Scope

- Define the on-disk **bundle directory layout**: one directory per
  snippet under the configured root, containing `manifest.json` (a
  `CapabilityManifest` plus `handler_ref`/`event` — see blueprint), `run.py`
  (the Python source), and an optional `client.js` (compiled TS output,
  produced by TASK-3174's bundler — this loader only reads it if present).
- Implement `GitSnippetLoader.discover()` — walks the root, parses each
  bundle, verifies `python_sha256`, and yields `SnippetBundle(source=GIT,
  tenant=None, status=PUBLISHED)` instances.
- Implement `GitSnippetLoader.register_all()` — calls `discover()`, then
  `register_resolver()` (TASK-3163) once per bundle; refuses (raises
  `SnippetTierUnavailableError`) any tier-3/4 bundle when gVisor is
  unavailable, per OQ-4 (a hard prerequisite this loader enforces at the
  earliest possible point).
- Implement the `SnippetSourceProtocol.resolve_current()` method on
  `GitSnippetLoader` itself (or a small in-memory companion class) — git
  bundles never change without a redeploy, so this is a plain dict lookup
  populated by `discover()`, not a cache with invalidation.
- Write `packages/parrot-formdesigner/tests/unit/test_git_snippet_loader.py`.

**NOT in scope**: the DB-backed loader (TASK-3165); the gVisor
availability probe itself (`GVisorWorkerPool.is_available()` is
TASK-3170) — this task only calls it, injected as a parameter so it does
not import `services/sandbox/gvisor_pool.py` before that module exists.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/snippets/git_loader.py` | CREATE | `GitSnippetLoader` |
| `packages/parrot-formdesigner/tests/unit/test_git_snippet_loader.py` | CREATE | Unit tests |
| `packages/parrot-formdesigner/tests/fixtures/snippet_bundles/pure_example/manifest.json` | CREATE | Fixture bundle used by tests |
| `packages/parrot-formdesigner/tests/fixtures/snippet_bundles/pure_example/run.py` | CREATE | Fixture bundle Python source |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pathlib import Path
import hashlib
import json
from parrot_formdesigner.core.snippets import (
    CapabilityManifest, CapabilityTier, SnippetBundle, SnippetSource,
    SnippetStatus, SnippetIntegrityError, SnippetTierUnavailableError,
)  # TASK-3161
from parrot_formdesigner.services.snippets.base import (
    SnippetSourceProtocol, register_resolver,
)  # TASK-3163
```

### Existing Signatures to Use
```python
# TASK-3161 — packages/parrot-formdesigner/src/parrot_formdesigner/core/snippets.py
class SnippetBundle(BaseModel):
    source: SnippetSource
    status: SnippetStatus = SnippetStatus.PUBLISHED
    version: int = 1
    approved_by: str | None = None
    approved_at: datetime | None = None
    handler_ref: str = Field(..., pattern=r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$")
    event: FormEventName
    tenant: str | None = None
    manifest: CapabilityManifest
    python_source: str
    python_sha256: str
    client_source: str | None = None
    client_sha256: str | None = None

# TASK-3163 — packages/parrot-formdesigner/src/parrot_formdesigner/services/snippets/base.py
class SnippetSourceProtocol(Protocol):
    async def resolve_current(self, *, tenant: str | None, handler_ref: str) -> SnippetBundle | None: ...

def register_resolver(
    handler_ref: str, *, tenant: str | None, source: SnippetSourceProtocol,
    project_context: ContextProjectorFn, execute: SandboxExecutorFn,
) -> None: ...  # raises ValueError on duplicate key
```

### Does NOT Exist
- ~~A snippet bundle directory layout anywhere in the repo~~ — this task
  defines it for the first time; there is no precedent format to copy.
- ~~`services/snippets/git_loader.py`~~ — being created by this task.
- ~~`GVisorWorkerPool`~~ / ~~`.is_available()`~~ — does not exist yet
  (TASK-3170). Receive the availability check as an injected
  `Callable[[], bool]` parameter (default `lambda: False`, i.e. fail safe:
  assume gVisor is absent unless told otherwise), never import
  `services/sandbox/gvisor_pool.py` from this module.
- ~~A TS/JS bundler invocation inside this loader~~ — `client.js` is read
  as a static file if present; **never compiled here**. Compilation is
  TASK-3174's build-time script, run before this loader ever executes.

---

## Implementation Notes

### Key Constraints
- SHA-256 verification happens against the **actual file content on disk**
  at `discover()` time, not a value trusted from `manifest.json` — the
  manifest declares the *expected* hash, this loader recomputes and
  compares (`hashlib.sha256(source_bytes).hexdigest() ==
  manifest["python_sha256"]`), else raises `SnippetIntegrityError` and the
  whole `register_all()` call fails (fail at boot, per spec §7).
- `discover()` must be deterministic in bundle iteration order (`sorted()`
  the directory listing) — nondeterministic registration order makes a
  duplicate-ref failure flaky to reproduce.
- Async I/O: `pathlib.Path.read_text()` and `.iterdir()` are synchronous.
  Per `.agent/CONTEXT.md`'s async-first rule, wrap blocking directory
  walks with `asyncio.to_thread()` rather than calling them directly
  inside `async def discover()`.

### References in Codebase
- `services/snippets/base.py` (TASK-3163) — `register_resolver()`,
  `SnippetSourceProtocol`.
- `core/snippets.py` (TASK-3161) — `SnippetBundle` and its validators; a
  malformed `manifest.json` should surface as a Pydantic `ValidationError`
  when constructing `CapabilityManifest`/`SnippetBundle`, not a custom
  parse error.

---

## Implementation Blueprint

### Steps (in order)
1. Define the bundle directory layout as a short module docstring —
   *why*: this is new ground, the format must be documented where anyone
   implementing TASK-3174 (TS bundler) or TASK-3176 (LLM authoring
   surface) will look first.
2. Implement `_load_bundle_dir()` — parses one directory into a
   `SnippetBundle`, verifying the hash.
3. Implement `GitSnippetLoader.discover()` — walks the root, calls
   `_load_bundle_dir()` per subdirectory, collects results.
4. Implement `resolve_current()` and `register_all()`.
5. Write the fixture bundle and tests.

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/snippets/git_loader.py` (CREATE)
```python
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
from pathlib import Path
from typing import Callable

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
    client_sha256 = (
        hashlib.sha256(client_source.encode("utf-8")).hexdigest()
        if client_source is not None
        else None
    )
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
                discover() entirely. FILL IN: decide the non-strict
                behavior — bounded by whether a partial platform snippet
                set is ever an acceptable boot state (spec leans toward
                "no" — G4/G5 treat an unverified source as unsafe to run
                at all, suggesting strict=False should still be rare/ops-only).
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

    async def resolve_current(
        self, *, tenant: str | None, handler_ref: str
    ) -> SnippetBundle | None:
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
```
**Why this shape**: `resolve_current` and `register_all` live on the same
class deliberately — `GitSnippetLoader` IS its own `SnippetSourceProtocol`
implementation, since a git-backed bundle set is immutable at runtime
(no separate cache layer is needed the way TASK-3165's DB store needs
one). `gvisor_available` defaults to `lambda: False` — fail closed, not
fail open — so a caller wiring this loader before TASK-3170 exists gets a
loud refusal for tier-3/4 bundles instead of an accidental bypass of OQ-4.

### `packages/parrot-formdesigner/tests/fixtures/snippet_bundles/pure_example/run.py` (CREATE)
```python
"""Fixture snippet: no-op onBeforeSubmit handler for GitSnippetLoader tests."""
def run(ctx: dict) -> dict:
    return {}
```

### `packages/parrot-formdesigner/tests/fixtures/snippet_bundles/pure_example/manifest.json` (CREATE)
```json
{
  "handler_ref": "pure_example.onBeforeSubmit",
  "event": "onBeforeSubmit",
  "python_sha256": "FILL_IN_AT_TEST_SETUP",
  "manifest": {
    "tier": "pure",
    "timeout_ms": 1000
  }
}
```
**Why**: `python_sha256` cannot be hand-computed reliably in this
blueprint block — the test setup (or a `conftest.py` fixture) must compute
`hashlib.sha256(Path("run.py").read_bytes()).hexdigest()` and either
rewrite this fixture file once at test-collection time or construct the
bundle directory in a `tmp_path` fixture instead of committing a
pre-hashed static file. **FILL IN**: pick one of those two approaches when
implementing the test file below — bounded by "the fixture must always
hash-verify, even after an unrelated whitespace edit to run.py".

### `packages/parrot-formdesigner/tests/unit/test_git_snippet_loader.py` (CREATE)
```python
"""Unit tests for GitSnippetLoader — FEAT-459 / TASK-3164."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from parrot_formdesigner.core.snippets import SnippetIntegrityError, SnippetTierUnavailableError
from parrot_formdesigner.services.snippets.git_loader import GitSnippetLoader


def _write_bundle(
    root: Path, name: str, *, handler_ref: str, tier: str = "pure", source: str = "def run(ctx): return {}"
) -> None:
    bundle_dir = root / name
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "run.py").write_text(source)
    sha256 = hashlib.sha256(source.encode("utf-8")).hexdigest()
    (bundle_dir / "manifest.json").write_text(json.dumps({
        "handler_ref": handler_ref,
        "event": "onBeforeSubmit",
        "python_sha256": sha256,
        "manifest": {"tier": tier},
    }))


@pytest.fixture
def snippet_root(tmp_path: Path) -> Path:
    _write_bundle(tmp_path, "pure_example", handler_ref="pure_example.onBeforeSubmit")
    return tmp_path


async def test_discover_returns_valid_bundle(snippet_root: Path) -> None:
    loader = GitSnippetLoader(snippet_root)
    bundles = await loader.discover()
    assert len(bundles) == 1
    assert bundles[0].handler_ref == "pure_example.onBeforeSubmit"
    assert bundles[0].tenant is None


async def test_git_loader_rejects_hash_mismatch(tmp_path: Path) -> None:
    _write_bundle(tmp_path, "bad", handler_ref="bad.onBeforeSubmit")
    # Corrupt the source AFTER writing a valid hash for the original content.
    (tmp_path / "bad" / "run.py").write_text("def run(ctx): return {'tampered': True}")
    loader = GitSnippetLoader(tmp_path)
    with pytest.raises(SnippetIntegrityError):
        await loader.discover()


async def test_git_loader_rejects_tier3_without_gvisor(tmp_path: Path) -> None:
    _write_bundle(tmp_path, "brokered", handler_ref="b.onBeforeSubmit", tier="brokered")
    loader = GitSnippetLoader(tmp_path)

    async def _fake_project(ctx, bundle):  # pragma: no cover — not reached
        raise AssertionError("should not execute")

    async def _fake_execute(bundle, ctx):  # pragma: no cover — not reached
        raise AssertionError("should not execute")

    with pytest.raises(SnippetTierUnavailableError):
        await loader.register_all(
            project_context=_fake_project, execute=_fake_execute, gvisor_available=lambda: False
        )


async def test_git_loader_duplicate_ref_raises(tmp_path: Path) -> None:
    # FILL IN: write two bundle dirs with the SAME handler_ref, call
    #   register_all(), assert ValueError propagates from
    #   register_form_event() via register_resolver() — bounded by
    #   spec's "two snippets claim one handler_ref" risk row.
    pass


async def test_resolve_current_returns_none_for_unknown_key(snippet_root: Path) -> None:
    loader = GitSnippetLoader(snippet_root)
    await loader.discover()
    result = await loader.resolve_current(tenant=None, handler_ref="nonexistent.onBeforeSubmit")
    assert result is None
```
**Why**: hash-mismatch and tier-refusal are the two security-critical
paths and are written in full; the duplicate-ref test is a one-line stub
since `test_resolver_registers_once_per_key` (TASK-3163) already proves
the underlying mechanism — this test only needs to prove the loader wires
it through unchanged.

### FILL IN checklist
- [ ] `GitSnippetLoader.__init__` docstring — decide `strict=False` behavior; bounded by G4/G5 (unverified source is unsafe)
- [ ] `pure_example/manifest.json` fixture — resolve the `python_sha256` placeholder via a `tmp_path`-based fixture rather than a static file, OR compute it once and commit the real value
- [ ] `test_git_loader_duplicate_ref_raises` — full test body

---

## Acceptance Criteria

- [ ] `GitSnippetLoader(root).discover()` returns a `SnippetBundle` per valid bundle directory, `tenant=None`, `source=GIT`, `status=PUBLISHED`
- [ ] An edited `run.py` whose hash no longer matches `manifest.json` raises `SnippetIntegrityError` from `discover()`
- [ ] A tier-3/4 bundle raises `SnippetTierUnavailableError` from `register_all()` when `gvisor_available()` returns `False`
- [ ] Two bundles declaring the same `handler_ref` raise `ValueError` (from the underlying `register_form_event()`) via `register_all()`
- [ ] `resolve_current()` returns `None` for an unregistered key, never raises
- [ ] All tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_git_snippet_loader.py -v`
- [ ] `ruff check` and `mypy` clean on `services/snippets/git_loader.py`

---

## Test Specification

See the blueprint's test file above — 5 test functions, 1 stubbed.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§2 Overview point 2, §3 Module 4, §7 "Snippet edited without manifest update" risk row)
2. **Check dependencies** — TASK-3161 and TASK-3163 must be `done`
3. **Verify the Codebase Contract** — confirm `SnippetSourceProtocol`/`register_resolver` signatures in `services/snippets/base.py` match what TASK-3163 actually shipped (it may have adjusted the FILL IN sections)
4. **Update status** in `sdd/tasks/index/formbuilder-custom-code.json` → `"in-progress"`
5. **Implement** from the blueprint; complete every `# FILL IN:`
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-3164-git-snippet-loader.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
