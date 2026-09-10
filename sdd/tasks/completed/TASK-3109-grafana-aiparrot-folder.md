# TASK-3109: Add an AI-Parrot Grafana folder via a second provisioning provider

**Feature**: FEAT-548 — Observability — OTEL to Prometheus + Grafana usage/cost dashboard
**Spec**: `sdd/specs/observability-otel-grafana.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 3. The running Grafana provisions dashboards through a
single provider named `claudestats` that files everything into a folder literally
called **Claude Code**. Dropping a parrot dashboard in as-is would put an
AI-Parrot dashboard under a folder named for a different product.

This task is independent of every other task in the feature (it shares no files)
and can run in a parallel worktree.

---

## Scope

- Append a second provider entry (`parrot`, folder `AI-Parrot`) to
  `docker/grafana/provisioning/dashboards/dashboards.yml`.
- Create the `docker/grafana/provisioning/dashboards/parrot/` directory.
- **Verify the existing `claudestats` provider does not also pick up the new
  subdirectory** — if it does, dashboards would be provisioned twice, in two
  folders.

**NOT in scope**: the dashboard JSON itself (TASK-3110); touching the two
existing dashboards or the `claudestats` provider's own settings.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docker/grafana/provisioning/dashboards/dashboards.yml` | MODIFY | Append the `parrot` provider |
| `docker/grafana/provisioning/dashboards/parrot/.gitkeep` | CREATE | Hold the empty dir until TASK-3110 fills it |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```yaml
# No Python. The verified current file, in full (15 lines, sha256
# 23b20c273f7c5176a7931caeacc24966f15609b7bf88aea26193c7aa1fff86ae):
apiVersion: 1                                              # line 1
providers:                                                 # line 3
  - name: claudestats                                      # line 4
    orgId: 1                                               # line 5
    folder: Claude Code                                    # line 6
    type: file                                             # line 7
    disableDeletion: false                                 # line 8
    allowUiUpdates: false                                  # line 11
    updateIntervalSeconds: 30                              # line 12
    options:                                               # line 13
      path: /etc/grafana/provisioning/dashboards           # line 14
      foldersFromFilesStructure: false                     # line 15
```

### Existing Signatures to Use

```yaml
# docker/grafana/provisioning/datasources/prometheus.yml — the datasource a
# dashboard must reference (TASK-3110 needs this; not changed here)
  - name: Prometheus
    uid: claudestats-prometheus     # <- the uid, verified
    url: http://prometheus:9090
    isDefault: true

# docker/grafana/docker-compose.yml — how the dir reaches the container
    volumes:
      - ./provisioning/dashboards:/etc/grafana/provisioning/dashboards:ro
```

### Does NOT Exist

- ~~a `parrot` provider~~ — this task creates the first one.
- ~~`docker/grafana/provisioning/dashboards/parrot/`~~ — does not exist yet.
- ~~a Grafana folder named `AI-Parrot`~~ — created by provisioning, not by hand
  in the UI.
- ~~`foldersFromFilesStructure: true` anywhere in this repo~~ — the existing
  provider sets it `false`; do not flip it (that would re-file the two existing
  dashboards, which is out of scope).

---

## Implementation Notes

### Key Constraints

- The mount is **read-only** (`:ro`), so the directory must exist on the host
  before Grafana can see it — hence the `.gitkeep`.
- `updateIntervalSeconds: 30` means no Grafana restart is needed; wait 30 s.
- Match the existing provider's conventions exactly (`allowUiUpdates: false`,
  `orgId: 1`, `type: file`) so the two behave identically.

### References in Codebase

- `docker/grafana/provisioning/dashboards/codex-overview.json` — a working
  provisioned dashboard, added days ago by the same mechanism.

---

## Implementation Blueprint

### Steps (in order)

1. Append the `parrot` provider block to `dashboards.yml` — *why*: a second
   provider is the only way to get a second folder while
   `foldersFromFilesStructure` stays `false`.
2. Create `docker/grafana/provisioning/dashboards/parrot/.gitkeep` — *why*: the
   provisioning mount is read-only, so the host directory must exist first, and
   git does not track empty directories.
3. Reload Grafana's provisioning (wait 30 s, or restart the container) and
   **verify the two existing dashboards still appear exactly once** — *why*: the
   `claudestats` provider scans the parent of `parrot/`; if it also descends into
   it, TASK-3110's dashboard would appear in both folders.
4. If step 3 shows duplication, do **not** flip `foldersFromFilesStructure` —
   narrow `claudestats`' path or move `parrot/` outside it, and record which in
   the completion note. *why*: flipping it re-files the Claude Code and Codex
   dashboards, which this task must not touch.

### `docker/grafana/provisioning/dashboards/dashboards.yml` (MODIFY)

```yaml
# occurrences: 1 (verified: grep -c 'foldersFromFilesStructure: false' docker/grafana/provisioning/dashboards/dashboards.yml)
# AFTER — append below `      foldersFromFilesStructure: false` (verified: docker/grafana/provisioning/dashboards/dashboards.yml:15)

  # AI-Parrot agent telemetry. Separate provider (not just another file in the
  # dir above) so these land in their own folder instead of "Claude Code".
  - name: parrot
    orgId: 1
    folder: AI-Parrot
    type: file
    disableDeletion: false
    # Same convention as `claudestats`: provisioned dashboards are read-only in
    # the UI; "Save as" makes an editable copy.
    allowUiUpdates: false
    updateIntervalSeconds: 30
    options:
      path: /etc/grafana/provisioning/dashboards/parrot
      foldersFromFilesStructure: false
```

**Why this shape**: it mirrors the `claudestats` entry key-for-key so both
providers behave identically, differing only in `name`, `folder` and `path`. The
existing entry is left byte-identical — this task appends, never rewrites. Do not
change `folder: AI-Parrot`; TASK-3110's acceptance criterion (AC-9) names it.

### `docker/grafana/provisioning/dashboards/parrot/.gitkeep` (CREATE)

```text
```

**Why**: an empty file so git tracks the directory. The provisioning mount is
`:ro`, so Grafana cannot create it. TASK-3110 adds the real dashboard here; the
`.gitkeep` may be removed then.

### FILL IN checklist

- [ ] Step 3 duplication check — record the observed folder/dashboard counts in
      the completion note; bounded by AC-9 ("each provisioned exactly once").
- [ ] If duplication occurs: which mitigation was chosen and why; bounded by the
      step-4 constraint (do not flip `foldersFromFilesStructure`).

---

## Acceptance Criteria

- [ ] `dashboards.yml` parses as valid YAML and contains exactly two providers.
- [ ] The `claudestats` entry is byte-identical to before (`git diff` shows only
      an append).
- [ ] An **AI-Parrot** folder appears in Grafana at http://localhost:3001.
- [ ] **AC-9 (partial)** `claude-code-metrics` and `codex-overview` still appear
      in **Claude Code**, exactly once each, in no other folder.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/observability/test_grafana_provisioning.py
from pathlib import Path
import yaml

DASHBOARDS_YML = Path("docker/grafana/provisioning/dashboards/dashboards.yml")


def test_provisioning_yaml_parses_and_has_both_providers():
    """dashboards.yml declares claudestats and parrot, each with its own folder."""
    cfg = yaml.safe_load(DASHBOARDS_YML.read_text())
    by_name = {p["name"]: p for p in cfg["providers"]}
    assert set(by_name) == {"claudestats", "parrot"}
    assert by_name["parrot"]["folder"] == "AI-Parrot"
    assert by_name["parrot"]["options"]["path"].endswith("/parrot")
    # The two providers must not share a path, or dashboards provision twice.
    assert by_name["parrot"]["options"]["path"] != by_name["claudestats"]["options"]["path"]
```

---

## Agent Instructions

Standard SDD task flow. Step 3 needs the running Grafana; if it is not up, do the
file changes, then mark the duplication check as unverified in the completion
note rather than claiming AC-9.

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-09-10
**Notes**:
- `dashboards.yml` before-edit sha256 matched the Codebase Contract exactly
  (`23b20c27...`); the `parrot` provider block was appended verbatim from the
  blueprint, `claudestats` untouched (`git diff` shows a pure append).
- `docker/grafana/provisioning/dashboards/parrot/.gitkeep` created.
- `test_provisioning_yaml_parses_and_has_both_providers` (from this task's own
  Test Specification) added at
  `packages/ai-parrot/tests/unit/observability/test_grafana_provisioning.py`
  and passes.
- **UPDATE (same session, after operator brought up the docker stack):**
  `parrot-prometheus` recreated with `docker compose -f
  docker/prometheus/docker-compose.yml up -d` (old container predated the
  docker/ reorg entirely — mounted from the pre-move
  `packages/.../examples/prometheus.yml` config, missing
  `--enable-feature=otlp-write-receiver`; removed and recreated cleanly).
  `parrot-grafana` brought up via `docker compose -f
  docker/grafana/docker-compose.yml up -d --build` (required creating the
  external volume `parrot-grafana-data` first).
- **Step 3 duplication check: RUN, and it failed as designed to catch.** A
  probe dashboard JSON placed at
  `docker/grafana/provisioning/dashboards/parrot/_probe-test.json` (not
  committed) was, after the 30s provisioning scan, claimed by `claudestats`
  and misfiled into **Claude Code** — not "AI-Parrot", and not duplicated
  into both; `claudestats` recursively scans its path and evidently wins
  ownership of anything under it. This is precisely the failure mode Step
  3/4 of this task's own blueprint anticipated, independently corroborated
  by two adversarial code reviews (Claude static analysis + `codex`, P1)
  before the live check confirmed it.
- **Step 4 remediation applied**, per this task's own authorized
  contingency ("narrow claudestats' path or move parrot/ outside it"):
  moved `docker/grafana/provisioning/dashboards/parrot/` to the sibling
  `docker/grafana/provisioning/dashboards-parrot/` (git mv), added a
  matching sibling bind mount in `docker/grafana/docker-compose.yml`, and
  updated the `parrot` provider's `options.path` in `dashboards.yml`
  accordingly. `foldersFromFilesStructure` was **not** flipped (forbidden
  by the blueprint) and `claudestats`' own entry was **not** touched.
  Re-verified with a second probe in the new location: landed correctly in
  **AI-Parrot**, exactly once; `claudestats`' two existing dashboards
  (`claude-code-metrics`, `codex-overview`) stayed in **Claude Code**,
  untouched, exactly once each. Both probe files were removed after
  verification (not committed).
- Added `test_parrot_path_is_not_nested_under_claudestats` as a permanent
  static regression guard, separate from committing this in a follow-up
  commit (`fix(...): TASK-3109 — move parrot dashboards to a sibling
  mount...`) once the live evidence existed.
- **AC-9 is now fully claimed and verified**, not left unverified.

**Deviations from spec**: the file contract in spec §3 Module 3 specified
`path: /etc/grafana/provisioning/dashboards/parrot` (nested). Live
verification proved this nesting causes silent misfiling by the
`claudestats` provider, defeating AC-9. Remediated to a sibling path
(`docker/grafana/provisioning/dashboards-parrot/`) per this task's own
explicit Step 4 contingency for exactly this outcome — not an unauthorized
redesign, but the designated fallback, now exercised because Step 3's live
check (previously blocked, now run) confirmed the failure it was written to
catch.
