"""Unit tests for patch parsing, application and artifact storage (TASK-3084)."""

import hashlib
import os
import stat

import pytest

from parrot_tools.tool_optimizations.models import PatchManifest
from parrot_tools.tool_optimizations.patches import (
    ApplyJournal,
    ArtifactStore,
    JournalEntry,
    PatchError,
    apply_in_memory,
    check_scope,
    normalize_patch,
    parse_patch,
)

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

BASE_INIT = b'from .a import a\n__all__ = ["a"]\n'


def _manifest(artifact_id: str, patch_text: str, packet_json: str = "{}") -> PatchManifest:
    """Build a manifest whose hashes match the supplied artifact contents."""
    return PatchManifest(
        artifact_id=artifact_id,
        task_id="TASK-1000",
        task_path="sdd/tasks/active/TASK-1000-example.md",
        packet_sha256=hashlib.sha256(packet_json.encode()).hexdigest(),
        patch_sha256=hashlib.sha256(patch_text.encode()).hexdigest(),
        before_hashes={"pkg/__init__.py": hashlib.sha256(BASE_INIT).hexdigest()},
        after_hashes={"pkg/__init__.py": hashlib.sha256(b"x").hexdigest()},
        allowed_paths=["pkg/__init__.py"],
        configured_model="bedrock-converse:qwen3-coder-480b-a35b",
        actual_model="bedrock-converse:qwen3-coder-480b-a35b",
        used_fallback=False,
        usage={"prompt_tokens": None, "completion_tokens": None, "total_tokens": None},
        repairs=0,
        elapsed_ms=1,
        validation_state="validated",
        created_at="2026-01-01T00:00:00Z",
    )


# --------------------------------------------------------------------------- #
# Parse + apply
# --------------------------------------------------------------------------- #
def test_parse_and_apply_create_and_modify():
    """A two-file patch applies byte-exactly against its expected sources."""
    patches = parse_patch(normalize_patch(MODIFY + CREATE), max_bytes=128_000)
    check_scope(patches, {"pkg/__init__.py": "modify", "pkg/greeter.py": "create"})

    after = apply_in_memory(patches, {"pkg/__init__.py": BASE_INIT, "pkg/greeter.py": None})
    assert after["pkg/__init__.py"] == b'from .a import a\nfrom .greeter import greet\n__all__ = ["a"]\n'
    assert after["pkg/greeter.py"].endswith(b'return f"hello {name}"\n')
    assert len(after) == 2


def test_crlf_preserved():
    """Added lines adopt the file's CRLF convention; existing lines are untouched."""
    patches = parse_patch(normalize_patch(MODIFY), max_bytes=128_000)
    after = apply_in_memory(patches, {"pkg/__init__.py": b'from .a import a\r\n__all__ = ["a"]\r\n'})
    assert after["pkg/__init__.py"] == b'from .a import a\r\nfrom .greeter import greet\r\n__all__ = ["a"]\r\n'


def test_missing_final_newline_is_preserved():
    """`\\ No newline at end of file` survives the round trip."""
    patch_text = (
        "--- a/f.txt\n"
        "+++ b/f.txt\n"
        "@@ -1,2 +1,2 @@\n"
        " one\n"
        "-two\n"
        "\\ No newline at end of file\n"
        "+three\n"
        "\\ No newline at end of file\n"
    )
    patches = parse_patch(normalize_patch(patch_text), max_bytes=128_000)
    after = apply_in_memory(patches, {"f.txt": b"one\ntwo"})
    assert after["f.txt"] == b"one\nthree"


def test_multiple_hunks_in_one_file():
    """Hunks apply in order with untouched regions passed through verbatim."""
    source = b"".join(f"line{i}\n".encode() for i in range(1, 11))
    patch_text = (
        "--- a/f.txt\n"
        "+++ b/f.txt\n"
        "@@ -1,2 +1,3 @@\n"
        " line1\n"
        "+inserted-a\n"
        " line2\n"
        "@@ -9,2 +10,3 @@\n"
        " line9\n"
        "+inserted-b\n"
        " line10\n"
    )
    patches = parse_patch(normalize_patch(patch_text), max_bytes=128_000)
    after = apply_in_memory(patches, {"f.txt": source})
    assert b"line1\ninserted-a\nline2\nline3\n" in after["f.txt"]
    assert after["f.txt"].endswith(b"line9\ninserted-b\nline10\n")


# --------------------------------------------------------------------------- #
# Rejections
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "text,code",
    [
        ("```diff\n" + MODIFY + "```\n", "not_a_patch"),
        ("Here is the patch you asked for:\n" + MODIFY, "not_a_patch"),
        (MODIFY.replace("b/pkg/__init__.py", "b//etc/passwd"), "absolute_path"),
        (MODIFY.replace("b/pkg/__init__.py", "b/../x.py"), "path_escape"),
        (MODIFY + MODIFY, "duplicate_target"),
        (MODIFY.replace("+++ b/pkg/__init__.py", "+++ /dev/null"), "deletion_rejected"),
        ("diff --git a/x b/y\nrename from x\nrename to y\n", "rename_rejected"),
        ("diff --git a/x b/x\nold mode 100644\nnew mode 100755\n" + MODIFY, "mode_change_rejected"),
        ("diff --git a/x b/x\nGIT binary patch\n", "binary_rejected"),
        (
            "diff --git a/sub b/sub\n--- a/sub\n+++ b/sub\n@@ -1 +1 @@\n-Subproject commit a\n+Subproject commit b\n",
            "submodule_rejected",
        ),
        (MODIFY.replace("@@ -1,2 +1,3 @@", "@@ -1,9 +1,3 @@"), "malformed_hunk"),
        ("--- a/x\n+++ b/x\n@@ nonsense @@\n one\n", "malformed_hunk"),
        ("diff --git a/x b/x\ndeleted file mode 100644\n" + MODIFY, "deletion_rejected"),
        ("diff --git a/x b/x\nnew file mode 120000\n" + CREATE, "mode_change_rejected"),
        ("--- a/x\n+++ b/x\n", "malformed_hunk"),
    ],
)
def test_rejections(text, code):
    """Every unsupported or malformed diff feature has its own rejection code."""
    with pytest.raises(PatchError) as info:
        parse_patch(normalize_patch(text), max_bytes=128_000)
    assert info.value.code == code


def test_patch_too_large():
    """The patch byte budget is enforced on the raw text."""
    with pytest.raises(PatchError) as info:
        parse_patch(normalize_patch(MODIFY), max_bytes=10)
    assert info.value.code == "patch_too_large"


def test_scope_violations():
    """Paths and create/modify semantics must match the approved packet."""
    modify_patches = parse_patch(normalize_patch(MODIFY), max_bytes=128_000)
    with pytest.raises(PatchError) as info:
        check_scope(modify_patches, {"other.py": "modify"})
    assert info.value.code == "path_outside_scope"

    with pytest.raises(PatchError) as info:
        check_scope(modify_patches, {"pkg/__init__.py": "create"})
    assert info.value.code == "create_needs_dev_null"

    create_patches = parse_patch(normalize_patch(CREATE), max_bytes=128_000)
    with pytest.raises(PatchError) as info:
        check_scope(create_patches, {"pkg/greeter.py": "modify"})
    assert info.value.code == "path_outside_scope"


def test_context_mismatch_details():
    """A mismatch names the file, hunk, line and both sides — no fuzzy match."""
    patches = parse_patch(normalize_patch(MODIFY), max_bytes=128_000)
    with pytest.raises(PatchError) as info:
        apply_in_memory(patches, {"pkg/__init__.py": b"something else\n"})
    assert info.value.code == "context_mismatch"
    assert info.value.details["line_no"] == 1
    assert info.value.details["expected"] == "from .a import a"
    assert info.value.details["actual"] == "something else"
    assert info.value.details["path"] == "pkg/__init__.py"


def test_modify_of_missing_file_is_a_mismatch():
    """A modify whose target vanished is refused, not treated as a create."""
    patches = parse_patch(normalize_patch(MODIFY), max_bytes=128_000)
    with pytest.raises(PatchError) as info:
        apply_in_memory(patches, {"pkg/__init__.py": None})
    assert info.value.code == "context_mismatch"


def test_no_fuzz_offset_search():
    """A correct patch applied at the wrong offset is rejected, not relocated."""
    shifted = b"# header added later\n" + BASE_INIT
    patches = parse_patch(normalize_patch(MODIFY), max_bytes=128_000)
    with pytest.raises(PatchError) as info:
        apply_in_memory(patches, {"pkg/__init__.py": shifted})
    assert info.value.code == "context_mismatch"


# --------------------------------------------------------------------------- #
# Normalization
# --------------------------------------------------------------------------- #
def test_normalize_is_idempotent_and_hash_is_stable():
    """The stored/hashed text is canonical, so a review hash cannot drift."""
    once = normalize_patch(MODIFY + "\n\n   \n")
    twice = normalize_patch(once)
    assert once == twice
    assert once.endswith("\n")
    assert hashlib.sha256(once.encode()).hexdigest() == hashlib.sha256(twice.encode()).hexdigest()
    assert normalize_patch("\n\n" + MODIFY) == normalize_patch(MODIFY)


# --------------------------------------------------------------------------- #
# Artifact store
# --------------------------------------------------------------------------- #
def test_store_permissions_and_tamper(tmp_path):
    """Artifacts are private, and an edited artifact is detected on load."""
    store = ArtifactStore(tmp_path)
    artifact_id = store.new_id()
    manifest = _manifest(artifact_id, MODIFY)

    directory = store.write_generation(artifact_id, manifest=manifest, patch_text=MODIFY, packet_json="{}")
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE((directory / "patch.diff").stat().st_mode) == 0o600
    assert stat.S_IMODE((directory / "manifest.json").stat().st_mode) == 0o600

    loaded_manifest, patch_text, packet_json = store.load(artifact_id)
    assert loaded_manifest.artifact_id == artifact_id
    assert patch_text == MODIFY
    assert packet_json == "{}"

    (directory / "patch.diff").write_text(MODIFY + "+x\n")
    with pytest.raises(PatchError) as info:
        store.load(artifact_id)
    assert info.value.code == "artifact_tampered"


def test_store_detects_tampered_packet(tmp_path):
    """The packet is hash-checked too, not just the patch."""
    store = ArtifactStore(tmp_path)
    artifact_id = store.new_id()
    directory = store.write_generation(
        artifact_id, manifest=_manifest(artifact_id, MODIFY), patch_text=MODIFY, packet_json="{}"
    )
    (directory / "packet.json").write_text('{"changed": true}')
    with pytest.raises(PatchError) as info:
        store.load(artifact_id)
    assert info.value.code == "artifact_tampered"


def test_crash_between_write_and_publish_leaves_no_artifact(tmp_path, monkeypatch):
    """A crash before the rename can never publish a half-written artifact."""
    store = ArtifactStore(tmp_path)
    artifact_id = store.new_id()

    def _boom(*args, **kwargs):
        raise OSError("simulated crash")

    monkeypatch.setattr(os, "rename", _boom)
    with pytest.raises(OSError):
        store.write_generation(
            artifact_id, manifest=_manifest(artifact_id, MODIFY), patch_text=MODIFY, packet_json="{}"
        )

    monkeypatch.undo()
    assert not (store.root / artifact_id).exists()
    with pytest.raises(PatchError) as info:
        store.load(artifact_id)
    assert info.value.code == "artifact_not_found"


def test_store_rejects_invalid_artifact_id(tmp_path):
    """Only opaque 32-hex ids are accepted, so no path can be smuggled in."""
    store = ArtifactStore(tmp_path)
    for bad in ("../escape", "not-hex", "", "A" * 32):
        with pytest.raises(PatchError) as info:
            store.load(bad)
        assert info.value.code == "invalid_artifact_id"


def test_journal_and_before_roundtrip(tmp_path):
    """The recovery journal and saved originals survive a round trip."""
    store = ArtifactStore(tmp_path)
    artifact_id = store.new_id()
    store.write_generation(artifact_id, manifest=_manifest(artifact_id, MODIFY), patch_text=MODIFY, packet_json="{}")
    assert store.read_journal(artifact_id) is None

    journal = ApplyJournal(
        artifact_id=artifact_id,
        started_at="2026-01-01T00:00:00Z",
        entries=[
            JournalEntry(path="pkg/__init__.py", before_sha256="a" * 64, after_sha256="b" * 64, before_index=0),
            JournalEntry(path="pkg/greeter.py", before_sha256=None, after_sha256="c" * 64, before_index=1),
        ],
        state="pending",
    )
    store.write_journal(artifact_id, journal)
    restored = store.read_journal(artifact_id)
    assert restored == journal

    store.save_before(artifact_id, 0, BASE_INIT)
    store.save_before(artifact_id, 1, None)
    assert store.load_before(artifact_id, 0) == BASE_INIT
    assert store.load_before(artifact_id, 1) is None

    journal.state = "applied"
    store.write_journal(artifact_id, journal)
    assert store.read_journal(artifact_id).state == "applied"


def test_no_external_command_in_module():
    """Patches are applied in pure Python; no external diff tool is invoked."""
    import inspect

    import parrot_tools.tool_optimizations.patches as module

    source = inspect.getsource(module)
    assert "sub" + "process" not in source
    assert "git apply" not in source
