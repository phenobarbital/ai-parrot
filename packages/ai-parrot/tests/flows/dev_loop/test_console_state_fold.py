"""The consoles' ``run/closed`` fold must consume every ``RunClosed`` field.

Asserted against the HTML source because the repo has no JS test harness.

Regression (run-949f8afa): the fold read ``a.phase`` — a field ``RunClosed``
does not have — so every finished run rendered as phase ``"closed"``, and it
dropped ``a.pr_url``/``a.jira_issue_key`` entirely. ``run/closed`` is the only
action that reliably carries them (the runner reads both off the Handoff
node's response), so a run whose ``run/prLinked`` never landed showed the
"Run finished without a pull request" warning while its PR was open.

These are contract tests: the expected field names come from the Pydantic
model, so changing ``RunClosed`` fails here instead of silently desyncing
the browser-side fold from the server reducer.
"""

from pathlib import Path

import pytest

from parrot.flows.dev_loop.session_state import RunClosed

_REPO_ROOT = Path(__file__).resolve().parents[5]
_STATIC = _REPO_ROOT / "examples" / "dev_loop" / "static"

# Both consoles carry the same fold; dev.html is a copy-and-trim of index.html.
_CONSOLES = ("index.html", "dev.html")


def _console(name: str) -> str:
    return (_STATIC / name).read_text(encoding="utf-8")


def _run_closed_arm(source: str) -> str:
    """Return the ``case "run/closed":`` arm of ``foldAction``, up to ``break``."""
    start = source.index('case "run/closed":')
    end = source.index("break;", start)
    return source[start:end]


@pytest.mark.parametrize("console", _CONSOLES)
def test_run_closed_arm_consumes_every_action_field(console):
    """Every payload field of RunClosed must be read by the fold."""
    arm = _run_closed_arm(_console(console))
    payload = set(RunClosed.model_fields) - {"type"}
    assert payload, "RunClosed lost its payload fields — update this test"
    missing = sorted(f for f in payload if f"a.{f}" not in arm)
    assert not missing, f"{console} run/closed fold ignores {missing}"


@pytest.mark.parametrize("console", _CONSOLES)
def test_run_closed_arm_reads_no_field_the_action_lacks(console):
    """`a.phase` was the original bug: a field RunClosed never sends."""
    arm = _run_closed_arm(_console(console))
    known = set(RunClosed.model_fields) | {"ts"}
    read = {token.split(".", 1)[1].rstrip(" |&);,") for token in arm.split() if token.startswith("a.")}
    unknown = sorted(f for f in read if f and f not in known)
    assert not unknown, f"{console} run/closed fold reads unknown field(s) {unknown}"


@pytest.mark.parametrize("console", _CONSOLES)
def test_run_closed_projects_the_terminal_pr_and_ticket(console):
    """The PR banner and Jira chip must survive a run with no `run/prLinked`."""
    arm = _run_closed_arm(_console(console))
    assert "s.prUrl = a.pr_url" in arm
    assert "s.jiraKey = a.jira_issue_key" in arm
    # ...and the outcome must reach the phase the summary tag renders.
    assert "s.phase = a.outcome" in arm


# ---------------------------------------------------------------------------
# Narrative channel (node/progress) + narrative/raw event view
# ---------------------------------------------------------------------------


def _arm(source: str, case: str) -> str:
    """Return the ``case "<type>":`` arm of ``foldAction``, up to ``break``."""
    start = source.index(f'case "{case}":')
    end = source.index("break;", start)
    return source[start:end]


@pytest.mark.parametrize("console", _CONSOLES)
def test_node_progress_arm_consumes_every_action_field(console):
    """The browser-side fold must carry every NodeProgress field into the entry."""
    from parrot.flows.dev_loop.session_state import NodeProgress

    arm = _arm(_console(console), "node/progress")
    payload = set(NodeProgress.model_fields) - {"type"}
    missing = sorted(f for f in payload if f"a.{f}" not in arm)
    assert not missing, f"{console} node/progress fold ignores {missing}"


@pytest.mark.parametrize("console", _CONSOLES)
def test_node_progress_is_bounded_like_the_reducer(console):
    from parrot.flows.dev_loop.session_state import PROGRESS_MAX

    source = _console(console)
    assert f"const PROGRESS_MAX = {PROGRESS_MAX};" in source
    assert ".slice(-PROGRESS_MAX)" in _arm(source, "node/progress")


@pytest.mark.parametrize("console", _CONSOLES)
def test_narrative_view_reads_the_delta_and_seat_fields_the_server_sends(console):
    """``thinking`` rides ``dispatch/delta`` → ``SeatState.last_thinking``; both consoles read it."""
    from parrot.flows.dev_loop.session_state import DispatchDelta, SeatState

    source = _console(console)
    assert "thinking" in DispatchDelta.model_fields and "last_thinking" in SeatState.model_fields
    assert "next.last_thinking = String(a.thinking)" in source
    assert "s.last_thinking" in source
    # The raw/narrative toggle exists, is persisted, and the filter keeps the
    # rows an operator needs (tool calls, failures, the assistant's words).
    assert 'data-evmode="' in source
    assert "function narrativeWorthy(e)" in source
    for kind in ("dispatch.tool_use", "dispatch.tool_result", "dispatch.message", "dispatch.failed"):
        assert f'"{kind}"' in source
    assert "function progressEvents(nodeId)" in source


# ---------------------------------------------------------------------------
# Run summary: changeset (files changed) + per-seat usage, sourced from the bundle
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("console", _CONSOLES)
def test_summary_actions_are_folded(console):
    from parrot.flows.dev_loop.session_state import ChangesetRecorded, SeatUsageRecorded

    source = _console(console)
    for action_cls, key in ((ChangesetRecorded, "changeset"), (SeatUsageRecorded, "seats")):
        action_type = action_cls.model_fields["type"].default
        arm = _arm(source, action_type)
        assert f"a.{key}" in arm, f"{console} {action_type} fold ignores a.{key}"
    # Snapshot adoption carries both projections too.
    assert "st.changeset" in source and "st.seat_usage" in source


@pytest.mark.parametrize("console", _CONSOLES)
def test_summary_fetches_bundle_and_usage_and_renders_every_field(console):
    from parrot.flows.dev_loop.session_state import ChangedFile, ChangeSet, SeatUsageSummary

    source = _console(console)
    assert "bundle?format=${fmt}" in source and 'fetchJson("json")' in source and 'fetchJson("usage")' in source
    assert "function loadBundle(" in source and "loadBundle();" in source
    assert "function filesChangedCard(" in source and "function seatsCard(" in source
    # Every ChangeSet / ChangedFile field the card renders is read by name.
    for field in (
        "files",
        "total_additions",
        "total_deletions",
        "commits",
        "base_ref",
        "branch",
        "uncommitted",
        "worktree_path",
    ):
        assert field in ChangeSet.model_fields and f"cs.{field}" in source, f"{console}: cs.{field}"
    for field in ("path", "additions", "deletions", "status", "binary"):
        assert field in ChangedFile.model_fields and f"f.{field}" in source, f"{console}: f.{field}"
    for field in (
        "seat",
        "backend",
        "model",
        "tasks_handled",
        "tasks_merged",
        "attempts",
        "retries",
        "failures",
        "duration_s",
        "input_tokens",
        "output_tokens",
        "usage_known",
    ):
        assert field in SeatUsageSummary.model_fields and f"s.{field}" in source, f"{console}: s.{field}"
