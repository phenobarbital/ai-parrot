"""FEAT-713 AC1 — the accounting compile path imports without the governed stack."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PACKAGES = Path(__file__).resolve().parents[3]  # .../packages
SOURCE_PATH = os.pathsep.join(str(PACKAGES / name / "src") for name in ("ai-parrot-semantic", "ai-parrot"))
GOVERNED = ("parrot.semantic.toolkit", "parrot.semantic.governance", "parrot.tools.databasequery")


def _run(code: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": SOURCE_PATH}
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=120)


def test_semantic_package_exports_unchanged() -> None:
    from parrot.semantic import SemanticLayerToolkit, SemanticQuery, SemanticQueryResult

    assert SemanticQuery.__name__ == "SemanticQuery"
    assert SemanticQueryResult.__name__ == "SemanticQueryResult"
    assert SemanticLayerToolkit.tool_prefix == "sl"


def test_accounting_import_is_isolated() -> None:
    code = (
        "import sys, parrot.semantic.accounting as a\n"
        "from parrot.semantic.accounting import AccountingError\n"
        f"print([m for m in {GOVERNED!r} if m in sys.modules])\n"
    )
    result = _run(code)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"


def test_import_isolation(troc_pnl_yaml, chart_snapshot, tmp_path) -> None:
    """Compiling a metric in a fresh interpreter loads no governed-stack module (AC1)."""
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(chart_snapshot.model_dump_json(), encoding="utf-8")
    code = (
        "import sys\n"
        "from pathlib import Path\n"
        "from parrot.semantic.accounting import MetricRequest, compile_metric, load_model\n"
        "from parrot.semantic.accounting.models import ChartSnapshot\n"
        f"snapshot = ChartSnapshot.model_validate_json(Path({str(snapshot_path)!r}).read_text(encoding='utf-8'))\n"
        f"model = load_model(Path({str(troc_pnl_yaml)!r}), snapshot)\n"
        "request = MetricRequest.model_validate(\n"
        "    {'metric': 'gross_margin_pct', 'grain': 'month', 'period': {'from': '2025-01-01', 'to': '2025-03-31'}}\n"
        ")\n"
        "compiled = compile_metric(model, request, 'duckdb')\n"
        "assert compiled.sql.startswith('SELECT ')\n"
        f"print([m for m in {GOVERNED!r} if m in sys.modules])\n"
    )
    result = _run(code)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"
