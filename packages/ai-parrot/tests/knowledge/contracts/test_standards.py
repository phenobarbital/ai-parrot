"""Unit tests for the seeded compliance standards (TASK-3025)."""

from __future__ import annotations

import pytest

from parrot.knowledge.contracts.standards import (
    STANDARD_IDS,
    STANDARDS,
    find_standards,
    get_standard,
    normalize_standard_text,
    resolve_standard,
)

EXPECTED_IDS = (
    "soc2",
    "soc1",
    "iso27001",
    "gdpr",
    "uk_gdpr",
    "ccpa",
    "hipaa",
    "pci_dss",
    "nist_800_53",
    "cyber_insurance",
)


def test_all_standards_are_seeded_in_a_deterministic_order():
    assert STANDARD_IDS == EXPECTED_IDS
    assert set(STANDARDS) == set(EXPECTED_IDS)


@pytest.mark.parametrize("standard_id", EXPECTED_IDS)
def test_every_standard_resolves_from_its_own_id(standard_id):
    assert resolve_standard(standard_id) == standard_id
    assert get_standard(standard_id).standard_id == standard_id


@pytest.mark.parametrize(
    ("written", "standard_id"),
    [
        ("SOC 2", "soc2"),
        ("SOC 2 Type II", "soc2"),
        ("soc-2", "soc2"),
        ("SSAE 18", "soc2"),
        ("ISO/IEC 27001", "iso27001"),
        ("ISO 27001:2022", "iso27001"),
        ("General Data Protection Regulation", "gdpr"),
        ("Regulation (EU) 2016/679", "gdpr"),
        ("California Consumer Privacy Act", "ccpa"),
        ("CPRA", "ccpa"),
        ("HIPAA Security Rule", "hipaa"),
        ("Business Associate Agreement", "hipaa"),
        ("PCI-DSS", "pci_dss"),
        ("Payment Card Industry Data Security Standard", "pci_dss"),
        ("NIST SP 800-53", "nist_800_53"),
        ("800-53", "nist_800_53"),
        ("Cyber Liability Insurance", "cyber_insurance"),
    ],
)
def test_written_aliases_resolve_to_stable_ids(written, standard_id):
    assert resolve_standard(written) == standard_id


def test_unknown_or_empty_values_do_not_resolve():
    assert resolve_standard(None) is None
    assert resolve_standard("") is None
    assert resolve_standard("   ") is None
    assert resolve_standard("FedRAMP High") is None
    assert get_standard("fedramp") is None


def test_normalization_strips_punctuation_and_case():
    assert normalize_standard_text("ISO/IEC 27001:2022") == "iso iec 27001 2022"
    assert normalize_standard_text("  SOC-2  ") == "soc 2"


def test_find_standards_reads_a_full_question_without_erasing_the_entity():
    question = "Which active contracts require SOC 2 and cyber liability insurance?"
    assert find_standards(question) == ["soc2", "cyber_insurance"]


def test_find_standards_prefers_the_longest_alias():
    assert find_standards("we need SOC 2 Type II evidence") == ["soc2"]


def test_find_standards_returns_seeded_order_without_duplicates():
    text = "PCI DSS, GDPR, and PCI-DSS again, plus HIPAA"
    assert find_standards(text) == ["gdpr", "hipaa", "pci_dss"]


def test_find_standards_on_empty_text():
    assert find_standards(None) == []
    assert find_standards("") == []
    assert find_standards("...") == []


def test_aliases_are_normalized_and_unique():
    for standard in STANDARDS.values():
        assert standard.aliases[0] == normalize_standard_text(standard.standard_id)
        assert len(set(standard.aliases)) == len(standard.aliases)
        for alias in standard.aliases:
            assert alias == normalize_standard_text(alias)


def test_aliases_do_not_collide_across_standards():
    seen: dict[str, str] = {}
    for standard in STANDARDS.values():
        for alias in standard.aliases:
            assert alias not in seen, f"{alias!r} shared by {seen.get(alias)} and {standard.standard_id}"
            seen[alias] = standard.standard_id


def test_framework_ids_match_existing_security_report_mappings():
    # parrot_tools/security/reports/mappings/{soc2,hipaa,pci_dss}_controls.yaml
    for framework in ("soc2", "hipaa", "pci_dss"):
        assert framework in STANDARDS
