"""FEAT-621 M1 — migration file format and manifest (AC1, AC2; CI gate)."""

import re
from pathlib import Path

import pytest

from parrot.handlers.studio.storage import migrate
from parrot.handlers.studio.storage.migrate import (
    LEDGER_MARKER,
    STUDIO_SCHEMA_REQUIRED,
    body_checksum,
    list_migrations,
    split_body,
    stamp_migrations,
)

MIG_DIR = Path(migrate.__file__).parent / "migrations"


def test_checksum_body_split() -> None:
    raw = b"SELECT 1;\n" + LEDGER_MARKER.encode() + b"\nINSERT ... '00';\n"
    body, trailer = split_body(raw)
    assert body == b"SELECT 1;\n"
    assert trailer.startswith(LEDGER_MARKER.encode())
    assert body_checksum(raw) == body_checksum(raw.replace(b"'00'", b"'ff'"))
    assert body_checksum(raw) != body_checksum(raw.replace(b"SELECT 1", b"SELECT 2"))
    with pytest.raises(ValueError):
        split_body(b"SELECT 1;\n")
    with pytest.raises(ValueError):
        split_body(raw + LEDGER_MARKER.encode() + b"\n")
    with pytest.raises(ValueError):
        split_body(LEDGER_MARKER.encode() + b"\nINSERT;\n")
    # A marker embedded in a longer line is not the marker line.
    assert split_body(b"-- x -- @studio-ledger\n" + raw)[0] == b"-- x -- @studio-ledger\nSELECT 1;\n"


def _first_statement(body: str) -> str:
    lines = [ln for ln in body.splitlines() if ln.strip() and not ln.lstrip().startswith("--")]
    return lines[0].split("--")[0].strip()


def test_migration_files_match_manifest() -> None:
    migs = list_migrations()
    assert [m.version for m in migs] == list(range(1, len(migs) + 1))
    assert len(migs) >= STUDIO_SCHEMA_REQUIRED
    for mig in migs:
        trailer = mig.trailer.decode()
        hexes = re.findall(r"'([0-9a-f]{64})'", trailer)
        assert hexes == [mig.checksum], mig.name
        assert f"VALUES ({mig.version}, '{mig.name}'," in trailer
        assert _first_statement(mig.body.decode()) == "SELECT pg_advisory_xact_lock(4715391001);"
        assert b"\r" not in mig.body and not mig.body.startswith(b"\xef\xbb\xbf")
        assert not re.search(r"\b(BEGIN|COMMIT|ROLLBACK)\s*;", mig.body.decode())


def test_unstamped_body_change_is_detected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for f in MIG_DIR.iterdir():
        if f.suffix in (".sql", ".json"):
            (tmp_path / f.name).write_bytes(f.read_bytes())
    target = tmp_path / "0002_ai_agents.sql"
    target.write_bytes(target.read_bytes().replace(b"agent_id ", b"agent_idx", 1))
    manifest = (tmp_path / "MANIFEST.json").read_text()
    stamp_migrations(tmp_path)
    assert (tmp_path / "MANIFEST.json").read_text() != manifest  # stamping repairs drift
    stamped = target.read_bytes()
    assert body_checksum(stamped) in stamped.decode()
