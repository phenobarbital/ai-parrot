# F009 — S3Toolkit (AWS bucket inspection)

**Path**: `packages/ai-parrot-tools/src/parrot_tools/aws/s3.py`
**Lines**: 47-372

`class S3Toolkit(AbstractToolkit)` — inspects bucket-level security.
NOT a content reader. Tools: list_buckets, get_bucket_details,
analyze_bucket_security, find_public_buckets.

This is about bucket configuration, not about reading objects inside
buckets. The new toolkit needs object-level reading, not bucket-level.
