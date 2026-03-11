# TASK-289 — Add Storage Backend Fields to VideoReelRequest

**Feature**: FEAT-043 (Configurable Persistency for Video Reel Generation)
**Spec**: `sdd/specs/persistency-videos-generate-reel-videos.spec.md`
**Status**: done
**Completed**: 2026-03-11
**Verification**: verified
**Priority**: high
**Effort**: S
**Depends on**: —
**Parallel**: false
**Parallelism notes**: Other tasks import `VideoReelRequest` and depend on these new fields existing.

---

## Objective

Add `storage_backend` and `storage_config` fields to the `VideoReelRequest` Pydantic model
so downstream pipeline code can determine which storage backend to use.

## Files to Modify

- `parrot/models/google.py` — `VideoReelRequest` model

## Implementation Details

1. Add `storage_backend: Literal["fs", "temp", "s3", "gcs"]` field with default `"fs"`.
2. Add `storage_config: Optional[Dict[str, Any]]` field with default `None`.
3. Import `Literal` and `Dict` from `typing` if not already imported.
4. Ensure backward compatibility: existing requests without these fields still parse correctly.

## Acceptance Criteria

- [ ] `VideoReelRequest(prompt="test")` has `storage_backend == "fs"` and `storage_config is None`
- [ ] `VideoReelRequest(prompt="test", storage_backend="s3", storage_config={"bucket": "x"})` parses correctly
- [ ] All existing tests pass without modification

## Tests

```python
def test_videoreelrequest_storage_defaults():
    req = VideoReelRequest(prompt="test")
    assert req.storage_backend == "fs"
    assert req.storage_config is None

def test_videoreelrequest_storage_s3():
    req = VideoReelRequest(prompt="test", storage_backend="s3", storage_config={"bucket": "x"})
    assert req.storage_backend == "s3"

def test_videoreelrequest_storage_gcs():
    req = VideoReelRequest(prompt="test", storage_backend="gcs", storage_config={"bucket": "b"})
    assert req.storage_backend == "gcs"

def test_videoreelrequest_invalid_backend():
    with pytest.raises(ValidationError):
        VideoReelRequest(prompt="test", storage_backend="invalid")
```
