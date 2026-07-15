---
type: Wiki Summary
title: parrot_tools.s3.report_reader
id: mod:parrot_tools.s3.report_reader
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: S3ReportReaderToolkit — LLM-facing agnostic S3 report reader.
relates_to:
- concept: class:parrot_tools.s3.report_reader.S3ReportReaderToolkit
  rel: defines
- concept: mod:parrot.interfaces.file
  rel: references
- concept: mod:parrot.storage.security_reports
  rel: references
- concept: mod:parrot_tools.s3.comparator
  rel: references
- concept: mod:parrot_tools.security.parsers
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.s3.report_reader`

S3ReportReaderToolkit — LLM-facing agnostic S3 report reader.

Exposes 8 agent tools (``s3_`` prefix) for reading, filtering, comparing,
and summarizing S3-stored reports.  Operates in dual mode:

- With ``SecurityReportStore``: catalog-backed queries for indexed reports.
- Without ``SecurityReportStore``: raw S3 browsing via ``FileManagerInterface``
  only (catalog-dependent tools return an informative error dict).

Module implements Spec §3 Module 1 (FEAT-184).

## Classes

- **`S3ReportReaderToolkit(AbstractToolkit)`** — Agnostic read-only toolkit for LLM agents to explore S3-stored reports.
