---
type: Wiki Summary
title: parrot_tools.s3.comparator
id: mod:parrot_tools.s3.comparator
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: GenericReportComparator — agnostic structural diff for S3-stored reports.
relates_to:
- concept: class:parrot_tools.s3.comparator.GenericReportComparator
  rel: defines
- concept: mod:parrot_tools.cloudsploit.comparator
  rel: references
- concept: mod:parrot_tools.cloudsploit.parser
  rel: references
---

# `parrot_tools.s3.comparator`

GenericReportComparator — agnostic structural diff for S3-stored reports.

Provides two comparison modes:
1. Generic structural JSON diff (always available).
2. Parser-dispatch for scanner-aware comparison when scanner name is known.
   Currently dispatches to ``ScanComparator`` for CloudSploit; all other
   scanners fall back to generic diff.

Module implements Spec §3 Module 2 (FEAT-184).

## Classes

- **`GenericReportComparator`** — Structural diff engine for S3-stored report documents.
