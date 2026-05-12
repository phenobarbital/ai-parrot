---
id: F014
query_id: Q014
type: grep
intent: Check navconfig (parrot.conf) for AWS_KEY, AWS_SECRET, S3_ARTIFACT_BUCKET, AWS_REGION_NAME, DEFAULT_PG_DSN, aws_security.* keys actually defined.
executed_at: 2026-05-12T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F014 — navconfig keys exist but with DIFFERENT names than the brainstorm assumes; `aws_security.*` is NOT in `parrot.conf`

## Summary

The brainstorm assumes `config.AWS_KEY`, `config.AWS_SECRET`,
`config.S3_ARTIFACT_BUCKET`, `config.AWS_REGION_NAME`, `config.DEFAULT_PG_DSN`,
and `config.aws_security.*`. The reality:
- `parrot/conf.py` exports **`AWS_ACCESS_KEY`** (not `AWS_KEY`) and
  **`AWS_SECRET_KEY`** (not `AWS_SECRET`). Lowercase `aws_key` / `aws_secret`
  do exist as **module-level locals**, accessed via `config.get("AWS_KEY")`.
- `S3_ARTIFACT_BUCKET` exists (line 475) — confirmed.
- `AWS_REGION_NAME` exists (line 418) — confirmed.
- There is **NO `DEFAULT_PG_DSN`** in `parrot.conf`. The Postgres DSN is
  imported from `navigator.conf` as `default_dsn` (line 7). Also exposed as
  `CREW_RESULT_STORAGE_PG_DSN` (line 275) and `PARROT_POSTGRES_DSN` (line 486).
- `aws_security.*` is **not present in `parrot/conf.py`** — but `agents/security.py`
  uses it: `config.get("aws_security", "AWS_ACCESS_SECURITY_KEY_ID")` (line 101),
  meaning it is a separate ini section read on demand, NOT a parrot.conf constant.

## Citations

- path: `packages/ai-parrot/src/parrot/conf.py`
  lines: 7
  symbol: import of navconfig default_dsn
  excerpt: |
    from navigator.conf import default_dsn, CACHE_HOST, CACHE_PORT

- path: `packages/ai-parrot/src/parrot/conf.py`
  lines: 60-68
  symbol: fallback default_dsn local definition
  excerpt: |
    default_dsn = f'postgres://{DBUSER}{_pwd}@{DBHOST}:{DBPORT}/{DBNAME}'
    async_default_dsn = f'postgresql+asyncpg://{DBUSER}{_pwd}@{DBHOST}:{DBPORT}/{DBNAME}'

- path: `packages/ai-parrot/src/parrot/conf.py`
  lines: 408-422
  symbol: AWS credentials
  excerpt: |
    aws_region = config.get("AWS_REGION", fallback="us-east-1")
    aws_bucket = config.get("AWS_BUCKET", fallback="static-files")
    aws_key    = config.get("AWS_KEY")
    aws_secret = config.get("AWS_SECRET")
    AWS_ACCESS_KEY = config.get("AWS_ACCESS_KEY", fallback=aws_key)
    AWS_SECRET_KEY = config.get("AWS_SECRET_KEY", fallback=aws_secret)
    AWS_REGION_NAME = config.get("AWS_REGION_NAME", fallback=aws_region)

- path: `packages/ai-parrot/src/parrot/conf.py`
  lines: 432-458
  symbol: AWS_CREDENTIALS dict (used by S3FileManager via aws_id)
  excerpt: |
    AWS_CREDENTIALS = {
        "default":    {..., "aws_key": aws_key,        "aws_secret": aws_secret,        "region_name": aws_region,    "bucket_name": aws_bucket},
        "monitoring": {..., "aws_key": AWS_ACCESS_KEY, "aws_secret": AWS_SECRET_KEY,    "region_name": AWS_REGION_NAME},
        "cloudwatch": {..., "aws_key": config.get("AWS_CLOUDWATCH_KEY"), ...},
        "backend":    {..., "aws_key": BACKEND_AWS_ACCESS_KEY,           "aws_secret": BACKEND_AWS_SECRET_KEY, ...},
    }

- path: `packages/ai-parrot/src/parrot/conf.py`
  lines: 475
  symbol: S3_ARTIFACT_BUCKET
  excerpt: |
    S3_ARTIFACT_BUCKET = config.get("S3_ARTIFACT_BUCKET", fallback=aws_bucket)

- path: `agents/security.py`
  lines: 100-108
  symbol: real usage of aws_security ini section
  excerpt: |
    aws_access_key_id = config.get("aws_security", "AWS_ACCESS_SECURITY_KEY_ID")
    aws_secret_access_key = config.get("aws_security", "AWS_SECRET_SECURITY_KEY")

## Notes

- For the SecurityAgent's persistence wiring, the cleanest pattern is to add a
  new `AWS_CREDENTIALS["security"] = {...}` slot in `parrot.conf` sourced from
  the `aws_security` ini section, then call `FileManagerFactory.create("s3",
  bucket_name=SECURITY_REPORT_BUCKET, prefix=..., aws_id="security")`. That
  removes the need to plumb explicit `credentials` dicts through the mixin.
- Brainstorm Env Var table (§8) introduces 5 new keys:
  `SECURITY_REPORT_BUCKET`, `SECURITY_REPORT_S3_PREFIX`,
  `SECURITY_REPORT_PG_DSN`, `SECURITY_REPORT_DEFAULT_VISIBILITY_DAYS`,
  `SECURITY_REPORT_LLM_MODEL`. None exist yet.
- `S3_ARTIFACT_BUCKET` defaults to `aws_bucket` ("static-files") — using it as
  fallback is fine but the security spec should clearly require an explicit
  `SECURITY_REPORT_BUCKET` in production.
