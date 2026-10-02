"""Row-level migration runner for ``troc.planograms_configurations`` (FEAT-574, FEAT-612).

Drives the deployment sequence of ``docs/pipelines/planogram-cycle-migration.md`` over every
active row: export originals, convert each one into a reviewable candidate, render the approved
candidates as one guarded SQL transaction, and apply it. ``migration.py`` stays offline and
read-only; this module is the only place that writes, and only through ``alter`` / ``apply`` with
an explicit ``--yes``.

Work directory layout::

    <dir>/original/<config_name>.json     exported rows, never rewritten
    <dir>/candidates/<config_name>.json   proposals edited by the reviewer
    <dir>/apply.sql                       rendered from approved candidates
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urlsplit

from parrot_pipelines.planogram.migration import (
    MIGRATED_TYPES,
    _decode,
    check_row,
    convert_config,
    preflight,
)

logger = logging.getLogger(__name__)

TABLE = "troc.planograms_configurations"
_EXPORT_ACTIVE_SQL = f"SELECT * FROM {TABLE} WHERE is_active = TRUE ORDER BY config_name"
_EXPORT_ALL_SQL = f"SELECT * FROM {TABLE} ORDER BY config_name"
_ALTER_SQL_PATH = Path(__file__).resolve().parents[1] / "alter_planograms_configurations_feat574.sql"
_DEFAULT_TYPE = "product_on_shelves"


def _file_stem(config_name: str) -> str:
    """Filesystem-safe file stem for a ``config_name``."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", config_name).strip("._") or "unnamed"


def _read_json(path: Path) -> Dict[str, Any]:
    """Load one JSON object file."""
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    """Write one JSON object file (timestamps and decimals as text)."""
    path.write_text(json.dumps(payload, indent=2, default=str, ensure_ascii=False) + "\n", encoding="utf-8")


def _quote(text: str, base: str = "pgm") -> str:
    """Dollar-quote ``text`` with a tag that does not occur in it."""
    tag, suffix = base, 0
    while f"${tag}$" in text:
        suffix += 1
        tag = f"{base}{suffix}"
    return f"${tag}${text}${tag}$"


def build_candidate(row: Dict[str, Any]) -> Dict[str, Any]:
    """Convert one exported row into a reviewable candidate document.

    Args:
        row: One exported ``troc.planograms_configurations`` row.

    Returns:
        The candidate: the proposed ``slots_definition``, the original ``planogram_config`` with
        ``rule_bindings`` / ``layout_profile`` merged in, and the ``unresolved`` review list.

    Raises:
        ValueError: When the row's planogram type is not convertible.
    """
    planogram_type = row.get("planogram_type") or _DEFAULT_TYPE
    original = _decode(row.get("planogram_config")) or {}
    source = copy.deepcopy(original)
    existing = _decode(row.get("slots_definition")) if row.get("slots_definition") else None
    if existing and "slots_definition" not in source:
        source["slots_definition"] = existing
    report = convert_config(source, planogram_type=planogram_type)
    warnings = list(report.warnings)
    merged = copy.deepcopy(original)
    if merged.get("rule_bindings") and merged["rule_bindings"] != report.bindings:
        warnings.append("existing rule_bindings replaced by the converted bindings — review")
    merged["rule_bindings"] = report.bindings
    if report.layout_profile:
        merged["layout_profile"] = report.layout_profile
    return {
        "config_name": row.get("config_name", ""),
        "planogram_type": planogram_type,
        "updated_at": row.get("updated_at"),
        "slots_definition": report.candidate,
        "planogram_config": merged,
        "unresolved": list(report.unresolved),
        "warnings": warnings,
    }


def candidate_problems(candidate: Dict[str, Any]) -> List[str]:
    """Everything that blocks a candidate from being applied.

    Args:
        candidate: A candidate document, possibly edited by the reviewer.

    Returns:
        Open ``unresolved`` items plus the readiness problems the runtime preflight would report.
    """
    problems = [f"unresolved: {item}" for item in candidate.get("unresolved") or []]
    verdict = check_row(
        {
            "config_name": candidate.get("config_name", ""),
            "planogram_type": candidate.get("planogram_type"),
            "slots_definition": candidate.get("slots_definition"),
            "planogram_config": candidate.get("planogram_config"),
        }
    )
    return problems + list(verdict.problems)


def render_update(candidate: Dict[str, Any]) -> str:
    """One guarded UPDATE for an approved candidate.

    The statement fails (aborting the surrounding transaction) when the row is gone or was
    modified after the export.

    Args:
        candidate: An approved candidate document.

    Returns:
        A ``DO`` block updating ``slots_definition`` and ``planogram_config`` of one row.
    """
    name = str(candidate["config_name"])
    slots = json.dumps(candidate["slots_definition"], ensure_ascii=False)
    config = json.dumps(candidate["planogram_config"], ensure_ascii=False)
    guard = ""
    if candidate.get("updated_at"):
        guard = f"\n       AND updated_at = {_quote(str(candidate['updated_at']))}::timestamptz"
    body = (
        "BEGIN\n"
        f"    UPDATE {TABLE}\n"
        f"       SET slots_definition = {_quote(slots)}::jsonb,\n"
        f"           planogram_config = {_quote(config)}::jsonb\n"
        f"     WHERE config_name = {_quote(name)}{guard};\n"
        "    IF NOT FOUND THEN\n"
        f"        RAISE EXCEPTION 'planogram configuration % is missing or changed since the export', {_quote(name)};\n"
        "    END IF;\n"
        "END"
    )
    return f"-- {name}\nDO {_quote(body, 'row')};\n"


def _default_dsn() -> Optional[str]:
    """The writable ``default_dsn`` of the active querysource environment, when available."""
    try:
        from querysource.conf import default_dsn  # lazy: offline subcommands must not need it
    except ImportError:
        return None
    return default_dsn or None


def _dsn(args: argparse.Namespace) -> str:
    """DSN from ``--dsn`` or ``querysource.conf.default_dsn``; logs the target without credentials."""
    dsn = args.dsn or _default_dsn()
    if not dsn:
        raise ValueError("no DSN: pass --dsn or configure querysource.conf.default_dsn")
    target = urlsplit(dsn)
    logger.info("Target database: %s:%s%s", target.hostname, target.port or 5432, target.path)
    return dsn


async def _fetch_rows(dsn: str, sql: str) -> List[Dict[str, Any]]:
    """Run one SELECT and return the rows as dicts."""
    from asyncdb import AsyncDB  # lazy: offline subcommands must not need a DB driver

    db = AsyncDB("pg", dsn=dsn)
    async with await db.connection() as conn:
        rows: Sequence[Any] = await conn.fetch_all(sql) or []
    return [dict(row) for row in rows]


async def _execute(dsn: str, sql: str) -> None:
    """Run one SQL script; raise when the driver reports an error."""
    from asyncdb import AsyncDB  # lazy: offline subcommands must not need a DB driver

    db = AsyncDB("pg", dsn=dsn)
    async with await db.connection() as conn:
        outcome = await conn.execute(sql)
    error = outcome[1] if isinstance(outcome, (list, tuple)) and len(outcome) == 2 else None
    if error:
        raise RuntimeError(str(error))


def _cmd_alter(args: argparse.Namespace) -> int:
    """Apply the idempotent FEAT-574 ALTER script."""
    sql = _ALTER_SQL_PATH.read_text(encoding="utf-8")
    if not args.yes:
        sys.stdout.write(sql + "\n")
        logger.warning("Nothing executed: re-run with --yes to apply the statements above")
        return 0
    asyncio.run(_execute(_dsn(args), sql))
    logger.info("ALTER script applied (%s)", _ALTER_SQL_PATH.name)
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    """Export rows into ``<dir>/original``; existing exports are never overwritten."""
    target = args.dir / "original"
    if target.exists() and any(target.iterdir()):
        logger.error("%s already holds an export; use a new --dir to keep the originals intact", target)
        return 1
    rows = asyncio.run(_fetch_rows(_dsn(args), _EXPORT_ALL_SQL if args.all else _EXPORT_ACTIVE_SQL))
    target.mkdir(parents=True, exist_ok=True)
    stems: Dict[str, str] = {}
    for row in rows:
        name = str(row.get("config_name", ""))
        stem = _file_stem(name)
        if stem in stems:
            logger.error("config names %r and %r collide on file name %s.json", stems[stem], name, stem)
            return 1
        stems[stem] = name
        for column in ("planogram_config", "slots_definition", "reference_images"):
            row[column] = _decode(row.get(column))
        _write_json(target / f"{stem}.json", row)
    logger.info("Exported %d row(s) to %s", len(rows), target)
    return 0


def _cmd_convert(args: argparse.Namespace) -> int:
    """Convert every exported row that is not ready yet into ``<dir>/candidates``."""
    originals = sorted((args.dir / "original").glob("*.json"))
    if not originals:
        logger.error("no exported rows under %s; run export first", args.dir / "original")
        return 1
    target = args.dir / "candidates"
    target.mkdir(parents=True, exist_ok=True)
    summary: List[Dict[str, Any]] = []
    for path in originals:
        row = _read_json(path)
        name = str(row.get("config_name", path.stem))
        planogram_type = row.get("planogram_type") or _DEFAULT_TYPE
        entry: Dict[str, Any] = {"config_name": name, "planogram_type": planogram_type}
        out = target / path.name
        if planogram_type not in MIGRATED_TYPES:
            entry.update(status="unsupported", problems=[f"unknown planogram_type '{planogram_type}'"])
        elif check_row(row).ok:
            entry.update(status="ready", problems=[])
        elif out.exists() and not args.force:
            entry.update(status="kept", problems=candidate_problems(_read_json(out)))
        else:
            candidate = build_candidate(row)
            _write_json(out, candidate)
            entry.update(status="converted", problems=candidate_problems(candidate))
        summary.append(entry)
    sys.stdout.write(json.dumps(summary, indent=2) + "\n")
    return 2 if any(entry["problems"] for entry in summary) else 0


def _cmd_render(args: argparse.Namespace) -> int:
    """Render approved candidates into ``<dir>/apply.sql``; blocked candidates are reported."""
    candidates = sorted((args.dir / "candidates").glob("*.json"))
    if not candidates:
        logger.error("no candidates under %s; run convert first", args.dir / "candidates")
        return 1
    statements: List[str] = []
    blocked: Dict[str, List[str]] = {}
    for path in candidates:
        candidate = _read_json(path)
        problems = candidate_problems(candidate)
        if problems:
            blocked[str(candidate.get("config_name", path.stem))] = problems
        else:
            statements.append(render_update(candidate))
    out = args.dir / "apply.sql"
    if blocked and not args.partial:
        out.unlink(missing_ok=True)
        sys.stdout.write(json.dumps({"blocked": blocked}, indent=2) + "\n")
        logger.error("%d candidate(s) are not approved; resolve them or pass --partial", len(blocked))
        return 2
    if not statements:
        logger.error("no approved candidate to render")
        return 2
    header = f"-- FEAT-574 planogram configuration migration: {len(statements)} row(s). Review before applying.\n"
    out.write_text(header + "BEGIN;\n\n" + "\n".join(statements) + "\nCOMMIT;\n", encoding="utf-8")
    sys.stdout.write(json.dumps({"rendered": len(statements), "blocked": blocked, "sql": str(out)}, indent=2) + "\n")
    return 2 if blocked else 0


def _cmd_apply(args: argparse.Namespace) -> int:
    """Execute ``<dir>/apply.sql`` in its own transaction."""
    path = args.dir / "apply.sql"
    if not path.is_file():
        logger.error("%s not found; run render first", path)
        return 1
    if not args.yes:
        logger.warning("Nothing executed: review %s, then re-run with --yes", path)
        return 0
    asyncio.run(_execute(_dsn(args), path.read_text(encoding="utf-8")))
    logger.info("Applied %s", path)
    return 0


def _cmd_target(args: argparse.Namespace) -> int:
    """Log the database the other subcommands would connect to (credentials never shown)."""
    _dsn(args)
    return 0


def _cmd_preflight(args: argparse.Namespace) -> int:
    """Read-only readiness report for every active row."""
    rows = asyncio.run(preflight(_dsn(args)))
    sys.stdout.write(json.dumps([row.model_dump() for row in rows], indent=2) + "\n")
    return 0 if all(row.ok for row in rows) else 2


def _main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point. Exit codes: 0 ok, 2 unresolved / not-ready rows, 1 usage, I/O or database error."""
    parser = argparse.ArgumentParser(prog="python -m parrot_pipelines.planogram.migration_runner")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, help_text: str, *, dsn: bool = False, workdir: bool = False) -> argparse.ArgumentParser:
        command = sub.add_parser(name, help=help_text)
        if dsn:
            command.add_argument("--dsn", default=None, help="PostgreSQL DSN (default: querysource.conf.default_dsn)")
        if workdir:
            command.add_argument("--dir", type=Path, required=True, help="migration work directory")
        return command

    alter = add("alter", "apply the idempotent FEAT-574 ALTER script (prints it without --yes)", dsn=True)
    alter.add_argument("--yes", action="store_true")
    export = add("export", "export active rows to <dir>/original", dsn=True, workdir=True)
    export.add_argument("--all", action="store_true", help="include inactive rows")
    convert = add("convert", "convert exported rows to <dir>/candidates", workdir=True)
    convert.add_argument("--force", action="store_true", help="regenerate candidates, discarding review edits")
    render = add("render", "render approved candidates to <dir>/apply.sql", workdir=True)
    render.add_argument("--partial", action="store_true", help="render approved rows even when others are blocked")
    apply = add("apply", "execute <dir>/apply.sql (requires --yes)", dsn=True, workdir=True)
    apply.add_argument("--yes", action="store_true")
    add("preflight", "read-only readiness report", dsn=True)
    add("target", "show host/database the DSN points at, without credentials", dsn=True)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    commands = {
        "alter": _cmd_alter,
        "export": _cmd_export,
        "convert": _cmd_convert,
        "render": _cmd_render,
        "apply": _cmd_apply,
        "preflight": _cmd_preflight,
        "target": _cmd_target,
    }
    try:
        return commands[args.command](args)
    except Exception as exc:  # noqa: BLE001 - CLI boundary: report and exit non-zero
        logger.error("%s failed: %s", args.command, exc)
        return 1


if __name__ == "__main__":
    sys.exit(_main())
