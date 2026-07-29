---
type: Wiki Summary
title: parrot_tools.security.persistence
id: mod:parrot_tools.security.persistence
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: ReportPersistenceMixin — catalog write-side mixin for producer toolkits.
relates_to:
- concept: class:parrot_tools.security.persistence.ReportPersistenceMixin
  rel: defines
- concept: func:parrot_tools.security.persistence.pop_persistence_kwargs
  rel: defines
- concept: mod:parrot.interfaces.file
  rel: references
- concept: mod:parrot.storage.security_reports
  rel: references
- concept: mod:parrot_tools.security.parsers
  rel: references
---

# `parrot_tools.security.persistence`

ReportPersistenceMixin — catalog write-side mixin for producer toolkits.

Scanner toolkits (CloudSploit, ComplianceReport, ContainerSecurity) compose
this mixin to gain automatic report cataloging without coupling to the store
internals.

Construction protocol
---------------------
Producer toolkits that inherit from both this mixin and ``AbstractToolkit``
MUST pop ``file_manager`` and ``report_store`` from ``**kwargs`` before
calling ``super().__init__(**kwargs)``, otherwise ``AbstractToolkit``
receives unknown keyword arguments.

Example::

    class MyToolkit(ReportPersistenceMixin, AbstractToolkit):
        def __init__(self, *, config, **kwargs):
            self.file_manager, self.report_store = pop_persistence_kwargs(kwargs)
            super().__init__(**kwargs)
            self.config = config

## Classes

- **`ReportPersistenceMixin`** — Mixin that gives producer toolkits catalog write capability.

## Functions

- `def pop_persistence_kwargs(kwargs: dict[str, Any]) -> tuple[FileManagerInterface | None, SecurityReportStore | None]` — Pop ``file_manager`` and ``report_store`` from a toolkit's ``**kwargs``.
