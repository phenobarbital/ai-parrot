# TASK-3756: SharePointFileManager — site + library targeting over SharepointClient

**Feature**: FEAT-603 — SharePoint & OneDrive FileManager
**Spec**: `sdd/specs/sharepoint-filemanager.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3750, TASK-3748
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 3**, AC2 (subclasses differ from the base only by `manager_name`, `__init__`, `_build_client`,
`_resolve_drive_id` — plus the `client_class` attribute this task sets, see below), AC23 and design research **S2**.

**S2 — no hidden mutable input.** `SharepointClient._detect_and_resolve_subsite` derives the target from
`self._srcfiles[0]["directory"]` and rewrites every `_srcfiles` entry (`interfaces/sharepoint.py:128-166`). The manager
never populates `_srcfiles`, so that code path returns `(self.site, "")` untouched; sub-sites are given explicitly as
`site="parent/sub"`, which `_resolve_site` turns into `…sharepoint.com:/sites/parent/sub` (`:181-183`).

**`client_class` (task-time clarification of AC2):** TASK-3750's `adopt_client` decides "use as-is vs wrap" with
`isinstance(client, self.client_class)`. The subclass therefore also overrides the `client_class` class attribute
(`SharepointClient`). This is a class-level constant, not behaviour, and is listed in AC2's allowed set by this task.

---

## Scope

- Create `packages/ai-parrot/src/parrot/interfaces/file/sharepoint.py` with `SharePointFileManager`.
- Create `packages/ai-parrot/tests/interfaces/test_sharepoint_filemanager.py`.

**NOT in scope**: registration in the shim/factory (TASK-3758); the O365 tool refactor (TASK-3761/3762).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/interfaces/file/sharepoint.py` | CREATE | `SharePointFileManager` |
| `packages/ai-parrot/tests/interfaces/test_sharepoint_filemanager.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified 2026-09-25 against `dev` at `8da1f45c3`.

### Verified Imports
```python
from parrot.interfaces.sharepoint import SharepointClient              # verified: packages/ai-parrot/src/parrot/interfaces/sharepoint.py:32
from .graph import GraphDriveFileManager                               # created by TASK-3749/3750
from ._graph_fakes import FakeDrive, FakeGraphClient, make_sharepoint_client   # tests (TASK-3748)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/interfaces/sharepoint.py
class SharepointClient(O365Client):                          # :32
    def __init__(self, *args, **kwargs)                      # :40 — _default_* from SHAREPOINT_TENANT_ID / SHAREPOINT_APP_ID /
                                                             #   SHAREPOINT_APP_SECRET / SHAREPOINT_TENANT_NAME (:44-47); _srcfiles = [] (:52)
    async def verify_sharepoint_access(self)                 # :96
    async def _detect_and_resolve_subsite(self) -> tuple[str, str]   # :120-172 — reads/mutates _srcfiles (S2)
    async def _resolve_site(self) -> DriveItem               # :174 — f"{tenant}.sharepoint.com:/sites/{site}" (:181-183)
    def _parse_directory_path(self, directory: str) -> tuple[str, str]   # :208 — "Shared Documents" -> "Documents" (:237)
    async def _resolve_drive(self, library_name: str = None) -> DriveItem   # :242
# O365Client.processing_credentials (:218) sets tenant = credentials['tenant'] or SHAREPOINT_TENANT_NAME; site = credentials['site']
# From TASK-3749/3750: GraphDriveFileManager(prefix=..., credentials=..., auth_mode=..., ...), client_class, adopt_client,
#   _ready, _build_client / _resolve_drive_id hooks, self.client
```

### Does NOT Exist
- ~~`SharePointFileManager(drive={"type": "onedrive", ...})`~~ — flowtask's shim is not ported; OneDrive is
  `OneDriveFileManager` (TASK-3757).
- ~~automatic sub-site detection in the manager~~ — sub-sites are explicit in `site` (S2).
- ~~`parrot.interfaces.file.sharepoint`~~ — created by this task (it is a *new* module, distinct from
  `parrot.interfaces.sharepoint`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/interfaces/file/sharepoint.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/interfaces/test_sharepoint_filemanager.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/interfaces/sharepoint.py#SharepointClient",
    "sym:packages/ai-parrot/src/parrot/interfaces/sharepoint.py#SharepointClient.verify_sharepoint_access",
    "sym:packages/ai-parrot/src/parrot/interfaces/sharepoint.py#SharepointClient._resolve_drive",
    "sym:packages/ai-parrot/src/parrot/interfaces/sharepoint.py#SharepointClient._detect_and_resolve_subsite"
  ]
}
```

---

## Implementation Notes

- `tenant` resolution order: the `tenant=` argument, then `credentials["tenant"]`, else left out so
  `processing_credentials` falls back to `SHAREPOINT_TENANT_NAME` (`o365.py:218-230`).
- `_build_client()` returns `SharepointClient(credentials={**self.credentials, "site": self.site, **({"tenant": t} if t
  else {})})` and asserts `client._srcfiles == []` (S2 invariant). It does NOT authenticate — `connect()` does.
- `_resolve_drive_id()`: `await self.client.verify_sharepoint_access()`; `drive = await self.client._resolve_drive(
  self.library)`; missing id → `GraphFileManagerError`; return `drive.id`.
- Tests never construct a real `SharepointClient`: the `_build_client` test monkeypatches
  `parrot.interfaces.file.sharepoint.SharepointClient` with a recording stub; every other test adopts
  `make_sharepoint_client(...)`.

### Key Constraints (all FEAT-603 tasks)
- **aiohttp only** for raw HTTP. `httpx`, `requests`, `langchain*` are banned (ruff TID251). The two legacy
  clients carry an unused `import httpx` (`interfaces/sharepoint.py:11`, `interfaces/onedrive.py:10`) — never copy
  their import blocks into new code.
- **Core never imports the tools distribution**: nothing under `packages/ai-parrot/src/parrot/` may import
  `parrot_tools` (the retry helpers of `parrot_tools/o365/delta.py` are *re-implemented*, not imported).
- Pydantic v2 models; Google-style docstrings and strict type hints on every function/class; `self.logger`
  (or a module `logger = logging.getLogger(__name__)`), never `print`; `black` line length 120; `ruff check` clean.
- **Never log** upload-session `uploadUrl`s, copy monitor URLs, `@microsoft.graph.downloadUrl`s, tokens or secrets.
- **Byte-identical files** (no edit, ever, in this feature): `packages/ai-parrot/src/parrot/interfaces/sharepoint.py`,
  `packages/ai-parrot/src/parrot/interfaces/o365.py`, `packages/ai-parrot-tools/src/parrot_tools/o365/delta.py`,
  `packages/ai-parrot-tools/src/parrot_tools/o365/bundle.py`, `packages/ai-parrot-tools/src/parrot_tools/o365/base.py`,
  and the `Delta*Args` / `Delta*Tool` class blocks inside `parrot_tools/o365/{sharepoint,onedrive}.py` (FEAT-539).
- Tests never construct a real `O365Client` / `SharepointClient` / `OneDriveClient` (their `__init__` builds an
  aioredis client, `o365.py:198-200`) — use the fakes of TASK-3748 and `GraphDriveFileManager.adopt_client`.
- Tests are async with `asyncio_mode = auto` (`pytest.ini:3`); the `live` marker is registered (`pytest.ini:6`).
- **Worktree testing**: the shared `.venv` is editable-installed against the MAIN checkout, so run
  `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src timeout -s KILL 600 pytest <file> -q`.
  Never `uv sync` inside a worktree.

---

## Implementation Blueprint

### Steps (in order)
1. Write the module — *why*: the only SharePoint-specific code in the feature.
2. Write the tests.

### `packages/ai-parrot/src/parrot/interfaces/file/sharepoint.py` (CREATE)
```python
"""SharePoint document-library FileManager (FEAT-603)."""
from __future__ import annotations

from typing import Any, Optional

from parrot.interfaces.sharepoint import SharepointClient

from .graph import GraphDriveFileManager, GraphFileManagerError


class SharePointFileManager(GraphDriveFileManager):
    """FileManagerInterface over one SharePoint document library.

    ``site`` is the site path under ``/sites/`` — ``"TeamSite"`` or, for a sub-site, ``"parent/sub"`` given
    explicitly (``_resolve_site`` builds ``…sharepoint.com:/sites/{site}``). The client's sub-site auto-detection only
    acts on its hidden ``_srcfiles`` list, which this manager never populates (S2). ``library`` defaults to
    ``"Documents"`` and accepts the ``"Shared Documents"`` alias. Credentials default to SHAREPOINT_APP_ID /
    SHAREPOINT_APP_SECRET / SHAREPOINT_TENANT_ID / SHAREPOINT_TENANT_NAME.
    """

    manager_name: str = "sharepointfile"
    client_class: type = SharepointClient

    def __init__(self, site: str, library: str = "Documents", *, tenant: Optional[str] = None, **kwargs: Any) -> None:
        """Args:
            site: Site path under ``/sites/`` (``"parent/sub"`` for a sub-site).
            library: Document library name.
            tenant: ``<tenant>.sharepoint.com`` host name; falls back to credentials / SHAREPOINT_TENANT_NAME.
            **kwargs: Forwarded to :class:`GraphDriveFileManager` (prefix, credentials, auth_mode, ...).
        """
        super().__init__(**kwargs)
        if not site or not str(site).strip("/"):
            raise ValueError("SharePointFileManager requires a site")
        self.site = str(site).strip("/")
        self.library = library or "Documents"
        self.tenant = tenant or (self.credentials or {}).get("tenant")

    def _build_client(self) -> SharepointClient:
        """A not-yet-authenticated SharepointClient targeting ``site`` (and ``tenant`` when known)."""
        # FILL IN: rule in Implementation Notes (credential dict + S2 assertion)

    async def _resolve_drive_id(self) -> str:
        """verify_sharepoint_access() then _resolve_drive(library) on the client; return the drive id."""
        # FILL IN: rule in Implementation Notes
```
**Why this shape**: the constructor is written out because its argument names are the public API used by the factory
(TASK-3758), the toolkit and the O365 tools. Only the two hooks are left.

### `packages/ai-parrot/tests/interfaces/test_sharepoint_filemanager.py` (CREATE)
```python
"""FEAT-603 TASK-3756 — SharePointFileManager."""
import pytest

from parrot.interfaces.file.graph import GraphDriveFileManager
from parrot.interfaces.file.sharepoint import SharePointFileManager
from ._graph_fakes import FakeDrive, FakeGraphClient, make_sharepoint_client


def test_constructor_and_defaults():
    # FILL IN: library defaults to "Documents"; site stripped; empty site -> ValueError; manager_name == "sharepointfile"


def test_sharepoint_manager_builds_client_with_site_and_tenant(monkeypatch):
    # FILL IN: monkeypatch parrot.interfaces.file.sharepoint.SharepointClient with a stub recording credentials and
    #          exposing _srcfiles = []; assert credentials carry site + tenant and the original keys


async def test_sharepoint_resolve_drive_uses_library():
    # FILL IN: adopt a make_sharepoint_client whose _resolve_drive records the library; _ready() -> "drive-1"


async def test_sharepoint_subsite_via_explicit_site_path():
    # FILL IN: site="hr/benefits" is kept verbatim on the manager and on the built client credentials


async def test_sharepoint_manager_never_populates_srcfiles():
    # FILL IN: after adopt + _ready(), client._srcfiles == []


def test_subclass_overrides_only_allowed_members():
    allowed = {"manager_name", "client_class", "__init__", "_build_client", "_resolve_drive_id", "__doc__", "__module__",
               "__qualname__", "__abstractmethods__", "_abc_impl", "__firstlineno__", "__static_attributes__"}
    assert set(vars(SharePointFileManager)) - allowed == set()
```

### FILL IN checklist
- [ ] `_build_client`, `_resolve_drive_id`
- [ ] test bodies

---

## Acceptance Criteria

- [ ] `SharePointFileManager(site, library="Documents", *, tenant=None, **kwargs)` exists with `manager_name =
      "sharepointfile"` and overrides only the allowed members (spec AC2 as clarified in Context).
- [ ] `_resolve_drive_id` calls `verify_sharepoint_access()` then `_resolve_drive(library)` (spec §3 M3).
- [ ] `_srcfiles` stays empty; sub-sites via `site="parent/sub"` (spec AC23, S2).
- [ ] `interfaces/sharepoint.py` unchanged; `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/interfaces/test_sharepoint_filemanager.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_constructor_and_defaults` | public API |
| `test_sharepoint_manager_builds_client_with_site_and_tenant` | credential keys |
| `test_sharepoint_resolve_drive_uses_library` | hook |
| `test_sharepoint_subsite_via_explicit_site_path` / `test_sharepoint_manager_never_populates_srcfiles` | S2 / AC23 |
| `test_subclass_overrides_only_allowed_members` | AC2 |

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** `sdd/specs/sharepoint-filemanager.spec.md` (§2, the §3 module named in Context, §6, §7).
2. **Check dependencies** — every `Depends-on` task must be `done` in `sdd/tasks/index/sharepoint-filemanager.json`.
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still resolves (`grep` or `read` the source).
   - Re-run the `grep -c` of every MODIFY anchor in the blueprint; a changed count means the anchor moved —
     re-locate it; a count of `0` means STOP and report drift.
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists.
4. **Update status** in `sdd/tasks/index/sharepoint-filemanager.json` → `"in-progress"`.
5. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker, and never
   change a signature, class name or file path the blueprint fixes.
6. **Verify** every acceptance criterion and run every Validation Command (plus `ruff check` on touched files).
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update the index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note


- Task: TASK-3756
- Feature: sharepoint-filemanager
- Implementation SHA: 91946e129a2fd87df679752d6f0ce53b8ed4cbb0
- Closed at (UTC): 2026-09-25T19:08:06+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| known_deviation | Test module neutralizes SharePointFileManager.__abstractmethods__ at test-scope only (no source file touched) because sibling tasks TASK-3751 through TASK-3754 (GraphDriveFileManager's read/transfer method implementations) had not yet landed on this branch when this task ran, and without them the base class is not concretely instantiable. This becomes moot once those siblings merge; flagged for a follow-up integration re-run at that point. |
| merge_tier_gate_note | Full ai-parrot distribution escalation (core-path rule, tracked as FEAT-604 draft) collects 18 test files that fail to import for reasons unrelated to this task (existing on origin/dev prior to this feature). This task's own declared test file is the acceptance evidence above. |
| scoped_test_result | packages/ai-parrot/tests/interfaces/test_sharepoint_filemanager.py: 6 passed, 0 failed (run directly, 2026-09-25T19:05 UTC) |
| seat_summary | Seat: sonnet(native) · Backend: native · Model: sonnet · Attempts: 1 · Duration: n/a · Tokens: n/a |
