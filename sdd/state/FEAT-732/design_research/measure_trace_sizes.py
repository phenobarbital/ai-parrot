"""Measure the serialized byte cost of the FEAT-732 trace shapes."""
import json

CHECKS_TYPICAL = ["field.required", "field.coerce", "field.type", "constraint.pattern"]
CHECKS_HEAVY = [
    "field.required", "field.coerce", "field.type", "constraint.min_length",
    "constraint.max_length", "constraint.pattern", "field.option_set", "field.cross_field",
]

def summary_field(fid, checks):
    return {"field_id": fid, "required_effective": True, "visible_effective": True,
            "checks_ran": checks, "records": [], "failures": []}

def full_field(fid, checks):
    return {"field_id": fid, "required_effective": True, "visible_effective": True,
            "checks_ran": checks,
            "records": [{"check": c, "outcome": "pass", "bound": "max_length=120",
                         "skip_reason": None, "message": None} for c in checks],
            "failures": []}

HEADER = {"trace_schema": 1, "detail": "summary", "form_uid": "0f8f0a3e-1c4a-4b7e-9f1d-2a3b4c5d6e7f",
          "form_id": "contract-intake-form", "form_version": "1.0",
          "schema_fingerprint": "sha256:" + "a" * 64, "ruleset_version": "1.3.0",
          "locale": "es-ES", "validated_at": "2026-10-23T12:00:00+00:00",
          "duration_ms": 42, "checks_run": 0, "checks_failed": 0, "is_valid": True,
          "form_checks": [{"check": "form.circular_dependencies", "outcome": "pass",
                           "bound": None, "skip_reason": None, "message": None},
                          {"check": "form.rule_integrity", "outcome": "pass",
                           "bound": None, "skip_reason": None, "message": None}],
          "fields": [], "truncated": False, "omitted_fields": 0, "omitted_checks": 0}

def size(n_fields, builder, checks):
    t = dict(HEADER)
    t["fields"] = [builder(f"field_{i:03d}", checks) for i in range(n_fields)]
    t["checks_run"] = n_fields * len(checks) + 2
    return len(json.dumps(t, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))

print(f"header only: {size(0, summary_field, []):,} bytes\n")
print(f"{'fields':>7} | {'summary/4chk':>13} | {'summary/8chk':>13} | {'full/4chk':>11} | {'full/8chk':>11}")
print("-" * 72)
for n in (10, 25, 50, 100, 150, 200, 400):
    print(f"{n:>7} | {size(n, summary_field, CHECKS_TYPICAL):>13,} | "
          f"{size(n, summary_field, CHECKS_HEAVY):>13,} | "
          f"{size(n, full_field, CHECKS_TYPICAL):>11,} | "
          f"{size(n, full_field, CHECKS_HEAVY):>11,}")

print("\nfields that fit in each candidate cap:")
for cap_name, cap in (("32 KiB", 32768), ("64 KiB", 65536), ("128 KiB", 131072), ("256 KiB", 262144)):
    row = []
    for label, builder, checks in (("sum/4", summary_field, CHECKS_TYPICAL),
                                   ("sum/8", summary_field, CHECKS_HEAVY),
                                   ("full/4", full_field, CHECKS_TYPICAL),
                                   ("full/8", full_field, CHECKS_HEAVY)):
        n = 0
        while size(n + 1, builder, checks) <= cap and n < 5000:
            n += 1
        row.append(f"{label}={n}")
    print(f"  {cap_name:>8}: " + "  ".join(row))
