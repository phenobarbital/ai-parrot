"""Loader test for the sdd-codereview subagent (FEAT-250 TASK-005)."""
from __future__ import annotations

import pytest

from parrot.flows.dev_loop._subagent_defs import (
    _VALID_NAMES,
    load_subagent_definition,
)


def test_codereview_in_valid_names():
    assert "sdd-codereview" in _VALID_NAMES


def test_codereview_subagent_loads_and_strips_frontmatter():
    body = load_subagent_definition("sdd-codereview")
    assert body  # non-empty
    # Frontmatter must be stripped: the first line is no longer the fence.
    assert body.splitlines()[0].strip() != "---"


def test_codereview_body_demands_single_json_object():
    body = load_subagent_definition("sdd-codereview")
    # The prompt must instruct the documented JSON verdict shape.
    assert "passed" in body
    assert "findings" in body
    assert "summary" in body
    assert "Output Contract" in body


def test_codereview_body_is_write_enabled_posture():
    """FEAT-270: the reviewer may fix issues it finds and commit the fix."""
    body = load_subagent_definition("sdd-codereview").lower()
    assert "fix" in body
    assert "commit" in body
    assert "files_modified" in body


def test_unknown_subagent_still_rejected():
    with pytest.raises(ValueError):
        load_subagent_definition("sdd-nope")
