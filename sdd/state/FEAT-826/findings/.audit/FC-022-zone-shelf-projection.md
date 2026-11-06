---
id: FC-022
query_id: Q019
type: read
intent: "Follow-up: how unowned zones become shelves and how zone results are projected to the legacy ComplianceResult."
executed_at: 2026-11-06T16:08:30Z
duration_ms: 1200
parent_id: FC-010
depth: 1
---

# FC-022 — Each unowned zone becomes a virtual shelf "zone:<zone_id>" with level None: default threshold 0.8, no product names, only illumination failures surfaced

## Summary

`_normalise_zone_shelves` gives every zone with `shelf_id=None` a virtual `ShelfDefinition` (`shelf_id="zone:<zone_id>"`, `level=None`, no facings). `project_compliance` then emits one legacy `ComplianceResult` per shelf: `shelf_level = score.shelf_level` (the virtual id), `expected_products` / `found_products` built from facings (so empty for zones), threshold from `ShelfConfig` matched by level or the default (0.8 per the docstring), status COMPLIANT only when the shelf is completely assessed, meets the threshold and has no failed rule. `missing_products` receives a failed rule's detail **only when its penalty is > 0**, i.e. illumination failures; failed text, visual, appearance or zone-absent rules change the status but are not listed. `finalize_comparison` sets `overall_compliant` only when the assessment is COMPLETE and every shelf is COMPLIANT.

## Citations

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py`
  lines: 341-362
  symbol: `_normalise_zone_shelves`
  excerpt: |
    """Give every unowned zone a deterministic virtual score shelf ``zone:<zone_id>`` (in place, after sorting).
    ...
    virtual_shelf_id = f"{VIRTUAL_SHELF_PREFIX}{zone.zone_id}"
    zone.shelf_id = virtual_shelf_id
    definition.shelves.append(
        ShelfDefinition(shelf_id=virtual_shelf_id, shelf_number=next_shelf_number + index, level=None, facings=[])
    )
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py`
  lines: 53-58
  symbol: `_threshold`
  excerpt: |
    """Per-shelf compliance threshold (``ShelfConfig.compliance_threshold``), 0.8 without a config."""
    for config in getattr(description, "shelves", None) or []:
        if level is not None and config.level == level:
            return float(config.compliance_threshold)
    return _DEFAULT_THRESHOLD
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py`
  lines: 139-153
  symbol: `project_compliance`
  excerpt: |
    missing += [o.detail for o in failed_rules if o.penalty > 0 and o.detail]
    threshold = _threshold(description, shelf.level)
    if score.expected_facings:
        meets_threshold = score.facing_lenient >= threshold
    else:
        meets_threshold = score.lenient_score >= threshold
    ...
    if complete and meets_threshold and not failed_rules:
        status = ComplianceStatus.COMPLIANT
    ...
    else:
        status = ComplianceStatus.NON_COMPLIANT
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py`
  lines: 166-176
  symbol: `project_compliance`
  excerpt: |
    ComplianceResult(
        shelf_level=score.shelf_level,
        expected_products=expected,
        found_products=found,
        missing_products=missing,
        unexpected_products=unexpected,
        compliance_status=status,
        compliance_score=max(0.0, min(1.0, score.lenient_score)),
        assessment=assessment,
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py`
  lines: 181-202
  symbol: `finalize_comparison`
  excerpt: |
    compliant = bool(
        compliance_results
        and comparison.assessment_status == AssessmentStatus.COMPLETE
        and all(r.compliance_status == ComplianceStatus.COMPLIANT for r in compliance_results)
    )

## Notes

- Consequences for planograms 23/24 as rewritten: the legacy per-level thresholds (0.95 / 0.9 in the ticket logs) no longer apply — every zone uses the default; the report a user sees (FC-020) names shelves `ZONE:ZONE-HEADER-1` etc. with empty product lists; and a failed "correct image" (text / visual) check is visible only as a lower score and a NON_COMPLIANT status, not as an issue line. Only "backlight OFF (required: ON)" style details reach `missing_products`.
- The projected result has no `text_compliance_results` in the lines read, so the consumer's "Text Requirements" block would not print for these rows — not verified against the `ComplianceResult` model.
- `_DEFAULT_THRESHOLD`'s value was read from the docstring ("0.8 without a config"), not from its definition line.
- `VIRTUAL_SHELF_PREFIX` is taken to be `zone:` from the docstring; its definition line was not read.
