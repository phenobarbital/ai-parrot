"""Tests for pure consequence report digest contracts."""

from parrot.knowledge.wiki.decisions.consequences import (
    EXIT_CODES,
    Finding,
    canonicalize_spec,
    evaluation_digest,
    finding_fingerprint,
    input_digest,
    status_precedence,
)
from parrot.knowledge.wiki.decisions.inventory import SnapshotManifest
from parrot.knowledge.wiki.decisions.models import DecisionRef


SPEC = "# T\n\n**Status**: draft\n\n## 2. Design\nbody\n"


def _manifest(**overrides: object) -> SnapshotManifest:
    """Build a stable manifest, allowing one input to vary per test."""
    base: dict[str, object] = {
        "inventory": {"adr:a": "hash-a"},
        "taxonomy_digest": "taxonomy",
        "approvals_digest": "approvals",
        "structural_revision": "structural",
        "rules_version": 1,
        "config_digest": "config",
    }
    return SnapshotManifest(**(base | overrides))


def test_status_line_and_generated_sections_ignored() -> None:
    """Generated output and authored status do not affect the canonical spec."""
    with_sections = SPEC.replace("## 2.", "## Governing Decisions\nx\n\n## 2.") + "\n## Consequences\ny\n"
    assert canonicalize_spec(SPEC) == canonicalize_spec(SPEC.replace("draft", "approved"))
    assert canonicalize_spec(SPEC) == canonicalize_spec(with_sections)


def test_input_digest_sensitive_to_every_input() -> None:
    """Every specified evaluation input changes the input digest."""
    base = input_digest(b"s", b"b", b"w", "c", _manifest())
    assert base == input_digest(b"s", b"b", b"w", "c", _manifest())

    variants = [
        input_digest(b"S", b"b", b"w", "c", _manifest()),
        input_digest(b"s", b"B", b"w", "c", _manifest()),
        input_digest(b"s", b"b", b"W", "c", _manifest()),
        input_digest(b"s", b"b", b"w", "C", _manifest()),
        input_digest(b"s", b"b", b"w", "c", _manifest(inventory={"adr:b": "hash-b"})),
        input_digest(b"s", b"b", b"w", "c", _manifest(taxonomy_digest="taxonomy-2")),
        input_digest(b"s", b"b", b"w", "c", _manifest(approvals_digest="approvals-2")),
        input_digest(b"s", b"b", b"w", "c", _manifest(structural_revision="structural-2")),
        input_digest(b"s", b"b", b"w", "c", _manifest(rules_version=2)),
        input_digest(b"s", b"b", b"w", "c", _manifest(config_digest="config-2")),
    ]
    assert all(variant != base for variant in variants)


def test_evaluation_digest_order_independent() -> None:
    """Finding order cannot alter an evaluation digest."""
    first = Finding(kind="contradiction", rule_version=1, fingerprint="finding-a")
    second = Finding(kind="evidence-gap", rule_version=1, fingerprint="finding-b")
    assert evaluation_digest("sha256:input", [first, second]) == evaluation_digest("sha256:input", [second, first])


def test_fingerprint_sorted_participants() -> None:
    """Participant and scope order cannot alter a finding fingerprint."""
    first = DecisionRef(decision_id="adr:x", revision=1)
    second = DecisionRef(decision_id="adr:y", revision=2)
    assert finding_fingerprint("contradiction", 1, [first, second], ["s2", "s1"]) == finding_fingerprint(
        "contradiction", 1, [second, first], ["s1", "s2"]
    )


def test_precedence_and_exit_codes() -> None:
    """Status priority and public exit codes remain fixed."""
    assert status_precedence(["conflict", "incomplete", "invalid"]) == "invalid"
    assert status_precedence([]) == "pass"
    assert status_precedence(["skipped"]) == "pass"
    assert EXIT_CODES == {"pass": 0, "skipped": 0, "conflict": 1, "invalid": 2, "incomplete": 3}
