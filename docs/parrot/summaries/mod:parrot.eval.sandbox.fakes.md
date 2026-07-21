---
type: Wiki Summary
title: parrot.eval.sandbox.fakes
id: mod:parrot.eval.sandbox.fakes
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Fake driver implementations for the Generic Agent Evaluation Harness.
relates_to:
- concept: class:parrot.eval.sandbox.fakes.FakeJiraClient
  rel: defines
- concept: class:parrot.eval.sandbox.fakes.FakeRawConnection
  rel: defines
- concept: class:parrot.eval.sandbox.fakes.FakeTableMetadata
  rel: defines
- concept: class:parrot.eval.sandbox.fakes.StaticResolver
  rel: defines
---

# `parrot.eval.sandbox.fakes`

Fake driver implementations for the Generic Agent Evaluation Harness.

FEAT-217 — These fakes translate toolkit method calls into
``DictStateBackend`` operations with NO real network/database/HTTP calls.

Provided fakes
--------------
``FakeTableMetadata``
    Minimal dataclass stub returned by ``DatabaseToolkitBinder._fake_resolve_table``
    to avoid importing ``parrot.bots.database.models`` (which has broken
    optional deps in the test venv).

``FakeRawConnection``
    Implements the raw asyncpg connection surface (``execute``, ``fetchrow``,
    ``fetch``, ``close``) by routing simple INSERT/UPDATE/DELETE/SELECT SQL
    to ``DictStateBackend`` operations.  Only the SQL shape produced by
    ``PostgresToolkit``'s CRUD methods is handled — this is NOT a SQL engine.

``FakeJiraClient``
    Implements the subset of the ``pycontribs.jira.JIRA`` API exercised by
    the Jira triage benchmark: ``search_issues``, ``assign_issue``,
    ``transition_issue``.  State lives in a ``DictStateBackend``.

``StaticResolver``
    Trivial credential resolver that always returns the same pre-built
    ``FakeJiraClient`` without any network I/O.

## Classes

- **`FakeTableMetadata`** — Minimal table metadata stub used by ``DatabaseToolkitBinder``.
- **`FakeRawConnection`** — Fake asyncpg connection that routes CRUD SQL to a ``DictStateBackend``.
- **`FakeJiraClient`** — In-memory Jira client backed by a ``DictStateBackend``.
- **`StaticResolver`** — Credential resolver that always returns a pre-built ``FakeJiraClient``.
