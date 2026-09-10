"""The committed env example must document only variables that do something.

FEAT-548 AC-2. ``OBSERVABILITY_OPENLIT`` sat in ``env/.env`` long after FEAT-462
turned it into a no-op; this test stops the example file from acquiring the same
kind of dead entry.
"""
from __future__ import annotations

import re
from pathlib import Path

# NOTE: TASK-3114's blueprint specified parents[4]; verified against this file's
# actual location (packages/ai-parrot/tests/unit/observability/) that resolves
# to `packages/`, not the repo root. parents[5] is correct — stale contract
# reference corrected here per the anti-hallucination verification step.
REPO_ROOT = Path(__file__).resolve().parents[5]
EXAMPLE = REPO_ROOT / "env/.env.observability.example"

# Verified from ObservabilityConfig.from_env() (config.py:264-360).
RECOGNISED_ENV_VARS: frozenset[str] = frozenset({
    "OBSERVABILITY_ENABLED", "OBSERVABILITY_BACKEND", "OBSERVABILITY_SERVICE_NAME",
    "OBSERVABILITY_COST", "OBSERVABILITY_LOG_LEVEL", "OBSERVABILITY_SAMPLING",
    "OBSERVABILITY_OPENLIT", "OBSERVABILITY_OPENLIT_DISABLE",
    "OBSERVABILITY_OPENLIT_LOG_LEVEL", "OBSERVABILITY_OPENLIT_DISABLE_METRICS",
    "OBSERVABILITY_TRACELOOP", "OBSERVABILITY_CAPTURE_CONTENT",
    "OTEL_EXPORTER_OTLP_ENDPOINT", "OBSERVABILITY_PROM_PORT",
    "OBSERVABILITY_PROM_ADDR", "PARROT_PRICING_PATH", "OTLP_TARGETS",
    "OBSERVABILITY_OPENLIT_RECORDER", "OBSERVABILITY_OPENLIT_RECORDER_ENDPOINT",
})

_ASSIGNMENT = re.compile(r"^([A-Z][A-Z0-9_]*)=", re.MULTILINE)

# Heuristic patterns for values that look like a live credential rather than
# this feature's own config (URLs, booleans, plain words). Deliberately loose:
# false positives just mean a legitimate value needs a clearer name, which is
# itself useful signal for a file that must never carry secrets.
_SECRET_LIKE_KEY = re.compile(r"(KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL)", re.IGNORECASE)
_SECRET_LIKE_VALUE = re.compile(r"^[A-Za-z0-9+/_-]{20,}={0,2}$")  # base64/opaque-token shaped


def _declared_keys() -> set[str]:
    """Uncommented KEY=VALUE assignments in the example file."""
    body = "\n".join(
        line for line in EXAMPLE.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )
    return set(_ASSIGNMENT.findall(body))


def _declared_assignments() -> list[tuple[str, str]]:
    """Uncommented KEY=VALUE pairs (key, raw value) in the example file."""
    pairs: list[tuple[str, str]] = []
    for line in EXAMPLE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = re.match(r"^([A-Z][A-Z0-9_]*)=(.*)$", stripped)
        if match:
            pairs.append((match.group(1), match.group(2)))
    return pairs


def test_example_file_exists_and_is_committed():
    """env/.env is git-ignored, so the example is the only versioned record."""
    assert EXAMPLE.is_file(), f"{EXAMPLE} is missing (AC-2)"


def test_every_declared_key_is_read_by_from_env():
    """No dead configuration: every key must actually reach ObservabilityConfig."""
    unknown = _declared_keys() - RECOGNISED_ENV_VARS
    assert not unknown, (
        f"{EXAMPLE.name} declares {sorted(unknown)}, which "
        f"ObservabilityConfig.from_env() never reads"
    )


def test_endpoint_is_a_base_url():
    """The exporter appends /v1/metrics; a full path here doubles it.

    ``http://localhost:9090/api/v1/otlp`` is the correct BASE url and
    legitimately contains ``/v1/`` as part of Prometheus's own
    ``/api/v1/otlp`` route — the defect this guards against is the exporter's
    *own* signal suffix (``/v1/metrics`` or ``/v1/traces``) being pre-appended
    by hand, which doubles it (``exporters.py:152``).
    """
    text = EXAMPLE.read_text(encoding="utf-8")
    match = re.search(r"^OTEL_EXPORTER_OTLP_ENDPOINT=(\S+)$", text, re.MULTILINE)
    assert match, "OTEL_EXPORTER_OTLP_ENDPOINT is not declared in the example"
    endpoint = match.group(1).rstrip("/")
    assert not endpoint.endswith(("/v1/metrics", "/v1/traces")), (
        f"OTEL_EXPORTER_OTLP_ENDPOINT={endpoint!r} already carries the "
        "exporter's own signal suffix; it must be a BASE url — "
        "make_metric_exporter appends /v1/metrics itself (exporters.py:152), "
        "so a full path here doubles the suffix"
    )


def test_example_contains_no_secrets():
    """The [observability] block has no credentials; keep it that way."""
    for key, value in _declared_assignments():
        assert not _SECRET_LIKE_KEY.search(key), (
            f"{key} looks like a credential name; the observability block has "
            "none and must never gain one (env/.env holds live credentials and "
            "must never be echoed into a committed file)"
        )
        assert not _SECRET_LIKE_VALUE.match(value), (
            f"{key}={value!r} looks like an opaque token/secret value, not a "
            "config value"
        )
