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
