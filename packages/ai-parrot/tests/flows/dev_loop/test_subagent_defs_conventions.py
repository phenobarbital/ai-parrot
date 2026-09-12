"""The dev-loop re-export is the SAME object as the leaf module's (FEAT-553)."""

from parrot.flows import conventions
from parrot.flows.dev_loop import _subagent_defs


def test_reexport_identity():
    assert _subagent_defs.load_project_conventions is conventions.load_project_conventions
    assert _subagent_defs.CONVENTIONS_PREAMBLE == conventions.CONVENTIONS_PREAMBLE
    assert _subagent_defs.CODER_RULE_NAMES == conventions.CODER_RULE_NAMES
