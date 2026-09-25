---
id: F013
query_id: Q017
type: grep
intent: aiogoogle media upload/download support (upload_file / pipe_from / download_file / pipe_to / resumable)
executed_at: 2026-09-25T22:54:20Z
duration_ms: 500
parent_id: null
depth: 0
---

# F013 — aiogoogle 5.19 supports file-path and async-iterator media in both directions, chunked via aiofiles; resumable uploads are modeled but need explicit handling

## Summary

`aiogoogle/resource.py` accepts `upload_file` (path), `pipe_from` (async
iterable), `download_file` (path) and `pipe_to` (async writer) on any
discovered method that declares media support, raising a clear error
otherwise. `models.py` has `MediaUpload(file_path, upload_path, chunk_size,
resumable=ResumableUpload)` and `MediaDownload(file_path | pipe_to,
chunk_size)`. The aiohttp session streams uploads from disk with `aiofiles`
and downloads with `response.content.iter_chunked(chunk_size)`; multipart
metadata+media uploads set `Content-Type: multipart/related`. This is enough
for Drive `files.create`/`files.update` (media) and `files.get(alt="media")`
without hand-rolled aiohttp, but resumable sessions (>5 MB is Google's
recommendation) are only partially wired (`_build_upload_media` "If resumable"
branch) and must be verified at spec time.

## Citations

- path: `.venv/lib/python3.12/site-packages/aiogoogle/resource.py`
  lines: 394-397
  symbol: `Method.__call__` kwargs
  excerpt: |
    upload_file=None, pipe_from=None, download_file=None, pipe_to=None,

- path: `.venv/lib/python3.12/site-packages/aiogoogle/resource.py`
  lines: 563-601
  symbol: media validation
  excerpt: |
    if download_file and pipe_to: raise ValidationError("can't have both (download_file) and (pipe_to) options")
    ... "download_file was provided while method doesn't support media download"
    media_download = MediaDownload(file_path=download_file)   # or MediaDownload(pipe_to=pipe_to)
    if upload_file: ... self._build_upload_media(upload_file, uri, validate, fallback_url=url, pipe_from=None)

- path: `.venv/lib/python3.12/site-packages/aiogoogle/resource.py`
  lines: 654-663
  symbol: `_build_upload_media`
  excerpt: |
    return MediaUpload(upload_file, upload_path=fallback_url)
    # If resumable, create resumable object

- path: `.venv/lib/python3.12/site-packages/aiogoogle/models.py`
  lines: 33-82
  symbol: `MediaUpload`
  excerpt: |
    class MediaUpload:  # file_path | file_body | pipe_from; chunk_size; resumable: ResumableUpload

- path: `.venv/lib/python3.12/site-packages/aiogoogle/sessions/aiohttp_session.py`
  lines: 24-34, 71-81, 130-150
  symbol: streaming helpers
  excerpt: |
    async def _aiter_file(file_name, chunk_size): async with aiofiles.open(file_name, "rb") as f: ...
    async for line in response.content.iter_chunked(chunk_size): ...
    req_content_type = 'multipart/related'
