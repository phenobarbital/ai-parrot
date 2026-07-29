---
type: Wiki Summary
title: parrot_tools.cloudsploit.reports
id: mod:parrot_tools.cloudsploit.reports
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Report generator for CloudSploit scan results.
relates_to:
- concept: class:parrot_tools.cloudsploit.reports.ReportGenerator
  rel: defines
- concept: mod:parrot_tools.cloudsploit.models
  rel: references
---

# `parrot_tools.cloudsploit.reports`

Report generator for CloudSploit scan results.

Produces HTML and PDF reports from scan results and comparison data.
Uses Jinja2 for templating and xhtml2pdf for PDF generation.

## Classes

- **`ReportGenerator`** — Generates HTML and PDF reports from CloudSploit scan results.
