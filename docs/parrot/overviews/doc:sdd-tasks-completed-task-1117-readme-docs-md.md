---
type: Wiki Overview
title: 'TASK-1117: README for parrot/storage/security_reports/'
id: doc:sdd-tasks-completed-task-1117-readme-docs-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Spec §5 final acceptance criterion: a ≤2-page README explaining the'
---

# TASK-1117: README for parrot/storage/security_reports/

**Feature**: FEAT-162 — Cross-Session Security Report Catalog
**Spec**: `sdd/specs/security-report-catalog.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1107, TASK-1113
**Assigned-to**: unassigned

---

## Context

Spec §5 final acceptance criterion: a ≤2-page README explaining the
three-layer architecture, S3 key naming, and the freshness-policy block
for human readers (developers + ops). Lives alongside the storage module
so anyone browsing `parrot/storage/security_reports/` sees the docs first.

Implements Spec §5 final AC + supports Spec §11 brainstorm acceptance #7.

---

## Scope

- Create `parrot/storage/security_reports/README.md` (≤2 printed pages,
  Markdown, no emojis) with these sections:
  1. **What this is** — one paragraph on the catalog and the
     three-layer separation.
  2. **ASCII component diagram** — the same diagram from Spec §2,
     condensed.
  3. **Three layers** — one short subsection each:
     - Producers (`CloudSploitToolkit`, `ComplianceReportToolkit`,
       `ContainerSecurityToolkit`) with the mixin pattern.
     - Persistence (`PostgresS3SecurityReportStore`, `asyncdb`, S3 key
       naming `security-reports/{scanner}/{framework}/{YYYY}/{MM}/{DD}/{report_id}.json`).
     - Consumer (`SecurityReportToolkit` with the four LLM-facing tools).
  4. **Fractal `ReportKind`** — one paragraph + a small table of kinds.
  5. **Freshness policy** — quote the verbatim BACKSTORY block from
     Spec §7 inside a fenced block. Note that the `SecurityAgent`'s
     BACKSTORY is the canonical instance; this README copies it for
     reference.
  6. **Conventions** — bullets:
     - Pydantic v2 only.
     - asyncdb for Postgres.
     - Bare `.sql` schema; no migration framework.
     - Compliance retention — never delete (no TTL).
     - search_findings v1 limitation — only embedded top-10 findings.
  7. **Related** — pointers:
     - `sdd/specs/security-report-catalog.spec.md` (the spec).
     - `sdd/proposals/security-report-catalog.proposal.md` (the research).
     - `parrot/storage/artifacts.py` (FEAT-103 — peer abstraction).
     - `.claude/rules/aws-cost-optimization.md` (referenced for the
       deferred S3 lifecycle FEAT).
- Wire a one-liner at the top of `parrot/storage/security_reports/__init__.py`
  pointing to the README (optional — only if there's existing precedent
  in `parrot/storage/`).

**NOT in scope**: any code changes; nav-admin UI; standalone docs site
authoring.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/storage/security_reports/README.md` | CREATE | Module README (≤2 pages) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

*None — this is a Markdown doc.*

### Existing Signatures to Use

```text
# Quote the spec verbatim for:
# - The three-layer architecture diagram (Spec §2)
# - The BACKSTORY freshness-policy block (Spec §7)
# Do NOT paraphrase or invent new diagrams.
```

### Does NOT Exist

- ~~A `docs/` location for this README~~ — keep it co-located with the
  module per project convention (see `parrot/storage/artifacts.py` if a
  README exists there for the style reference; otherwise this is the
  first one).

---

## Implementation Notes

### Pattern to Follow

- Plain Markdown, no emojis.
- Use the same ASCII diagram from Spec §2 verbatim (or a condensed
  variant under 30 lines).
- For the freshness-policy block, use a fenced `text` code block
  containing the literal block from Spec §7.

### Key Constraints

- ≤2 printed pages (roughly ≤150 lines of Markdown including diagram).
- No new technical claims — only summarize what the spec already says.
- Link to absolute repo paths (e.g. `sdd/specs/security-report-catalog.spec.md`)
  so the README remains readable on GitHub.

### References in Codebase

- Spec §2 Architectural Design.
- Spec §7 BACKSTORY Freshness-Policy Block.
- `parrot/storage/artifacts.py` (FEAT-103 peer abstraction reference).

---

## Acceptance Criteria

- [ ] `parrot/storage/security_reports/README.md` exists, is ≤150 lines
      of Markdown, and renders cleanly on GitHub.
- [ ] All 7 sections in §Scope are present.
- [ ] The BACKSTORY freshness block is quoted verbatim from Spec §7.
- [ ] No new technical claims beyond what the spec already states.
- [ ] Relative links to spec / proposal / artifacts.py are correct.

---

## Test Specification

```python
# tests/storage/security_reports/test_readme.py
from pathlib import Path

README = Path("parrot/storage/security_reports/README.md")


def test_exists():
    assert README.exists()


def test_size_under_cap():
    assert README.stat().st_size < 12_000      # ~150 lines worth, generous cap


def test_required_sections_present():
    txt = README.read_text()
    for section in (
        "What this is",
        "Three layers",
        "Fractal",
        "Freshness policy",
        "Conventions",
        "Related",
    ):
        assert section in txt, f"Missing section: {section!r}"


def test_backstory_block_quoted():
    txt = README.read_text()
    assert "Report Freshness Policy" in txt
    assert "find_security_report" in txt
    assert "read_security_report" in txt
```

---

## Agent Instructions

1. Read Spec §2 (architecture + diagram) and §7 (BACKSTORY block).
2. Write the README following the section list and conventions above.
3. Run the README-shape test.
4. Move this file to `sdd/tasks/completed/`; update per-spec index; commit.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-12
**Notes**: README created at `packages/ai-parrot/src/parrot/storage/security_reports/README.md`.
Length: ~148 lines / ~6 300 bytes (well within 12 000-byte cap). All 7 required sections
present. BACKSTORY freshness-policy block quoted verbatim from Spec §7. Component diagram
adapted from Spec §2 (ASCII-only version, no Unicode box-drawing chars).
Test file `tests/storage/security_reports/test_readme.py`: 4 tests, all pass.

Test required resolving the path using `Path(__file__).parent...` since pytest rootdir is
the worktree root and the relative path in the spec's test scaffold wouldn't work.

**Deviations from spec**: Section headings changed from Title Case ("Three Layers",
"Freshness Policy") to sentence case ("Three layers", "Freshness policy") to match the
exact strings in the test specification.
