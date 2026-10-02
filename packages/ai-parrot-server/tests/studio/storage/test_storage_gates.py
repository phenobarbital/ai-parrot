"""FEAT-621 release gates: AC1 (no startup/handler DDL, no migration at startup), AC17 (``ai_bots`` untouched).

Source-level gates: they read the repository checkout and skip (with a reason) when it is not available.
"""
from __future__ import annotations

import ast
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[5]
SERVER_SRC = REPO / "packages" / "ai-parrot-server" / "src" / "parrot"
CORE_SRC = REPO / "packages" / "ai-parrot" / "src" / "parrot"
STORAGE = SERVER_SRC / "handlers" / "studio" / "storage"
MANAGER_PY = "packages/ai-parrot-server/src/parrot/manager/manager.py"
BOTS_PY = "packages/ai-parrot-server/src/parrot/handlers/models/bots.py"
CREATION_SQL = "packages/ai-parrot-server/src/parrot/handlers/creation.sql"

# Phase-2 (BYOK / vault / overrides / copy script) modules hold INSERT/UPSERT SQL only — they must stay in scope.
PHASE2_MODULES = ("byok_store.py", "vault_store.py", "overrides_store.py", "vault_targets.py", "secrets_copy.py")
DDL = re.compile(
    r"\b(?:create|alter|drop)\s+(?:or\s+replace\s+)?(?:unique\s+)?"
    r"(?:table|index|schema|extension|type|function|view|sequence|materialized)\b",
    re.IGNORECASE,
)
MIGRATION_ENTRYPOINTS = ("apply_studio_migrations", "stamp_migrations")
# Startup-path callables that must never apply migrations (X8/X10, spec §2.2).
STARTUP_FUNCTIONS = {
    "setup", "setup_registry_only", "setup_studio_routes", "ensure_studio_storage", "resolve_studio_storage",
    "add_studio_runtime_hooks", "install_studio_runtime", "shutdown_studio_runtime",
}


def _studio_stack_files() -> list[Path]:
    """Every Python module of the Studio storage stack, the handlers around it and the secret-store seams."""
    files = [p for p in (SERVER_SRC / "handlers" / "studio").rglob("*.py") if "migrations" not in p.parts]
    files += [SERVER_SRC / "manager" / "studio_runtime.py", SERVER_SRC / "handlers" / "toolkit_persistence.py"]
    files += [CORE_SRC / "security" / "vault_utils.py", CORE_SRC / "auth" / "broker.py"]
    return sorted({p for p in files if p.exists() and p.name != "migrate.py"})


def test_no_ddl_outside_migrations():
    """AC1: DDL lives only in ``storage/migrations/*.sql`` (and ``migrate.py``'s runner); phase 2 included."""
    files = _studio_stack_files()
    if not files:
        pytest.skip("source tree not available (installed distribution)")
    scanned = {p.name for p in files}
    assert set(PHASE2_MODULES) <= scanned, "phase-2 modules must be inside the DDL gate"
    offenders = [
        f"{p.relative_to(REPO)}:{n}: {line.strip()}"
        for p in files
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if DDL.search(line)
    ]
    assert not offenders, "DDL outside storage/migrations/*.sql:\n" + "\n".join(offenders)
    sql_outside = [p for p in STORAGE.rglob("*.sql") if "migrations" not in p.parts]
    assert not sql_outside, f"stray .sql files in the storage package: {sql_outside}"


def _references(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in MIGRATION_ENTRYPOINTS:
            return True
        if isinstance(node, ast.Attribute) and node.attr in MIGRATION_ENTRYPOINTS:
            return True
        if isinstance(node, ast.ImportFrom) and any(a.name in MIGRATION_ENTRYPOINTS for a in node.names):
            return True
    return False


def test_no_migration_call_at_startup():
    """AC1: nothing on the startup path (nor anywhere in the server/core source) calls the migration runner."""
    modules = sorted(p for root in (SERVER_SRC, CORE_SRC) for p in root.rglob("*.py"))
    if not modules:
        pytest.skip("source tree not available (installed distribution)")
    referencing, startup_hits = [], []
    for path in modules:
        if path == STORAGE / "migrate.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if _references(tree):
            referencing.append(str(path.relative_to(REPO)))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in STARTUP_FUNCTIONS:
                if _references(node):
                    startup_hits.append(f"{path.relative_to(REPO)}::{node.name}")
    assert not startup_hits, f"startup hooks apply migrations: {startup_hits}"
    assert not referencing, f"only migrate.py (CLI / host deploy hook) may reference the runner: {referencing}"


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO), *args], check=True, capture_output=True, text=True).stdout


def _merge_base() -> str:
    if shutil.which("git") is None or not (REPO / ".git").exists():
        pytest.skip("git checkout not available (e.g. an sdist)")
    try:
        return _git("merge-base", "HEAD", "origin/dev").strip()
    except (subprocess.CalledProcessError, OSError) as exc:
        pytest.skip(f"cannot resolve `git merge-base HEAD origin/dev`: {exc}")


def _method_source(source: str, cls: str, method: str) -> str:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == cls:
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == method:
                    return ast.get_source_segment(source, item) or ""
    raise AssertionError(f"{cls}.{method} not found")


def _ai_bots_ddl(source: str) -> str:
    match = re.search(r"CREATE TABLE IF NOT EXISTS navigator\.ai_bots \(.*?\n\s*\)\s*;", source, re.DOTALL)
    assert match, "navigator.ai_bots DDL block not found in bots.py"
    return match.group(0)


def test_load_database_bots_untouched():
    """AC17: ``_load_database_bots`` and the ``navigator.ai_bots`` DDL are identical to the ``origin/dev`` merge-base."""
    base = _merge_base()
    try:
        old_manager, old_bots, old_sql = (_git("show", f"{base}:{p}") for p in (MANAGER_PY, BOTS_PY, CREATION_SQL))
    except subprocess.CalledProcessError as exc:
        pytest.skip(f"files not present at the merge-base {base[:9]}: {exc}")
    new_manager = (REPO / MANAGER_PY).read_text(encoding="utf-8")
    assert _method_source(new_manager, "BotManager", "_load_database_bots") == _method_source(
        old_manager, "BotManager", "_load_database_bots"
    ), "BotManager._load_database_bots changed since the merge-base"
    new_bots = (REPO / BOTS_PY).read_text(encoding="utf-8")
    assert _ai_bots_ddl(new_bots) == _ai_bots_ddl(old_bots), "navigator.ai_bots DDL changed in handlers/models/bots.py"
    assert (REPO / CREATION_SQL).read_text(encoding="utf-8") == old_sql, "handlers/creation.sql changed"
