#!/usr/bin/env python
"""Pydantic -> JSON Schema exporter for the Admin UI TS codegen pipeline.

TASK-2526 (FEAT-468). Implements the pattern decided in
``sdd/proposals/dev-loop-session-state-hitl.brainstorm.md:497-509``: the
Admin UI (packages/ai-parrot-server/ui/) consumes generated TypeScript
types, never hand-written ones, so drift between a Python response model
and the UI becomes a ``tsc``/build failure instead of a silent bug.

This script exports ``model_json_schema()`` for every UI-consumed
response model into one deterministic JSON Schema file per model under
``packages/ai-parrot-server/ui/schemas/``. The JSON Schema -> TypeScript
step itself is a separate, Python-independent tool (``pnpm generate`` /
``json-schema-to-typescript``, wired in ``ui/package.json``) so the UI's
CI job never needs a Python environment to produce fresh types from the
committed schemas.

Usage:
    source .venv/bin/activate
    python scripts/generate_ts_types.py

Run from within a git worktree, prepend the worktree's package sources so
this resolves worktree-local model changes instead of a stale editable
install elsewhere on PYTHONPATH, e.g.:
    PYTHONPATH="$(pwd)/packages/ai-parrot-server/src:$(pwd)/packages/ai-parrot/src" \\
        python scripts/generate_ts_types.py
(pytest picks this up automatically via the worktree's root conftest.py;
this script does not import pytest so it needs the explicit PYTHONPATH
when invoked directly outside a test run.)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = REPO_ROOT / "packages" / "ai-parrot-server" / "ui" / "schemas"


def _models() -> dict[str, type[BaseModel]]:
    """Return the name -> Pydantic model mapping this script exports.

    Imported lazily (not at module scope) so ``--help``-style tooling and
    static analysis do not require the full ``parrot`` import chain.

    Returns:
        Mapping of the TypeScript-facing model name to its Pydantic class.
    """
    from parrot.server.ui.catalog import AdminCatalog, KnowledgeBaseOption
    from parrot.server.ui.models import (
        BotAgentItem,
        BotMutationResponse,
        BotsListResponse,
        BotWritePayload,
        ToolInfo,
        ToolsListResponse,
    )
    from parrot.server.ui.status import AdminStatus, AgentCounts, DependencyHealth

    return {
        "AdminStatus": AdminStatus,
        "AgentCounts": AgentCounts,
        "DependencyHealth": DependencyHealth,
        "BotsListResponse": BotsListResponse,
        "BotAgentItem": BotAgentItem,
        "AdminCatalog": AdminCatalog,
        "KnowledgeBaseOption": KnowledgeBaseOption,
        "ToolInfo": ToolInfo,
        "ToolsListResponse": ToolsListResponse,
        "BotWritePayload": BotWritePayload,
        "BotMutationResponse": BotMutationResponse,
    }


def export_schemas(output_dir: Path = SCHEMAS_DIR) -> dict[str, Path]:
    """Write one deterministic JSON Schema file per model.

    Args:
        output_dir: Directory to write ``<ModelName>.json`` files into.
            Created if it does not already exist.

    Returns:
        Mapping of model name to the path it was written to.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for name, model in _models().items():
        schema = model.model_json_schema()
        path = output_dir / f"{name}.json"
        # sort_keys + fixed indent -> deterministic, diff-friendly output.
        path.write_text(
            json.dumps(schema, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written[name] = path
    return written


def main() -> int:
    """CLI entry point: export all schemas and print what was written.

    Returns:
        Process exit code (always ``0`` on success).
    """
    written = export_schemas()
    for name, path in sorted(written.items()):
        print(f"wrote {path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
