---
id: F003
query_id: Q003
type: read
intent: Read FileManagerFactory and its create() signature for s3/fs/gcs/temp manager types.
executed_at: 2026-05-12T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F003 — Two `FileManagerFactory` classes exist; parrot-side one accepts `manager_type` literal but DOES NOT accept `aws_config` kwarg

## Summary

There are TWO `FileManagerFactory` classes. The parrot-side one in
`parrot.tools.filemanager` is a thin delegate that translates `"fs"` → `"local"`
and forwards everything else to the upstream `navigator.utils.file.FileManagerFactory`.
The upstream factory creates managers by **kwargs forwarded to the manager constructor**.
The brainstorm's call shape `FileManagerFactory.create(manager_type="s3", bucket_name=..., prefix=..., aws_config={...})`
is **partially wrong**: there is no `aws_config` parameter on either factory or on `S3FileManager.__init__`.
The S3 manager uses `aws_id` (a key into `AWS_CREDENTIALS`) OR an explicit `credentials` kwarg
(`{aws_key, aws_secret, region_name, bucket_name}`).

## Citations

- path: `packages/ai-parrot/src/parrot/tools/filemanager.py`
  lines: 22-62
  symbol: FileManagerFactory.create (parrot-side delegate)
  excerpt: |
    class FileManagerFactory:
        _PARROT_TO_UPSTREAM = {"fs": "local", "temp": "temp", "s3": "s3", "gcs": "gcs"}

        @staticmethod
        def create(
            manager_type: Literal["fs", "temp", "s3", "gcs"],
            **kwargs: Any,
        ) -> FileManagerInterface:
            upstream_key = FileManagerFactory._PARROT_TO_UPSTREAM[manager_type]
            return _UpstreamFileManagerFactory.create(upstream_key, **kwargs)

- path: `.venv/lib/python3.11/site-packages/navigator/utils/file/factory.py`
  lines: 14-73
  symbol: upstream FileManagerFactory (navigator.utils.file)
  excerpt: |
    class FileManagerFactory:
        _EAGER_MANAGERS = {"local": (".local", "LocalFileManager"), "temp": (".tmp", "TempFileManager")}
        _LAZY_MANAGERS  = {"s3": (".s3", "S3FileManager"),          "gcs": (".gcs", "GCSFileManager")}
        @staticmethod
        def create(manager_type: str, **kwargs: Any) -> FileManagerInterface:
            module = importlib.import_module(module_rel, package=__package__)
            cls = getattr(module, class_name)
            return cls(**kwargs)

- path: `.venv/lib/python3.11/site-packages/navigator/utils/file/s3.py`
  lines: 55-115
  symbol: S3FileManager.__init__
  excerpt: |
    def __init__(self,
        bucket_name: Optional[str] = None,
        aws_id: str = "default",           # key into AWS_CREDENTIALS
        region_name: Optional[str] = None,
        prefix: str = "",
        multipart_threshold: Optional[int] = None,
        multipart_chunksize: Optional[int] = None,
        max_concurrency: Optional[int] = None,
        **kwargs,                          # may contain credentials={"aws_key":..., "aws_secret":...}
    ) -> None:

## Notes

- The brainstorm's `FileManagerFactory.create(manager_type="s3", bucket_name=..., prefix=..., aws_config={"aws_access_key_id":..., "aws_secret_access_key":..., "region_name":...})`
  must be **rewritten** to either:
  (a) `FileManagerFactory.create("s3", bucket_name=..., prefix=..., credentials={"aws_key":..., "aws_secret":..., "region_name":...})` OR
  (b) `FileManagerFactory.create("s3", bucket_name=..., prefix=..., aws_id="monitoring")` (uses preconfigured AWS_CREDENTIALS["monitoring"] from parrot.conf).
- Option (b) is more idiomatic for AI-Parrot.
