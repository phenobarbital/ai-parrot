---
finding_id: F001
query_id: Q001,Q002,Q014
type: file-inventory
confidence: high
citations:
  - packages/ai-parrot-tools/src/parrot_tools/cloudsploit/__init__.py
  - packages/ai-parrot-tools/src/parrot_tools/cloudsploit/toolkit.py
  - packages/ai-parrot-tools/src/parrot_tools/cloudsploit/executor.py
  - packages/ai-parrot-tools/src/parrot_tools/cloudsploit/models.py
  - packages/ai-parrot-tools/src/parrot_tools/cloudsploit/parser.py
  - packages/ai-parrot-tools/src/parrot_tools/cloudsploit/reports.py
  - packages/ai-parrot-tools/src/parrot_tools/cloudsploit/comparator.py
---

# CloudSploit toolkit shape

The toolkit is a single `CloudSploitToolkit(ReportPersistenceMixin, AbstractToolkit)`
that orchestrates four collaborators:

- **`CloudSploitExecutor`** (`executor.py`) — runs `cloudsploit` via Docker (default)
  or direct CLI. Strictly tied to running the **CloudSploit CLI itself**: builds
  CLI args (`--json=`, `--cloud=`, `--config=`), bind-mounts a temp dir for output,
  passes AWS creds via env vars (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
  `AWS_SESSION_TOKEN`, `AWS_PROFILE`, `AWS_REGION`, `AWS_DEFAULT_REGION`,
  `AWS_SDK_LOAD_CONFIG`).
- **`ScanResultParser`** (`parser.py`) — parses CloudSploit's own JSON shape
  (either flat array or nested-by-plugin) into `ScanResult`.
- **`ReportGenerator`** (`reports.py`) — Jinja2-based HTML + xhtml2pdf PDF.
  Templates live in `cloudsploit/templates/` (`scan_report.html`,
  `comparison_report.html`).
- **`ScanComparator`** (`comparator.py`) — diffs two `ScanResult`s by
  `(plugin, region, resource)` key.

`CloudSploitToolkit` (`toolkit.py:27`) exposes five public async methods
(each auto-becomes an agent tool via `AbstractToolkit`):

- `run_scan(...)` — `toolkit.py:105`
- `run_compliance_scan(framework, ...)` — `toolkit.py:157`
- `get_summary()` — `toolkit.py:204`
- `generate_report(format, output_path)` — `toolkit.py:215`
- `compare_scans(baseline_path, current_path)` — `toolkit.py:249`
- `list_findings(severity, category, region)` — `toolkit.py:276`

Persistence is wired via `ReportPersistenceMixin` mixed in first
(`toolkit.py:27`), with `pop_persistence_kwargs(kwargs)` called BEFORE
`super().__init__(**kwargs)` (toolkit.py:36-39).

**Implication for ECR work:** The "CloudSploit" toolkit is currently a
**single-target wrapper around the CloudSploit Node.js scanner**. ECR vuln
collection is *not* a CloudSploit-CLI invocation — it talks directly to the
AWS ECR API. So the JS scripts the user pasted are conceptually orthogonal
to `CloudSploitExecutor`: they belong alongside it but should not run through it.

Naming the new capability "CloudSploitToolkit.scan_ecr_images" would be
misleading. The natural home is either:
1. A sibling module (e.g. `cloudsploit/ecr.py` with an `ECRScanCollector`
   collaborator) wired into the same toolkit class, OR
2. The existing `parrot_tools/aws/ecr.py::ECRToolkit` extended with a
   multi-repo aggregator (see F003).
