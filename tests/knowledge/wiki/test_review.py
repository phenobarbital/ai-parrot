"""Unit tests for parrot.knowledge.wiki.review (TASK-2070, FEAT-402)."""

import pytest
from parrot.knowledge.wiki.charter import CalibrationPolicy, Thresholds
from parrot.knowledge.wiki.review import (
    Claim,
    DimensionScores,
    ManifestDocEntry,
    ManifestParseError,
    ManifestReader,
    ManifestRunHeader,
    ManifestWriter,
    TriageOutput,
    agreement_rate,
    propose_gray_zone_widening,
    stratified_sample,
)
from pydantic import ValidationError


def _make_header(**overrides) -> ManifestRunHeader:
    data = {
        "charter_sha256": "deadbeef" * 8,
        "charter_version": "1",
        "mode": "dry-run",
        "novelty_backend": "grounding",
        "counts": {"admit": 1, "archive": 1, "discard": 0},
        "created_at": "2026-08-02T00:00:00+00:00",
    }
    data.update(overrides)
    return ManifestRunHeader(**data)


def _make_entry(composite: float, **overrides) -> ManifestDocEntry:
    data = {
        "source_uri": f"docs/{composite}.md",
        "file_hash": f"sha256:{composite}",
        "briefing": "A test document briefing.",
        "scores": DimensionScores(density=0.5, novelty=0.5, durability=0.5),
        "composite": composite,
        "proposed_action": "admit" if composite >= 0.75 else "archive",
        "claims": [],
    }
    data.update(overrides)
    return ManifestDocEntry(**data)


class TestTriageModels:
    def test_triage_output_has_no_composite_field(self):
        """TriageOutput must NOT expose a composite field (spec §5)."""
        assert "composite" not in TriageOutput.model_fields

    def test_claim_defaults(self):
        claim = Claim(text="Some fact")
        assert claim.grounded is None

    def test_dimension_scores_bounds(self):
        with pytest.raises(ValidationError):
            DimensionScores(density=1.5, novelty=0.5, durability=0.5)


class TestManifestRoundtrip:
    def test_manifest_roundtrip(self, tmp_path):
        """write -> hand-edit a decision -> read back with edits applied."""
        manifest_path = tmp_path / "manifest.jsonl"
        header = _make_header()
        entries = [
            _make_entry(0.9, source_uri="docs/a.md"),
            _make_entry(0.1, source_uri="docs/b.md"),
        ]

        ManifestWriter(manifest_path).write(header, entries)

        # Simulate a human hand-editing the manifest: fill in `decision`.
        lines = manifest_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 3  # header + 2 entries

        import json

        edited_lines = [lines[0]]
        for line in lines[1:]:
            row = json.loads(line)
            row["decision"] = row["proposed_action"]
            row["decision_source"] = "human"
            edited_lines.append(json.dumps(row))
        manifest_path.write_text("\n".join(edited_lines) + "\n", encoding="utf-8")

        read_header, read_entries = ManifestReader(manifest_path).read()

        assert read_header == header
        assert len(read_entries) == 2
        assert all(e.decision == e.proposed_action for e in read_entries)
        assert all(e.decision_source == "human" for e in read_entries)

    def test_manifest_rejects_bad_decision(self, tmp_path):
        """An invalid hand-edited decision value fails with a line number."""
        manifest_path = tmp_path / "manifest.jsonl"
        header = _make_header()
        entries = [_make_entry(0.9)]
        ManifestWriter(manifest_path).write(header, entries)

        lines = manifest_path.read_text(encoding="utf-8").splitlines()
        import json

        row = json.loads(lines[1])
        row["decision"] = "definitely-not-a-valid-action"
        bad_lines = [lines[0], json.dumps(row)]
        manifest_path.write_text("\n".join(bad_lines) + "\n", encoding="utf-8")

        with pytest.raises(ManifestParseError) as exc_info:
            ManifestReader(manifest_path).read()
        assert "line 2" in str(exc_info.value)

    def test_manifest_missing_header(self, tmp_path):
        manifest_path = tmp_path / "manifest.jsonl"
        entries = [_make_entry(0.9)]
        manifest_path.write_text(
            "\n".join(e.model_dump_json() for e in entries) + "\n", encoding="utf-8"
        )
        with pytest.raises(ManifestParseError, match="run_header"):
            ManifestReader(manifest_path).read()

    def test_manifest_unknown_kind(self, tmp_path):
        manifest_path = tmp_path / "manifest.jsonl"
        header = _make_header()
        manifest_path.write_text(
            header.model_dump_json() + "\n" + '{"kind": "mystery"}\n',
            encoding="utf-8",
        )
        with pytest.raises(ManifestParseError, match="line 2"):
            ManifestReader(manifest_path).read()


class TestStratifiedSampler:
    def test_stratified_sampler_fractions(self):
        thresholds = Thresholds(admit=0.75, reject=0.35)
        # 10 entries spread across the composite range.
        entries = [_make_entry(round(i / 10, 2)) for i in range(10)]

        stratified_sample(
            entries,
            thresholds,
            sample_size=10,
            near_fraction=0.6,
            uniform_fraction=0.4,
            seed=42,
        )

        sampled = [e for e in entries if e.audit_sample]
        assert len(sampled) == 10  # sample_size == len(entries) here

        near = [e for e in sampled if e.audit_stratum == "near_threshold"]
        uniform = [e for e in sampled if e.audit_stratum == "uniform"]
        assert len(near) == 6
        assert len(uniform) == 4

    def test_stratified_sampler_deterministic_with_seed(self):
        thresholds = Thresholds(admit=0.75, reject=0.35)
        entries_a = [_make_entry(round(i / 20, 2)) for i in range(20)]
        entries_b = [_make_entry(round(i / 20, 2)) for i in range(20)]

        stratified_sample(entries_a, thresholds, sample_size=6, seed=7)
        stratified_sample(entries_b, thresholds, sample_size=6, seed=7)

        strata_a = [(e.source_uri, e.audit_stratum) for e in entries_a if e.audit_sample]
        strata_b = [(e.source_uri, e.audit_stratum) for e in entries_b if e.audit_sample]
        assert strata_a == strata_b

    def test_stratified_sampler_clamps_to_available_entries(self):
        thresholds = Thresholds(admit=0.75, reject=0.35)
        entries = [_make_entry(0.5), _make_entry(0.6)]

        stratified_sample(entries, thresholds, sample_size=100, seed=1)

        assert all(e.audit_sample for e in entries)

    def test_stratified_sampler_near_threshold_prefers_closest(self):
        thresholds = Thresholds(admit=0.75, reject=0.35)
        # entry at 0.74 is very close to admit; entry at 0.01 is far from both.
        close_to_admit = _make_entry(0.74, source_uri="close")
        far = _make_entry(0.01, source_uri="far")
        entries = [close_to_admit, far]

        stratified_sample(entries, thresholds, sample_size=1, near_fraction=1.0, uniform_fraction=0.0, seed=1)

        assert close_to_admit.audit_sample is True
        assert close_to_admit.audit_stratum == "near_threshold"
        assert far.audit_sample is False


class TestAgreementRate:
    def test_agreement_rate(self):
        entries = [
            _make_entry(0.9, proposed_action="admit", decision="admit"),
            _make_entry(0.1, proposed_action="archive", decision="discard"),
            _make_entry(0.2, proposed_action="archive", decision="archive"),
        ]
        rate = agreement_rate(entries)
        assert rate == pytest.approx(2 / 3, abs=1e-4)

    def test_agreement_rate_none_when_undecided(self):
        entries = [_make_entry(0.9), _make_entry(0.1)]
        assert agreement_rate(entries) is None

    def test_agreement_rate_perfect(self):
        entries = [
            _make_entry(0.9, proposed_action="admit", decision="admit"),
            _make_entry(0.1, proposed_action="archive", decision="archive"),
        ]
        assert agreement_rate(entries) == 1.0


class TestGrayZoneWidening:
    def test_widening_is_propose_only(self):
        thresholds = Thresholds(admit=0.75, reject=0.35)
        calibration = CalibrationPolicy(
            min_agreement=0.9, on_low_agreement="widen_gray_zone", gray_zone_step=0.05
        )

        proposal = propose_gray_zone_widening(thresholds, calibration, observed_agreement=0.5)

        assert proposal is not None
        assert proposal is not thresholds  # new instance, never mutates input
        assert proposal.admit == pytest.approx(0.80)
        assert proposal.reject == pytest.approx(0.30)
        # original thresholds object is untouched
        assert thresholds.admit == 0.75
        assert thresholds.reject == 0.35

    def test_widening_none_when_agreement_sufficient(self):
        thresholds = Thresholds(admit=0.75, reject=0.35)
        calibration = CalibrationPolicy(min_agreement=0.9)
        assert propose_gray_zone_widening(thresholds, calibration, observed_agreement=0.95) is None

    def test_widening_none_when_agreement_unknown(self):
        thresholds = Thresholds(admit=0.75, reject=0.35)
        calibration = CalibrationPolicy(min_agreement=0.9)
        assert propose_gray_zone_widening(thresholds, calibration, observed_agreement=None) is None

    def test_widening_none_when_autotune_off(self):
        thresholds = Thresholds(admit=0.75, reject=0.35)
        calibration = CalibrationPolicy(min_agreement=0.9, autotune="off")
        assert propose_gray_zone_widening(thresholds, calibration, observed_agreement=0.1) is None

    def test_widening_none_when_policy_not_widen(self):
        thresholds = Thresholds(admit=0.75, reject=0.35)
        calibration = CalibrationPolicy(min_agreement=0.9, on_low_agreement="halt")
        assert propose_gray_zone_widening(thresholds, calibration, observed_agreement=0.1) is None
