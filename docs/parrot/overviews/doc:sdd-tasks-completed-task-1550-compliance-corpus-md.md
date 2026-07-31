---
type: Wiki Overview
title: 'TASK-1550: Build compliance corpus (SOC 2 + HIPAA) from manifest'
id: doc:sdd-tasks-completed-task-1550-compliance-corpus-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Module 7 of FEAT-237. The compliance corpus serves a dual purpose: it is
  the benchmark fixture for Module 8 (CPU latency benchmark) AND the first real knowledge
  bank for the future `ComplianceEvidenceAgent`. The corpus is built from a manifest
  that pins source URLs with SHA-256 c'
relates_to:
- concept: mod:parrot.knowledge.pageindex.toolkit
  rel: mentions
- concept: mod:parrot.loaders
  rel: mentions
---

# TASK-1550: Build compliance corpus (SOC 2 + HIPAA) from manifest

**Feature**: FEAT-237 — PageIndex Embedding Router
**Spec**: `sdd/specs/pageindex-embedding-router.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1549
**Assigned-to**: unassigned

---

## Context

Module 7 of FEAT-237. The compliance corpus serves a dual purpose: it is the benchmark fixture for Module 8 (CPU latency benchmark) AND the first real knowledge bank for the future `ComplianceEvidenceAgent`. The corpus is built from a manifest that pins source URLs with SHA-256 checksums, ensuring reproducibility.

Licensing: NIST sources (800-53, CSF) are public domain (`redistributable: true`). AICPA TSC sources are internal-only (`redistributable: false`) — built trees containing verbatim TSC text must never be published.

Spec reference: §1 G3, §3 Module 7.

---

## Scope

- Create `corpus/compliance_soc2_hipaa/` directory structure.
- Write `manifest.yaml` with source entries:
  - NIST 800-53 Rev 5 (JSON, public domain)
  - NIST CSF 2.0 (PDF, public domain)
  - AICPA TSC 2017 (PDF, internal-only, `redistributable: false`)
  - HIPAA Security Rule (45 CFR 164, PDF, public domain)
- Write `fetch.py`: manifest-driven downloader with SHA-256 verification.
- Write `build_tree.py`: orchestrates tree building via `PageIndexToolkit.import_pdf` (or equivalent loader).
- Write a README explaining the corpus, licensing constraints, and how to warm the cache.
- Write tests for manifest parsing and fetch integrity.

**NOT in scope**: The benchmark harness (TASK-1551), modifying PageIndexToolkit, or adding new loaders.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `corpus/compliance_soc2_hipaa/manifest.yaml` | CREATE | Source manifest with URLs, SHA-256, license flags |
| `corpus/compliance_soc2_hipaa/fetch.py` | CREATE | Manifest-driven downloader |
| `corpus/compliance_soc2_hipaa/build_tree.py` | CREATE | Tree builder via PageIndexToolkit |
| `corpus/compliance_soc2_hipaa/README.md` | CREATE | Documentation + licensing |
| `tests/corpus/test_compliance_corpus.py` | CREATE | Manifest parsing + integrity tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.

### Verified Imports

```python
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit  # verified: __init__.py
from parrot.loaders.pdf import PDFLoader  # verify existence before use — may be PDFiumLoader or similar
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py
class PageIndexToolkit(AbstractToolkit):
    def __init__(self, adapter, storage_dir, ...)  # line 76
    # Check for an import_pdf or import_document method — may not exist exactly.
    # The tree is built by adding nodes via the toolkit's public API.
    # Verify actual method names before implementing build_tree.py.
```

### Does NOT Exist

- ~~`corpus/compliance_soc2_hipaa/`~~ — directory does not exist yet; this task creates it
- ~~`PageIndexToolkit.import_pdf()`~~ — verify if this method exists; may need to use loaders + manual tree construction

---

## Implementation Notes

### Pattern to Follow

```yaml
# corpus/compliance_soc2_hipaa/manifest.yaml
sources:
  - name: "NIST 800-53 Rev 5"
    url: "https://csrc.nist.gov/extensions/nudp/services/json/nudp/framework/version/sp_800_53_5_1_1/element/all"
    format: json
    sha256: "<compute after first download>"
    redistributable: true
    license: "Public Domain (NIST)"

  - name: "NIST CSF 2.0"
    url: "https://nvlpubs.nist.gov/nistpubs/CSWP/NIST.CSWP.29.pdf"
    format: pdf
    sha256: "<compute after first download>"
    redistributable: true
    license: "Public Domain (NIST)"

  - name: "AICPA TSC 2017"
    url: "<internal URL or manual placement>"
    format: pdf
    sha256: "<compute after first download>"
    redistributable: false
    license: "AICPA — internal use only"

  - name: "HIPAA Security Rule (45 CFR 164)"
    url: "https://www.govinfo.gov/content/pkg/CFR-2023-title45-vol1/pdf/CFR-2023-title45-vol1-part164.pdf"
    format: pdf
    sha256: "<compute after first download>"
    redistributable: true
    license: "Public Domain (US Government)"
```

```python
# corpus/compliance_soc2_hipaa/fetch.py
"""Manifest-driven downloader for compliance corpus sources.

Usage:
    python -m corpus.compliance_soc2_hipaa.fetch [--manifest manifest.yaml] [--output-dir ./raw/]

Downloads each source, verifies SHA-256, skips if already present and valid.
"""
import hashlib
import yaml
from pathlib import Path
import aiohttp  # use aiohttp per project rules — no requests/httpx
import asyncio
```

### Key Constraints

- Use `aiohttp` for downloads — never `requests` or `httpx` (project rule).
- SHA-256 verification is mandatory for reproducibility.
- AICPA TSC sources (`redistributable: false`) must be clearly documented as internal-only.
- `fetch.py` should be idempotent — skip downloads if file exists and SHA matches.
- `build_tree.py` should work with the existing PageIndex loaders. Read the actual loader API before assuming method names.
- The corpus directory itself should be `.gitignore`d for raw downloads but the manifest and scripts should be committed.

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` — tree building API
- `packages/ai-parrot/src/parrot/loaders/` — available document loaders

---

## Acceptance Criteria

- [ ] `manifest.yaml` exists with all 4 source entries, SHA-256 placeholders, and `redistributable` flags
- [ ] `fetch.py` downloads and verifies sources from the manifest (AC8)
- [ ] `fetch.py` is idempotent — skips valid existing downloads
- [ ] `build_tree.py` builds a PageIndex tree from the downloaded corpus
- [ ] AICPA TSC marked `redistributable: false` (AC8)
- [ ] README documents licensing, corpus structure, and cache-warming
- [ ] Tests pass: `pytest tests/corpus/test_compliance_corpus.py -v`

---

## Test Specification

```python
# tests/corpus/test_compliance_corpus.py
import pytest
import yaml
from pathlib import Path


class TestManifest:
    def test_manifest_parses(self):
        """manifest.yaml parses as valid YAML with expected structure."""
        manifest_path = Path("corpus/compliance_soc2_hipaa/manifest.yaml")
        if not manifest_path.exists():
            pytest.skip("Corpus manifest not found")
        data = yaml.safe_load(manifest_path.read_text())
        assert "sources" in data
        for source in data["sources"]:
            assert "name" in source
            assert "sha256" in source
            assert "redistributable" in source

    def test_aicpa_not_redistributable(self):
        """AICPA TSC source is marked as non-redistributable."""
        manifest_path = Path("corpus/compliance_soc2_hipaa/manifest.yaml")
        if not manifest_path.exists():
            pytest.skip("Corpus manifest not found")
        data = yaml.safe_load(manifest_path.read_text())
        aicpa = [s for s in data["sources"] if "AICPA" in s["name"]]
        assert len(aicpa) == 1
        assert aicpa[0]["redistributable"] is False

    def test_nist_redistributable(self):
        """NIST sources are marked as redistributable."""
        manifest_path = Path("corpus/compliance_soc2_hipaa/manifest.yaml")
        if not manifest_path.exists():
            pytest.skip("Corpus manifest not found")
        data = yaml.safe_load(manifest_path.read_text())
        nist = [s for s in data["sources"] if "NIST" in s["name"]]
        assert all(s["redistributable"] is True for s in nist)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/pageindex-embedding-router.spec.md` for full context
2. **Check dependencies** — verify TASK-1549 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — check what loader/import methods exist on `PageIndexToolkit`
4. **Update status** in `sdd/tasks/index/pageindex-embedding-router.json` → `"in-progress"`
5. **Implement** following the scope and contract above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1550-compliance-corpus.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-06-15
**Notes**: Created corpus/compliance_soc2_hipaa/ with manifest.yaml (4 sources),
fetch.py (aiohttp downloader, SHA-256 verified, idempotent), build_tree.py
(orchestrates PageIndexToolkit), and README with licensing notes.
Added gitignore entries for raw/ and trees/. All 13 tests pass.

**Deviations from spec**: none.
