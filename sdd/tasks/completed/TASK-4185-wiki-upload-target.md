# TASK-4185: Knowledge upload — LLM wiki target (FEAT-402 triage)

**Feature**: FEAT-647 — Chat-driven document upload into Bookstore / LLM Wiki
**Spec**: `sdd/specs/teams-telegram-uploader-bookstore.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4183, TASK-4180
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. `/ingest_wiki` runs the FEAT-402 supervised path (G5, AC7):
charter-driven triage first, then `WikiIngestOrchestrator.ingest` — **only
`proposed_action == "admit"` is ingested**; `archive`, gray-zone and `discard`
are rejected with the triage briefing; `--force` only bypasses the duplicate
check, never triage. Both triage stages and the ingest use
`google:gemini-3.1-flash-lite` by default (AC8). No charter ⇒ target
unavailable (AC9).

The service stack comes from the public `build_ingest_runtime` that TASK-4180
extracts from the CLI into `parrot/knowledge/wiki/runtime.py`.

---

## Scope

- Implement `WikiTarget(IngestTarget)` in `targets/wiki.py` per spec §3 M5.
- In `available()`: load the effective project config, open the store and the
  source manager (sqlite backend), load the charter, build the runtime once and
  cache it on `self._runtime`.
- In `ingest()`: acquire → triage → admit-only ingest → WAL checkpoint, mapping
  results to `UploadOutcome`.
- Unit tests with a fake runtime (fake acquirer / router / orchestrator).

**NOT in scope**: `wiki/runtime.py` itself (TASK-4180); writing a charter (user
deliverable, spec Non-Goals); `InboxProcessor` (inbox-centric — do not use it);
non-sqlite backends (see Implementation Notes).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/targets/wiki.py` | CREATE | `WikiTarget` |
| `packages/ai-parrot-integrations/tests/knowledge_upload/test_wiki_target.py` | CREATE | admit / archive / discard / duplicate / unavailable tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# all lazy (inside methods) — spec §7
from parrot.knowledge.wiki.project import load_effective_config, sqlite_policy_from_config, WikiConfigError  # project.py:1111, :893, :943
from parrot.knowledge.wiki.store import create_wiki_store, SQLiteWikiStore    # store.py:2665, :948
from parrot.knowledge.wiki.sources import SourceCollectionManager             # sources.py:108
from parrot.knowledge.wiki.charter import load_charter                        # charter.py:404
from parrot.knowledge.wiki.documents import DocumentRef                       # documents.py:69
# Created by TASK-4180 (dependency):
from parrot.knowledge.wiki.runtime import build_ingest_runtime, WikiRuntimeError
# Created by TASK-4182 / TASK-4183 (dependencies):
from ..models import UploadOutcome, UploadRequest, UploadStatus, UploadTargetKind, WikiTargetConfig
from .base import IngestTarget
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py
class WikiProjectConfig(BaseModel):            # :531 — wiki_name (:572), backend, sqlite_busy_timeout, storage_dir
    def storage_path(self, root: Path) -> Path  # :713
class WikiEffectiveConfig(BaseModel):          # :1056 — .config: WikiProjectConfig (:1070)
def load_effective_config(root: Path, env: str | None = None) -> WikiEffectiveConfig   # :1111 (raises WikiConfigError :943)
def sqlite_policy_from_config(config: "WikiProjectConfig") -> "SQLitePragmaPolicy"      # :893

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
def create_wiki_store(storage_dir: str | Path, wiki_name: str = "", backend: str = "sqlite", **kwargs: Any) -> BaseWikiStore  # :2665
class SQLiteWikiStore(BaseWikiStore):          # :948
    async def checkpoint(self, truncate: bool = True) -> dict[str, int | bool]   # :2502

# packages/ai-parrot/src/parrot/knowledge/wiki/sources.py
class SourceCollectionManager:                 # :108
    def __init__(self, sources_dir: Path, db_path: Path | None = None,
                 backend: Literal["sqlite", "json", "arangodb"] = "sqlite", arango_db=None, arango_store=None,
                 *, busy_timeout: float = 15.0) -> None   # :144

# CLI-private openers this task mirrors for sqlite (read, do not import): wiki/cli.py
#   _open_store :469 → storage = config.storage_path(root); storage.mkdir(...);
#       create_wiki_store(storage, wiki_name=config.wiki_name, backend=config.backend,
#                         sqlite_policy=sqlite_policy_from_config(config))
#   _open_sources :526 → SourceCollectionManager(storage / "sources", db_path=storage / "wiki.db",
#                                                busy_timeout=config.sqlite_busy_timeout)
#   _resolve_charter_path :4564 → default <root>/.parrot/charter.yaml
#   --auto path :5370-5372 → entry.decision = entry.proposed_action; entry.decision_source = "auto"
#   _apply_all :5219-5233 → await orch.ingest(entry.source_uri, wiki_config, triage=entry,
#                                              charter_version=charter_version, acquired=...)

# packages/ai-parrot/src/parrot/knowledge/wiki/charter.py
class Charter(BaseModel):  # :311 — version: str (:334)
def load_charter(path: Path) -> Charter   # :404

# packages/ai-parrot/src/parrot/knowledge/wiki/triage.py
class IngestTriageRouter:                  # :243
    async def triage(self, path: Path, content: str, *, skip_duplicate_check: bool = False) -> ManifestDocEntry  # :295
    # heuristic rejects (:353-392) return proposed_action="discard", decision_source="heuristic",
    # briefing=f"Rejected by heuristic: {reason}" (:394-407); duplicate reasons start with "duplicate"
    # ("duplicate: unchanged since last ingest" :386, "duplicate content of …" :390);
    # skip_duplicate_check=True bypasses ONLY those two checks (:379-380)

# packages/ai-parrot/src/parrot/knowledge/wiki/review.py
class ManifestDocEntry(BaseModel):         # :135
    source_uri: str (:159); briefing: str (:161); proposed_action: Literal["admit","archive","discard"] (:164)
    decision: Literal[...] | None (:166); decision_source: Literal["heuristic","model","human","auto"] | None (:167)

# packages/ai-parrot/src/parrot/knowledge/wiki/documents.py
class DocumentRef(BaseModel): uri: str; is_url: bool = False; suffix: str = ""   # :69-80 (suffix lowercased, with dot)
class DocumentAcquirer:                    # :466
    async def acquire(self, ref: DocumentRef) -> AcquiredDocument   # :500 — .text

# packages/ai-parrot/src/parrot/knowledge/wiki/ingest.py
class IngestReport(BaseModel):             # :120 — pages_created, pages_updated, status ("ok"|"error"), error
class WikiIngestOrchestrator:              # :144
    async def ingest(self, source_path: str, wiki_config: WikiConfig, *, triage=None,
                     charter_version=None, acquired=None) -> IngestReport   # :198

# packages/ai-parrot/src/parrot/knowledge/wiki/inbox/processor.py
class InboxRuntime(BaseModel):             # :43 — fields (:48-61): root, config, wiki_config, charter, store,
    # sources, bookkeeper, acquirer, router, orchestrator, light_adapter, heavy_adapter, search, models

# Created by TASK-4180 (dependency — signature fixed by spec §3 M3):
# (final signatures as written in sdd/tasks/active/TASK-4180-wiki-ingest-runtime.md — they refine spec §3 M3)
async def build_novelty_scorer(root: Path, config: WikiProjectConfig, store: BaseWikiStore) -> Any
def build_ingest_runtime(root: Path, config: WikiProjectConfig, store: BaseWikiStore,
                         sources: SourceCollectionManager, charter: Charter, charter_path: Path, *,
                         lightweight_model: str, model: str, novelty_scorer: Any,
                         adapters: tuple[Any, Any, str, bool] | None = None,
                         fetch_timeout: float = 30.0) -> InboxRuntime
class WikiRuntimeError(RuntimeError)
```

### Does NOT Exist
- ~~A public `open_store` / `open_sources` / `resolve_project` in `parrot.knowledge.wiki`~~ — CLI-private (`_open_store`, `_open_sources`, `_resolve_project`); mirror the sqlite branch here, do not import `cli`.
- ~~`WikiIngestOrchestrator.ingest(source_uri=...)`~~ — identity is the resolved `source_path`.
- ~~`ManifestDocEntry.reason` / `.explanation`~~ — the text field is `briefing`.
- ~~`IngestReport.pages`~~ — use `pages_created` / `pages_updated`.
- ~~`LLMWikiToolkit.ingest_source` for this path~~ — it is the legacy non-triage path; use the runtime's orchestrator.
- ~~`InboxProcessor.process_one` for chat uploads~~ — inbox-centric (archives/moves files); do not use.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/targets/wiki.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-integrations/tests/knowledge_upload/test_wiki_target.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#load_effective_config",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#sqlite_policy_from_config",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiProjectConfig",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#create_wiki_store",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/sources.py#SourceCollectionManager",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/charter.py#load_charter",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/documents.py#DocumentRef",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/triage.py#IngestTriageRouter.triage",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/review.py#ManifestDocEntry",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ingest.py#WikiIngestOrchestrator.ingest",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ingest.py#IngestReport"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **sqlite backend only** in v1: `available()` returns `(False, "wiki backend
  '<x>' not supported for uploads")` for any other `config.backend`. Reason: the
  Odoo wiki is sqlite (`agents/odoo_wiki/.parrot/wiki.json`), and mirroring the
  ArangoDB opener would duplicate CLI-private connection logic. (Spec §3 M5 does
  not fix store opening — this is the decided scope; record it in the Completion
  Note.)
- Build everything **once** in `available()` and cache `self._runtime`
  (fork directive + spec "the runtime builds"); blocking construction
  (config load, store/LLM client creation) via `asyncio.to_thread`.
- `lightweight_model = model = self.config.llm` (AC8 — same flash-lite for both
  stages and ingest).
- Decision mapping in `ingest()`:
  - `entry.decision_source == "heuristic"` and `"duplicate"` in `entry.briefing`
    → SKIPPED "Already present (same content) — use --force" (G7);
  - `entry.proposed_action == "admit"` → ingest with
    `entry.model_copy(update={"decision": "admit", "decision_source": "auto"})`,
    `charter_version=runtime.charter.version`, `acquired=acquired`;
  - anything else → REJECTED_BY_TRIAGE, message = the briefing (AC7).
  - `request.force` → `triage(..., skip_duplicate_check=True)` — nothing else.
- `report.status != "ok"` → FAILED with `report.error` (strip absolute paths);
  `pages_updated > 0` → UPDATED else ADDED; `detail = {"pages_created",
  "pages_updated", "triage_action": entry.proposed_action}` (the service reads
  `triage_action` for the audit record, AC13). Put `triage_action` in `detail`
  for rejections too.
- After an orchestrator write, if `isinstance(runtime.store, SQLiteWikiStore)`:
  `await runtime.store.checkpoint()` inside `try/except Exception` (maintenance
  must never fail the job — same rule as `cli._checkpoint_if_sqlite` :504).
- `staged_path` lives under `<wiki_root>/.parrot/uploads/` — `.parrot` is in
  `VAULT_EXCLUDE_DIRS` (vault_scan.py:58), so `wikitoolkit build --vault` never
  picks it up.

---

## Implementation Blueprint

### Steps (in order)
1. Write `targets/wiki.py` (two blocks) — *why*: spec §3 M5.
2. Write `test_wiki_target.py` with a fake runtime injected as `target._runtime` — *why*: no real LLM in tests (spec §4).
3. Run the Validation Commands.

### `packages/ai-parrot-integrations/src/parrot/integrations/knowledge_upload/targets/wiki.py` (CREATE) — block 1/2
```python
"""LLM-wiki ingest target (``/ingest_wiki``) — FEAT-402 triage, admit-only."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from ..models import UploadOutcome, UploadRequest, UploadStatus, UploadTargetKind, WikiTargetConfig
from .base import IngestTarget


class WikiTarget(IngestTarget):
    """Triage with the wiki's charter, ingest only ``admit`` documents."""

    kind = UploadTargetKind.WIKI

    def __init__(self, config: WikiTargetConfig) -> None:
        """wiki_root resolved; staging_dir = wiki_root/'.parrot'/'uploads';
        charter_path = config.charter_path or wiki_root/'.parrot'/'charter.yaml'."""
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.wiki_root = Path(config.wiki_root).expanduser().resolve()
        self.charter_path = (
            Path(config.charter_path).expanduser().resolve()
            if config.charter_path
            else self.wiki_root / ".parrot" / "charter.yaml"
        )
        self._runtime: Any | None = None  # InboxRuntime, cached by available()

    @property
    def lock_key(self) -> Path:
        return self.wiki_root

    @property
    def staging_dir(self) -> Path:
        return self.wiki_root / ".parrot" / "uploads"

    async def available(self) -> tuple[bool, str]:
        """Charter file exists and loads; project config loads; the runtime builds."""
        if not self.charter_path.is_file():
            return False, f"no charter at {self.charter_path.name}"
        try:
            self._runtime = await self._build_runtime()
        except Exception as exc:  # noqa: BLE001 - any construction failure disables the target
            self.logger.warning("Wiki upload target unavailable: %s", exc, exc_info=True)
            return False, str(exc)
        return True, ""

    async def _build_runtime(self) -> Any:
        from parrot.knowledge.wiki.charter import load_charter
        from parrot.knowledge.wiki.project import load_effective_config, sqlite_policy_from_config
        from parrot.knowledge.wiki.runtime import build_ingest_runtime, build_novelty_scorer
        from parrot.knowledge.wiki.sources import SourceCollectionManager
        from parrot.knowledge.wiki.store import create_wiki_store

        config = load_effective_config(self.wiki_root).config
        # FILL IN: reject non-sqlite backends (raise RuntimeError with a short message); mirror cli._open_store
        # / cli._open_sources sqlite branches exactly (storage.mkdir, create_wiki_store(..., sqlite_policy=...),
        # SourceCollectionManager(storage/"sources", db_path=storage/"wiki.db", busy_timeout=...));
        # charter = load_charter(self.charter_path);
        # scorer = await build_novelty_scorer(self.wiki_root, config, store)   # async — never asyncio.run in the server loop
        # return build_ingest_runtime(self.wiki_root, config, store, sources, charter, self.charter_path,
        #     lightweight_model=self.config.llm, model=self.config.llm, novelty_scorer=scorer)
        # Blocking pieces (config load, store/sources/LLM client creation) go through asyncio.to_thread individually.
        # — bounded by AC8, AC9 and the sqlite-only decision above
        raise NotImplementedError
```

### `targets/wiki.py` (CREATE) — block 2/2 (continue the class)
```python
    async def ingest(self, staged_path: Path, request: UploadRequest, job_id: str) -> UploadOutcome:
        """acquire → triage → admit only → orchestrator.ingest → checkpoint."""
        from parrot.knowledge.wiki.documents import DocumentRef
        from parrot.knowledge.wiki.store import SQLiteWikiStore

        rt = self._runtime
        if rt is None:
            raise RuntimeError("WikiTarget used before available()")
        acquired = await rt.acquirer.acquire(DocumentRef(uri=str(staged_path), suffix=staged_path.suffix.lower()))
        entry = await rt.router.triage(staged_path, acquired.text, skip_duplicate_check=request.force)
        # FILL IN: heuristic duplicate → SKIPPED; proposed_action != "admit" → REJECTED_BY_TRIAGE with the
        # briefing as message — bounded by AC7, G7 (force never bypasses triage)
        decided = entry.model_copy(update={"decision": "admit", "decision_source": "auto"})
        report = await rt.orchestrator.ingest(
            str(staged_path),
            rt.wiki_config,
            triage=decided,
            charter_version=rt.charter.version,
            acquired=acquired,
        )
        if isinstance(rt.store, SQLiteWikiStore):
            try:
                await rt.store.checkpoint()
            except Exception:  # noqa: BLE001 - maintenance must never fail the job
                self.logger.debug("wiki WAL checkpoint failed", exc_info=True)
        # FILL IN: report.status != "ok" → FAILED (report.error without absolute paths); else ADDED/UPDATED
        # by pages_updated, message "Wiki: N pages created, M updated", detail incl. triage_action — bounded by
        # AC7, AC13
        raise NotImplementedError
```
**Why this shape**: identical to the CLI `--auto` apply step (cli.py:5370-5372 +
:5219-5233) restricted to `admit`; the staged path is passed as `source_path`
because orchestrator identity is path-derived, so a re-upload under the same
file name replaces the same source slice (spec §2 Staging).

### FILL IN checklist
- [ ] `wiki.py::_build_runtime` — sqlite-only store/sources, charter, runtime; bounded by AC8, AC9
- [ ] `wiki.py::ingest` — duplicate/reject mapping; bounded by AC7, G7
- [ ] `wiki.py::ingest` — report → outcome mapping + detail; bounded by AC7, AC13
- [ ] test bodies in `test_wiki_target.py`

---

## Acceptance Criteria

- [ ] `available()` is `(False, reason)` when the charter file is missing (AC9) or the backend is not sqlite.
- [ ] Only `proposed_action == "admit"` reaches `orchestrator.ingest`, with `decision="admit"`, `decision_source="auto"`, `charter_version=charter.version` (AC7).
- [ ] `archive` and `discard` (incl. gray-zone results) → REJECTED_BY_TRIAGE with the briefing; `orchestrator.ingest` not called (AC7).
- [ ] Heuristic duplicate → SKIPPED; `force=True` passes `skip_duplicate_check=True` and nothing else (G7).
- [ ] Runtime is built once with `lightweight_model == model == config.llm` (AC8).
- [ ] `report.status != "ok"` → FAILED; checkpoint failure never fails the job.
- [ ] `ruff check` clean on touched files.

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/knowledge_upload/test_wiki_target.py -q`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/knowledge_upload/test_wiki_target.py
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.integrations.knowledge_upload import (
    UploaderIdentity, UploadRequest, UploadStatus, UploadTargetKind, WikiTargetConfig,
)
from parrot.integrations.knowledge_upload.targets.wiki import WikiTarget


def _entry(action, source="model", briefing="because"):
    entry = MagicMock(proposed_action=action, decision_source=source, briefing=briefing)
    entry.model_copy.return_value = entry
    return entry


def _target(tmp_path, entry, report=None):
    t = WikiTarget(WikiTargetConfig(wiki_root=str(tmp_path)))
    t._runtime = SimpleNamespace(
        acquirer=MagicMock(acquire=AsyncMock(return_value=SimpleNamespace(text="# doc"))),
        router=MagicMock(triage=AsyncMock(return_value=entry)),
        orchestrator=MagicMock(ingest=AsyncMock(return_value=report or SimpleNamespace(
            status="ok", error=None, pages_created=3, pages_updated=0))),
        wiki_config=object(), charter=SimpleNamespace(version="v1"), store=object(),
    )
    return t


def _req(force=False):
    return UploadRequest(target=UploadTargetKind.WIKI, filename="sop.md", data=b"# sop", force=force,
                         identity=UploaderIdentity(platform="slack", platform_user_id="U1"))


async def test_admit_is_ingested(tmp_path):
    t = _target(tmp_path, _entry("admit"))
    out = await t.ingest(tmp_path / "sop.md", _req(), "j1")
    assert out.status == UploadStatus.ADDED
    kwargs = t._runtime.orchestrator.ingest.call_args.kwargs
    assert kwargs["charter_version"] == "v1"


@pytest.mark.parametrize("action", ["archive", "discard"])
async def test_non_admit_rejected(tmp_path, action):
    t = _target(tmp_path, _entry(action, briefing="off-charter"))
    out = await t.ingest(tmp_path / "sop.md", _req(), "j1")
    assert out.status == UploadStatus.REJECTED_BY_TRIAGE and "off-charter" in out.message
    t._runtime.orchestrator.ingest.assert_not_called()


async def test_duplicate_skipped_and_force_flag(tmp_path):
    # FILL IN: heuristic "Rejected by heuristic: duplicate: …" → SKIPPED; force=True → triage called with
    # skip_duplicate_check=True
    ...


async def test_unavailable_without_charter(tmp_path):
    ok, reason = await WikiTarget(WikiTargetConfig(wiki_root=str(tmp_path))).available()
    assert not ok and "charter" in reason
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug teams-telegram-uploader-bookstore --feature-id FEAT-647`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/teams-telegram-uploader-bookstore.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/teams-telegram-uploader-bookstore.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4185 teams-telegram-uploader-bookstore verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
