from __future__ import annotations

import json
from pathlib import Path

from scripts.sdd.check_task_graph import check_graph, main, module_of, parse_declared_files

_TASK = """# {tid}: demo

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
{rows}

## Codebase Contract

{contract}
"""


def _repo(tmp_path: Path, tasks: list[dict], header: dict | None = None) -> Path:
    active = tmp_path / "sdd/tasks/active"
    active.mkdir(parents=True)
    entries = []
    for t in tasks:
        rows = "\n".join(f"| `{p}` | {action} | x |" for p, action in t["files"].items())
        rel = f"sdd/tasks/active/{t['id']}-demo.md"
        (tmp_path / rel).write_text(_TASK.format(tid=t["id"], rows=rows, contract=t.get("contract", "")))
        entries.append(
            {
                "id": t["id"],
                "depends_on": t.get("depends_on", []),
                "parallel": t.get("parallel", True),
                "parallelism_notes": t.get("notes", ""),
                "file": rel,
            }
        )
    index = tmp_path / "sdd/tasks/index/demo.json"
    index.parent.mkdir(parents=True)
    index.write_text(
        json.dumps({**({"parallel_semantics": "exclusive"} if header is None else header), "tasks": entries})
    )
    return index


def _codes(report) -> list[str]:
    return sorted(f.code for f in report.findings)


def test_parse_declared_files_marks_create():
    md = _TASK.format(tid="TASK-1", rows="| `a/b.py` | CREATE | x |\n| `a/c.py` | MODIFY | x |", contract="")
    assert parse_declared_files(md) == {"a/b.py": True, "a/c.py": False}


def test_module_of_is_src_layout_aware():
    assert module_of("packages/ai-parrot/src/parrot/a/b.py") == "parrot.a.b"
    assert module_of("querysource/tenants.py") == "querysource.tenants"
    assert module_of("conftest.py") is None


def test_file_overlap_without_dependency_is_an_error(tmp_path):
    index = _repo(
        tmp_path,
        [{"id": "TASK-1", "files": {"pkg/cli.py": "MODIFY"}}, {"id": "TASK-2", "files": {"pkg/cli.py": "MODIFY"}}],
    )
    report = check_graph(index, tmp_path)
    assert "file-overlap" in _codes(report)
    assert main([str(index), "--root", str(tmp_path)]) == 1


def test_evidence_free_chain_is_flagged(tmp_path):
    notes = "Sequential per spec."
    tasks = [
        {
            "id": f"TASK-{i}",
            "files": {f"pkg/m{i}.py": "CREATE"},
            "notes": notes,
            "depends_on": [f"TASK-{i - 1}"] if i else [],
        }
        for i in range(3)
    ]
    report = check_graph(_repo(tmp_path, tasks), tmp_path)
    assert _codes(report) == ["duplicate-notes", "unjustified-edge", "unjustified-edge"]
    assert [len(w) for w in report.waves] == [1, 1, 1]


def test_justified_edges_pass(tmp_path):
    tasks = [
        {"id": "TASK-1", "files": {"pkg/models.py": "CREATE"}},
        {
            "id": "TASK-2",
            "files": {"pkg/api.py": "CREATE"},
            "depends_on": ["TASK-1"],
            "contract": "from pkg.models import X",
        },
        {
            "id": "TASK-3",
            "files": {"docs/x.md": "CREATE"},
            "depends_on": ["TASK-2"],
            "notes": "Documents the API of TASK-2.",
        },
        {
            "id": "TASK-4",
            "files": {"pkg/other.py": "CREATE"},
            "parallel": False,
            "notes": "Rebuilds Cython extensions.",
        },
    ]
    report = check_graph(_repo(tmp_path, tasks), tmp_path)
    assert report.findings == []
    assert report.exclusive == ["TASK-4"]
    assert report.waves == [["TASK-1", "TASK-4"], ["TASK-2"], ["TASK-3"]]


def test_missing_dependency_and_legacy_semantics_warned(tmp_path):
    tasks = [
        {"id": "TASK-1", "files": {"pkg/models.py": "CREATE"}},
        {"id": "TASK-2", "files": {"pkg/api.py": "CREATE"}, "contract": "uses `pkg/models.py`"},
    ]
    report = check_graph(_repo(tmp_path, tasks, header={}), tmp_path)
    assert _codes(report) == ["legacy-semantics", "possible-missing-dependency"]
