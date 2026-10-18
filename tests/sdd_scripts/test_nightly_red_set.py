"""Tests for scripts/sdd/nightly_red_set.py (FEAT-699 TASK-4453)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "sdd"))

import nightly_red_set as nrs  # noqa: E402

XML = """<testsuites><testsuite>
<testcase classname="tests.unit.test_a.TestC" name="test_bad"><failure>x</failure></testcase>
<testcase classname="tests.unit.test_a" name="test_err"><error>x</error></testcase>
<testcase classname="tests.unit.test_a" name="test_ok"/>
</testsuite></testsuites>"""


def test_nodeid():
    assert nrs.nodeid_from_testcase("tests.unit.test_a.TestC", "test_x") == "tests/unit/test_a.py::TestC::test_x"


def test_new_reds_exit_1(tmp_path):
    (tmp_path / "root.xml").write_text(XML)
    out = tmp_path / "out.json"
    assert nrs.main([str(tmp_path), "--out", str(out)]) == 1
    data = json.loads(out.read_text())
    assert len(data["suites"]["root"]) == 2
    assert len(data["new_reds"]) == 2


def test_previous_suppresses(tmp_path):
    (tmp_path / "root.xml").write_text(XML)
    first = tmp_path / "first.json"
    nrs.main([str(tmp_path), "--out", str(first)])
    out = tmp_path / "out.json"
    assert nrs.main([str(tmp_path), "--out", str(out), "--previous", str(first)]) == 0
    assert json.loads(out.read_text())["new_reds"] == []
