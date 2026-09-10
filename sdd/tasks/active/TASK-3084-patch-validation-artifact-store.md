# TASK-3084: Unified-diff parser/validator, staging-area application and artifact store

**Feature**: FEAT-543 — Claude Code and Codex Tool Optimizations
**Spec**: `sdd/specs/tool-optimizations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3079
**Assigned-to**: unassigned

---

## Context

Spec §2 "Delegation Packet and Writer Contract" items 4–5 and the
`writer_apply` paragraph's storage/journal requirements; §3 Module M5
(`patches.py`); AC9, AC10 (storage half). This module is pure Python,
stdlib-only, model-free: it parses the unified diff a model returned,
rejects everything outside CREATE/MODIFY, applies hunks in memory against
expected source bytes, and persists artifacts with restrictive
permissions. TASK-3085 (generate) and TASK-3086 (apply) call it.

**Decisions fixed here:**

1. Patch text is applied in **pure Python** (exact context match, zero
   fuzz, no line-offset search). `git apply` is NOT used: model-written
   paths must never reach a git pathspec/argv.
2. Artifact directory: `<repo_root>/artifacts/tool-optimizations/<artifact_id>/`
   (`artifacts/` is gitignored — verified `.gitignore:283`). Files:
   `manifest.json`, `patch.diff`, `packet.json`, `journal.json` (apply
   time), `before/<n>.bin` (apply time). Directory mode `0o700`, files
   `0o600`. `artifact_id = uuid.uuid4().hex` (32 hex chars, matches
   `WriterApplyArgs.artifact_id`).
3. Hashes: `sha256` hex of raw bytes (`patch_sha256` over the normalized
   patch text encoded UTF-8; `before/after` over file bytes; a missing
   file's before-hash is `None`).

---

## Scope

- Create `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/patches.py`:
  - Exceptions: `PatchError(ValueError)` with `code`, `details`. Codes:
    `not_a_patch` (no `---`/`+++` headers or prose/fence detected —
    text starting with ```` ``` ```` or containing lines outside
    diff grammar before the first header), `absolute_path`,
    `path_escape` (`..` segment or leading `/`), `path_outside_scope`,
    `duplicate_target`, `deletion_rejected` (`+++ /dev/null` or
    `deleted file mode`), `rename_rejected` (`rename from/to`,
    `similarity index`, `copy from/to`), `mode_change_rejected`
    (`old mode`/`new mode`/`new file mode 1006xx` non-regular),
    `binary_rejected` (`GIT binary patch`, `Binary files`),
    `submodule_rejected` (`Subproject commit`), `malformed_hunk`
    (bad `@@` header, counts not matching body), `context_mismatch`
    (hunk context/removed lines do not equal the expected source at the
    stated position), `create_needs_dev_null` (a create target's patch
    must have `--- /dev/null`), `patch_too_large`.
  - `class FilePatch(BaseModel)`: `path` (repo-relative POSIX, taken
    from the `+++ b/<path>` header with the `a/`/`b/` prefixes stripped
    when present), `is_create: bool`, `hunks: list[Hunk]`;
    `class Hunk(BaseModel)`: `old_start, old_count, new_start, new_count, lines: list[str]`
    (each with its leading ` `, `-`, `+` marker preserved; `\ No newline
    at end of file` markers folded into a `no_newline_old/new` flag).
  - `def normalize_patch(text: str) -> str`: strip a trailing whitespace-only
    tail, ensure final `\n`, reject fences/prose (`not_a_patch`), and
    return the canonical text that is hashed and stored.
  - `def parse_patch(text: str, *, max_bytes: int) -> list[FilePatch]`:
    strict grammar: optional `diff --git a/x b/x` line, optional
    `index ...` line, `--- a/x` | `--- /dev/null`, `+++ b/x`, hunks.
    Anything else → the specific rejection code above. Paths validated
    (`absolute_path`, `path_escape`, backslashes rejected). Duplicates →
    `duplicate_target`.
  - `def check_scope(patches: list[FilePatch], allowed: dict[str, Literal["create", "modify"]]) -> None`:
    each patched path must be in `allowed` with matching create/modify
    semantics (`path_outside_scope`, `create_needs_dev_null`).
  - `def apply_file_patch(before: bytes | None, patch: FilePatch) -> bytes`:
    split `before` with `keepends=True` on `\n` (CRLF lines keep `\r\n`),
    walk hunks in order verifying every context (` `) and removed (`-`)
    line equals the source line (comparing WITHOUT the trailing newline,
    then re-attaching the source's original newline to context lines and
    the patch's `\n` — or CRLF if the surrounding file uses CRLF
    consistently — to added lines). `no_newline` markers control the last
    line's newline. `context_mismatch` details: `{path, hunk_index, expected_line, actual_line, line_no}`.
  - `def apply_in_memory(patches: list[FilePatch], sources: dict[str, bytes | None]) -> dict[str, bytes]`:
    returns `path → after_bytes` for every patched path; missing source
    for modify → `context_mismatch`; source present for create →
    handled by caller (scope check).
  - `class ArtifactStore`:
    `__init__(self, repo_root: Path)`; `root` property =
    `repo_root / "artifacts" / "tool-optimizations"`.
    - `def new_id() -> str`.
    - `def write_generation(self, artifact_id: str, *, manifest: PatchManifest, patch_text: str, packet_json: str) -> Path`:
      writes into a temp dir `root/.tmp-<id>` then `os.rename` to the
      final dir (atomic publish; a crash leaves only a `.tmp-` dir that
      the next `new_id()` call may sweep if older than 1 h). Files
      `0o600`, dir `0o700`. `manifest.json` is `compact_json(manifest.model_dump(mode="json"))`.
    - `def load(self, artifact_id: str) -> tuple[PatchManifest, str, str]`:
      validates id format, refuses symlinked dirs, returns
      `(manifest, patch_text, packet_json)`; recomputes
      `sha256(patch_text) == manifest.patch_sha256` else
      `PatchError("artifact_tampered")`; also verifies
      `sha256(packet_json) == manifest.packet_sha256`.
    - `def write_journal(self, artifact_id, journal: ApplyJournal) -> None` /
      `def read_journal(self, artifact_id) -> ApplyJournal | None`.
    - `def save_before(self, artifact_id, index: int, data: bytes | None) -> None` /
      `def load_before(self, artifact_id, index) -> bytes | None`
      (`before/<index>.bin`; `None` recorded as absent file + journal flag).
  - `class ApplyJournal(BaseModel)`: `artifact_id`, `started_at`,
    `entries: list[JournalEntry]`, `state: Literal["pending", "applied", "rolled_back", "recovery_required"]`;
    `class JournalEntry`: `path`, `before_sha256: str | None`,
    `after_sha256: str`, `before_index: int`,
    `state: Literal["pending", "written", "verified", "restored", "unrecoverable"]`.
- Tests: `packages/ai-parrot-tools/tests/tool_optimizations/test_patches.py`
  (spec §4 names `test_apply.py` for M5 — that file is TASK-3086's;
  parser/store tests live in `test_patches.py`).

**NOT in scope**: filesystem mutation of targets, locks, recovery logic
(TASK-3086); model prompts (TASK-3085).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/patches.py` | CREATE | Diff grammar, in-memory apply, artifact store, journal models |
| `packages/ai-parrot-tools/tests/tool_optimizations/test_patches.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.tool_optimizations.models import PatchManifest, WriterLimits         # TASK-3079
from parrot_tools.tool_optimizations.policy import compact_json                        # TASK-3079
import hashlib, os, re, stat, tempfile, uuid
from pydantic import BaseModel, ConfigDict, Field
```

### Existing Signatures to Use
```python
# TASK-3079 models.py
class PatchManifest(BaseModel):   # artifact_id, task_id, packet_sha256, patch_sha256, before_hashes: dict[str, str|None],
                                  # after_hashes: dict[str, str], allowed_paths, configured_model, actual_model, used_fallback,
                                  # usage: dict[str, int|None], repairs, elapsed_ms, validation_state, created_at
# .gitignore:283  →  "artifacts/" is ignored (verified with `git check-ignore -v`), so artifact dirs never pollute git status.
```

### Does NOT Exist
- ~~`git apply` / `patch(1)` subprocess~~ — forbidden here (Decision 1); tests assert no subprocess import usage.
- ~~`difflib.restore` / `unidiff` / `whatthepatch`~~ — `unidiff` is not a dependency; `difflib` cannot apply patches. Write the applier.
- ~~Fuzz factor / offset search~~ — exact match only; a mismatch is a rejection returned to the thinking model.
- ~~Rename/delete/mode/binary support~~ — v1 rejects them (spec item 4).
- ~~`artifacts/tool-optimizations/` being tracked~~ — it is gitignored; do not `git add -f` it.

---

## Implementation Notes

### Pattern to Follow
```python
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

def apply_file_patch(before: bytes | None, patch: FilePatch) -> bytes:
    src = (before or b"").decode("utf-8").splitlines(keepends=True)   # strict decode; caller guarantees text
    out: list[str] = []; cursor = 0                                    # 0-based index into src
    for hi, h in enumerate(patch.hunks):
        target = h.old_start - 1 if h.old_count else h.old_start      # "@@ -0,0 +1,N @@" for creates
        if target < cursor: raise PatchError("malformed_hunk", {...})
        out.extend(src[cursor:target]); cursor = target
        for ln in h.lines:
            tag, body = ln[0], ln[1:]
            if tag in " -":
                if cursor >= len(src) or src[cursor].rstrip("\r\n") != body:
                    raise PatchError("context_mismatch", {"path": patch.path, "hunk_index": hi, "line_no": cursor + 1,
                                                          "expected": body, "actual": src[cursor].rstrip("\r\n") if cursor < len(src) else None})
                if tag == " ": out.append(src[cursor])
                cursor += 1
            elif tag == "+":
                out.append(body + _newline_for(src))
    out.extend(src[cursor:])
    return "".join(out).encode("utf-8")
```

```python
# Atomic artifact publish
tmp = self.root / f".tmp-{artifact_id}"; tmp.mkdir(mode=0o700, parents=True)
for name, text in (("manifest.json", ...), ("patch.diff", patch_text), ("packet.json", packet_json)):
    fd = os.open(tmp / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh: fh.write(text); fh.flush(); os.fsync(fh.fileno())
os.rename(tmp, self.root / artifact_id)
```

### Key Constraints
- Normalised patch text is what gets hashed; `writer_apply` receives that
  hash as `reviewed_sha256` (TASK-3086), so `normalize_patch` must be
  idempotent (`normalize(normalize(x)) == normalize(x)`).
- Reject before doing work: header/path/scope checks precede any hunk
  application.
- `max_bytes` (`WriterLimits.max_patch_bytes`) enforced on the raw text.
- Never write outside `artifacts/tool-optimizations/`; the store must
  refuse an `artifact_id` that fails `^[0-9a-f]{32}$`.
- No logging of patch contents above DEBUG.

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/repo/confinement.py:63-90` — containment semantics to mirror for `path_escape`.

---

## Acceptance Criteria

- [ ] Parses a valid two-file patch (one create with `--- /dev/null`, one modify) and applies it byte-exact against fixtures, including CRLF sources and missing final newline (`\ No newline at end of file`).
- [ ] Each rejection code in Scope has a test: fenced prose, absolute path, `../x`, duplicate file, deletion, rename, mode change, binary, submodule, malformed hunk counts, context mismatch (with `expected`/`actual` in details), create without `/dev/null`, out-of-scope path, too large.
- [ ] `normalize_patch` is idempotent; hash of normalized text is stable.
- [ ] `ArtifactStore.write_generation` creates `0o700` dir / `0o600` files; a crash simulated between temp-write and rename (monkeypatch `os.rename`) leaves no final dir; `load` on a hand-edited `patch.diff` → `artifact_tampered`.
- [ ] Journal round-trip; `save_before(None)` and `load_before` returns `None`.
- [ ] Module never imports `subprocess`/`asyncio.subprocess` (test greps source).
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/tool_optimizations/test_patches.py -v`; lint clean; log in `artifacts/logs/TASK-3084-pytest.log`.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/tool_optimizations/test_patches.py
import hashlib, os, stat
import pytest
from parrot_tools.tool_optimizations.patches import ArtifactStore, PatchError, apply_in_memory, normalize_patch, parse_patch, check_scope
from parrot_tools.tool_optimizations.models import PatchManifest

MODIFY = """--- a/pkg/__init__.py
+++ b/pkg/__init__.py
@@ -1,2 +1,3 @@
 from .a import a
+from .greeter import greet
 __all__ = ["a"]
"""
CREATE = """--- /dev/null
+++ b/pkg/greeter.py
@@ -0,0 +1,2 @@
+def greet(name: str) -> str:
+    return f"hello {name}"
"""

def test_parse_and_apply_create_and_modify():
    patches = parse_patch(normalize_patch(MODIFY + CREATE), max_bytes=128_000)
    check_scope(patches, {"pkg/__init__.py": "modify", "pkg/greeter.py": "create"})
    after = apply_in_memory(patches, {"pkg/__init__.py": b'from .a import a\n__all__ = ["a"]\n', "pkg/greeter.py": None})
    assert after["pkg/__init__.py"] == b'from .a import a\nfrom .greeter import greet\n__all__ = ["a"]\n'
    assert after["pkg/greeter.py"].endswith(b'return f"hello {name}"\n')

def test_crlf_preserved():
    patches = parse_patch(normalize_patch(MODIFY), max_bytes=128_000)
    after = apply_in_memory(patches, {"pkg/__init__.py": b'from .a import a\r\n__all__ = ["a"]\r\n'})
    assert after["pkg/__init__.py"] == b'from .a import a\r\nfrom .greeter import greet\r\n__all__ = ["a"]\r\n'

@pytest.mark.parametrize("text,code", [
    ("```diff\n" + MODIFY + "```\n", "not_a_patch"),
    (MODIFY.replace("b/pkg/__init__.py", "b//etc/passwd"), "absolute_path"),
    (MODIFY.replace("b/pkg/__init__.py", "b/../x.py"), "path_escape"),
    (MODIFY + MODIFY, "duplicate_target"),
    (MODIFY.replace("+++ b/pkg/__init__.py", "+++ /dev/null"), "deletion_rejected"),
    ("diff --git a/x b/y\nrename from x\nrename to y\n", "rename_rejected"),
    ("diff --git a/x b/x\nold mode 100644\nnew mode 100755\n" + MODIFY, "mode_change_rejected"),
    ("diff --git a/x b/x\nGIT binary patch\n", "binary_rejected"),
    ("diff --git a/sub b/sub\n--- a/sub\n+++ b/sub\n@@ -1 +1 @@\n-Subproject commit a\n+Subproject commit b\n", "submodule_rejected"),
    (MODIFY.replace("@@ -1,2 +1,3 @@", "@@ -1,9 +1,3 @@"), "malformed_hunk"),
])
def test_rejections(text, code):
    with pytest.raises(PatchError) as ei:
        parse_patch(normalize_patch(text), max_bytes=128_000)
    assert ei.value.code == code

def test_context_mismatch_details():
    patches = parse_patch(normalize_patch(MODIFY), max_bytes=128_000)
    with pytest.raises(PatchError) as ei:
        apply_in_memory(patches, {"pkg/__init__.py": b"something else\n"})
    assert ei.value.code == "context_mismatch" and ei.value.details["line_no"] == 1

def test_store_permissions_and_tamper(tmp_path):
    store = ArtifactStore(tmp_path); aid = store.new_id()
    manifest = PatchManifest(artifact_id=aid, task_id="TASK-1", packet_sha256=hashlib.sha256(b"{}").hexdigest(),
                             patch_sha256=hashlib.sha256(MODIFY.encode()).hexdigest(), before_hashes={}, after_hashes={},
                             allowed_paths=["pkg/__init__.py"], configured_model="m", actual_model="m", used_fallback=False,
                             usage={"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}, repairs=0,
                             elapsed_ms=1, validation_state="validated", created_at="2026-01-01T00:00:00Z")
    d = store.write_generation(aid, manifest=manifest, patch_text=MODIFY, packet_json="{}")
    assert stat.S_IMODE(d.stat().st_mode) == 0o700 and stat.S_IMODE((d / "patch.diff").stat().st_mode) == 0o600
    (d / "patch.diff").write_text(MODIFY + "+x\n")
    with pytest.raises(PatchError) as ei: store.load(aid)
    assert ei.value.code == "artifact_tampered"

def test_no_subprocess_in_module():
    import inspect, parrot_tools.tool_optimizations.patches as m
    assert "subprocess" not in inspect.getsource(m)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-3079 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/tool-optimizations.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-3084-patch-validation-artifact-store.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
