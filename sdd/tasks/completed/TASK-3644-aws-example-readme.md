# TASK-3644: `examples/planogram/aws/README.md`

**Feature**: FEAT-592 — Amazon Nova 2 Lite slot identification for planogram images
**Spec**: `sdd/specs/nova-image-planogram.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3639
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 5 (documentation half).

The example has prerequisites a reader cannot guess: Nova 2 Lite has **no
in-region access in any region**, so a geo inference profile is mandatory; the
credentials come from `parrot.conf`'s `AWS_CREDENTIALS` profile chain rather than
plain env vars; and the whole `examples/planogram/` tree is git-ignored except
for explicit negation rules. Without this README the first run fails with a raw
AWS access error and the reader has no way to know why.

The flag list, output files and exit codes are already fixed by spec §3 Module 5,
so this task needs no code to exist first.

---

## Scope

- Write `examples/planogram/aws/README.md` covering: what the example does,
  prerequisites (region, model access, IAM, credentials), install, usage with
  every flag, the output files, exit codes, the geo-prefix caveat, cost notes and
  the relationship to the planogram pipeline.

**NOT in scope**: any Python file (TASK-3640/3641/3642/3643 own those); editing
`examples/planogram/README.md`; documenting the follow-up `BedrockConverseBase`
image-support feature beyond a one-line pointer.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/planogram/aws/README.md` | CREATE | Setup, usage, prerequisites and caveats |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# None — this task creates a Markdown document only.
```

### Existing Signatures to Use
```text
# Facts this README must state, all verified:
#
# packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/client.py:58-62
#   "Nova 2 Lite and Nova Premier have NO in-region model access; they require a
#    geo/global inference-profile prefix (us./eu./jp./global.). region_prefix
#    therefore DEFAULTS to 'us' here."
# packages/ai-parrot-client-amazon/src/parrot/clients/amazon/models.py:150
#   "nova-2-lite": "amazon.nova-2-lite-v1:0"   -> resolves to us.amazon.nova-2-lite-v1:0
# packages/ai-parrot-client-amazon/src/parrot/clients/amazon/bedrock.py:300-313
#   credential chain: aws_id -> AWS_CREDENTIALS[profile] -> AWS_CREDENTIALS['default']
#   -> explicit kwargs -> bearer token; region: kwarg -> profile.region_name ->
#   BEDROCK_AWS_REGION -> AWS_REGION_NAME -> "us-east-1"
# packages/ai-parrot/src/parrot/conf.py:496-531
#   AWS_CREDENTIALS profiles: default, monitoring, cloudwatch, backend, security,
#   security_bucket; keys use_credentials / aws_key / aws_secret / region_name
# packages/ai-parrot-client-amazon/pyproject.toml:17
#   "aioboto3>=13.2.0"   -> already declared; no new dependency
# .gitignore:418  examples/planogram/*      -> the tree is ignored by default
# .gitignore:442+ the FEAT-592 negation block added by TASK-3639
#
# Flags, outputs and exit codes — spec §3 Module 5 / §2 "User-Facing Behavior":
#   --image (required) --boxes --planogram --output (required) --model --region
#   --aws-id --concurrency (default 4) --no-marks --cache-dir
#   outputs: detections.json, annotated.jpg, run.json
#   exit codes: 0 success, 1 invalid input, 2 completed with errors
```

### Does NOT Exist
- ~~`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` as this example's documented mechanism~~ — credentials resolve through `parrot.conf`'s `AWS_CREDENTIALS` profiles (resolved decision); the plain env vars are only the SDK's last fallback.
- ~~in-region `amazon.nova-2-lite-v1:0`~~ — Nova 2 Lite has NO in-region access in ANY region; a geo/global prefix is mandatory.
- ~~a `requirements.txt` for this example~~ — dependencies are declared in `pyproject.toml`; `aioboto3` is already present.
- ~~`git add -f` as the way to track these files~~ — TASK-3639 adds `.gitignore` negation rules instead.
- ~~a test suite covering the Converse transport~~ — spec §8 Q1 resolved to a runtime guard; do not promise tests that do not exist.
- ~~`examples/planogram/aws/README.md`~~ — created by this task.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "examples/planogram/aws/README.md",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- The repo is **public**. Never include real account ids, ARNs, access keys,
  bucket names or retailer data. Use placeholders.
- State plainly that photos, `results/` and the vision cache stay git-ignored and
  only code plus this README are tracked — mirroring the wording style of
  `examples/planogram/README.md`.
- Lead with the geo-prefix caveat: it is the single most likely first-run failure.
- Be honest about what is NOT covered: no automated test of the live Converse
  round-trip; the transport is guarded at runtime instead (spec §8 Q1).

### References in Codebase
- `examples/planogram/README.md` — tone, structure and the "What stays local" section to mirror.
- `examples/planogram/perception_spike/README.md` and `examples/planogram/pipelines/README.md` — sibling example READMEs.
- `examples/agents/aws/README.md` — existing AWS Bedrock setup instructions.

---

## Implementation Blueprint

### Steps (in order)
1. Open with one paragraph on what the example does and how it relates to the planogram cycle — *why*: a reader landing here from `examples/planogram/` needs to know this is Stage-2 identification on a different provider, not a new pipeline.
2. Put prerequisites second, geo-prefix caveat first within them — *why*: it is the most likely first-run failure and a raw AWS access error does not explain itself.
3. Document every flag from spec §3 Module 5 — *why*: AC1 asserts `--help` lists them, and the README must not drift from it.
4. Document the three output files and the three exit codes — *why*: exit 2 ("completed with errors") is meaningless to a script author who has not been told.
5. Close with cost notes and the known limitations — *why*: the run's whole purpose is a cost/accuracy decision (spec G5).

### `examples/planogram/aws/README.md` (CREATE)
```markdown
# Planogram slot identification with Amazon Nova 2 Lite

Feeds real Stage-1 OpenCV detection boxes to Amazon Nova 2 Lite and asks, per box,
whether a product is present and which brand/product it is. Output is flat
`{bbox, brand, product, occupancy}` JSON in source-image pixels, plus an annotated
image.

This is Stage-2 **identification** of the planogram cycle
(`perceive → identify → compare`) running on a different provider — not a new
pipeline. It reuses the pipeline's Set-of-Marks rendering, response cache, repair
retry and id reconciliation unchanged.

<!-- FILL IN: one short paragraph on WHY this exists — that no parrot client can
     send Nova an image today, and this example is the evidence that decides
     whether to add that support. Bounded by spec §1 Problem Statement. -->

## What stays local

<!-- FILL IN: photos, results/, the vision cache and any planogram JSON are
     git-ignored; only the .py files and this README are tracked, via the
     negation rules in .gitignore. Bounded by: the repo is public. -->

## Prerequisites

> **Nova 2 Lite has no in-region access in any AWS region.** A geo inference
> profile prefix (`us.` / `eu.` / `jp.` / `global.`) is mandatory. The default
> model id is `us.amazon.nova-2-lite-v1:0`; a bare `amazon.nova-2-lite-v1:0`
> fails with an access error.

<!-- FILL IN: Bedrock model access must be granted per account AND per region
     (us-east-1 for the reference runs); the IAM permission needed is
     bedrock:InvokeModel on the inference profile; credentials resolve through
     parrot.conf AWS_CREDENTIALS profiles (keys: aws_key, aws_secret,
     region_name), selected with --aws-id, falling back to 'default' then to the
     SDK chain. Use placeholders only — the repo is public.
     Bounded by: bedrock.py:300-313 and conf.py:496-531. -->

## Install

<!-- FILL IN: source .venv/bin/activate; the packages needed are ai-parrot,
     ai-parrot-client-amazon, ai-parrot-pipelines, opencv-python, numpy;
     aioboto3 is already a declared dependency of ai-parrot-client-amazon, so
     there is nothing extra to install. Bounded by: no new dependency (spec §7). -->

## Usage

```bash
source .venv/bin/activate
python examples/planogram/aws/nova2.py \
    --image examples/planogram/images/shelf_01.jpg \
    --planogram examples/planogram/planogram_page1.json \
    --output examples/planogram/results/nova_run1
```

<!-- FILL IN: a table or list of all ten flags with defaults —
     --image (required), --boxes, --planogram, --output (required), --model,
     --region, --aws-id, --concurrency (4), --no-marks, --cache-dir.
     Bounded by spec §3 Module 5; must match `--help` exactly (AC1). -->

## Outputs

<!-- FILL IN: detections.json (flat rows, bbox in SOURCE-IMAGE PIXELS),
     annotated.jpg, run.json (model id, region, prompt version, strips, calls,
     cache_hits, incomplete_retries, image_bytes_sent, tokens, wall time).
     Exit codes: 0 success, 1 invalid input, 2 completed with errors.
     Bounded by spec §2 "User-Facing Behavior" and AC5. -->

## Cost and repeat runs

<!-- FILL IN: one strip can cost up to THREE provider calls (a schema repair retry
     plus a missing-id repair prompt), so read run.json's `calls`, not `strips`,
     when reasoning about cost; --cache-dir makes a re-run free and byte-identical.
     Bounded by spec §9 S8 and AC14. -->

## Known limitations

<!-- FILL IN: (1) the transport is a prototype shim — parrot's Bedrock client still
     drops image attachments, and this example works around that; (2) the closed-set
     prompt is example-local and does not exist in the pipeline; (3) there is no
     automated test of the live Converse round-trip — the request is guarded at
     runtime instead, refusing to send a call with no image block.
     Bounded by spec §1 Non-Goals and §8 Q1. -->
```
**Why this shape**: the geo-prefix caveat is a block quote directly under
Prerequisites because it is the single most likely first-run failure and the AWS
error message does not explain itself. The flag list must be kept in step with
`_build_parser` in `nova2.py` — AC1 asserts `--help` lists every flag, so a drifted
README is a real defect, not cosmetic. The "Known limitations" section is required,
not optional: this example deliberately has no transport test, and a reader who
assumes otherwise would over-trust a green run.

### FILL IN checklist
- [ ] Intro paragraph — why this exists; bounded by spec §1 Problem Statement
- [ ] "What stays local" — bounded by: the repo is public, only code + README tracked
- [ ] Prerequisites body — model access, IAM, credential chain; bounded by `bedrock.py:300-313`, `conf.py:496-531`; placeholders only
- [ ] Install — bounded by: no new dependency
- [ ] Flag list — all ten flags with defaults; bounded by spec §3 Module 5 / AC1
- [ ] Outputs + exit codes — bounded by spec §2 and AC5
- [ ] Cost and repeat runs — bounded by spec §9 S8 and AC14
- [ ] Known limitations — bounded by spec §1 Non-Goals and §8 Q1

---

## Acceptance Criteria

- [ ] The README documents all ten flags with their defaults, matching spec §3 Module 5.
- [ ] The geo-prefix requirement is stated prominently, with the correct default id `us.amazon.nova-2-lite-v1:0`.
- [ ] Credential resolution is documented as the `parrot.conf` `AWS_CREDENTIALS` profile chain, selected by `--aws-id`.
- [ ] The three output files and the three exit codes are documented.
- [ ] It states that one strip can cost up to three provider calls and points at `run.json`'s `calls`.
- [ ] It states that there is no automated test of the live Converse round-trip and that the request is guarded at runtime instead.
- [ ] No real account id, ARN, access key or retailer data appears anywhere.
- [ ] `git check-ignore -q examples/planogram/aws/README.md` exits 1 (the file is trackable).

---

## Validation Commands

- `pytest examples/planogram/tests/test_plancheck_gitignore.py -q`

---

## Test Specification

No new test module — this task ships documentation only. The gitignore invariant
test is the one automated check that applies, since it proves the README is
trackable rather than silently ignored:

```python
# examples/planogram/tests/test_plancheck_gitignore.py (existing)
@pytest.mark.parametrize("path", NOT_IGNORED)
def test_gitignore_tracks_code_not_photos(path: str) -> None:
    assert not _is_ignored(path)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§2 "User-Facing Behavior", §3 Module 5, §7, §8 Q1).
2. **Check dependencies** — TASK-3639 must be in `sdd/tasks/completed/`: without its `.gitignore` negation block, `git add` of your new files under `examples/planogram/aws/` silently does nothing. The flag list is fixed by the spec, so this can be
   written before `nova2.py` exists; if TASK-3643 has landed, cross-check `--help`.
3. **Verify the Codebase Contract** — confirm the model-access and credential facts
   still read as listed before documenting them.
4. **Update status** in `sdd/tasks/index/nova-image-planogram.json` → `"in-progress"`.
5. **Implement** — start from the blueprint block, complete every `<!-- FILL IN -->`,
   and keep the heading structure the blueprint fixes.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/TASK-3644-aws-example-readme.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note


- Task: TASK-3644
- Feature: nova-image-planogram
- Implementation SHA: 3c496a740d1899a1f6feb034a764fcdbde74e64f
- Closed at (UTC): 2026-09-23T00:00:18+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: kimi · Backend: nova · Model: moonshotai.kimi-k2.5 · Attempts: 1 · Duration: 87.12s · Tokens: 610797/2714 |
| test_result | No code; README reviewed in full against spec S3 M5, no corrections needed. |
| tests_passed | True |
