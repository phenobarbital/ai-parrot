# Code Review: FEAT-127 — Contextual Embedding Headers + FileManagerToolkit Migration

**Date**: 2026-04-27
**Reviewer**: Claude Code (code-reviewer agent)
**Spec files**: `sdd/specs/contextual-embedding-headers.spec.md`, `sdd/specs/filemanagertool-migration-toolkit.spec.md`

**Reviewed files**:
- `packages/ai-parrot/src/parrot/stores/utils/contextual.py` (TASK-861)
- `packages/ai-parrot/src/parrot/stores/abstract.py` (TASK-862)
- `packages/ai-parrot/src/parrot/stores/postgres.py` (TASK-863)
- `packages/ai-parrot/tests/unit/stores/utils/test_contextual.py` (TASK-861 tests)
- `packages/ai-parrot/tests/unit/stores/test_abstract_contextual.py` (TASK-862 tests)
- `packages/ai-parrot/tests/integration/stores/test_contextual_pgvector.py` (TASK-863 tests)
- `docs/contextual-embedding.md` (TASK-869-docs)
- `packages/ai-parrot/src/parrot/tools/filemanager.py` (TASK-869-core)
- `packages/ai-parrot/src/parrot/tools/__init__.py` (TASK-870)
- `packages/ai-parrot-tools/src/parrot_tools/__init__.py` (TASK-871)
- `tests/tools/test_filemanager_toolkit.py` (TASK-872)
- `examples/tool/fs.py` (TASK-873)

**Overall verdict**: ⚠ Approved with notes — 2 correctness bugs and 2 important issues must be addressed before merge

---

## Summary

Both sub-features are functionally complete and all acceptance criteria pass structurally. The contextual embedding helper contains two correctness bugs — one in the callable-template path (page content is silently dropped) and one where the header-token cap assertion in tests is weaker than the spec — that will cause subtle, hard-to-diagnose failures in production. The FileManagerToolkit migration is solid, but a test-isolation hazard from module-level `sys.modules` surgery could corrupt unrelated test sessions. Several SDD task completion notes were left blank (TASK-862, TASK-863, TASK-869-docs), breaking the audit trail.

---

## Findings

### 🔴 Critical — Must Fix Before Merge

#### 1. `contextual.py` — Callable template silently discards `page_content`

**Location**: `parrot/stores/utils/contextual.py`, callable-template branch

The callable receives only `meta` (the `document_meta` dict) — `page_content` is **never passed** into it. The function then returns `(full_text, header)` where `full_text` is entirely the callable's own output:

```python
if callable(template):
    full_text = template(meta)   # ← meta only, page_content NOT passed
    ...
    return (full_text, header)   # ← page_content is silently dropped
```

In production, any callable template that doesn't somehow include the chunk text in its output will produce embeddings with **zero chunk content**. Retrieval will silently degrade. The passing test `assert text.endswith("BODY")` masks the bug — "BODY" is not the real `page_content`.

**Fix** (preferred — append content after callable header):

```python
if callable(template):
    header_part = template(meta)
    if not isinstance(header_part, str):
        header_part = str(header_part)
    header_words = header_part.split()
    if len(header_words) > max_header_tokens:
        header_part = " ".join(header_words[:max_header_tokens])
    if not header_part.strip():
        return (content, "")
    return (header_part.strip() + "\n\n" + content, header_part.strip())
```

Update the test accordingly:
```python
assert doc_full.page_content in text   # not text.endswith("BODY")
```

> ⚠️ If Option A (callable receives `(meta, content)`) is preferred, update `ContextualTemplate = Union[str, Callable[[dict, str], str]]` as well.

---

#### 2. `test_contextual.py` — Header-token cap assertion too loose

**Location**: `tests/unit/stores/utils/test_contextual.py`, `test_caps_header_tokens`

```python
assert len(header.split()) <= 12  # spec allows a small slack
```

`max_header_tokens=10` is passed. No slack exists in the spec or implementation — the cap is `header_words[:max_header_tokens]` (exact). The assertion passes even if the implementation is off by two words, giving false assurance:

```python
# Fix:
assert len(header.split()) <= max_header_tokens   # enforce the exact contract
```

---

### 🟠 Important — Should Fix

#### 3. `contextual.py` — Fragile `"\n\n{content}"` detection is a double-format injection vector

**Location**: `parrot/stores/utils/contextual.py`, string-template path

```python
if "\n\n{content}" in template:          # fast path
    text_to_embed = header + "\n\n" + content
else:                                     # re-render path
    full_ctx["content"] = content
    text_to_embed = template.format_map(full_ctx)  # second format_map!
```

The else-branch applies `format_map` on values that were **already brace-escaped** in `_sanitise_meta`. A metadata value of `"{world}"` was sanitised to `"{{world}}"`. The second `format_map` renders `{{world}}` → `{world}`, which is then embedded verbatim — bypassing the injection protection for any custom template that doesn't exactly match `"\n\n{content}"`.

**Fix**: Remove the conditional fast path entirely. Always take the re-render path:

```python
full_ctx: _DefaultEmpty = _DefaultEmpty(sanitised)
full_ctx["content"] = content
try:
    text_to_embed = template.format_map(full_ctx)
except (KeyError, ValueError):
    text_to_embed = header + "\n\n" + content
```

---

#### 4. `postgres.py` — 2N INFO log lines per `from_documents` call

**Location**: `parrot/stores/postgres.py`, per-document loop in `from_documents`

`_apply_contextual_augmentation` is called **twice per source document**: once for the parent and once for its chunks. Each call emits an `INFO` log line. For 100 source docs each with 10 chunks this produces 200 `INFO` lines per batch — flooding production logs.

**Fix**: log once at the call site in `from_documents` after the loop:

```python
total_headered = 0
for doc_idx, document in enumerate(documents):
    ...
    if self.contextual_embedding:
        [parent_text] = self._apply_contextual_augmentation([parent_view], _silent=True)
        ...
        chunk_texts = self._apply_contextual_augmentation(chunk_views, _silent=True)
        total_headered += 1 if full_header else 0

if self.contextual_embedding and documents:
    self.logger.info("Contextual embedding: %d/%d documents received header", total_headered, len(documents))
```

Alternatively add a `_log: bool = True` parameter to `_apply_contextual_augmentation` so call sites can suppress the internal log.

---

#### 5. `test_filemanager_toolkit.py` — Module-level `sys.modules` surgery affects entire pytest session

**Location**: `tests/tools/test_filemanager_toolkit.py`, module-level bootstrap block

```python
# Runs at import time — affects all other modules in the same pytest session
sys.modules["navigator.utils.file"] = _nav_mock   # replaces real module globally
for _key in list(sys.modules):
    if "parrot.interfaces.file" in _key or ...:
        del sys.modules[_key]
```

With `pytest-xdist` or if test collection order changes, other tests that rely on the real `navigator.utils.file` will silently see the mock. Move this into a module-scoped fixture:

```python
@pytest.fixture(autouse=True, scope="module")
def _patch_navigator(monkeypatch):
    nav_mock = _make_navigator_mock()
    monkeypatch.setitem(sys.modules, "navigator.utils.file", nav_mock)
    for key in [k for k in sys.modules if "parrot.interfaces.file" in k or "parrot.tools.filemanager" in k]:
        monkeypatch.delitem(sys.modules, key, raising=False)
    # monkeypatch restores automatically after scope exits
```

---

#### 6. `FileManagerToolkit` — `allowed_operations` not validated against `_ALL_OPS`

**Location**: `parrot/tools/filemanager.py`, `FileManagerToolkit.__init__`

A caller passing `allowed_operations={"list", "creat"}` (typo) gets no error. The misspelled operation `"creat"` is silently ignored — `create_file` remains exposed when the intent was to restrict it. This is a **security-relevant misconfiguration** since the toolkit is designed to let operators lock down file access.

**Fix**:
```python
if allowed_operations is not None:
    unknown = set(allowed_operations) - _ALL_OPS
    if unknown:
        raise ValueError(
            f"FileManagerToolkit: unknown operations: {sorted(unknown)!r}. "
            f"Valid operations: {sorted(_ALL_OPS)}"
        )
```

---

### 🟡 Suggestions

- **`abstract.py`** — `contextual_template` type is not validated at construction. Passing an integer proceeds silently and fails deep inside `_apply_contextual_augmentation`. Add a `isinstance` check in `__init__`.

- **`contextual.py`** — `KNOWN_PLACEHOLDERS` is defined but never referenced by any code. Either use it for template validation or remove it to avoid confusion.

- **`contextual.py`** — `_sanitise_meta` swallows exceptions from `str(v)` without any log output, even at DEBUG level. Since it's a module-level function (no `self`), at minimum add a comment explaining which types trigger this path.

- **`postgres.py` + `contextual.py`** — In `from_documents`, the parent document is re-augmented via `_apply_contextual_augmentation([parent_view])` on every call. For idempotent re-ingest of the same documents this is wasted work. Consider caching on `(content[:64], frozenset(meta.items()))` if this path proves hot.

---

### 💡 Nitpicks

- **TASK-862, TASK-863, TASK-869-docs completion notes**: Template placeholders were left blank (`**Completed by**: `, `**Date**: `, etc.). Fill in at least one sentence per task for audit trail.
- **TASK-873**: Duplicate `**Deviations from spec**` line at the bottom of the file — template not cleaned up.
- **`contextual.py`**: The `_DefaultEmpty.__missing__` returns plain `""` with no escaping. Add a comment explaining why this is safe (it is not user-supplied data, so brace injection is not a risk from this path).
- **`filemanager.py`**: `tool_prefix: Optional[str] = "fs"` uses `Optional` but the value should never be `None` in practice. Consider `tool_prefix: ClassVar[str] = "fs"` for clarity.

---

## Acceptance Criteria Check

| Task | Criterion | Status | Notes |
|---|---|---|---|
| TASK-861 | `build_contextual_text` returns `(text, header)` | ✅ | |
| TASK-861 | `DEFAULT_TEMPLATE` exported | ✅ | |
| TASK-861 | No new dependencies | ✅ | |
| TASK-861 | 14 unit tests pass | ⚠ | `test_caps_header_tokens` assertion is too loose |
| TASK-861 | Callable template supported | ❌ | Page content silently dropped in callable path |
| TASK-862 | `contextual_embedding` kwarg on `AbstractStore` | ✅ | |
| TASK-862 | `_apply_contextual_augmentation` implemented | ✅ | |
| TASK-862 | 8 unit tests pass | ✅ | |
| TASK-862 | Completion note filled | ❌ | Template placeholders left blank |
| TASK-863 | `add_documents` wired | ✅ | |
| TASK-863 | `from_documents` wired, precedence rule enforced | ✅ | |
| TASK-863 | Integration tests pass | ✅ | `asyncio_mode=auto` covers unmarked async tests |
| TASK-863 | RAW `page_content` stored in `content_column` | ✅ | |
| TASK-863 | Completion note filled | ❌ | Template placeholders left blank |
| TASK-869-docs | All 8 required H2 sections present | ✅ | |
| TASK-869-docs | Code examples are correct | ✅ | |
| TASK-869-docs | Migration warning references script path | ✅ | |
| TASK-869-docs | Completion note filled | ❌ | Template placeholders left blank |
| TASK-869-core | `FileManagerToolkit` class with 9 tools | ✅ | |
| TASK-869-core | `tool_prefix = "fs"` | ✅ | |
| TASK-869-core | `allowed_operations` filtering works | ⚠ | No validation against `_ALL_OPS` — silent misconfiguration possible |
| TASK-869-core | `FileManagerTool` preserved with deprecation notice | ✅ | |
| TASK-870 | `FileManagerToolkit` in `__all__` | ✅ | |
| TASK-870 | `FileManagerToolkit` in `_LAZY_CORE_TOOLS` | ✅ | |
| TASK-871 | `"file_manager_toolkit"` in `TOOL_REGISTRY` | ✅ | |
| TASK-872 | 45 tests covering all categories | ✅ | `sys.modules` surgery is a test isolation hazard |
| TASK-873 | Example updated with `FileManagerToolkit` | ✅ | Duplicate "Deviations from spec" line |
| TASK-873 | Legacy `FileManagerTool` usage preserved | ✅ | |

---

## Positive Highlights

- **`_DefaultEmpty` sentinel**: An elegant, zero-overhead solution for suppressing `KeyError` on missing metadata keys without try/except in the hot render path.
- **`_collapse_pipes`**: Handles the three structural cases (label:value, trailing-colon-only, bare segment) correctly. Well-structured and readable.
- **`exclude_tools` ordering**: Setting `self.exclude_tools` before `super().__init__()` in `FileManagerToolkit` correctly anticipates that `AbstractToolkit` reads this during tool registration. Non-obvious constraint handled correctly.
- **`pytest.ini` asyncio_mode = auto**: The project-wide decision avoids `@pytest.mark.asyncio` boilerplate throughout all async tests — clean choice.
- **`docs/contextual-embedding.md`**: Excellent: covers all three configuration paths, includes runnable examples for all four stores, warns about the re-index requirement, and includes the Spanish-corpus template example the spec called for.
- **PgVector `add_documents` diff**: The separation of `texts_for_embed` (augmented) from `raw_texts` (for `content_column`) is clean and clearly commented.

---

## AI Hallucination Check 🤖

| Check | Result |
|---|---|
| `build_contextual_text(document, template, max_header_tokens)` signature — all call sites | ✅ Consistent |
| `_apply_contextual_augmentation([parent_view])` single-element destructuring | ✅ Correct |
| `AbstractToolkit` base class usage and `exclude_tools` pattern | ✅ Matches `toolkit.py:168` contract |
| `Document(page_content=..., metadata=...)` constructor | ✅ Matches `models.py:21` |
| `FileManagerFactory.create(manager_type, **kwargs)` signature | ✅ Matches `filemanager.py:18` |
| `TOOL_REGISTRY` key naming (`"file_manager_toolkit"`) | ✅ Correct |
| `_LAZY_CORE_TOOLS` module path (`".filemanager"`) | ✅ Correct |
| `frozenset` type annotation on `_ALL_OPS` | ⚠ Missing type parameter — should be `frozenset[str]` |
| `ContextualTemplate = Union[str, Callable[[dict], str]]` vs callable fix | ⚠ Must be updated if callable signature changes to `(meta, content)` |

No phantom imports, no invented framework methods, no fabricated base classes detected.
