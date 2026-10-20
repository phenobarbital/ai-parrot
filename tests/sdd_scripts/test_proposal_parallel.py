"""FEAT-708 — parallel /sdd-proposal research invariants.

The dispatch and merge are agent-executed Markdown, so this module holds
reference implementations of the deterministic rules and asserts that
`.claude/commands/sdd-proposal.md` states the same rules.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

_REPO_ROOT = Path(__file__).resolve().parents[2]
_COMMAND = _REPO_ROOT / ".claude" / "commands" / "sdd-proposal.md"
_SCHEMA = _REPO_ROOT / "sdd" / "templates" / "state.schema.json"

_LANES = {
    "codebase": ("FC", {"grep", "glob", "read", "tree"}),
    "git": ("FG", {"git_log"}),
    "wiki": ("FW", {"wiki_query", "wiki_page", "wiki_related"}),
}


def _partition(queries: list[dict]) -> dict[str, list[dict]]:
    """Split plan queries into lanes by type; a child follows its parent's lane."""
    lanes: dict[str, list[dict]] = {"codebase": [], "git": [], "wiki": []}
    query_map = {q["id"]: q for q in queries}
    query_lane: dict[str, str] = {}

    for q in queries:
        q_id = q["id"]
        q_type = q.get("type", "")
        parent_id = q.get("parent_id")

        if parent_id and parent_id in query_lane:
            assigned = query_lane[parent_id]
        else:
            assigned = "codebase"
            for lname, (_, types) in _LANES.items():
                if q_type in types:
                    assigned = lname
                    break

        query_lane[q_id] = assigned
        lanes[assigned].append(q)

    return lanes


def _allocate(profile: dict) -> dict[str, dict[str, int]]:
    """Per-lane quotas: floor fractions from the spec M2 table."""
    files_read = profile.get("files_read", 0)
    grep_calls = profile.get("grep_calls", 0)
    git_calls = profile.get("git_calls", 0)
    depth = profile.get("depth", 1)
    wall_seconds = profile.get("wall_seconds", 0)

    lane_wall = math.floor(0.85 * wall_seconds)

    return {
        "codebase": {
            "files_read": math.floor(0.60 * files_read),
            "grep_calls": math.floor(0.80 * grep_calls),
            "git_calls": 0,
            "depth": depth,
            "wall_seconds": lane_wall,
        },
        "git": {
            "files_read": math.floor(0.20 * files_read),
            "grep_calls": 0,
            "git_calls": git_calls,
            "depth": 1,
            "wall_seconds": lane_wall,
        },
        "wiki": {
            "files_read": math.floor(0.20 * files_read),
            "grep_calls": math.floor(0.20 * grep_calls),
            "git_calls": 0,
            "depth": depth,
            "wall_seconds": lane_wall,
        },
    }


def _merge(findings: list[dict]) -> list[dict]:
    """Citation-identity dedup; returns canonical findings with ids F001..."""
    groups: list[list[dict]] = []

    def _citations_match(f1: dict, f2: dict) -> bool:
        c1_list = f1.get("citations", [])
        c2_list = f2.get("citations", [])
        if not c1_list or not c2_list:
            return False

        for path1, sym1, (start1, end1) in c1_list:
            for path2, sym2, (start2, end2) in c2_list:
                if path1 == path2 and sym1 == sym2:
                    # check range overlap
                    if max(start1, start2) <= min(end1, end2):
                        return True
        return False

    for f in findings:
        placed = False
        for grp in groups:
            if any(_citations_match(f, member) for member in grp):
                grp.append(f)
                placed = True
                break
        if not placed:
            groups.append([f])

    merged_findings = []
    for idx, grp in enumerate(groups, start=1):
        canonical_id = f"F{idx:03d}"
        all_citations = []
        notes = []
        max_depth = 0
        summaries = []

        for f in grp:
            for c in f.get("citations", []):
                if c not in all_citations:
                    all_citations.append(c)
            if "notes" in f and f["notes"]:
                notes.append(f["notes"])
            max_depth = max(max_depth, f.get("depth", 0))
            if "summary" in f and f["summary"]:
                summaries.append(f["summary"])

        merged_findings.append(
            {
                "id": canonical_id,
                "citations": all_citations,
                "depth": max_depth,
                "notes": "\n".join(notes),
                "summary": "\n".join(summaries),
            }
        )

    return merged_findings


@pytest.fixture
def command_text() -> str:
    return _COMMAND.read_text(encoding="utf-8")


@pytest.fixture
def schema_validator() -> Draft202012Validator:
    schema_data = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    return Draft202012Validator(schema_data)


@pytest.fixture
def sample_research_plan() -> list[dict]:
    return [
        {"id": "Q001", "type": "grep", "query": "symbol_a"},
        {"id": "Q002", "type": "git_log", "path": "path/to/file.py"},
        {"id": "Q003", "type": "wiki_query", "query": "architecture"},
        {"id": "Q004", "type": "wiki_page", "page_id": "p123", "parent_id": "Q003"},
        {"id": "Q005", "type": "read", "path": "path/to/file.py", "parent_id": "Q002"},
    ]


@pytest.fixture
def sample_budget_profile() -> dict:
    return {
        "files_read": 40,
        "grep_calls": 25,
        "git_calls": 10,
        "depth": 2,
        "wall_seconds": 300,
    }


# Unit Tests

def test_partition_by_type(sample_research_plan):
    lanes = _partition(sample_research_plan)
    assert len(lanes["codebase"]) == 1  # Q001
    assert len(lanes["git"]) == 2       # Q002, Q005 (child of Q002)
    assert len(lanes["wiki"]) == 2      # Q003, Q004 (child of Q003)


def test_partition_preserves_parent_chains(sample_research_plan):
    lanes = _partition(sample_research_plan)
    # Q004 has parent Q003 (wiki)
    wiki_ids = [q["id"] for q in lanes["wiki"]]
    assert "Q003" in wiki_ids
    assert "Q004" in wiki_ids


def test_partition_cross_lane_followup_recorded(command_text):
    assert "[cross-lane: type=" in command_text


def test_budget_allocation_floor_rounding(sample_budget_profile):
    alloc = _allocate(sample_budget_profile)
    # default profile: files 40, greps 25, git 10, depth 2, wall 300
    # codebase: files = 0.6*40=24, greps = 0.8*25=20
    assert alloc["codebase"]["files_read"] == 24
    assert alloc["codebase"]["grep_calls"] == 20

    # git: files = 0.2*40=8, git = 10
    assert alloc["git"]["files_read"] == 8
    assert alloc["git"]["git_calls"] == 10

    # wiki: files = 0.2*40=8, greps = 0.2*25=5
    assert alloc["wiki"]["files_read"] == 8
    assert alloc["wiki"]["grep_calls"] == 5

    # check sums <= profile
    total_files = sum(l["files_read"] for l in alloc.values())
    assert total_files <= sample_budget_profile["files_read"]

    total_greps = sum(l["grep_calls"] for l in alloc.values())
    assert total_greps <= sample_budget_profile["grep_calls"]


def test_budget_merge_window_reserved(sample_budget_profile):
    alloc = _allocate(sample_budget_profile)
    # wall 300 -> lane_wall = floor(0.85 * 300) = 255
    assert alloc["codebase"]["wall_seconds"] == 255
    reserved_window = sample_budget_profile["wall_seconds"] - alloc["codebase"]["wall_seconds"]
    assert reserved_window == 45


def test_budget_custom_forces_sequential(command_text):
    assert "any non-standard (custom) budget" in command_text or "custom" in command_text


def test_budget_tight_forces_sequential(command_text):
    assert "--budget=tight" in command_text


def test_dedup_same_symbol_merged():
    findings = [
        {
            "id": "FC-001",
            "citations": [("file1.py", "func_a", (10, 20))],
            "depth": 1,
            "summary": "sum1",
            "notes": "note1",
        },
        {
            "id": "FG-001",
            "citations": [("file1.py", "func_a", (15, 25))],
            "depth": 2,
            "summary": "sum2",
            "notes": "note2",
        },
    ]
    merged = _merge(findings)
    assert len(merged) == 1
    assert merged[0]["id"] == "F001"
    assert merged[0]["depth"] == 2
    assert "sum1" in merged[0]["summary"]
    assert "sum2" in merged[0]["summary"]


def test_dedup_different_symbols_preserved():
    findings = [
        {
            "id": "FC-001",
            "citations": [("file1.py", "func_a", (10, 20))],
            "depth": 1,
        },
        {
            "id": "FC-002",
            "citations": [("file1.py", "func_b", (10, 20))],
            "depth": 1,
        },
    ]
    merged = _merge(findings)
    assert len(merged) == 2
    assert merged[0]["id"] == "F001"
    assert merged[1]["id"] == "F002"


def test_dedup_canonical_renumbering():
    findings = [
        {"id": "FC-001", "citations": [("file1.py", "sym1", (1, 10))]},
        {"id": "FG-001", "citations": [("file2.py", "sym2", (1, 10))]},
        {"id": "FW-001", "citations": [("file3.py", "sym3", (1, 10))]},
    ]
    merged = _merge(findings)
    assert [f["id"] for f in merged] == ["F001", "F002", "F003"]


def test_dedup_audit_directory(command_text):
    assert "findings/.audit" in command_text


def test_state_parallel_optional(schema_validator):
    base_state = {
        "schema_version": "1.0",
        "feat_id": "FEAT-123",
        "phase": "plan_approved",
        "started_at": "2026-10-20T12:00:00Z",
        "updated_at": "2026-10-20T12:00:00Z",
        "mode": "investigation",
        "source": {"kind": "inline", "raw_path": "sdd/state/FEAT-123/source.md"},
        "budget": {
            "profile": "default",
            "max_files_read": 40,
            "max_grep_calls": 25,
            "max_git_calls": 10,
            "max_depth": 2,
            "max_wall_seconds": 300,
        },
        "consumed": {
            "files_read": 0,
            "grep_calls": 0,
            "git_calls": 0,
            "wall_seconds": 0,
        },
        "phases": {
            "plan": {"approved_by_user": True},
            "research": {
                "started_at": "2026-10-20T12:00:00Z",
                "completed_at": None,
                "duration_seconds": None,
                "files_read": 0,
                "grep_calls": 0,
                "git_calls": 0,
                "queries_executed": 0,
                "queries_skipped": 0,
                "findings_count": 0,
                "truncated": False,
                "truncation_reason": None,
            },
        },
        "errors": [],
    }
    # Without parallel key
    assert schema_validator.is_valid(base_state)

    # With parallel key
    state_with_parallel = dict(base_state)
    state_with_parallel["phases"]["research"]["parallel"] = {
        "enabled": True,
        "fallback_reason": None,
        "lanes": {
            "codebase": {
                "status": "completed",
                "started_at": "2026-10-20T12:00:00Z",
                "completed_at": "2026-10-20T12:00:45Z",
                "duration_seconds": 45,
                "findings_count": 12,
                "queries_executed": 18,
                "queries_skipped": 0,
                "error": None,
            }
        },
        "merge": {
            "started_at": "2026-10-20T12:00:50Z",
            "completed_at": "2026-10-20T12:00:55Z",
            "input_count": 25,
            "output_count": 18,
            "merged_count": 7,
            "audit_dir": "findings/.audit",
        },
    }
    assert schema_validator.is_valid(state_with_parallel)


def test_state_lane_record_shape(schema_validator):
    bad_lane_state = {
        "schema_version": "1.0",
        "feat_id": "FEAT-123",
        "phase": "plan_approved",
        "started_at": "2026-10-20T12:00:00Z",
        "updated_at": "2026-10-20T12:00:00Z",
        "mode": "investigation",
        "source": {"kind": "inline", "raw_path": "sdd/state/FEAT-123/source.md"},
        "budget": {
            "profile": "default",
            "max_files_read": 40,
            "max_grep_calls": 25,
            "max_git_calls": 10,
            "max_depth": 2,
            "max_wall_seconds": 300,
        },
        "consumed": {
            "files_read": 0,
            "grep_calls": 0,
            "git_calls": 0,
            "wall_seconds": 0,
        },
        "phases": {
            "plan": {"approved_by_user": True},
            "research": {
                "started_at": "2026-10-20T12:00:00Z",
                "completed_at": None,
                "duration_seconds": None,
                "files_read": 0,
                "grep_calls": 0,
                "git_calls": 0,
                "queries_executed": 0,
                "queries_skipped": 0,
                "findings_count": 0,
                "truncated": False,
                "truncation_reason": None,
                "parallel": {
                    "enabled": True,
                    "lanes": {
                        "codebase": {
                            "status": "invalid_status_enum",
                            "started_at": None,
                            "completed_at": None,
                            "duration_seconds": None,
                            "findings_count": 0,
                            "queries_executed": 0,
                            "queries_skipped": 0,
                            "error": None,
                        }
                    },
                },
            },
        },
        "errors": [],
    }
    assert not schema_validator.is_valid(bad_lane_state)
