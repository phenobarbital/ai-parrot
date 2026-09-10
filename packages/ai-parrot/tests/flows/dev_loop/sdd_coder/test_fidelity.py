from parrot.flows.dev_loop.sdd_coder.fidelity import check_fidelity, parse_task_files

SECTION = """## Scope
x
## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `pkg/a.py` | CREATE | a |
| `tests/test_a.py` | CREATE | t |
| `pkg/a.py` | MODIFY | dup |

## Codebase Contract
- `not/this.py`
"""


def test_parse_task_files_from_template_section():
    assert parse_task_files(SECTION) == ["pkg/a.py", "tests/test_a.py"]
    assert parse_task_files("no section") == []


def test_fidelity_rejects_unexpected_and_sdd():
    r = check_fidelity(["a.py"], ["a.py", "b.py", "sdd/x.json"])
    assert not r.ok and r.unexpected == ["b.py", "sdd/x.json"] and r.sdd_touched == ["sdd/x.json"]
    assert check_fidelity(["a.py"], ["a.py"]).ok
