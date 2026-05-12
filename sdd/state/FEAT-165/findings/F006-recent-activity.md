---
finding_id: F006
query_id: Q016
type: activity
confidence: medium
citations:
  - git log dev -- packages/ai-parrot-tools/src/parrot_tools/cloudsploit/
  - git log dev -- packages/ai-parrot-tools/src/parrot_tools/aws/inspector.py
  - git log dev -- packages/ai-parrot-tools/src/parrot_tools/aws/ecr.py
---

# Active feature work in adjacent areas

Recent commits on `dev` (since 2026-04):

- **`feat-160-cloudsploit-config-support`** (merged 2026-05-12, `bfb825e7`):
  added `--config=<path>` plumbing through `CloudSploitConfig.config_file`,
  `_build_cli_args`, executor, and toolkit. The `_resolve_config` helper
  (toolkit.py:75-101) is now the canonical pattern for per-call overrides.
- **`feat-XXX-inspector-toolkit`** (commits `5d88b83c`...`a9e3fabd`, merged
  early May 2026): full `InspectorToolkit` with ECR-aware filters
  (`AWS_ECR_CONTAINER_IMAGE`, `repository_name`, `ecrImageHash`).
- **`security-report-catalog`** (commit `87efb7d9`, 2026-05-12, TASK-1110):
  CloudSploitToolkit wired through `ReportPersistenceMixin` for catalog
  uploads.
- **`8b7eb250 wip: aws agent`** (current branch tip 2026-05-12): in-flight
  work on an AWS agent — likely the consumer of these toolkits.

**Implication:** The toolkit surface is being actively expanded. The user's
proposal lands in a hot zone — coordination with the "aws agent" work
matters. No code currently does multi-repo ECR scan aggregation, so there's
no overlap to merge with.

The ECR Basic Scanning API the JS script calls is the *legacy* path; the
new `InspectorToolkit` provides the Enhanced-Scanning equivalent. Both
should be supported — many of the listed repos may only have Basic Scanning
enabled, while newer/Enhanced-scanned repos surface their data via
Inspector v2 instead.
