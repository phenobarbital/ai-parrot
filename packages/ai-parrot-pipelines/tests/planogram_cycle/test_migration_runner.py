"""Offline tests for the row-level planogram migration runner."""

import copy
import json

import pytest

from parrot_pipelines.planogram import migration_runner
from parrot_pipelines.planogram.migration import check_row
from parrot_pipelines.planogram.migration_runner import (
    _ALTER_SQL_PATH,
    _EXPORT_ACTIVE_SQL,
    _EXPORT_ALL_SQL,
    _main,
    _quote,
    build_candidate,
    candidate_problems,
    render_update,
)


@pytest.fixture
def clean_row() -> dict:
    """A legacy row that converts without human decisions."""
    return {
        "config_name": "acme v1",
        "planogram_type": "product_on_shelves",
        "updated_at": "2026-01-01 10:00:00.123456+00:00",
        "slots_definition": None,
        "planogram_config": {
            "brand": "Acme",
            "shelves": [
                {
                    "level": "middle",
                    "compliance_threshold": 0.9,
                    "products": [
                        {
                            "name": "ES-400",
                            "product_type": "product",
                            "quantity_range": [2, 2],
                            "descriptors": {"display_name": "EcoTank ES-400"},
                        }
                    ],
                }
            ],
        },
    }


@pytest.fixture
def ranged_row(clean_row) -> dict:
    """A legacy row whose quantity range needs a human decision."""
    row = copy.deepcopy(clean_row)
    row["config_name"] = "acme ranged"
    row["planogram_config"]["shelves"][0]["products"][0]["quantity_range"] = [1, 3]
    return row


@pytest.fixture
def fake_db(monkeypatch):
    """Replace the two database helpers; records executed SQL."""
    state = {"rows": [], "executed": []}

    async def fetch_rows(_dsn, sql):
        state["executed"].append(sql)
        return [dict(row) for row in state["rows"]]

    async def execute(_dsn, sql):
        state["executed"].append(sql)

    monkeypatch.setattr(migration_runner, "_fetch_rows", fetch_rows)
    monkeypatch.setattr(migration_runner, "_execute", execute)
    monkeypatch.setattr(migration_runner, "_default_dsn", lambda: "postgres://user:secret@db.test:5432/navigator")
    return state


def test_export_sql_is_select_only():
    for sql in (_EXPORT_ACTIVE_SQL, _EXPORT_ALL_SQL):
        assert sql.upper().startswith("SELECT")
        assert not any(word in sql.upper() for word in ("UPDATE", "INSERT", "DELETE", "ALTER"))


def test_alter_script_exists():
    assert "ADD COLUMN IF NOT EXISTS slots_definition" in _ALTER_SQL_PATH.read_text(encoding="utf-8")


def test_quote_avoids_tag_collision():
    assert _quote("plain") == "$pgm$plain$pgm$"
    assert _quote("has $pgm$ inside") == "$pgm1$has $pgm$ inside$pgm1$"


def test_build_candidate_is_ready_and_keeps_original_config(clean_row):
    candidate = build_candidate(clean_row)
    assert candidate_problems(candidate) == []
    assert candidate["planogram_config"]["shelves"] == clean_row["planogram_config"]["shelves"]
    assert "rule_bindings" in candidate["planogram_config"]
    assert "rule_bindings" not in clean_row["planogram_config"]
    assert check_row(candidate).ok


def test_unresolved_candidate_is_blocked_until_reviewed(ranged_row):
    candidate = build_candidate(ranged_row)
    assert any(problem.startswith("unresolved:") for problem in candidate_problems(candidate))
    candidate["unresolved"] = []
    assert candidate_problems(candidate) == []


def test_cleared_unresolved_does_not_hide_an_invalid_definition(ranged_row):
    candidate = build_candidate(ranged_row)
    candidate["unresolved"] = []
    candidate["slots_definition"] = {}
    assert candidate_problems(candidate) == ["slots_definition is missing"]


def test_render_update_guards_on_export_timestamp(clean_row):
    sql = render_update(build_candidate(clean_row))
    assert sql.count("UPDATE troc.planograms_configurations") == 1
    assert "WHERE config_name = $pgm$acme v1$pgm$" in sql
    assert "updated_at = $pgm$2026-01-01 10:00:00.123456+00:00$pgm$::timestamptz" in sql
    assert "IF NOT FOUND THEN" in sql and "RAISE EXCEPTION" in sql
    assert "DELETE" not in sql.upper()


def test_full_cycle_export_convert_render_apply(tmp_path, fake_db, clean_row):
    fake_db["rows"] = [clean_row]
    assert _main(["export", "--dir", str(tmp_path)]) == 0
    exported = tmp_path / "original" / "acme_v1.json"
    assert json.loads(exported.read_text())["config_name"] == "acme v1"
    assert _main(["export", "--dir", str(tmp_path)]) == 1, "an existing export is never overwritten"

    assert _main(["convert", "--dir", str(tmp_path)]) == 0
    assert _main(["render", "--dir", str(tmp_path)]) == 0
    sql = (tmp_path / "apply.sql").read_text()
    assert sql.count("BEGIN;") == 1 and sql.rstrip().endswith("COMMIT;")

    executed_before = len(fake_db["executed"])
    assert _main(["apply", "--dir", str(tmp_path)]) == 0
    assert len(fake_db["executed"]) == executed_before, "apply without --yes executes nothing"
    assert _main(["apply", "--dir", str(tmp_path), "--yes"]) == 0
    assert fake_db["executed"][-1] == sql


def test_blocked_candidate_stops_render(tmp_path, fake_db, clean_row, ranged_row):
    fake_db["rows"] = [clean_row, ranged_row]
    assert _main(["export", "--dir", str(tmp_path)]) == 0
    assert _main(["convert", "--dir", str(tmp_path)]) == 2
    assert _main(["render", "--dir", str(tmp_path)]) == 2
    assert not (tmp_path / "apply.sql").exists()
    assert _main(["apply", "--dir", str(tmp_path), "--yes"]) == 1


def test_convert_keeps_review_edits_unless_forced(tmp_path, fake_db, ranged_row):
    fake_db["rows"] = [ranged_row]
    assert _main(["export", "--dir", str(tmp_path)]) == 0
    assert _main(["convert", "--dir", str(tmp_path)]) == 2
    path = tmp_path / "candidates" / "acme_ranged.json"
    reviewed = json.loads(path.read_text())
    reviewed["unresolved"] = []
    path.write_text(json.dumps(reviewed))
    assert _main(["convert", "--dir", str(tmp_path)]) == 0
    assert json.loads(path.read_text())["unresolved"] == []
    assert _main(["convert", "--dir", str(tmp_path), "--force"]) == 2


def test_ready_and_unsupported_rows_get_no_candidate(tmp_path, fake_db, clean_row):
    ready = build_candidate(clean_row)
    fake_db["rows"] = [
        {**clean_row, "slots_definition": ready["slots_definition"], "planogram_config": ready["planogram_config"]},
        {"config_name": "legacy", "planogram_type": "not_a_type", "planogram_config": {}},
    ]
    assert _main(["export", "--dir", str(tmp_path)]) == 0
    assert _main(["convert", "--dir", str(tmp_path)]) == 2
    assert list((tmp_path / "candidates").iterdir()) == []


def test_alter_prints_without_yes_and_executes_with_it(fake_db, capsys):
    assert _main(["alter"]) == 0
    assert fake_db["executed"] == []
    assert "ALTER TABLE" in capsys.readouterr().out
    assert _main(["alter", "--yes"]) == 0
    assert "ALTER TABLE troc.planograms_configurations" in fake_db["executed"][0]


def test_missing_dsn_is_a_usage_error(tmp_path, monkeypatch):
    monkeypatch.setattr(migration_runner, "_default_dsn", lambda: None)
    assert _main(["export", "--dir", str(tmp_path)]) == 1


def test_target_logs_host_and_database_without_credentials(fake_db, caplog):
    with caplog.at_level("INFO"):
        assert _main(["target"]) == 0
    assert "db.test:5432/navigator" in caplog.text
    assert "secret" not in caplog.text and "user" not in caplog.text
    assert fake_db["executed"] == []
