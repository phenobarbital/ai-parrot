"""Tests for ``scripts/sdd/spec_tools.py`` (FEAT-633 TASK-4334, Q1 residual)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts.sdd import spec_tools
from scripts.sdd.spec_tools import main

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROMPT = _REPO_ROOT / "sdd" / "templates" / "design_research.prompt.md"
_SCHEMA = _REPO_ROOT / "sdd" / "templates" / "design_research.schema.json"

_SAMPLE_SUGGESTIONS = {
    "summary": "Two suggestions on the accepted design.",
    "suggestions": [
        {
            "id": "S1",
            "kind": "architecture",
            "title": "Stage output under sdd/state",
            "rationale": "artifacts/ is gitignored.",
            "affected_paths": [".gitignore"],
            "risk": "low",
            "confidence": "high",
        },
        {
            "id": "S2",
            "kind": "testing",
            "title": "Add twin parity test",
            "rationale": "Twins drift silently.",
            "affected_paths": [".agent/workflows/sdd-spec.md"],
            "risk": "medium",
            "confidence": "medium",
        },
    ],
}


def _write_brief_inputs(dr: Path) -> None:
    for i, name in enumerate(spec_tools.BRIEF_INPUTS):
        (dr / f"{name}.txt").write_text(f"  value for {name} #{i}\n", encoding="utf-8")


def _legacy_render(dr: Path, template: Path) -> str:
    """The exact logic of the retired heredoc (sdd-spec.md §3b.2) — the oracle for AC-2."""
    text = template.read_text(encoding="utf-8")
    names = [
        "problem_statement",
        "constraints_and_goals",
        "recommended_option_or_scope",
        "code_context_paths",
        "open_questions",
        "question",
    ]
    for name in names:
        value = (dr / f"{name}.txt").read_text(encoding="utf-8").strip()
        text = text.replace("{{" + name + "}}", value)
    assert "{{" not in text
    return text


# --- init-run -------------------------------------------------------------------------------


def test_init_run_writes_expected_keys(tmp_path: Path) -> None:
    (tmp_path / "probe.txt").write_text("probe ok\n", encoding="utf-8")
    rc = main(
        [
            "init-run",
            str(tmp_path),
            "--model",
            "gpt-x",
            "--codex-version",
            "1.2.3",
            "--probe-file",
            str(tmp_path / "probe.txt"),
        ]
    )
    assert rc == 0
    data = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert data == {
        "model": "gpt-x",
        "codex_cli_version": "1.2.3",
        "reasoning_effort": "high",
        "timeout_s": 600,
        "probe_output": "probe ok\n",
    }


def test_init_run_missing_probe_is_empty_string(tmp_path: Path) -> None:
    rc = main(
        [
            "init-run",
            str(tmp_path),
            "--model",
            "m",
            "--codex-version",
            "v",
            "--probe-file",
            str(tmp_path / "absent.txt"),
        ]
    )
    assert rc == 0
    assert json.loads((tmp_path / "run.json").read_text())["probe_output"] == ""


# --- render-brief ---------------------------------------------------------------------------


def test_render_brief_matches_legacy_heredoc(tmp_path: Path) -> None:
    _write_brief_inputs(tmp_path)
    assert main(["render-brief", str(tmp_path), "--template", str(_PROMPT)]) == 0
    assert (tmp_path / "brief.md").read_text(encoding="utf-8") == _legacy_render(tmp_path, _PROMPT)


def test_render_brief_refuses_unfilled_placeholder(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write_brief_inputs(tmp_path)
    tpl = tmp_path / "tpl.md"
    tpl.write_text("{{problem_statement}} and {{not_an_input}}", encoding="utf-8")
    assert main(["render-brief", str(tmp_path), "--template", str(tpl)]) == 1
    assert "unfilled placeholder" in capsys.readouterr().err
    assert not (tmp_path / "brief.md").exists()


def test_render_brief_refuses_missing_input(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write_brief_inputs(tmp_path)
    (tmp_path / "question.txt").unlink()
    assert main(["render-brief", str(tmp_path), "--template", str(_PROMPT)]) == 1
    assert "question.txt" in capsys.readouterr().err
    assert not (tmp_path / "brief.md").exists()


# --- stamp-run ------------------------------------------------------------------------------


def test_stamp_run_updates_in_place(tmp_path: Path) -> None:
    (tmp_path / "run.json").write_text(json.dumps({"model": "m"}), encoding="utf-8")
    rc = main(
        [
            "stamp-run",
            str(tmp_path),
            "--started-at",
            "2026-10-15T00:00:00+00:00",
            "--ended-at",
            "2026-10-15T00:01:00+00:00",
            "--exit-code",
            "124",
        ]
    )
    assert rc == 0
    data = json.loads((tmp_path / "run.json").read_text())
    assert data == {
        "model": "m",
        "started_at": "2026-10-15T00:00:00+00:00",
        "ended_at": "2026-10-15T00:01:00+00:00",
        "exit_code": 124,
    }


def test_stamp_run_missing_run_json_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["stamp-run", str(tmp_path), "--started-at", "a", "--ended-at", "b", "--exit-code", "0"])
    assert rc == 1
    assert "run.json" in capsys.readouterr().err


# --- validate-suggestions -------------------------------------------------------------------


def test_validate_suggestions_ok(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "suggestions.json").write_text(json.dumps(_SAMPLE_SUGGESTIONS), encoding="utf-8")
    assert main(["validate-suggestions", str(tmp_path), "--schema", str(_SCHEMA)]) == 0
    assert capsys.readouterr().out == "2 suggestions\n"


def test_validate_suggestions_rejects_unknown_kind(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = json.loads(json.dumps(_SAMPLE_SUGGESTIONS))
    bad["suggestions"][0]["kind"] = "vibes"
    (tmp_path / "suggestions.json").write_text(json.dumps(bad), encoding="utf-8")
    assert main(["validate-suggestions", str(tmp_path), "--schema", str(_SCHEMA)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "failed schema validation" in captured.err


def test_validate_suggestions_missing_file_exits_1(tmp_path: Path) -> None:
    assert main(["validate-suggestions", str(tmp_path), "--schema", str(_SCHEMA)]) == 1


# --- check-path -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rel", "expected"),
    [(".", 0), ("child/file.txt", 0), ("../outside.txt", 1), ("escape-link", 1)],
)
def test_check_path_inside_and_outside(tmp_path: Path, rel: str, expected: int) -> None:
    root = tmp_path / "root"
    (root / "child").mkdir(parents=True)
    (root / "child" / "file.txt").write_text("x", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("y", encoding="utf-8")
    os.symlink(tmp_path / "outside.txt", root / "escape-link")
    assert main(["check-path", str(root / rel), "--root", str(root)]) == expected


# --- commit-intake --------------------------------------------------------------------------


def test_commit_intake_stamps_fields(tmp_path: Path) -> None:
    intake = tmp_path / "intake.json"
    intake.write_text(json.dumps({"phase": "staged", "slug": "x"}), encoding="utf-8")
    assert main(["commit-intake", str(intake), "--feat-id", "FEAT-633"]) == 0
    data = json.loads(intake.read_text())
    assert data["feat_id"] == "FEAT-633"
    assert data["phase"] == "committed"
    assert data["slug"] == "x"
    assert data["updated_at"].endswith("+00:00")


def test_commit_intake_missing_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["commit-intake", str(tmp_path / "intake.json"), "--feat-id", "FEAT-1"]) == 1
    assert "intake.json" in capsys.readouterr().err


# --- existing-feature-id --------------------------------------------------------------------


def test_existing_feature_id_found_and_empty(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[tuple[Path, str]] = []

    def fake(root: Path, label: str):
        seen.append((root, label))
        return ("FEAT-633", "sdd/specs/x.spec.md") if label == "owned" else None

    monkeypatch.setattr(spec_tools, "existing_feature_id", fake)
    assert main(["existing-feature-id", "owned"]) == 0
    assert capsys.readouterr().out == "FEAT-633\n"
    assert main(["existing-feature-id", "fresh", "--root", "/tmp"]) == 0
    assert capsys.readouterr().out == "\n"
    assert seen == [(Path("."), "owned"), (Path("/tmp"), "fresh")]


def test_help_lists_all_subcommands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for sub in (
        "init-run",
        "render-brief",
        "stamp-run",
        "validate-suggestions",
        "check-path",
        "commit-intake",
        "existing-feature-id",
    ):
        assert sub in out
