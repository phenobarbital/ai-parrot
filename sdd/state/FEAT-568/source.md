---
kind: inline
jira_key: null
fetched_at: 2026-09-15T00:00:00+00:00
summary_oneline: Fix CI test failures in ai-parrot without compromising test validity
---

# Source Request

**Goal (verbatim from user):**
> your goal is to fix the CI test failures that we have in the ai-parrot repo, but
> be mindful that we want the tests to be actually valid, and not just fix them to
> get them to pass, that would forfeit the purpose of the test itself, so we need
> to understand why the CI test is failing and identify the best path of
> resolution, while keeping the test valid which it is its purpose, so lets not be
> lazy and think deeply about this tests.

**Supporting material**: a GitHub Copilot investigation (external agent, run
against `.github/workflows/ci.yml` on `phenobarbital/ai-parrot`) claiming two
failure regimes:

1. **Resolver unsat (newest runs)** — `uv sync` fails to resolve dependencies for
   a `split (python_full_version >= '3.13' and platform_machine == 'aarch64' and
   sys_platform == 'linux')` marker environment because `async-notify>=1.6.0`
   allegedly "has no Linux-compatible wheels", cascading through
   `ai-parrot[agents]` and blocking nearly every job's setup step (Lint,
   ai-parrot 3.11, ai-parrot-tools 3.11/3.12, tool-optimizations 3.11/3.12,
   wikitoolkit extras, loaders 3.11, Luau fallback).

2. **Real test/import failures (older runs, before the resolver regression
   allegedly took over)**:
   - `Test ai-parrot (Python 3.11)`: `ModuleNotFoundError: No module named
     'tqdm'` cascading into "278 failed … 318 errors", attributed to
     `parrot.bots.flows` importing `tqdm` unconditionally while the job installs
     only the core `ai-parrot` package.
   - `Test wikitoolkit with extras`: `ModuleNotFoundError: No module named
     'pymupdf'` in PDF-ingestion test paths, attributed to the job's installed
     extras (`wiki-languages`, `wiki-structural`) not including whatever extra
     provides PyMuPDF.
   - `Test tool-optimizations FEAT-543`: deterministic `ValueError: substring not
     found` assertions against SDD worker doc content (missing `### b2) Delegated
     implementation`, missing "never delegated, never silently invokes another
     coder" policy text) — attributed to "contract drift" between the SDD worker
     instructions/prompt content and what the FEAT-543 tests assert.

Copilot's proposed remediation checklist (P0–P2) is **not accepted at face
value** — per `/sdd-proposal` guardrails every claim above is treated as an
unverified hypothesis and must be checked directly against this repository's
current `.github/workflows/ci.yml`, `pyproject.toml`/`uv.lock`, source tree, and
test suite before any fix path is proposed. The user's explicit concern is that
"fixing" a test by relaxing its assertions to match current (possibly wrong)
behavior would defeat its purpose — so root cause must be established per
failure before recommending source-fix vs test-fix.
