# Changelog

All notable changes to `parrot-formdesigner` will be documented in this file.

## [0.2.0] — 2026-05-07 — Structural Refactor (FEAT-152)

### Breaking Changes

- **`from parrot_formdesigner import setup_form_routes` no longer works.**
  The route helper was split in two:
  - `from parrot_formdesigner.api import setup_form_api` — JSON REST surface.
  - `from parrot_formdesigner.ui import setup_form_ui` — HTML pages + Telegram WebApp.
- **`parrot_formdesigner.handlers` module is removed** entirely.
  All `FormAPIHandler`, `FormPageHandler`, `TelegramWebAppHandler`,
  `setup_form_routes`, and the `templates.py` HTML helpers moved to
  `parrot_formdesigner.api` / `parrot_formdesigner.ui`.
- **`parrot_formdesigner.__init__` no longer re-exports `FormSchema`,
  `FieldType`, `HTML5Renderer`, etc.** Import from explicit submodules
  (`parrot_formdesigner.core`, `parrot_formdesigner.renderers`, …).
  This makes `import parrot_formdesigner` a true zero-cost metadata-only
  import.
- **`navigator-auth` is now a HARD dependency.** Hosts that previously
  ran without auth must configure navigator-auth's `NoAuth` backend on
  the consumer side. The conditional `try/except ImportError` block is
  gone; missing navigator-auth makes
  `import parrot_formdesigner.api` raise `ImportError`.

### Added

- **Render dispatcher** — `GET /api/v1/forms/{form_id}/render/{format}`
  with name-keyed renderer registry. V1 ships `html` and `adaptive`;
  `xml` (XForms 1.1) and `pdf` (AcroForm fillable) are added in
  Wave 2 of FEAT-152 (0.3.x).
- **Form-controls registry** — `parrot_formdesigner.controls.register_field_control()`
  + `GET /api/v1/form-controls` endpoint. Seeded with all `FieldType`
  values; consumers can extend the toolbar via the registration
  function.
- **Edit operations API stub** — `PATCH /api/v1/forms/{id}/operations`
  is mounted with a 501 stub in 0.2.0; full atomic batched-edit
  implementation lands in 0.3.x.

### Deferred to 0.3.x (Wave 2 of FEAT-152)

- XForms 1.1 renderer (`/render/xml`).
- PDF AcroForm fillable renderer (`/render/pdf`).
- Atomic batched-edit endpoint (`PATCH /forms/{id}/operations`).

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
