from __future__ import annotations

import json
from pathlib import Path

from scripts.sdd.check_task_graph import _load_contract, check_graph, main, module_of, parse_declared_files

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


def _test_contract_header(tests: list[str]) -> dict:
    """Build an index header with a valid cached test contract."""
    contract = _load_contract()
    normalized = contract.parse_spec_contract(
        "### Validation Contract\n\n" + "tests:\n" + "\n".join(f"- {test}" for test in tests) + "\nmarkers: none\n"
    )
    assert normalized is not None
    return {
        "parallel_semantics": "exclusive",
        "test_contract": contract.contract_to_header(normalized),
    }


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


def test_missing_dependency_suppressed_when_notes_name_the_creator(tmp_path):
    """A parallelism_notes that names the creating task argues the non-edge (issue 56ba2e9689cd)."""
    tasks = [
        {"id": "TASK-1", "files": {"pkg/models.py": "CREATE"}, "validation": _self_validation("TASK-1")},
        {
            "id": "TASK-2",
            "files": {"pkg/api.py": "CREATE"},
            "contract": "uses `pkg/models.py`",
            "notes": "mentions pkg/models.py in prose only, so no edge to TASK-1",
            "validation": _self_validation("TASK-2"),
        },
        {
            "id": "TASK-3",
            "files": {"pkg/cli.py": "CREATE"},
            "contract": "uses `pkg/models.py`",
            "notes": "no edge to TASK-10 (a different task)",
            "validation": _self_validation("TASK-3"),
        },
    ]
    report = check_graph(_repo(tmp_path, tasks), tmp_path)
    missing = [f for f in report.findings if f.code == "possible-missing-dependency"]
    assert [f.tasks for f in missing] == [["TASK-3", "TASK-1"]]


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


def test_test_contract_findings(tmp_path):
    """A cached contract reports malformed, missing, real_llm, and uncovered operands."""
    task_test = "tests/task_test.py"
    missing = "tests/missing.py"
    real_llm = "tests/real_llm/test_live.py"
    (tmp_path / task_test).parent.mkdir()
    (tmp_path / task_test).write_text("def test_task(): pass\n")
    index = _repo(
        tmp_path,
        [
            {
                "id": "TASK-1",
                "files": {"tests/declared.py": "CREATE"},
                "validation": [f"pytest {task_test} -q"],
            }
        ],
        header=_test_contract_header([missing, real_llm, "tests/declared.py"]),
    )
    findings = {finding.code: finding for finding in check_graph(index, tmp_path).findings}
    assert findings["test-contract-operand-missing"].level == "error"
    assert findings["test-contract-real-llm"].level == "error"
    assert findings["test-contract-task-tests-uncovered"].level == "warning"
    assert "tests/declared.py" not in findings["test-contract-operand-missing"].message

    malformed = json.loads(index.read_text())
    malformed["test_contract"] = {"schema": 1}
    index.write_text(json.dumps(malformed))
    malformed_findings = check_graph(index, tmp_path).findings
    assert [(finding.level, finding.code) for finding in malformed_findings] == [("error", "test-contract-malformed")]


def test_legacy_index_has_no_test_contract_findings(tmp_path):
    """Indexes without a cached test contract retain their existing behavior."""
    report = check_graph(
        _repo(
            tmp_path,
            [{"id": "TASK-1", "files": {}, "validation": _self_validation("TASK-1")}],
        ),
        tmp_path,
    )
    assert not [finding for finding in report.findings if finding.code.startswith("test-contract-")]
