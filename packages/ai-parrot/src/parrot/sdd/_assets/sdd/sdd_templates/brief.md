---
kind: brief
slug: <slug>
key: <key>
base_branch: <base_branch>
source:
  type: <source_type>
  ref: <source_ref>
  url: <source_url>
jira_issue_key: null
ledger_issue: null
created: <created>
---

# Brief: <Title>

<!-- FEAT-698. One brief = one fix. Task files live in sdd/briefs/<slug>/tasks/. -->

## Problem
<!-- What is broken, for whom, and how it was observed (quote the source). -->

## Root cause
<!-- Research floor (required in every mode, including --research light):
     the fetched source, a one-paragraph root-cause statement, and at least one
     verified `path:line` anchor. Without these /sdd-brief creates no worktree. -->

## Research findings
<!-- Symbols touched, blast radius, related ledger issues, prior art. -->

## Decisions
<!-- Answers from the Q&A round. With --no-interview, rename to "## Assumptions". -->

## Fix plan
<!-- Ordered steps; one bullet per materialized task file (HOTFIX-<KEY>-N). -->

## Validation commands
<!-- File-level pytest only, e.g. `pytest path/to/test_file.py -q`. -->
