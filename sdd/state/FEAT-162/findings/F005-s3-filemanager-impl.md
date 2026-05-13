---
id: F005
query_id: Q005
type: read
intent: Read S3FileManager to confirm async upload/download API and aws_config shape.
executed_at: 2026-05-12T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F005 — S3FileManager: aioboto3-backed, no `aws_config` param; uses `credentials` dict or `aws_id` lookup

## Summary

`S3FileManager` lives at `.venv/lib/python3.11/site-packages/navigator/utils/file/s3.py`
(installed via the `navigator-api` package; re-exported by `parrot.interfaces.file.s3`).
It is fully async (uses `aioboto3`). Its constructor accepts `bucket_name`,
`aws_id` (key into `AWS_CREDENTIALS`), `region_name`, `prefix`, and an optional
`credentials` kwarg with `aws_key`/`aws_secret`. There is **NO `aws_config` parameter**
— the brainstorm's claim is wrong. The instance attribute `self.aws_config` exists
internally but is built from `creds["aws_key"]` etc., not passed in.

## Citations

- path: `.venv/lib/python3.11/site-packages/navigator/utils/file/s3.py`
  lines: 35-100
  symbol: S3FileManager class header + __init__
  excerpt: |
    class S3FileManager(FileManagerInterface):
        manager_name: str = "s3file"
        MULTIPART_THRESHOLD: int = 100 * 1024 * 1024  # 100MB
        MULTIPART_CHUNKSIZE: int = 10 * 1024 * 1024   # 10MB
        MAX_CONCURRENCY: int = 10
        def __init__(self, bucket_name=None, aws_id="default", region_name=None,
                     prefix="", multipart_threshold=None, multipart_chunksize=None,
                     max_concurrency=None, **kwargs) -> None:

- path: `.venv/lib/python3.11/site-packages/navigator/utils/file/s3.py`
  lines: 88-115
  symbol: credential resolution
  excerpt: |
    explicit_creds = kwargs.get("credentials", None)
    if explicit_creds:
        creds = explicit_creds
    else:
        creds = AWS_CREDENTIALS.get(aws_id) or AWS_CREDENTIALS.get("default")
    self.aws_config = {
        "aws_access_key_id": creds["aws_key"],
        "aws_secret_access_key": creds["aws_secret"],
        "region_name": region_name or creds.get("region_name", "us-east-1"),
    }
    self.bucket_name = bucket_name or creds.get("bucket_name")
    self.session = aioboto3.Session()

- path: `.venv/lib/python3.11/site-packages/navigator/utils/file/s3.py`
  lines: 120-160
  symbol: prefix + s3 client helpers
  excerpt: |
    def _prefixed(self, key: str) -> str:
        return self.prefix + key.lstrip("/")
    async def _s3_client(self):
        return self.session.client(
            "s3", aws_access_key_id=self.aws_config["aws_access_key_id"], ...
        )

## Notes

- AWS_CREDENTIALS is read from `parrot.conf` (see F014); it has slots `default`,
  `monitoring`, `cloudwatch`, `backend`. For SecurityAgent, the cleanest option
  is to add a new slot (`"security"`) sourced from `aws_security.*` ini, OR pass
  `credentials={...}` explicitly built from the existing
  `self._aws_credentials` dict on the agent.
- `prefix` is auto-appended with `/` (line 83): `prefix.rstrip("/") + "/"`.
