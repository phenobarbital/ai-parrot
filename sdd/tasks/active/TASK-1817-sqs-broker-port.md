# TASK-1817: Port SQS broker (navconfig creds desacople)

**Feature**: FEAT-316 — EventBus Brokers Port
**Spec**: `sdd/specs/eventbus-brokers-port.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1814
**Assigned-to**: unassigned

> **Repo**: `/home/jesuslara/proyectos/navigator-eventbus`
> (worktree `.claude/worktrees/feat-FEAT-316-eventbus-brokers-port`).
> Source: `/home/jesuslara/proyectos/navigator/navigator/brokers/sqs/`.

---

## Context

Spec §3 Module 5. Ports `sqs/{connection,consumer,producer}.py` (336+133+38 LOC).
The SQS connection already reads AWS creds via `navconfig.config` directly
(verified), so the main desacoples here are `ValidationError` and
`json_encoder/json_decoder`.

---

## Scope

- Create `src/navigator_eventbus/brokers/sqs/__init__.py` re-exporting
  `SQSConnection`, `SQSConsumer`, `SQSProducer`.
- Create `sqs/connection.py` — port `SQSConnection`:
  - Keep the existing navconfig reads for `AWS_KEY`/`AWS_SECRET`/`AWS_REGION`
    (already `config.get(...)` in the source — no navigator.conf involved).
  - Replace `navigator.exceptions.ValidationError` with local `Exception`
    handling + warning log.
  - Replace `datamodel.parsers.json.json_encoder/json_decoder` with
    `navigator_eventbus.serialization.dumps/loads`.
- Create `sqs/consumer.py` — port `SQSConsumer` (near-verbatim).
- Create `sqs/producer.py` — port `SQSProducer` (inherits fix #3 from TASK-1814).
- `navigator_eventbus.brokers` top-level must not import the sqs subpackage
  eagerly (aioboto3 only needed with the `[sqs]` extra).
- Tests: `tests/brokers/test_sqs.py` (creds from navconfig, no navigator
  imports) with `aioboto3` mocked.

**NOT in scope**: redis/rabbitmq ports; hooks; pyproject extras (TASK-1818);
live-AWS integration tests.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `src/navigator_eventbus/brokers/sqs/__init__.py` | CREATE | Re-exports |
| `src/navigator_eventbus/brokers/sqs/connection.py` | CREATE | `SQSConnection` |
| `src/navigator_eventbus/brokers/sqs/consumer.py` | CREATE | `SQSConsumer` |
| `src/navigator_eventbus/brokers/sqs/producer.py` | CREATE | `SQSProducer` |
| `tests/brokers/test_sqs.py` | CREATE | Unit tests (aioboto3 mocked) |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-07-18.

### Verified Imports

```python
# Keep:
import aioboto3                              # navigator/brokers/sqs/connection.py:9
from datamodel import Model, BaseModel       # :10
from navconfig import config                 # :11 — already navconfig-native
from navconfig.logging import logging        # :12

# REPLACE during port:
# from datamodel.parsers.json import json_encoder, json_decoder  # :13
# from navigator.exceptions import ValidationError               # :14

# New internal:
from ..connection import BaseConnection
from ..wrapper import BaseWrapper
from navigator_eventbus.serialization import dumps, loads
```

### Existing Signatures to Use (source: navigator repo)

```python
# navigator/brokers/sqs/connection.py:25
class SQSConnection(BaseConnection):
    def __init__(...)
    # :38-40 — creds pattern already navconfig-based, KEEP:
    #   credentials['aws_access_key_id'] = config.get('AWS_KEY')
    #   credentials['aws_secret_access_key'] = config.get('AWS_SECRET')
    #   credentials['region_name'] = config.get('AWS_REGION')

# navigator/brokers/sqs/consumer.py:15
class SQSConsumer(SQSConnection, BrokerConsumer):
    def __init__(...)   # :23

# navigator/brokers/sqs/producer.py:11
class SQSProducer(SQSConnection, BrokerProducer):
    def __init__(...)   # :24

# navigator/brokers/sqs/__init__.py (exports to preserve):
from .connection import SQSConnection
from .consumer import SQSConsumer
from .producer import SQSProducer

# Module-level logger tuning to preserve (sqs/connection.py:19-22):
logging.getLogger("botocore").setLevel(logging.INFO)
logging.getLogger("aiobotocore").setLevel(logging.INFO)
logging.getLogger("aioboto3").setLevel(logging.INFO)
logging.getLogger("boto3").setLevel(logging.WARNING)
```

### Does NOT Exist

- ~~`navigator_eventbus.brokers.sqs`~~ — created by THIS task.
- ~~`boto3`/`botocore` direct usage~~ — the implementation is async via
  `aioboto3` sessions; do not introduce sync boto3 calls.
- ~~AWS creds in `navigator.conf`~~ — the sqs module never imported them from
  navigator.conf; they come from `navconfig.config.get()` (keep as-is).

---

## Implementation Notes

### Key Constraints

- async/await throughout — aioboto3 client usage is `async with session.client("sqs", ...)`.
- Preserve the third-party logger level tuning at module import.
- `self.logger`; Google-style docstrings + strict typing.

### References in Codebase

- `navigator/brokers/sqs/*.py` (navigator repo) — sources; read IN FULL.
- TASK-1816 for the same ValidationError/json replacement pattern.

---

## Acceptance Criteria

- [ ] `from navigator_eventbus.brokers.sqs import SQSConnection, SQSConsumer, SQSProducer` works (with aioboto3 installed).
- [ ] AWS creds read via navconfig (`test_sqs_connection_creds_navconfig`).
- [ ] No `navigator.*` imports in `src/navigator_eventbus/brokers/sqs/`.
- [ ] `import navigator_eventbus.brokers` succeeds WITHOUT aioboto3 installed.
- [ ] All tests pass: `pytest tests/brokers/test_sqs.py -v`
- [ ] `ruff check src/navigator_eventbus/brokers/sqs/` passes.

---

## Test Specification

```python
# tests/brokers/test_sqs.py
import pytest
from navigator_eventbus.brokers.sqs import SQSConnection


def test_sqs_connection_creds_navconfig(monkeypatch):
    """AWS creds resolved via navconfig env, not navigator.conf."""
    monkeypatch.setenv("AWS_KEY", "AKIATEST")
    monkeypatch.setenv("AWS_SECRET", "s3cret")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    conn = SQSConnection()
    # assert the credentials dict was populated from env (adapt to impl)
    assert conn is not None


def test_sqs_no_navigator_imports():
    import navigator_eventbus.brokers.sqs.connection as m
    import inspect
    src = inspect.getsource(m)
    assert "from navigator." not in src and "import navigator." not in src
```

---

## Agent Instructions

1. Read spec §3 Module 5, §7. Read the three sqs source files IN FULL.
2. Check TASK-1814 is in `sdd/tasks/completed/`.
3. Verify the Codebase Contract; update index → `"in-progress"`.
4. Implement, run tests, move this file to `sdd/tasks/completed/`, index → `"done"`, fill Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
