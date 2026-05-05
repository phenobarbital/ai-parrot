# Changelog

All notable changes to `parrot-formdesigner` will be documented in this file.

## [Unreleased]

### Breaking Changes

#### `GET /api/v1/forms` Response Shape (FEAT-148)

**Before:**
```json
{
  "forms": ["form-id-1", "form-id-2"]
}
```

**After:**
```json
{
  "forms": [
    {
      "form_id": "form-id-1",
      "title": "Form Title",
      "description": "Optional description",
      "version": "1.0",
      "source": "memory|db",
      "created_at": "2026-04-12T10:31:00+00:00"
    }
  ]
}
```

**Migration Guide:**
- Change consumers from iterating over a list of strings to a list of descriptor dicts
- Access form ID via `item["form_id"]` instead of using the item directly
- The `source` field indicates the origin: `"memory"` for in-memory registered forms, `"db"` for persisted forms
- The `created_at` field is an ISO-8601 datetime string or `null` for in-memory forms without a creation timestamp

**Rationale:**
This change enables clients to display rich form metadata (title, description, creation date) without requiring N additional `GET /api/v1/forms/{form_id}` requests. The endpoint now merges both in-memory registered forms and persisted forms from storage in a single response.

### Added

- `FormSchema.created_at: datetime | None = None` — Optional timestamp for form creation
- `PostgresFormStorage.list_forms()` now includes `description` and `created_at` in the returned descriptors
- `FormAPIHandler.list_forms()` now merges registry-backed forms with storage-backed forms, deduplicating by `form_id`

### Fixed

- `PostgresFormStorage.load()` now populates `created_at` from the database row when available
- Malformed `schema_json` rows in storage now log a debug message instead of silently failing

### Internal

- Added `_loc_to_str()` helper in `FormAPIHandler` for consistent LocalizedString flattening across storage and API layers
- Updated return type annotations from `list[dict[str, str]]` to `list[dict[str, Any]]` for accuracy
