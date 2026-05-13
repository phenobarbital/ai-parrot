---
finding_id: F007
query_id: Q008,Q011,Q015
type: gap
confidence: high
citations:
  - packages/ai-parrot-tools/src/parrot_tools/aws/ecr.py
  - packages/ai-parrot-tools/src/parrot_tools/aws/inspector.py
  - packages/ai-parrot-tools/src/parrot_tools/cloudsploit/
---

# Gap: no multi-repo / tag-priority iteration anywhere

Greps for "describe_image_scan_findings" hit exactly ONE call site (ecr.py:196).
No code in `packages/` does:

- A hard-coded or config-driven list of repos.
- A per-repo prioritized list of tags with first-match-wins fallback.
- An aggregate JSON output of `{generated_at, region, repos: [...]}`.

The JS script's value-add is precisely this orchestration on top of the per-image
endpoint. Two design choices follow:

1. **Where the repo list lives.** Hard-coding in Python is worse than the JS
   version — the user already has 23 repos and tag priorities. Should be a
   Pydantic-validated config (file path / dict / env-driven) so it changes
   without code edits. Most natural: a `EcrCollectionPlan` Pydantic model
   loaded from a YAML/JSON file (path on `CloudSploitConfig` or a new
   `EcrScanConfig`).
2. **Where the orchestration lives.** Best as a standalone collaborator
   (`EcrScanCollector` or similar) that takes a plan + an `ECRToolkit`-like
   client and returns an `EcrCollectionResult`. Then a single public toolkit
   method (`collect_ecr_findings(plan_path=None)`) becomes the agent-facing
   tool.

Concurrency: ECR's `describe_image_scan_findings` is rate-limited; for 23
repos with up to 3 tag attempts each, parallel calls with a small semaphore
(e.g. 5–8 concurrent) is the right tradeoff. The JS script runs strictly
sequentially. The Python version can be significantly faster.
