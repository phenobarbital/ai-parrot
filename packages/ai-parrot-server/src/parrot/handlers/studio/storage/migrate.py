"""Studio schema migrations: file format, checksum and listing (spec §2.12). Never imported at startup."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

STUDIO_SCHEMA_REQUIRED: int = 5
STUDIO_SCHEMA_REQUIRED_PHASE2: int = 8
STUDIO_MIGRATION_LOCK_KEY: int = 4715391001
STUDIO_MIN_SERVER_VERSION_NUM: int = 140000
LEDGER_MARKER: str = "-- @studio-ledger"
MIGRATIONS_PACKAGE: str = "parrot.handlers.studio.storage.migrations"
MANIFEST_NAME: str = "MANIFEST.json"

_MARKER_RE = re.compile(b"^" + re.escape(LEDGER_MARKER.encode()) + b"$", re.MULTILINE)
_CHECKSUM_LITERAL = re.compile(rb"'[0-9a-f]{64}'")


@dataclass(frozen=True)
class StudioMigration:
    """One migration file: body, trailer and the body's sha256."""

    version: int
    name: str
    body: bytes
    trailer: bytes
    checksum: str


def split_body(raw: bytes) -> tuple[bytes, bytes]:
    """Split a file into (body, trailer).

    Body = bytes up to and including the LF before the marker line. Raises ``ValueError``
    when the marker line is absent, repeated, or the file starts with it.
    """
    positions = [m.start() for m in _MARKER_RE.finditer(raw)]
    if len(positions) != 1:
        raise ValueError(f"expected exactly one {LEDGER_MARKER!r} line, found {len(positions)}")
    if positions[0] == 0:
        raise ValueError("ledger marker at start of file: empty body")
    return raw[: positions[0]], raw[positions[0]:]


def body_checksum(raw: bytes) -> str:
    """sha256 hex of the body of a migration file (the trailer is not hashed)."""
    return hashlib.sha256(split_body(raw)[0]).hexdigest()


def _parse_name(filename: str) -> tuple[int, str]:
    """'0002_ai_agents.sql' -> (2, '0002_ai_agents')."""
    stem = filename.removesuffix(".sql")
    return int(stem.split("_", 1)[0]), stem


def _load_manifest(text: str) -> dict:
    manifest = json.loads(text)
    if not isinstance(manifest.get("migrations"), list):
        raise ValueError("MANIFEST.json has no 'migrations' list")
    return manifest


def _validate(migs: list[StudioMigration], manifest: dict) -> None:
    """Contiguity from 1, presence in the manifest and checksum equality."""
    if [m.version for m in migs] != list(range(1, len(migs) + 1)):
        raise ValueError(f"migration versions are not contiguous from 1: {[m.version for m in migs]}")
    expected = {e["version"]: e for e in manifest["migrations"]}
    for mig in migs:
        entry = expected.get(mig.version)
        if entry is None:
            raise ValueError(f"version {mig.version} missing from {MANIFEST_NAME}")
        if entry["sha256"] != mig.checksum or entry["name"] != mig.name:
            raise ValueError(f"{mig.name}: checksum/name differs from {MANIFEST_NAME}")
    missing = set(expected) - {m.version for m in migs}
    if missing:
        raise ValueError(f"manifest versions without a file: {sorted(missing)}")


def _read_dir(files: list[tuple[str, bytes]]) -> list[StudioMigration]:
    migs = []
    for filename, raw in files:
        version, name = _parse_name(filename)
        body, trailer = split_body(raw)
        migs.append(StudioMigration(version, name, body, trailer, hashlib.sha256(body).hexdigest()))
    return sorted(migs, key=lambda m: m.version)


def list_migrations() -> list[StudioMigration]:
    """Package data via importlib.resources, sorted; validated against MANIFEST.json."""
    root = resources.files(MIGRATIONS_PACKAGE)
    files = [(e.name, e.read_bytes()) for e in root.iterdir() if e.name.endswith(".sql")]
    migs = _read_dir(files)
    _validate(migs, _load_manifest((root / MANIFEST_NAME).read_text(encoding="utf-8")))
    return migs


def stamp_migrations(directory: Path | None = None) -> None:
    """Release tooling: rewrite every trailer hex and MANIFEST.json from the bodies (repository only)."""
    directory = directory or Path(__file__).parent / "migrations"
    manifest_path = directory / MANIFEST_NAME
    old = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    entries = []
    for path in sorted(directory.glob("*.sql")):
        raw = path.read_bytes()
        body, trailer = split_body(raw)
        digest = hashlib.sha256(body).hexdigest()
        new_trailer, count = _CHECKSUM_LITERAL.subn(f"'{digest}'".encode(), trailer)
        if count != 1:
            raise ValueError(f"{path.name}: trailer must carry exactly one checksum literal")
        path.write_bytes(body + new_trailer)
        version, name = _parse_name(path.name)
        entries.append({"version": version, "name": name, "sha256": digest})
    manifest = {
        "required": old.get("required", STUDIO_SCHEMA_REQUIRED),
        "required_phase2": old.get("required_phase2", STUDIO_SCHEMA_REQUIRED_PHASE2),
        "migrations": entries,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
