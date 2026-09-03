"""FEAT-498 TASK-2748 — SymbolResolver's three-step deterministic resolution."""

from __future__ import annotations

from pathlib import Path

from parrot.knowledge.wiki.repo_scan import (
    build_import_edges,
    build_symbol_edges,
    scan_repository,
)


def _write(root: Path, rel: str, content: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


class TestSymbolResolverThreeSteps:
    """a.py defines helper(); b.py imports a and calls helper() (step 1:
    same-file is trivially satisfied since the call site AND its own
    def live in different files — step 2 exercises the import-reachable
    case); c.py calls unique_fn() defined only in d.py with NO import
    edge between them (step 3: globally unique name); e.py and f.py both
    define dup() so a caller of dup() with no local/reachable resolution
    hits an ambiguous global name (no edge)."""

    def test_resolver_steps(self, tmp_path: Path):
        _write(tmp_path, "a.py", "def helper():\n    return 1\n")
        _write(
            tmp_path,
            "b.py",
            "from a import helper\n\n\ndef run():\n    return helper()\n",
        )
        _write(tmp_path, "d.py", "def unique_fn():\n    return 1\n")
        _write(tmp_path, "c.py", "def go():\n    return unique_fn()\n")
        _write(tmp_path, "e.py", "def dup():\n    return 1\n")
        _write(tmp_path, "f.py", "def dup():\n    return 2\n")
        _write(tmp_path, "g.py", "def call_dup():\n    return dup()\n")

        scan = scan_repository(tmp_path, use_git=False)
        prov = {(src, dst): provenance for src, dst, rel, provenance in scan.symbol_edges if rel == "calls"}

        assert prov[("sym:b.py#run", "sym:a.py#helper")] == "extracted"
        assert prov[("sym:c.py#go", "sym:d.py#unique_fn")] == "inferred"
        assert not any(dst.endswith("#dup") for (_src, dst) in prov)

    def test_same_file_resolution_is_extracted(self, tmp_path: Path):
        _write(
            tmp_path,
            "a.py",
            "def helper():\n    return 1\n\n\ndef run():\n    return helper()\n",
        )
        scan = scan_repository(tmp_path, use_git=False)
        edges = [(s, d, p) for s, d, rel, p in scan.symbol_edges if rel == "calls"]
        assert ("sym:a.py#run", "sym:a.py#helper", "extracted") in edges

    def test_extends_resolution(self, tmp_path: Path):
        _write(
            tmp_path,
            "a.py",
            "class Base:\n    pass\n\n\nclass Sub(Base):\n    pass\n",
        )
        scan = scan_repository(tmp_path, use_git=False)
        edges = [(s, d, p) for s, d, rel, p in scan.symbol_edges if rel == "extends"]
        assert ("sym:a.py#Sub", "sym:a.py#Base", "extracted") in edges

    def test_ambiguous_target_produces_no_edge(self, tmp_path: Path):
        _write(tmp_path, "e.py", "def dup():\n    return 1\n")
        _write(tmp_path, "f.py", "def dup():\n    return 2\n")
        _write(tmp_path, "g.py", "def call_dup():\n    return dup()\n")
        scan = scan_repository(tmp_path, use_git=False)
        assert not any(d.endswith("#dup") for _s, d, rel, _p in scan.symbol_edges if rel == "calls")

    def test_build_symbol_edges_matches_scan_repository(self, tmp_path: Path):
        _write(tmp_path, "a.py", "def helper():\n    return 1\n")
        _write(
            tmp_path,
            "b.py",
            "from a import helper\n\n\ndef run():\n    return helper()\n",
        )
        scan = scan_repository(tmp_path, use_git=False)
        import_edges = build_import_edges(scan.files)
        edges = build_symbol_edges(scan.files, import_edges)
        assert ("sym:b.py#run", "sym:a.py#helper", "calls", "extracted") in edges
