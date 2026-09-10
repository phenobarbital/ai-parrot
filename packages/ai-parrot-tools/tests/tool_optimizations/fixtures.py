"""Shared TASK-file fixtures for the delegation-contract tests (FEAT-543).

`make_valid_task` produces the canonical COMPLETE eligible TASK file used by
TASK-3083, TASK-3085 and TASK-3090, with real SHA-256 digests computed from
the repository the fixture just built — so it stays valid rather than
carrying hard-coded hashes that rot.
"""

import hashlib
import json
from pathlib import Path

__all__ = ("make_repo_with_target", "make_valid_task", "sha256_of", "PACKET_TASK_ID")

#: The task id used by the canonical fixture packet.
PACKET_TASK_ID = "TASK-9999"


def sha256_of(path: Path) -> str:
    """Return the lowercase hex SHA-256 of a file's bytes.

    Args:
        path: The file to hash.

    Returns:
        The digest.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_repo_with_target(tmp_path: Path) -> Path:
    """Create a small repository with one existing package module.

    Args:
        tmp_path: The pytest temporary directory.

    Returns:
        The repository root.
    """
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "sdd" / "tasks" / "active").mkdir(parents=True)
    (repo / "pkg" / "__init__.py").write_text('"""Package."""\n\n__all__ = []\n')
    return repo


def make_valid_task(repo: Path, *, name: str = "TASK-9999-greeter.md") -> Path:
    """Write a complete, eligible TASK file into ``repo``.

    Args:
        repo: The repository root created by :func:`make_repo_with_target`.
        name: The TASK file name.

    Returns:
        The absolute path of the written TASK file.
    """
    init_sha = sha256_of(repo / "pkg" / "__init__.py")
    packet = {
        "schema_version": 1,
        "task_id": PACKET_TASK_ID,
        "spec_path": "sdd/specs/example.spec.md",
        "design_complete": True,
        "targets": [
            {
                "path": "pkg/greeter.py",
                "action": "create",
                "expected_sha256": None,
                "planned_changes": "New module with greet()",
                "blocks": ["impl-greeter"],
            },
            {
                "path": "pkg/__init__.py",
                "action": "modify",
                "expected_sha256": init_sha,
                "planned_changes": "Export greet",
                "blocks": ["impl-init"],
            },
        ],
        "references": [
            {
                "path": "pkg/__init__.py",
                "sha256": init_sha,
                "start_line": 1,
                "end_line": 3,
                "purpose": "existing exports",
            }
        ],
        "implementation_blocks": ["impl-greeter", "impl-init"],
        "acceptance_criteria": ["pytest tests/test_greeter.py passes"],
        "validation_commands": [["pytest", "tests/test_greeter.py", "-q"]],
    }

    body = f"""# {PACKET_TASK_ID}: Add a greeter

Some prose that is not part of the contract.

## Delegation Contract

```json
{json.dumps(packet, indent=2)}
```

## Implementation

```python id=impl-greeter path=pkg/greeter.py
def greet(name: str) -> str:
    \"\"\"Return a greeting.\"\"\"
    return f"hello {{name}}"
```

```python id=impl-init
# Apply to pkg/__init__.py: add after the existing imports
from .greeter import greet

__all__ = [*__all__, "greet"]
```
"""
    task = repo / "sdd" / "tasks" / "active" / name
    task.write_text(body)
    return task
