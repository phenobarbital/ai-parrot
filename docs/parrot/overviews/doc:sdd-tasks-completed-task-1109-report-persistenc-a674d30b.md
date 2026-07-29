---
type: Wiki Overview
title: 'TASK-1109: ReportPersistenceMixin'
id: doc:sdd-tasks-completed-task-1109-report-persistence-mixin-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The mixin that producer scanner toolkits compose in. When both
relates_to:
- concept: mod:parrot.interfaces.file
  rel: mentions
- concept: mod:parrot.storage.security_reports
  rel: mentions
- concept: mod:parrot_tools.security.parsers
  rel: mentions
- concept: mod:parrot_tools.security.persistence
  rel: mentions
---

# TASK-1109: ReportPersistenceMixin

**Feature**: FEAT-162 — Cross-Session Security Report Catalog
**Spec**: `sdd/specs/security-report-catalog.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1105, TASK-1107, TASK-1108
**Assigned-to**: unassigned

---

## Context

The mixin that producer scanner toolkits compose in. When both
`file_manager` and `report_store` are injected, `_persist_report` becomes
active — it parses the scanner's output for the `(severity_summary,
top_findings)` summary, builds a `ReportRef`, uploads + indexes via the
store, and returns the persisted ref. When either dependency is `None`,
the method is a no-op (backward compatibility — existing toolkit callers
that don't inject deps see no behavior change).

Implements Spec §3 Module 5.

---

## Scope

- Create `parrot_tools/security/persistence.py` with `class ReportPersistenceMixin`.
- Class attributes:
  - `file_manager: FileManagerInterface | None = None`
  - `report_store: SecurityReportStore | None = None`
  - `parser_version: str = "1.0.0"`
- Method `_persist_report(self, *, scanner, framework, provider, scope,
  content, content_type="application/json", report_kind=ReportKind.SCAN,
  produced_by=None, severity_summary=None, top_findings=None) -> ReportRef | None`:
  1. If `file_manager is None` or `report_store is None`, return `None`
     (no-op, no log spam).
  2. If `severity_summary is None` or `top_findings is None`, look up
     the parser via `get_report_parser(scanner)` and call `parser.parse(content)`
     to derive the missing pieces.
  3. Build a `ReportRef` with `report_id=uuid4()`,
     `produced_at=datetime.now(timezone.utc)`,
     `produced_by=produced_by or f"toolkit:{type(self).__name__}"`,
     `uri=""` (the store fills it).
  4. `return await self.report_store.save_report(ref, content)`.
- Document the **construction protocol** in the docstring: subclassing
  toolkits MUST pop `file_manager` and `report_store` from `**kwargs`
  before calling `super().__init__(**kwargs)`.
- Provide a small helper `pop_persistence_kwargs(kwargs: dict) -> tuple[FileManagerInterface | None, SecurityReportStore | None]`
  that toolkits can call to do the pop cleanly.
- Unit tests covering:
  - `file_manager=None, report_store=None` → `_persist_report` returns `None` and never raises.
  - When deps are wired, the registered parser is invoked exactly once.
  - When caller provides explicit `severity_summary` + `top_findings`, no parser is invoked.
  - `produced_by` defaults to `f"toolkit:{class_name}"`.

**NOT in scope**: any toolkit-side integration (TASK-1110, 1111, 1112);
LLM-facing toolkit (TASK-1113); summarizers (TASK-1114).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot_tools/security/persistence.py` | CREATE | Mixin + `pop_persistence_kwargs` helper |
| `tests/security/test_persistence_mixin.py` | CREATE | Unit tests with mock file_manager + store |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from __future__ import annotations
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from parrot.interfaces.file import FileManagerInterface           # F002, F004
from parrot.storage.security_reports import (                     # TASK-1105 / TASK-1107
    ReportKind, ReportRef, SeverityBreakdown, EmbeddedFinding,
    SecurityReportStore,
)
from parrot_tools.security.parsers import get_report_parser       # TASK-1108
```

### Existing Signatures to Use

```python
# parrot/tools/toolkit.py:191 — AbstractToolkit constructor accepts **kwargs.
# The mixin is composed into AbstractToolkit subclasses; it does NOT inherit
# from AbstractToolkit itself. Subclasses must use the `pop_persistence_kwargs`
# helper before super().__init__(**kwargs).
class AbstractToolkit(ABC):
    def __init__(self, **kwargs): ...   # parrot/tools/toolkit.py:191
```

### Does NOT Exist

- ~~`AbstractToolkit.file_manager` / `AbstractToolkit.report_store`~~ —
  there is no parent-class hook; these live on the mixin only.
- ~~A pre-existing `Mixin` base class for toolkit persistence anywhere
  in `parrot_tools/`~~ — clean slate.
- ~~Any retention loop or automatic cleanup~~ — never deletes (Spec §1 Goals).

---

## Implementation Notes

### Pattern to Follow

```python
# parrot_tools/security/persistence.py
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from parrot.interfaces.file import FileManagerInterface
from parrot.storage.security_reports import (
    ReportKind, ReportRef, SeverityBreakdown, EmbeddedFinding,
    SecurityReportStore,
)
from parrot_tools.security.parsers import get_report_parser


def pop_persistence_kwargs(kwargs: dict[str, Any]) -> tuple[
    FileManagerInterface | None, SecurityReportStore | None,
]:
    """Pop file_manager + report_store from a toolkit's **kwargs.

    MUST be called BEFORE super().__init__(**kwargs) in producer toolkit
    constructors — otherwise AbstractToolkit receives unknown kwargs.
    """
    fm = kwargs.pop("file_manager", None)
    store = kwargs.pop("report_store", None)
    return fm, store


class ReportPersistenceMixin:
    """Mixin for any toolkit that produces a security report artifact.

    Activation: pass file_manager AND report_store to the toolkit
    constructor. If either is None, _persist_report() returns None
    (no-op, no error).

    Construction protocol — producer toolkits MUST:

        class MyToolkit(ReportPersistenceMixin, AbstractToolkit):
            def __init__(self, *, config, **kwargs):
                self.file_manager, self.report_store = pop_persistence_kwargs(kwargs)
                super().__init__(**kwargs)
                self.config = config
                # ...
    """

    file_manager: FileManagerInterface | None = None
    report_store: SecurityReportStore | None = None
    parser_version: str = "1.0.0"

    async def _persist_report(
        self,
        *,
        scanner: str,
        framework: str | None,
        provider: str,
        scope: dict,
        content: bytes | Path,
        content_type: str = "application/json",
        report_kind: ReportKind = ReportKind.SCAN,
        produced_by: str | None = None,
        severity_summary: SeverityBreakdown | None = None,
        top_findings: list[EmbeddedFinding] | None = None,
    ) -> ReportRef | None:
        if self.file_manager is None or self.report_store is None:
            return None

        if severity_summary is None or top_findings is None:
            parser = get_report_parser(scanner)
            parsed = parser.parse(content)
            severity_summary = severity_summary or parsed.severity_summary
            top_findings = (top_findings or parsed.top_findings)[:10]

        ref = ReportRef(
            report_kind=report_kind,
            scanner=scanner,
            framework=framework,
            provider=provider,
            scope=scope,
            severity_summary=severity_summary,
            top_findings=top_findings[:10],
            uri="",                       # store sets this
            content_type=content_type,
            produced_at=datetime.now(timezone.utc),
            produced_by=produced_by or f"toolkit:{type(self).__name__}",
            parser_version=self.parser_version,
        )
        return await self.report_store.save_report(ref, content)
```

### Key Constraints

- The mixin does NOT inherit `AbstractToolkit` — it is composed in via MRO.
- No-op path returns `None` and does **not** log a warning (would spam
  in test environments where deps are intentionally absent).
- All async. No sync I/O.
- `top_findings` is capped at 10 (sorted by the parser).

### References in Codebase

- Spec §3 Module 5 — verbatim source for the method shape.
- Finding F012 — producer toolkit `__init__` accepts `**kwargs` and
  forwards them to `super().__init__(**kwargs)`.

---

## Acceptance Criteria

- [ ] `from parrot_tools.security.persistence import ReportPersistenceMixin, pop_persistence_kwargs` resolves.
- [ ] When `file_manager=None` and `report_store=None`, `_persist_report` returns `None`.
- [ ] When deps are wired and `severity_summary`/`top_findings` are NOT provided,
      `get_report_parser(scanner).parse(content)` is called exactly once.
- [ ] When the caller provides explicit `severity_summary` AND `top_findings`,
      the parser is NOT invoked (verified via mock).
- [ ] All unit tests pass: `pytest tests/security/test_persistence_mixin.py -v`.
- [ ] No linting errors: `ruff check parrot_tools/security/persistence.py`.

---

## Test Specification

```python
# tests/security/test_persistence_mixin.py
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from parrot.storage.security_reports import (
    ReportKind, ReportRef, SeverityBreakdown, EmbeddedFinding,
)
from parrot_tools.security.persistence import (
    ReportPersistenceMixin, pop_persistence_kwargs,
)


class _Probe(ReportPersistenceMixin):
    pass


class TestNoOpWhenDepsMissing:
    async def test_returns_none_when_both_missing(self):
        probe = _Probe()
        result = await probe._persist_report(
            scanner="cloudsploit", framework="HIPAA", provider="aws",
            scope={}, content=b"{}",
        )
        assert result is None

    async def test_returns_none_when_only_file_manager_missing(self):
        probe = _Probe()
        probe.report_store = AsyncMock()
        result = await probe._persist_report(
            scanner="cloudsploit", framework="HIPAA", provider="aws",
            scope={}, content=b"{}",
        )
        assert result is None
        probe.report_store.save_report.assert_not_called()


class TestActivated:
    async def test_parser_invoked_when_summary_omitted(self):
        probe = _Probe()
        probe.file_manager = MagicMock()
        probe.report_store = AsyncMock()
        probe.report_store.save_report = AsyncMock(side_effect=lambda ref, content: ref)
        with patch("parrot_tools.security.persistence.get_report_parser") as gp:
            parser = MagicMock()
            parser.parse.return_value.severity_summary = SeverityBreakdown(critical=1)
            parser.parse.return_value.top_findings = []
            gp.return_value = parser
            await probe._persist_report(
                scanner="cloudsploit", framework="HIPAA", provider="aws",
                scope={}, content=b"{}",
            )
            gp.assert_called_once_with("cloudsploit")
            parser.parse.assert_called_once()

    async def test_parser_not_invoked_when_summary_provided(self):
        probe = _Probe()
        probe.file_manager = MagicMock()
        probe.report_store = AsyncMock()
        probe.report_store.save_report = AsyncMock(side_effect=lambda ref, content: ref)
        with patch("parrot_tools.security.persistence.get_report_parser") as gp:
            await probe._persist_report(
                scanner="cloudsploit", framework="HIPAA", provider="aws",
                scope={}, content=b"{}",
                severity_summary=SeverityBreakdown(critical=2),
                top_findings=[],
            )
            gp.assert_not_called()

    async def test_produced_by_defaults_to_class_name(self):
        probe = _Probe()
        probe.file_manager = MagicMock()
        probe.report_store = AsyncMock()
        captured = {}
        async def _save(ref, content):
            captured["ref"] = ref
            return ref
        probe.report_store.save_report = _save
        await probe._persist_report(
            scanner="cloudsploit", framework="HIPAA", provider="aws",
            scope={}, content=b"{}",
            severity_summary=SeverityBreakdown(),
            top_findings=[],
        )
        assert captured["ref"].produced_by == "toolkit:_Probe"


class TestPopKwargs:
    def test_pops_known_keys(self):
        kwargs = {"file_manager": "FM", "report_store": "RS", "other": 1}
        fm, store = pop_persistence_kwargs(kwargs)
        assert fm == "FM"
        assert store == "RS"
        assert kwargs == {"other": 1}

    def test_missing_keys_return_none(self):
        kwargs = {}
        fm, store = pop_persistence_kwargs(kwargs)
        assert fm is None and store is None
```

---

## Agent Instructions

1. Read the spec section §3 Module 5.
2. Verify the parser registry from TASK-1108 is importable.
3. Implement mixin.
4. Run unit tests.
5. Move this file to `sdd/tasks/completed/`; update per-spec index; commit.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-12
**Notes**: Created `persistence.py` with `ReportPersistenceMixin` and
`pop_persistence_kwargs`. No-op path (returns None, no log spam) when
either dep is None. Parser invoked only when severity_summary or
top_findings is not provided. top_findings capped at 10. 11 unit tests
pass covering all acceptance criteria.

**Deviations from spec**: none
