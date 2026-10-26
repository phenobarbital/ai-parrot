"""``cache_test_contract.py`` — cache a spec's §4 Validation Contract into its per-spec index (FEAT-699).

Both authoring forms are accepted — the flat ``tests:``/``markers:`` form (lifted to one pytest runner)
and the FEAT-709 ``runners:`` form — and the header is always written as schema 2. Runner kinds,
tiers and settings are validated against the registry under ``--root`` (``.parrot/test_runners.toml``).

Usage:
    python -m parrot.sdd.scripts.cache_test_contract --spec sdd/specs/<slug>.spec.md --index sdd/tasks/index/<slug>.json \
        [--root .] [--check]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import ModuleType

_KERNEL_PARENT = Path(__file__).resolve().parents[2] / "flows" / "dev_loop"


def _load_contract() -> ModuleType:
    """Import ``test_scope.contract`` by path (never ``import parrot``)."""
    if str(_KERNEL_PARENT) not in sys.path:
        sys.path.insert(0, str(_KERNEL_PARENT))
    import test_scope.contract as contract_mod  # noqa: PLC0415 -- path-dependent import

    return contract_mod


def _load_registry(root: Path):
    """Load the runner registry for ``root`` by path (never ``import parrot``).

    Raises:
        ValueError: If ``.parrot/test_runners.toml`` is invalid.
    """
    _load_contract()
    import test_scope.runners.registry as registry_mod  # noqa: PLC0415 -- path-dependent import

    return registry_mod.load_registry(root)


def _with_contract(index: dict, value: dict | None) -> dict:
    """Return a new index dict with ``test_contract`` set/removed at a stable position."""
    rest = {k: v for k, v in index.items() if k != "test_contract"}
    if value is None:
        return rest
    anchor = "validation_contract" if "validation_contract" in rest else "base_branch"
    out: dict = {}
    placed = False
    for key, val in rest.items():
        out[key] = val
        if key == anchor:
            out["test_contract"] = value
            placed = True
    if not placed:
        out["test_contract"] = value
    return out


def main(argv: list[str] | None = None) -> int:
    """0 cached/unchanged/fallback, 1 --check drift, 2 usage error or malformed contract."""
    parser = argparse.ArgumentParser(description="Cache a spec's Validation Contract into its index header.")
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--index", required=True, type=Path)
    parser.add_argument("--root", type=Path, default=Path("."), help="repo root holding .parrot/test_runners.toml")
    parser.add_argument("--check", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 2
    contract_mod = _load_contract()
    try:
        spec_md = args.spec.read_text(encoding="utf-8")
        index = json.loads(args.index.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not isinstance(index, dict):
        print("error: index is not a JSON object", file=sys.stderr)
        return 2
    try:
        registry = _load_registry(args.root)
        contract = contract_mod.parse_spec_contract(spec_md, registry=registry)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    value = contract_mod.contract_to_header(contract) if contract is not None else None
    new_index = _with_contract(index, value)
    if args.check:
        return 0 if index.get("test_contract") == new_index.get("test_contract") else 1
    args.index.write_text(json.dumps(new_index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"cached {value['digest']}" if value is not None else "fallback")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
