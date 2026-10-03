# TASK-4033: Entity commands and remember metadata flags

---

**Feature**: FEAT-627 — wikitoolkit standup: entity attributes and daily/period briefs
**Spec**: `sdd/specs/wikitoolkit-standup.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-4022, TASK-4023, TASK-4025, TASK-4030
**Assigned-to**: unassigned

---

## Context

Implement M4/AC5. Add entity add/list/reindex with documented options and JSON/table results. Add --body to add and use entity:<type>:<slug-hash>, authored origin and resolved author; optional links follow asserted-edge semantics. remember gains all six entity flags and attrs=normalized rows source=memory; defaults retain prior behavior. entity_cli must not import cli: use project/store/federation primitives directly, with Click wrappers running async work. Resolve root/store/backend overrides explicitly. Reindex refuses nonlocal --ns even though the existing write resolver now permits targeted namespace writes. Process inventory in batches of 500: list_pages has NO offset/cursor; snapshot IDs using stats/page count and list_pages before writing, then batch that stable inventory. Fetch bodies with get_page. For legacy Markdown unwrap only the verified leading repo-scan ## Content wrapper before parse_leading_yaml; vault bodies with discarded frontmatter cannot be reconstructed: skip/report instead of inventing attrs. Dry-run performs no write/audit mutation; unsupported stores fail actionably. Use writer lock and log ENTITY/REINDEX.

---

## Scope

Implement M4/AC5. Add entity add/list/reindex with documented options and JSON/table results. Add --body to add and use entity:<type>:<slug-hash>, authored origin and resolved author; optional links follow asserted-edge semantics. remember gains all six entity flags and attrs=normalized rows source=memory; defaults retain prior behavior. entity_cli must not import cli: use project/store/federation primitives directly, with Click wrappers running async work. Resolve root/store/backend overrides explicitly. Reindex refuses nonlocal --ns even though the existing write resolver now permits targeted namespace writes. Process inventory in batches of 500: list_pages has NO offset/cursor; snapshot IDs using stats/page count and list_pages before writing, then batch that stable inventory. Fetch bodies with get_page. For legacy Markdown unwrap only the verified leading repo-scan ## Content wrapper before parse_leading_yaml; vault bodies with discarded frontmatter cannot be reconstructed: skip/report instead of inventing attrs. Dry-run performs no write/audit mutation; unsupported stores fail actionably. Use writer lock and log ENTITY/REINDEX.

**NOT in scope**: changes outside the declared file table; new runtime dependencies; unrelated cleanup. Follow the approved v1 non-goals for backend parity and pre-existing ledger import cost.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/entity_cli.py` | CREATE | No CLI circular import and no fabricated pagination parameter are allowed. |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | The shared cli.py writer follows the identity task; importing entities at module load breaks AC13. |
| `packages/ai-parrot/tests/knowledge/wiki/test_entity_cli.py` | CREATE | Use isolated CliRunner and real SQLite; include wrapped legacy bodies. |

---

## Codebase Contract (Anti-Hallucination)

Verified at `75fe680a0`. Dependency-created imports below are planned contracts, not claims of current existence.

### Verified Imports

```python
import click  # stdlib or existing pyproject dependency/test environment
from parrot.knowledge.wiki.entities import normalize_frontmatter, parse_leading_yaml  # planned in TASK-4022; not present before that task
from parrot.knowledge.wiki.identity import authoring_identity  # planned in TASK-4030; not present before that task
from parrot.knowledge.wiki.store import WikiPageRecord, create_wiki_store  # verified source packages/ai-parrot/src/parrot/knowledge/wiki/store.py
from parrot.knowledge.wiki.project import load_effective_config, wiki_write_lock  # verified source packages/ai-parrot/src/parrot/knowledge/wiki/project.py
from pathlib import Path  # stdlib or existing pyproject dependency/test environment
import pytest  # stdlib or existing pyproject dependency/test environment
import parrot.knowledge.wiki.entity_cli as subject  # planned in TASK-4033; not present before that task
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:3806
def remember(
    text: str,
    path_: str | None,
    store_opt: str | None,
    backend_opt: str | None,
    title: str | None,
    category: str,
    links: tuple[str, ...],
    rel: str,
    ns_opt: str | None,
    source_uri: str | None,
    by: str | None,
    extract_: bool,
    as_json: bool,
) -> None:

# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:583
def _resolve_read_store(
    path_: str | None,
    store_opt: str | None,
    backend_opt: str | None,
    ns_opt: str | None = None,
) -> BaseWikiStore:

# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:3546
def _resolve_write_store(
    path_: str | None,
    store_opt: str | None,
    backend_opt: str | None,
    ns_opt: str | None = None,
) -> tuple[BaseWikiStore, Path | None, Path | None, WikiProjectConfig | None]:

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:409
class WikiPageRecord(BaseModel):

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:2376
def create_wiki_store(
    storage_dir: str | Path,
    wiki_name: str = "",
    backend: str = "sqlite",
    **kwargs: Any,
) -> BaseWikiStore:

# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:933
def load_effective_config(root: Path, env: str | None = None) -> WikiEffectiveConfig:

# packages/ai-parrot/src/parrot/knowledge/wiki/project.py:74
def wiki_write_lock(store_dir: Path, timeout: float = 0.0) -> Iterator[bool]:
```

### Does NOT Exist

- `packages/ai-parrot/src/parrot/knowledge/wiki/entity_cli.py` is created by this task; do not assume it already exists.
- `packages/ai-parrot/tests/knowledge/wiki/test_entity_cli.py` is created by this task; do not assume it already exists.
- `list_pages(offset=...)`, `DecisionRecord.updated_at`, and a JiraPerson email field are not existing APIs. Do not invent them.
- Category names remain open strings; no new WikiPageCategory enum members are required.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/entity_cli.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_entity_cli.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#remember",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_resolve_read_store",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_resolve_write_store",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#WikiPageRecord",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#create_wiki_store",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#load_effective_config",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#wiki_write_lock"
  ]
}
```

---

## Implementation Notes

TASK-4022: consumes strict normalization API; TASK-4023: consumes attrs persistence; TASK-4025: consumes namespace attrs listing; TASK-4030: consumes shared authoring_identity and earlier cli.py edit

Use async I/O paths, existing lifecycle/context managers, module logging, strict types and Google-style docstrings. Black uses 120 columns; ruff is the lint gate. Keep tests isolated and file-scoped. Fresh dependency code may shift anchors: reverify before edits, and retain the semantic attachment site.

---

## Implementation Blueprint

### Steps (in order)

1. Verify the existing references and completed dependency interfaces — because the blueprint must match the executing worktree.
2. Apply the per-file blocks below in declared order and complete only bounded FILL IN work — because each task owns a limited surface.
3. Implement the listed adversarial cases and run Validation Commands — because the acceptance criteria cover observable behavior, not only imports.

---

### `packages/ai-parrot/src/parrot/knowledge/wiki/entity_cli.py` (CREATE)

```python
"""Typed entity authoring, listing and deterministic local back-fill."""
import click
from parrot.knowledge.wiki.entities import normalize_frontmatter, parse_leading_yaml
from parrot.knowledge.wiki.identity import authoring_identity
from parrot.knowledge.wiki.store import WikiPageRecord, create_wiki_store
from parrot.knowledge.wiki.project import load_effective_config, wiki_write_lock

@click.group(name="entity")
def entity() -> None:
    """Typed entities: add, list and reindex page attributes."""
@entity.command("add")
@click.argument("type_")
@click.argument("title")
@click.option("--body")
@click.option("--project")
@click.option("--status")
@click.option("--date", "date_")
@click.option("--due")
@click.option("--owner")
@click.option("--link", "links", multiple=True)
@click.option("--rel", default="related_to")
@click.option("--by")
@click.option("--json", "as_json", is_flag=True)
@click.option("--path", "path_")
@click.option("--store", "store_opt")
@click.option("--backend", "backend_opt")
def add_entity(type_: str, title: str, body: str | None, project: str | None, status: str | None,
               date_: str | None, due: str | None, owner: str | None, links: tuple[str, ...],
               rel: str, by: str | None, as_json: bool, path_: str | None,
               store_opt: str | None, backend_opt: str | None) -> None:
    """Create a strictly validated authored entity and optional asserted links."""
    # FILL IN: validate, resolve local store, lock/write/audit and render; AC5.
    raise NotImplementedError
@entity.command("list")
@click.option("--type", "type_")
@click.option("--status")
@click.option("--project")
@click.option("--since")
@click.option("--until")
@click.option("--ns", "ns_opt")
@click.option("--limit", type=click.IntRange(min=1), default=200)
@click.option("--json", "as_json", is_flag=True)
@click.option("--path", "path_")
@click.option("--store", "store_opt")
@click.option("--backend", "backend_opt")
def list_entities(type_: str | None, status: str | None, project: str | None, since: str | None,
                  until: str | None, ns_opt: str | None, limit: int, as_json: bool,
                  path_: str | None, store_opt: str | None, backend_opt: str | None) -> None:
    """List matching entity stubs from selected readable planes."""
    # FILL IN: resolve stores, AND/date attrs query and table/JSON output; AC5.
    raise NotImplementedError
@entity.command("reindex")
@click.option("--category")
@click.option("--dry-run", is_flag=True)
@click.option("--ns", "ns_opt")
@click.option("--path", "path_")
@click.option("--store", "store_opt")
@click.option("--backend", "backend_opt")
def reindex_entities(category: str | None, dry_run: bool, ns_opt: str | None,
                     path_: str | None, store_opt: str | None, backend_opt: str | None) -> None:
    """Back-fill preserved source frontmatter in one writable local plane."""
    # FILL IN: reject foreign ns, snapshot IDs, batch 500, unwrap body, normalize.
    # Do not assume list_pages(offset=...) exists; dry-run never writes; AC5.
    raise NotImplementedError
```

**Why**: No CLI circular import and no fabricated pagination parameter are allowed.

---

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY)

Anchor `@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")` — occurrences: 11 (verified: `grep -F -c`), `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:3805`.

Unique attachment context:

```text
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
def remember(
    text: str,
    path_: str | None,
```

```python
# Add these options immediately above def remember, not the ten other JSON options:
@click.option("--type", "type_", default=None)
@click.option("--project", default=None)
@click.option("--status", default=None)
@click.option("--date", "date_", default=None)
@click.option("--due", default=None)
@click.option("--owner", default=None)
# FILL IN: extend remember's existing typed callback with these six optional str args.
# Inside remember execution, import normalize_frontmatter and add attrs to its record.
# Use source="memory"; preserve every existing option, link and extraction behavior.
# Preserve all existing parameters, adding the six typed options listed above.
def remember(
    text: str,
    path_: str | None,
    store_opt: str | None,
    backend_opt: str | None,
    title: str | None,
    category: str,
    links: tuple[str, ...],
    rel: str,
    ns_opt: str | None,
    source_uri: str | None,
    by: str | None,
    extract_: bool,
    as_json: bool,
    type_: str | None,
    project: str | None,
    status: str | None,
    date_: str | None,
    due: str | None,
    owner: str | None,
) -> None:
    # FILL IN: retain existing body and wire six entity values into attrs; AC5.
    raise NotImplementedError
```

**Why**: The shared cli.py writer follows the identity task; importing entities at module load breaks AC13.

---

### `packages/ai-parrot/tests/knowledge/wiki/test_entity_cli.py` (CREATE)

```python
"""Regression cases for FEAT-627."""
from pathlib import Path
import pytest
import parrot.knowledge.wiki.entity_cli as subject


def test_entity_add_list_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify entity add list roundtrip."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError


def test_reindex_large_inventory_and_dryrun(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify reindex large inventory and dryrun."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError


def test_remember_flags_and_ns_rejection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify remember flags and ns rejection."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError
```

**Why**: Use isolated CliRunner and real SQLite; include wrapped legacy bodies.

---

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/entity_cli.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/test_entity_cli.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.

---

## Acceptance Criteria

- [ ] Add/list round-trip, filters/date bounds/namespace selection and JSON shape work; strict errors exit 2 with stable codes.
- [ ] Reindex processes >500 distinct pages exactly once, handles wrapped Markdown, is idempotent and refuses foreign writes.
- [ ] Dry-run leaves the plane/audit untouched; remember flags persist attrs without changing existing defaults.
- [ ] All declared-file tests pass; no ruff errors or unfinished implementation placeholders remain.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_entity_cli.py -q`
- `pytest tests/knowledge/wiki/test_cli.py -q`

---

## Test Specification

- Add/list round-trip, filters/date bounds/namespace selection and JSON shape work; strict errors exit 2 with stable codes.
- Reindex processes >500 distinct pages exactly once, handles wrapped Markdown, is idempotent and refuses foreign writes.
- Dry-run leaves the plane/audit untouched; remember flags persist attrs without changing existing defaults.

Use temporary local state, deterministic clocks and fake network/model adapters. Test failures and negative cases as well as success. New tests live alongside the core distribution; legacy suites are validation references only unless explicitly declared MODIFY above.

---

## Agent Instructions

1. Run `$sdd-start TASK-4033`; implementation belongs in the feature worktree, never directly on dev.
2. Read the approved spec and verify dependency completion in `sdd/tasks/index/wikitoolkit-standup.json`.
3. Recheck imports/anchors, implement only declared files and run the validation commands.
4. Commit scoped implementation and finalize with `scripts.sdd.finalize_task` plus real `TaskCompletionEvidence` for the exact implementation HEAD. Do not manually move the task or manufacture completion evidence.

## Completion Note

Pending; owned by the evidence-based finalizer.
