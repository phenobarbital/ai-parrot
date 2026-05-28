# TASK-1337: Redistribute host pyproject extras after the move

**Feature**: FEAT-201 — ai-parrot-embeddings
**Spec**: `sdd/specs/ai-parrot-embeddings.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1334, TASK-1335, TASK-1336
**Assigned-to**: unassigned

---

## Context

Implements **Module 5** of the spec — host pyproject surgery after the
backend code has moved. Removes the now-orphaned extras, extracts
`pgvector==0.4.1` from the entangled `images` extra, and rewrites the
`all` / `all-fast` meta-extras so the legacy one-liner install
(`pip install ai-parrot[all]`) still yields the same functional stack
as today. Preserves `faiss-cpu` in core dependencies (episodic memory
still uses it as default backend).

Reference: spec §3 Module 5, §6 Codebase Contract, §7 host-pyproject
constraints.

---

## Scope

- Remove from `packages/ai-parrot/pyproject.toml`:
  - The `embeddings` extra block (currently lines 287-308).
  - The `milvus` extra block (currently lines 408-411).
  - The `chroma` extra block (currently lines 413-415).
  - The `arango` extra block (currently lines 172-174).
- Extract `pgvector==0.4.1` from the `images` extra (currently line
  352). The line is removed; the rest of `images` stays.
- Decide on the host `bigquery` extra (currently lines 124-126) —
  unresolved question in spec §8. Two options:
  - (a) Remove it; rely on `db` extra (`asyncdb[bigquery,...]`) for
    non-vector-store usage.
  - (b) Keep it; satellite's `bigquery` extra covers the
    `BigQueryStore` path while host's covers other consumers.
  Document which option was chosen in the completion note.
- Rewrite `all` (currently line 504-506) so `pip install ai-parrot[all]`
  still yields a full stack. New form (adjust based on bigquery
  decision):
  ```toml
  all = [
      "ai-parrot[agents,images,llms,integrations,db,bigquery,pdf,ocr,audio,finance,flowtask,scheduler,reddit,mcp,charts,docling]",
      "ai-parrot-embeddings[all]",
  ]
  ```
  (Note: `embeddings` removed from the inner list because the extra no
  longer exists; `ai-parrot-embeddings[all]` covers it.)
- Rewrite `all-fast` (currently line 508-510):
  ```toml
  all-fast = [
      "ai-parrot[agents-lite,llms,integrations]",
      "ai-parrot-embeddings[huggingface,faiss,pgvector]",
  ]
  ```
- **Keep `faiss-cpu>=1.9.0` in `[project] dependencies`** (currently
  line 98) — DO NOT move it to an extra. Comment line 96-97 explains why
  (episodic memory needs it as default).

**NOT in scope**:
- Touching `packages/ai-parrot/src/parrot/embeddings/__init__.py` —
  its `supported_embeddings` dispatch map and re-exports STAY
  unchanged.
- Touching `packages/ai-parrot/src/parrot/stores/__init__.py` — same
  (per TASK-1335 constraints).
- Touching `packages/ai-parrot/src/parrot/rerankers/__init__.py` —
  same.
- Modifying the satellite pyproject — that's TASK-1334/1335/1336.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/pyproject.toml` | MODIFY | Remove orphaned extras; extract pgvector from images; rewrite all + all-fast meta-extras |

---

## Codebase Contract (Anti-Hallucination)

### Verified existing extras in the host pyproject (sources of deps to move/remove)

```toml
# packages/ai-parrot/pyproject.toml:124-126
bigquery = [
    "google-cloud-bigquery>=3.30.0",
]

# packages/ai-parrot/pyproject.toml:172-174
arango = [
    "python-arango-async==1.2.0",
]

# packages/ai-parrot/pyproject.toml:287-308
embeddings = [
    "sentence-transformers>=5.0.0",
    "faiss-cpu>=1.9.0",
    "rank_bm25==0.2.2",
    "sentencepiece==0.2.1",
    "tiktoken==0.9.0",
    "chromadb==0.6.3",
    "bm25s[full]==0.2.14",
    "simsimd>=4.3.1",
    "tokenizers>=0.20.0,<=0.22.2",
    "safetensors>=0.4.3",
    "einops>=0.7.0",
    "accelerate>=0.30.0",
    "peft>=0.10.0",
    "xformers>=0.0.27",
]

# packages/ai-parrot/pyproject.toml:408-411
milvus = [
    "pymilvus==2.4.8",
    "milvus-lite>=2.4.0",
]

# packages/ai-parrot/pyproject.toml:413-415
chroma = [
    "chroma==0.2.0",
]

# packages/ai-parrot/pyproject.toml:345-367 (images — pgvector is line 352)
images = [
    "torchvision>=0.23.0,<0.24",
    "timm==1.0.15",
    "ultralytics==8.4.14",
    "albumentations==2.0.6",
    "filetype==1.2.0",
    "imagehash==4.3.1",
    "pgvector==0.4.1",         # ← EXTRACT THIS LINE; keep the rest
    "pyheif==0.8.0",
    # ... rest stays
]

# packages/ai-parrot/pyproject.toml:96-99 (core dependency to KEEP)
# Episodic memory default backend (FAISS) — required whenever an agent
# enables episodic memory without an explicit pgvector DSN.
"faiss-cpu>=1.9.0",

# packages/ai-parrot/pyproject.toml:504-506 (current all meta-extra)
all = [
    "ai-parrot[agents,images,llms,integrations,db,bigquery,pdf,ocr,audio,finance,flowtask,scheduler,arango,reddit,embeddings,mcp,charts,docling]"
]

# packages/ai-parrot/pyproject.toml:508-510 (current all-fast meta-extra)
all-fast = [
    "ai-parrot[agents-lite,llms,embeddings,integrations]"
]
```

### Does NOT Exist (Anti-Hallucination)

- ~~`pgvector` standalone extra in the host today~~ — currently
  pgvector lives ONLY inside `images`. There is no
  `[project.optional-dependencies] pgvector = [...]` block in the host
  today.
- ~~A `vectorstores` umbrella extra~~ — does NOT exist. Don't invent
  one in the host.
- ~~`tool.uv.workspace` declarations in the host pyproject~~ — the
  workspace lives in the **root** `pyproject.toml` (lines 43-44), NOT
  in the host package. Don't add `[tool.uv.workspace]` to the host.

### Verified Host Constants to Preserve

```toml
# packages/ai-parrot/pyproject.toml:529-532
[tool.setuptools.packages.find]
where = ["src"]
include = ["parrot*"]
namespaces = true
```

— Keep this block exactly as is.

---

## Implementation Notes

### Open question to settle in this task

Spec §8 Open Question #1: should the host `bigquery` extra (line
124-126) stay or be removed? Walk the code to decide:

```bash
# Find non-store-only consumers of google-cloud-bigquery
grep -rn "google-cloud-bigquery\|google.cloud.bigquery" packages/ai-parrot/src --include="*.py" | head
# Find consumers of asyncdb's bigquery extra
grep -rn "asyncdb\[.*bigquery" packages/ai-parrot --include="*.toml" --include="*.py" | head
```

Pick the option that minimizes user-visible churn. Document the
decision in the completion note + open a follow-up if needed.

### Suggested rewritten `all` (Option A — host bigquery removed)

```toml
all = [
    "ai-parrot[agents,images,llms,integrations,db,pdf,ocr,audio,finance,flowtask,scheduler,reddit,mcp,charts,docling]",
    "ai-parrot-embeddings[all]",
]
```

### Suggested rewritten `all` (Option B — host bigquery kept)

```toml
all = [
    "ai-parrot[agents,images,llms,integrations,db,bigquery,pdf,ocr,audio,finance,flowtask,scheduler,reddit,mcp,charts,docling]",
    "ai-parrot-embeddings[all]",
]
```

(Either way, `embeddings`, `milvus`, `chroma`, `arango` are dropped
from the inner list because the extras no longer exist; the satellite
`[all]` covers their backends.)

### Suggested rewritten `all-fast`

```toml
all-fast = [
    "ai-parrot[agents-lite,llms,integrations]",
    "ai-parrot-embeddings[huggingface,faiss,pgvector]",
]
```

### `images` extra — surgical edit

Remove ONLY the line `"pgvector==0.4.1",` (line 352). All other
entries in `images` stay. If you discover that something else in
`images` depended on `pgvector` being co-installed, add an explicit
`"ai-parrot-embeddings[pgvector]"` entry to `images` instead of
dropping it entirely (this preserves the legacy install behavior).

### Sanity check after editing

```bash
uv sync --all-packages
uv pip show ai-parrot     # should still install
uv pip show ai-parrot-embeddings   # should still install
python -c "import tomllib; print(tomllib.loads(open('packages/ai-parrot/pyproject.toml').read())['project']['optional-dependencies'].keys())"
# Expected NOT to contain: embeddings, milvus, chroma, arango
# Expected to still contain: images (without pgvector)
```

### References in Codebase

- `packages/ai-parrot-tools/pyproject.toml:72-74` — shape of a
  satellite `all` aggregator extra to mirror in `ai-parrot-embeddings`.
- `packages/ai-parrot/pyproject.toml:96-99` — core deps with
  faiss-cpu (KEEP).

---

## Acceptance Criteria

- [ ] Host pyproject no longer contains
      `[project.optional-dependencies] embeddings = [...]`.
- [ ] Host pyproject no longer contains the `milvus`, `chroma`,
      `arango` extras blocks.
- [ ] Host pyproject's `images` extra no longer contains the
      `pgvector==0.4.1` line.
- [ ] Host pyproject KEEPS `faiss-cpu>=1.9.0` in
      `[project] dependencies` (the line under the comment "Episodic
      memory default backend (FAISS)").
- [ ] Host pyproject's `all` meta-extra contains the string
      `"ai-parrot-embeddings[all]"`.
- [ ] Host pyproject's `all-fast` meta-extra contains the string
      `"ai-parrot-embeddings["`.
- [ ] Host pyproject's `[tool.setuptools.packages.find]` block remains
      EXACTLY: `where = ["src"]`, `include = ["parrot*"]`,
      `namespaces = true`.
- [ ] `uv sync --all-packages` succeeds after the edit.
- [ ] `tomllib.loads(...)` of the new pyproject succeeds (it is
      valid TOML).
- [ ] Decision on the `bigquery` extra documented in the completion
      note (kept or removed; rationale).

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/test_host_pyproject_after_feat201.py
import tomllib
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def host_pyproject() -> dict:
    text = (Path(__file__).parent.parent.parent / "pyproject.toml").read_text(encoding="utf-8")
    return tomllib.loads(text)


def test_moved_extras_gone(host_pyproject):
    """Extras that moved to ai-parrot-embeddings no longer exist in the host."""
    extras = host_pyproject["project"]["optional-dependencies"]
    for name in ("embeddings", "milvus", "chroma", "arango"):
        assert name not in extras, f"host still declares the {name!r} extra"


def test_pgvector_extracted_from_images(host_pyproject):
    """pgvector no longer rides inside the images extra."""
    images = host_pyproject["project"]["optional-dependencies"]["images"]
    pgvector_lines = [d for d in images if d.startswith("pgvector")]
    assert pgvector_lines == [], f"pgvector still in images: {pgvector_lines}"


def test_faiss_cpu_in_core_deps(host_pyproject):
    """faiss-cpu must remain a core dependency for episodic memory."""
    deps = host_pyproject["project"]["dependencies"]
    assert any(d.startswith("faiss-cpu") for d in deps), \
        f"faiss-cpu missing from core deps: {deps}"


def test_all_meta_extra_includes_satellite(host_pyproject):
    """pip install ai-parrot[all] must reach ai-parrot-embeddings[all]."""
    all_extra = host_pyproject["project"]["optional-dependencies"]["all"]
    assert any("ai-parrot-embeddings" in d for d in all_extra), \
        f"all meta-extra missing satellite ref: {all_extra}"


def test_all_fast_meta_extra_includes_satellite(host_pyproject):
    """pip install ai-parrot[all-fast] must reach ai-parrot-embeddings."""
    fast = host_pyproject["project"]["optional-dependencies"]["all-fast"]
    assert any("ai-parrot-embeddings" in d for d in fast), \
        f"all-fast missing satellite ref: {fast}"


def test_namespaces_setting_preserved(host_pyproject):
    """Namespace discovery must stay enabled."""
    find = host_pyproject["tool"]["setuptools"]["packages"]["find"]
    assert find["namespaces"] is True
    assert find["include"] == ["parrot*"]
    assert find["where"] == ["src"]
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §3 Module 5 and §6 Codebase Contract.
2. **Check dependencies** — TASK-1334, TASK-1335, TASK-1336 must all
   be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — re-read the host pyproject
   sections cited above (line numbers may have drifted since the spec
   was written; rely on block-content matching, not exact line
   numbers).
4. **Decide on `bigquery`** — investigate consumers; pick option A or
   B; document.
5. **Update status** in
   `sdd/tasks/index/ai-parrot-embeddings.json` → `"in-progress"`.
6. **Implement** — edit the host pyproject, run `uv sync`, run the
   unit test above + full core test suite (`pytest
   packages/ai-parrot/tests/`).
7. **Verify** all acceptance criteria.
8. **Move this file** to `sdd/tasks/completed/`.
9. **Update index** → `"done"`.
10. **Fill in the Completion Note** (with the `bigquery` decision).

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: …

**`bigquery` extra decision**: kept | removed — rationale: …

**Deviations from spec**: none | describe if any
