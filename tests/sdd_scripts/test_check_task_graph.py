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
{validation}"""


def _repo(tmp_path: Path, tasks: list[dict], header: dict | None = None) -> Path:
    active = tmp_path / "sdd/tasks/active"
    active.mkdir(parents=True)
    entries = []
    for t in tasks:
        rows = "\n".join(f"| `{p}` | {action} | x |" for p, action in t["files"].items())
        rel = f"sdd/tasks/active/{t['id']}-demo.md"
        commands = t.get("validation")
        validation = ""
        if commands is not None:
            bullets = "\n".join(f"- `{cmd}`" for cmd in commands)
            validation = f"\n## Validation Commands\n\n{bullets}\n"
        (tmp_path / rel).write_text(
            _TASK.format(tid=t["id"], rows=rows, contract=t.get("contract", ""), validation=validation)
        )
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


def _with_validation(tmp_path: Path, commands: list[str], required: bool, files: dict | None = None) -> Path:
    """One-task repo whose task file carries a Validation Commands section."""
    header = {"parallel_semantics": "exclusive"}
    if required:
        header["validation_contract"] = "required"
    task = {"id": "TASK-1", "files": files or {}, "validation": commands}
    return _repo(tmp_path, [task], header=header)


def _codes(report) -> list[str]:
    return sorted(f.code for f in report.findings)


def test_parse_declared_files_marks_create():
    md = _TASK.format(
        tid="TASK-1", rows="| `a/b.py` | CREATE | x |\n| `a/c.py` | MODIFY | x |", contract="", validation=""
    )
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


def _self_validation(tid: str) -> list[str]:
    """A validation command that always exists (the task's own generated file) — keeps
    tests that assert exact findings free of `missing-validation-commands` noise."""
    return [f"pytest sdd/tasks/active/{tid}-demo.md::test_ok"]


def test_evidence_free_chain_is_flagged(tmp_path):
    notes = "Sequential per spec."
    tasks = [
        {
            "id": f"TASK-{i}",
            "files": {f"pkg/m{i}.py": "CREATE"},
            "notes": notes,
            "depends_on": [f"TASK-{i - 1}"] if i else [],
            "validation": _self_validation(f"TASK-{i}"),
        }
        for i in range(3)
    ]
    report = check_graph(_repo(tmp_path, tasks), tmp_path)
    assert _codes(report) == ["duplicate-notes", "unjustified-edge", "unjustified-edge"]
    assert [len(w) for w in report.waves] == [1, 1, 1]


def test_justified_edges_pass(tmp_path):
    tasks = [
        {"id": "TASK-1", "files": {"pkg/models.py": "CREATE"}, "validation": _self_validation("TASK-1")},
        {
            "id": "TASK-2",
            "files": {"pkg/api.py": "CREATE"},
            "depends_on": ["TASK-1"],
            "contract": "from pkg.models import X",
            "validation": _self_validation("TASK-2"),
        },
        {
            "id": "TASK-3",
            "files": {"docs/x.md": "CREATE"},
            "depends_on": ["TASK-2"],
            "notes": "Documents the API of TASK-2.",
            "validation": _self_validation("TASK-3"),
        },
        {
            "id": "TASK-4",
            "files": {"pkg/other.py": "CREATE"},
            "parallel": False,
            "notes": "Rebuilds Cython extensions.",
            "validation": _self_validation("TASK-4"),
        },
    ]
    report = check_graph(_repo(tmp_path, tasks), tmp_path)
    assert report.findings == []
    assert report.exclusive == ["TASK-4"]
    assert report.waves == [["TASK-1", "TASK-4"], ["TASK-2"], ["TASK-3"]]


def test_missing_dependency_and_legacy_semantics_warned(tmp_path):
    tasks = [
        {"id": "TASK-1", "files": {"pkg/models.py": "CREATE"}, "validation": _self_validation("TASK-1")},
        {
            "id": "TASK-2",
            "files": {"pkg/api.py": "CREATE"},
            "contract": "uses `pkg/models.py`",
            "validation": _self_validation("TASK-2"),
        },
    ]
    report = check_graph(_repo(tmp_path, tasks, header={}), tmp_path)
    assert _codes(report) == ["legacy-semantics", "possible-missing-dependency"]


def test_missing_validation_commands_error_when_required(tmp_path):
    index = _with_validation(tmp_path, [], required=True)
    report = check_graph(index, tmp_path)
    missing = [f for f in report.findings if f.code == "missing-validation-commands"]
    assert missing and missing[0].level == "error"
    assert main([str(index), "--root", str(tmp_path)]) == 1


def test_missing_validation_commands_warning_on_legacy_header(tmp_path):
    index = _repo(tmp_path, [{"id": "TASK-1", "files": {"pkg/a.py": "CREATE"}}])
    report = check_graph(index, tmp_path)
    missing = [f for f in report.findings if f.code == "missing-validation-commands"]
    assert missing and missing[0].level == "warning"


def test_non_pytest_validation_command_is_error(tmp_path):
    """FEAT-563 review: a declared command that isn't pytest at all (e.g. `true`) used to pass
    the lint cleanly — it is invisible to select_tests.py's declared-command handling, so the
    task effectively has no enforced test coverage."""
    index = _with_validation(tmp_path, ["true"], required=True)
    report = check_graph(index, tmp_path)
    assert "non-pytest-validation-command" in _codes(report)
    assert main([str(index), "--root", str(tmp_path)]) == 1


def test_non_pytest_validation_command_does_not_also_fire_broad_or_directory_findings(tmp_path):
    index = _with_validation(tmp_path, ["ruff check ."], required=True)
    report = check_graph(index, tmp_path)
    assert _codes(report) == ["non-pytest-validation-command"]


def test_broad_validation_command_is_error(tmp_path):
    index = _with_validation(tmp_path, ["pytest packages/x/tests -q"], required=True)
    report = check_graph(index, tmp_path)
    assert "broad-validation-command" in _codes(report)
    assert main([str(index), "--root", str(tmp_path)]) == 1


def test_directory_validation_target_is_error(tmp_path):
    (tmp_path / "tests" / "sub").mkdir(parents=True)
    index = _with_validation(tmp_path, ["pytest tests/sub -q"], required=True)
    report = check_graph(index, tmp_path)
    assert "directory-validation-target" in _codes(report)
    assert main([str(index), "--root", str(tmp_path)]) == 1


def test_unknown_validation_path_is_warning(tmp_path):
    index = _with_validation(tmp_path, ["pytest tests/ghost.py -q"], required=True)
    report = check_graph(index, tmp_path)
    unknown = [f for f in report.findings if f.code == "validation-path-unknown"]
    assert unknown and unknown[0].level == "warning"
    # A warning alone must not fail the graph.
    assert main([str(index), "--root", str(tmp_path)]) == 0


def test_declared_or_existing_file_passes(tmp_path):
    index = _with_validation(
        tmp_path,
        ["pytest tests/foo.py::test_x -q"],
        required=True,
        files={"tests/foo.py": "CREATE"},
    )
    report = check_graph(index, tmp_path)
    contract_codes = {
        "missing-validation-commands",
        "non-pytest-validation-command",
        "broad-validation-command",
        "directory-validation-target",
        "validation-path-unknown",
    }
    assert not (contract_codes & set(_codes(report)))
    assert main([str(index), "--root", str(tmp_path)]) == 0
