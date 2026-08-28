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
    read = {
        token.split(".", 1)[1].rstrip(" |&);,")
        for token in arm.split()
        if token.startswith("a.")
    }
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
