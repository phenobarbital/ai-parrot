"""Report price-table coverage over sdd-coder attempt rows (FEAT-783 AC-6)."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


def coverage(rows_dir: Path) -> dict:
    """Measure how many attempt rows resolve to a priced ``(provider, model)`` pair.

    Args:
        rows_dir: Directory holding ``*.jsonl`` files of sdd-coder telemetry rows.

    Returns:
        ``{"rows": N, "priced": P, "ratio": P/N, "unpriced": {(provider, model): count}}``.
        Only ``kind == "attempt"`` rows are counted; rows with no model are skipped.
    """
    from parrot.observability.attributes import resolve_gen_ai_system
    from parrot.observability.cost.calculator import CostCalculator

    calc = CostCalculator()
    rows = 0
    priced = 0
    unpriced: Counter[tuple[str, str]] = Counter()
    for path in sorted(Path(rows_dir).glob("*.jsonl")):
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict) or row.get("kind") != "attempt":
                    continue
                model = row.get("resolved_model") or row.get("configured_model") or ""
                if not model:
                    continue
                provider = resolve_gen_ai_system(row.get("backend") or "")
                rows += 1
                if calc.cost_usd(provider=provider, model=model, input_tokens=1, output_tokens=1) is not None:
                    priced += 1
                else:
                    unpriced[(provider, model)] += 1
    return {"rows": rows, "priced": priced, "ratio": (priced / rows) if rows else 0.0, "unpriced": dict(unpriced)}


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: ``--rows-dir <dir> [--threshold 0.9]``; exits 1 below the threshold."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows-dir", type=Path, required=True)
    parser.add_argument("--threshold", type=float, default=0.9)
    args = parser.parse_args(argv)
    report = coverage(args.rows_dir)
    unpriced = {f"{p}/{m}": c for (p, m), c in sorted(report["unpriced"].items(), key=lambda kv: -kv[1])}
    sys.stdout.write(json.dumps({**report, "unpriced": unpriced}, indent=2) + "\n")
    return 0 if report["ratio"] >= args.threshold else 1


if __name__ == "__main__":
    raise SystemExit(main())
