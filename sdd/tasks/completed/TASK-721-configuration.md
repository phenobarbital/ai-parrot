# TASK-721: DynamoDB & S3 Configuration

**Feature**: FEAT-103 — Agent Artifact Persistency
**Spec**: `sdd/specs/agent-artifact-persistency.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec Module 6. Adds DynamoDB and S3 artifact configuration variables to `parrot/conf.py`. These are consumed by `ConversationDynamoDB` and `S3OverflowManager`.

---

## Scope

- Add to `parrot/conf.py`:
  - `DYNAMODB_CONVERSATIONS_TABLE` — table name for conversations+turns (default: `"parrot-conversations"`)
  - `DYNAMODB_ARTIFACTS_TABLE` — table name for artifacts (default: `"parrot-artifacts"`)
  - `DYNAMODB_REGION` — AWS region for DynamoDB (default: falls back to `AWS_REGION_NAME`)
  - `DYNAMODB_ENDPOINT_URL` — optional endpoint for DynamoDB Local testing (default: None)
  - `S3_ARTIFACT_BUCKET` — S3 bucket for artifact overflow (default: falls back to `aws_bucket`)
- Optionally add a `dynamodb` entry to `AWS_CREDENTIALS` dict if separate credentials are needed

**NOT in scope**: DynamoDB backend implementation, S3 overflow implementation.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/conf.py` | MODIFY | Add DynamoDB and S3 artifact config variables |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# parrot/conf.py uses navconfig for configuration:
# config = ... (navconfig instance)
# Variables are read via config.get("ENV_VAR", fallback="default")
```

### Existing Signatures to Use
```python
# parrot/conf.py:380-412 — existing AWS config pattern:
aws_region = config.get("AWS_REGION", fallback="us-east-1")
aws_bucket = config.get("AWS_BUCKET", fallback="static-files")
AWS_ACCESS_KEY = config.get("AWS_ACCESS_KEY", fallback=aws_key)
AWS_SECRET_KEY = config.get("AWS_SECRET_KEY", fallback=aws_secret)
AWS_REGION_NAME = config.get("AWS_REGION_NAME", fallback=aws_region)

AWS_CREDENTIALS = {
    'default': {
        'bucket_name': aws_bucket,
        'aws_key': AWS_ACCESS_KEY,
        'aws_secret': AWS_SECRET_KEY,
        'region_name': AWS_REGION_NAME,
    },
}
```

### Does NOT Exist
- ~~`parrot.conf.DYNAMODB_CONVERSATIONS_TABLE`~~ — does not exist; this task adds it
- ~~`parrot.conf.DYNAMODB_ARTIFACTS_TABLE`~~ — does not exist
- ~~`parrot.conf.S3_ARTIFACT_BUCKET`~~ — does not exist

---

## Implementation Notes

### Pattern to Follow
```python
# Follow the existing pattern in parrot/conf.py for AWS config:
DYNAMODB_CONVERSATIONS_TABLE = config.get(
    "DYNAMODB_CONVERSATIONS_TABLE", fallback="parrot-conversations"
)
DYNAMODB_ARTIFACTS_TABLE = config.get(
    "DYNAMODB_ARTIFACTS_TABLE", fallback="parrot-artifacts"
)
DYNAMODB_REGION = config.get("DYNAMODB_REGION", fallback=AWS_REGION_NAME)
DYNAMODB_ENDPOINT_URL = config.get("DYNAMODB_ENDPOINT_URL", fallback=None)
S3_ARTIFACT_BUCKET = config.get("S3_ARTIFACT_BUCKET", fallback=aws_bucket)
```

### Key Constraints
- Place new variables near the existing AWS configuration section (~line 380-412)
- Use `config.get()` with sensible fallback defaults
- Do NOT modify existing variables — only add new ones

---

## Acceptance Criteria

- [ ] `from parrot.conf import DYNAMODB_CONVERSATIONS_TABLE, DYNAMODB_ARTIFACTS_TABLE` works
- [ ] `from parrot.conf import DYNAMODB_REGION, S3_ARTIFACT_BUCKET` works
- [ ] Default values are reasonable (`"parrot-conversations"`, `"parrot-artifacts"`, etc.)
- [ ] No existing config broken

---

## Agent Instructions

When you pick up this task:

1. **Read** `parrot/conf.py` — find the AWS configuration section
2. **Add** the new variables following the existing pattern
3. **Verify** imports work
4. **Move + update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*
