"""Drift guard: the operator doc must not describe values the code does not have."""
from pathlib import Path

from parrot.interfaces.file import session

DOC = Path(__file__).resolve().parents[4] / "docs" / "files" / "session-file-store.md"


def _text() -> str:
    return DOC.read_text(encoding="utf-8")


class TestSessionStoreDocs:
    def test_doc_exists(self):
        assert DOC.is_file()

    def test_documented_warn_threshold_matches_code(self):
        """The documented SESSION_FILES_WARN_BYTES default matches session.py."""
        text = _text()
        assert "SESSION_FILES_WARN_BYTES" in text
        assert str(session.SESSION_FILES_WARN_BYTES) in text
        assert f"{session.SESSION_FILES_WARN_BYTES // (1024 * 1024)} MiB" in text

    def test_documented_suffixes_match_code(self):
        text = _text()
        assert f"<file_id>{session.BLOB_SUFFIX}" in text
        assert f"<file_id>{session.MANIFEST_SUFFIX}" in text

    def test_doc_promises_no_automatic_deletion(self):
        """Spec section 1 Non-Goals: nothing sweeps, and the doc must say so."""
        text = _text().lower()
        assert "nothing deletes files automatically" in text
        assert "no ttl" in text

    def test_doc_mentions_no_nonexistent_command(self):
        """Guard against documenting a cleanup CLI that does not exist."""
        assert "parrot files cleanup" not in _text()
