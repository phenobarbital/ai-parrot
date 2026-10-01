"""Studio schema migrations: file format, checksum and listing (spec §2.12). Never imported at startup."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import re
import sys
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Mapping

logger = logging.getLogger("Parrot.AgentStudio.Storage")

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


_SKILLS_NAME_UNIQUE_SQL = (
    "SELECT count(*) AS n FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid "
    "AND a.attnum = i.indkey[0] WHERE i.indrelid = to_regclass('navigator.ai_skills_catalog') "
    "AND i.indisunique AND i.indnatts = 1 AND i.indpred IS NULL AND a.attname = 'name'"
)


@dataclass(frozen=True)
class LedgerState:
    """What the (read-only) probe found: ledger presence, applied versions and server version."""

    present: bool
    applied: dict[int, str]
    server_version_num: int
    skills_name_unique_index: bool = False

    def complete_for(self, required: int, manifest: Mapping[int, str]) -> bool:
        """True iff the ledger is present and every version 1..required is there with the manifest checksum."""
        return self.present and not self.problems(required, manifest)

    def problems(self, required: int, manifest: Mapping[int, str]) -> list[str]:
        """Human-readable problems: 'server < 14', 'missing N', 'drift N', 'unknown N'."""
        found: list[str] = []
        if self.server_version_num < STUDIO_MIN_SERVER_VERSION_NUM:
            found.append(f"server < 14 (server_version_num={self.server_version_num})")
        found.extend(f"missing {v}" for v in range(1, required + 1) if v not in self.applied)
        found.extend(
            f"drift {v}" for v, digest in sorted(self.applied.items()) if v in manifest and manifest[v] != digest
        )
        found.extend(f"unknown {v}" for v in sorted(self.applied) if v not in manifest)
        return found

    def warnings(self) -> list[str]:
        """Non-fatal findings (do not affect ``complete_for``)."""
        if self.skills_name_unique_index:
            return [
                "host-created unique index on navigator.ai_skills_catalog(name) alone: "
                "per-tenant skill names will conflict across tenants until it is dropped"
            ]
        return []


def _first_value(row: Any) -> Any:
    """First column of an asyncdb/asyncpg row (Record, mapping or sequence)."""
    if hasattr(row, "values"):
        return next(iter(row.values()))
    return row[0]


async def read_ledger(conn: Any) -> LedgerState:
    """SHOW server_version_num; to_regclass(...); SELECT version, checksum ... Never DDL."""
    num = int(_first_value(await conn.fetch_one("SHOW server_version_num")))
    reg = _first_value(await conn.fetch_one("SELECT to_regclass('navigator.ai_studio_migrations')"))
    if reg is None:
        return LedgerState(False, {}, num)
    rows = await conn.fetch_all("SELECT version, checksum FROM navigator.ai_studio_migrations ORDER BY version")
    applied = {int(r["version"]): r["checksum"] for r in (rows or [])}
    dup = await conn.fetch_one(_SKILLS_NAME_UNIQUE_SQL)
    return LedgerState(True, applied, num, bool(dup and _first_value(dup)))


async def apply_studio_migrations(pool: Any, *, dry_run: bool = False) -> list[int]:
    """Per pending file: studio_transaction → body (advisory lock first) → re-read ledger → skip if
    recorded → trailer → commit. Returns versions applied (or pending, when ``dry_run``). Never called at startup."""
    from .repositories import _exec, studio_transaction   # local: repositories imports models only

    async with pool.acquire() as conn:
        state = await read_ledger(conn)
    if state.server_version_num < STUDIO_MIN_SERVER_VERSION_NUM:
        raise RuntimeError(
            f"PostgreSQL >= {STUDIO_MIN_SERVER_VERSION_NUM // 10000} required "
            f"(server_version_num={state.server_version_num}, minimum {STUDIO_MIN_SERVER_VERSION_NUM})"
        )
    pending = [m for m in list_migrations() if m.version not in state.applied]
    if dry_run:
        return [m.version for m in pending]
    applied: list[int] = []
    for mig in pending:
        async with studio_transaction(pool) as conn:
            await _exec(conn, mig.body.decode("utf-8"))
            if mig.version in (await read_ledger(conn)).applied:
                logger.info("studio migration %s already recorded by another runner", mig.name)
                continue
            await _exec(conn, mig.trailer.decode("utf-8"))
            applied.append(mig.version)
            logger.info("applied studio migration %s", mig.name)
    return applied


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="parrot-studio-migrate", description="Apply Agent Studio schema migrations.")
    parser.add_argument("--dsn", help="PostgreSQL DSN (required except with --stamp)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="list pending versions, change nothing")
    mode.add_argument("--verify", action="store_true", help="report missing/drifted/unknown versions; exit 1 on any")
    mode.add_argument("--print", dest="print_", action="store_true", help="emit pending files (body + trailer)")
    mode.add_argument("--stamp", action="store_true", help="release tooling: rewrite trailers and MANIFEST.json")
    return parser


async def _run(args: argparse.Namespace) -> int:
    from asyncdb import AsyncPool

    pool = AsyncPool("pg", dsn=args.dsn)
    await pool.connect()
    try:
        if args.verify:
            return await _verify(pool)
        if args.print_:
            return await _print_pending(pool)
        versions = await apply_studio_migrations(pool, dry_run=args.dry_run)
        label = "pending" if args.dry_run else "applied"
        print(f"{label}: {versions}")
        return 0
    finally:
        await pool.close()


async def _verify(pool: Any) -> int:
    manifest = {m.version: m.checksum for m in list_migrations()}
    async with pool.acquire() as conn:
        state = await read_ledger(conn)
    problems = state.problems(STUDIO_SCHEMA_REQUIRED, manifest)
    if not state.present:
        problems.insert(0, "ledger absent")
    for line in state.warnings():
        print(f"warning: {line}")
    for line in problems:
        print(f"problem: {line}")
    return 1 if problems else 0


async def _print_pending(pool: Any) -> int:
    async with pool.acquire() as conn:
        state = await read_ledger(conn)
    for mig in list_migrations():
        if mig.version not in state.applied:
            sys.stdout.write(mig.body.decode() + mig.trailer.decode())
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI: --dsn, --dry-run, --verify, --print, --stamp."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.stamp:
        stamp_migrations()
        print("stamped")
        return 0
    if not args.dsn:
        parser.error("--dsn is required")
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
