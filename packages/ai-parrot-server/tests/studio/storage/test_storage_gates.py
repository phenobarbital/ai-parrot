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
BOTS_PY = "packages/ai-parrot/src/parrot/models/bots.py"
# Pre-move location of BotModel (re-export shim today); used when the merge-base predates the move.
LEGACY_BOTS_PY = "packages/ai-parrot-server/src/parrot/handlers/models/bots.py"
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
    "setup",
    "setup_registry_only",
    "setup_studio_routes",
    "ensure_studio_storage",
    "resolve_studio_storage",
    "add_studio_runtime_hooks",
    "install_studio_runtime",
    "shutdown_studio_runtime",
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


def _bots_source_at(rev: str) -> str:
    """Return the ``BotModel`` module source at ``rev``, from its current or legacy path."""
    try:
        return _git("show", f"{rev}:{BOTS_PY}")
    except subprocess.CalledProcessError:
        return _git("show", f"{rev}:{LEGACY_BOTS_PY}")


# Sanctioned deltas: reviewed changes to the frozen ai_bots DDL. Applied to the merge-base
# copy only, so AC17 still catches any OTHER change to it.
#
# FEAT-638: the `language` column drops its DEFAULT 'en'.
_FEAT638_LANGUAGE_DEFAULT = re.compile(r"(language\s+VARCHAR\(10\))\s+DEFAULT\s+'en',")

# BotModel homologation (2026-10-21): the documented CREATE TABLE had drifted from the 44
# fields BotModel declares — it still carried the folded model_name / temperature /
# max_tokens / top_k / top_p / embedding_model columns and was missing prompt_config,
# toolkit_config, mcp_servers, use_kb / kb / custom_kbs and bot_class, so a strict row
# hydration failed with `column "toolkit_config" does not exist`. Each entry is
# (merge-base text, reviewed text); an entry whose old side is gone (already merged) is
# a no-op.
_SANCTIONED_REWRITES: tuple[tuple[str, str], ...] = (
    (
        "-- WARNING: Initial setup DDL only. DO NOT run against production.\n"
        "-- For migrations, use the ALTER TABLE ADD COLUMN IF NOT EXISTS statements at the bottom.\n"
        "DROP TABLE IF EXISTS navigator.ai_bots CASCADE;\n",
        "-- WARNING: Initial setup DDL only. DO NOT run against production.\n"
        "-- For migrations, use the ALTER TABLE ADD COLUMN IF NOT EXISTS statements at the bottom,\n"
        "-- or run sdd/migrations/ai-bots-homologate-botmodel.sql (idempotent, covers every column).\n"
        "--\n"
        "-- The CREATE TABLE below tracks parrot.models.bots.BotModel field-for-field (44 columns).\n"
        "-- Columns dropped from the model live only in their fold migrations:\n"
        "--   model_name/temperature/max_tokens/top_k/top_p -> FEAT-fold-legacy-llm-columns.sql\n"
        "--   embedding_model                               -> FEAT-fold-embedding-model-into-vector-store-config.sql\n"
        "DROP TABLE IF EXISTS navigator.ai_bots CASCADE;\n",
    ),
    (
        "    pre_instructions JSONB DEFAULT '[]'::JSONB,\n"
        "\n"
        "    -- LLM configuration\n"
        "    llm VARCHAR DEFAULT 'google',\n"
        "    model_name VARCHAR DEFAULT 'gemini-3.1-flash-lite-preview',\n"
        "    temperature FLOAT DEFAULT 0.1 CHECK (temperature >= 0 AND temperature <= 2),\n"
        "    max_tokens INTEGER DEFAULT 1024 CHECK (max_tokens > 0),\n"
        "    top_k INTEGER DEFAULT 41 CHECK (top_k > 0),\n"
        "    top_p FLOAT DEFAULT 0.9 CHECK (top_p >= 0 AND top_p <= 1),\n"
        "    model_config JSONB DEFAULT '{}'::JSONB,\n",
        "    pre_instructions JSONB DEFAULT '[]'::JSONB,\n"
        "    prompt_config JSONB NOT NULL DEFAULT '{}'::JSONB,\n"
        "\n"
        "    -- LLM configuration. model_config is the canonical home for every tuning key\n"
        "    -- (model / model_name, temperature, max_tokens, top_k, top_p).\n"
        "    llm VARCHAR DEFAULT 'google',\n"
        "    model_config JSONB DEFAULT '{}'::JSONB,\n",
    ),
    (
        "    tools JSONB DEFAULT '[]'::JSONB,\n"
        "    operation_mode VARCHAR DEFAULT 'adaptive' CHECK (operation_mode IN ('conversational', 'agentic', 'adaptive')),\n"
        "\n"
        "    -- Vector store and retrieval configuration\n",
        "    tools JSONB DEFAULT '[]'::JSONB,\n"
        "    toolkit_config JSONB DEFAULT '{}'::JSONB,\n"
        "    mcp_servers JSONB DEFAULT '[]'::JSONB,\n"
        "    operation_mode VARCHAR DEFAULT 'adaptive' CHECK (operation_mode IN ('conversational', 'agentic', 'adaptive')),\n"
        "\n"
        "    -- Knowledge base\n"
        "    use_kb BOOLEAN DEFAULT FALSE,\n"
        "    kb JSONB,\n"
        "    custom_kbs JSONB,\n"
        "\n"
        "    -- Vector store and retrieval configuration\n",
    ),
    (
        "    parent_searcher_config JSONB DEFAULT '{}'::JSONB,\n"
        '    embedding_model JSONB DEFAULT \'{"model_name": "sentence-transformers/all-mpnet-base-v2", "model_type": "huggingface"}\'::JSONB,\n'
        "    context_search_limit INTEGER DEFAULT 10 CHECK (context_search_limit > 0),\n",
        "    parent_searcher_config JSONB DEFAULT '{}'::JSONB,\n"
        "    context_search_limit INTEGER DEFAULT 10 CHECK (context_search_limit > 0),\n",
    ),
    (
        "\n" "    -- Security and permissions\n",
        "\n" "    -- Advanced: bot class\n" "    bot_class VARCHAR,\n" "\n" "    -- Security and permissions\n",
    ),
    (
        "\n" "    -- Metadata\n" "    language VARCHAR(10),\n",
        "\n"
        '    -- Metadata (language: NULL means "mirror the user" — FEAT-638, no DEFAULT)\n'
        "    language VARCHAR(10),\n",
    ),
    (
        "    llm,\n" "    model_name,\n" "    created_at,\n",
        "    llm,\n" "    model_config->>'model' AS model_name,\n" "    created_at,\n",
    ),
    (
        "    ON navigator.ai_bots USING GIN (parent_searcher_config);\n",
        "    ON navigator.ai_bots USING GIN (parent_searcher_config);\n"
        "\n"
        "-- Columns added after the original release (idempotent — see\n"
        "-- sdd/migrations/ai-bots-homologate-botmodel.sql for the runnable migration)\n"
        "ALTER TABLE navigator.ai_bots\n"
        "    ADD COLUMN IF NOT EXISTS prompt_config JSONB NOT NULL DEFAULT '{}'::JSONB;\n"
        "ALTER TABLE navigator.ai_bots\n"
        "    ADD COLUMN IF NOT EXISTS use_kb        BOOLEAN DEFAULT FALSE;\n"
        "ALTER TABLE navigator.ai_bots\n"
        "    ADD COLUMN IF NOT EXISTS kb            JSONB;\n"
        "ALTER TABLE navigator.ai_bots\n"
        "    ADD COLUMN IF NOT EXISTS custom_kbs    JSONB;\n"
        "ALTER TABLE navigator.ai_bots\n"
        "    ADD COLUMN IF NOT EXISTS bot_class     VARCHAR;\n"
        "ALTER TABLE navigator.ai_bots\n"
        "    ADD COLUMN IF NOT EXISTS timezone      VARCHAR(75) DEFAULT 'UTC';\n"
        "ALTER TABLE navigator.ai_bots\n"
        "    ADD COLUMN IF NOT EXISTS avatar        TEXT;\n"
        "ALTER TABLE navigator.ai_bots\n"
        "    ADD COLUMN IF NOT EXISTS disclaimer    TEXT;\n",
    ),
    (
        "        tools JSONB DEFAULT '[]'::JSONB,\n" "        operation_mode VARCHAR DEFAULT 'adaptive',\n",
        "        tools JSONB DEFAULT '[]'::JSONB,\n"
        "        toolkit_config JSONB DEFAULT '{}'::JSONB,\n"
        "        mcp_servers JSONB DEFAULT '[]'::JSONB,\n"
        "        operation_mode VARCHAR DEFAULT 'adaptive',\n",
    ),
)


def _with_sanctioned_deltas(source: str) -> str:
    """Apply sanctioned DDL deltas to a merge-base copy before AC17 compares it."""
    source = _FEAT638_LANGUAGE_DEFAULT.sub(r"\1,", source)
    for old, new in _SANCTIONED_REWRITES:
        source = source.replace(old, new)
    return source


def _ai_bots_ddl(source: str) -> str:
    match = re.search(r"CREATE TABLE IF NOT EXISTS navigator\.ai_bots \(.*?\n\s*\)\s*;", source, re.DOTALL)
    assert match, "navigator.ai_bots DDL block not found in bots.py"
    return match.group(0)


def test_load_database_bots_untouched():
    """AC17: ``_load_database_bots`` and the ``navigator.ai_bots`` DDL are identical to the ``origin/dev`` merge-base."""
    base = _merge_base()
    try:
        old_manager, old_sql = (_git("show", f"{base}:{p}") for p in (MANAGER_PY, CREATION_SQL))
        old_bots = _bots_source_at(base)
    except subprocess.CalledProcessError as exc:
        pytest.skip(f"files not present at the merge-base {base[:9]}: {exc}")
    new_manager = (REPO / MANAGER_PY).read_text(encoding="utf-8")
    assert _method_source(new_manager, "BotManager", "_load_database_bots") == _method_source(
        old_manager, "BotManager", "_load_database_bots"
    ), "BotManager._load_database_bots changed since the merge-base"
    new_bots = (REPO / BOTS_PY).read_text(encoding="utf-8")
    assert _ai_bots_ddl(new_bots) == _ai_bots_ddl(
        _with_sanctioned_deltas(old_bots)
    ), "navigator.ai_bots DDL changed in parrot/models/bots.py"
    assert (REPO / CREATION_SQL).read_text(encoding="utf-8") == _with_sanctioned_deltas(
        old_sql
    ), "handlers/creation.sql changed"
