# TASK-2335: `PLACE` — the granular location type

**Feature**: FEAT-448 — field-type-catalog-reconciliation
**Spec**: `sdd/specs/field-type-catalog-reconciliation.spec.md` §3
**Status**: pending · **Priority**: medium · **Effort**: M · **Depends-on**: —

## Context

`LOCATION` means two things. Here it is a country picker wired through eleven
sites — `_location_data.py` (pycountry, flag emoji, dial codes), the coercion
`str(value).strip().upper()`, the 2-char check, the registry description
*"Country or location selector using ISO codes"*, a `field_helpers` snippet
whose `field_id` is literally `country_code`, `format: "iso-country"` in JSON
Schema, and six renderers painting a country list. In navigator-svelte it is a
Country → State → City cascade.

Direction: neither displaces the other. `LOCATION` is untouched; the cascade
gets its own name.

`place`, not `address`: there is no street line and no postal code, so
`address` would misdescribe it.

## Scope

- `core/types.py` — `PLACE = "place"`.
- `services/validators.py` — accept
  `{"country": str, "state": str | None, "city": str | None}`; `country` is
  required and delegates to `is_valid_iso_country_code`, so `place` and
  `location` cannot disagree about a country code.
- `controls/builtin.py` — a registry entry.
- `extractors/{jsonschema,yaml}.py` — the reverse mapping, beside `location`.

## Acceptance Criteria

- AC1 `{"country":"CA","state":"ON","city":"Ottawa"}` validates.
- AC2 An invalid country code is rejected with the same message
  `is_valid_iso_country_code` drives for `location`.
- AC3 `state` and `city` are optional; `{"country":"CA"}` validates.
- AC4 **`LOCATION` behaviour is byte-identical to before.** Asserted, not
  assumed: the country coercion, the 2-char check and the registry entry all
  keep their current behaviour. This task is the one most likely to "tidy"
  `location` while passing through.

## Notes

Measured exposure of the original disagreement: ONE field in ONE form —
`untitled-form-2` / "ML Test #1", which looks like eight because that form has
eight versions — and two stored submissions holding
`{"country":"CA","state":"ON","city":"Ottawa"}`. Those two rows are
navigator-svelte FEAT-515's to re-type or drop; do not migrate data from here.

`pycountry` degrades gracefully: absent, `is_valid_iso_country_code` returns
True and the check silently passes. Any environment comparison must confirm the
package is installed before concluding a value was accepted on its merits.

### Completion Note

Added `FieldType.PLACE = "place"` to `core/types.py`, a registry entry in
`controls/builtin.py`, a `_coerce_value`/`_validate_by_type` branch pair in
`services/validators.py` placed immediately beside (never inside) the
existing `LOCATION` branches, and the reverse `"place" -> FieldType.PLACE`
mapping in both `extractors/jsonschema.py` and `extractors/yaml.py` beside
`"location"`.

`PLACE.country` delegates to `core._location_data.is_valid_iso_country_code`
(previously unused in production) rather than duplicating `LOCATION`'s own
`_validate_location` helper — so the two types share one source of truth
for what a valid country code is, per the task's own framing. `LOCATION`'s
existing branches, its `_validate_location` helper, and its registry entry
were not touched — verified with dedicated byte-identical-behaviour tests,
not merely left alone.

Renderer support for `PLACE` (a native html5 cascade being the natural
choice per the spec) is TASK-2337's scope, not this one.

Tests: `tests/formdesigner/test_feat448_place_type.py` — AC1 (full shape),
AC2 (invalid country rejected, with the LOCATION-matching message
wording), AC3 (state/city optional), and AC4 (LOCATION byte-identical:
coercion, both rejection messages, the `_validate_location` helper, and
the registry entry, all pinned explicitly). Full suite diffed against the
TASK-2334 baseline: no regressions.
