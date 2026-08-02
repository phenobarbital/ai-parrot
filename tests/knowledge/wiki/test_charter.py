"""Unit tests for parrot.knowledge.wiki.charter (TASK-2069, FEAT-402)."""

import textwrap

import pytest
from parrot.knowledge.wiki.charter import (
    Charter,
    Thresholds,
    TriageExample,
    append_example,
    load_charter,
)
from pydantic import ValidationError

# NOTE: admit=0.75 / reject=0.35 below are EXAMPLE values for this fixture
# only — they must never become hardcoded defaults in charter.py itself
# (spec §8 Open Questions: thresholds are calibrated per-charter during
# implementation, not baked into code).
_VALID_CHARTER_YAML = textwrap.dedent(
    """
    version: "1"
    scope:
      include:
        - id: decisions
          description: >
            Technical or business decisions with their rationale and
            discarded alternatives.
        - id: agreements
          description: Agreements, ownership, and commitments with a date.
      exclude:
        - id: social
          description: Small talk, jokes, purely social content.
        - id: sensitive
          description: Personal data, salaries, individual HR matters.
    weights:
      density: 0.40
      novelty: 0.35
      durability: 0.25
    thresholds:
      admit: 0.75
      reject: 0.35
    destinations:
      - wiki
      - archive
      - discard
    calibration:
      near_fraction: 0.6
      uniform_fraction: 0.4
      min_agreement: 0.9
      on_low_agreement: widen_gray_zone
      gray_zone_step: 0.05
      autotune: propose
    examples:
      - summary: >
          Meeting 2026-06-11: decided to migrate the graph store to
          ArangoDB; Neo4j was discarded for licensing reasons.
        why: durable decision with rationale and discarded alternatives
        destination: wiki
      - summary: "Standup 2026-06-12: routine status round, no new decisions."
        why: raw status update, near-zero density
        destination: archive
    examples_file: null
    amendments:
      - version: "1"
        date: 2026-08-01
        change: Initial charter.
        source: manual
    """
)


@pytest.fixture
def sample_charter(tmp_path):
    """Write a minimal, valid charter YAML fixture and return its path."""
    charter_path = tmp_path / "charter.yaml"
    charter_path.write_text(_VALID_CHARTER_YAML, encoding="utf-8")
    return charter_path


def _charter_yaml_with(**overrides) -> str:
    """Build a charter YAML string with select top-level keys overridden."""
    import yaml

    data = yaml.safe_load(_VALID_CHARTER_YAML)
    data.update(overrides)
    return yaml.safe_dump(data)


def test_charter_load_valid(sample_charter):
    """load_charter returns a validated Charter with a stable fingerprint."""
    charter1 = load_charter(sample_charter)
    charter2 = load_charter(sample_charter)

    assert isinstance(charter1, Charter)
    assert charter1.version == "1"
    assert charter1.weights == {"density": 0.40, "novelty": 0.35, "durability": 0.25}
    assert charter1.fingerprint  # non-empty
    assert charter1.fingerprint == charter2.fingerprint  # stable across loads


def test_charter_weights_must_sum(tmp_path):
    """Weights that do not sum to ~1.0 are rejected."""
    bad_yaml = _charter_yaml_with(
        weights={"density": 0.10, "novelty": 0.10, "durability": 0.10}
    )
    path = tmp_path / "charter.yaml"
    path.write_text(bad_yaml, encoding="utf-8")

    with pytest.raises(ValidationError):
        load_charter(path)


def test_charter_weights_unknown_dimension(tmp_path):
    """Weights with an unknown dimension key are rejected."""
    bad_yaml = _charter_yaml_with(
        weights={"density": 0.5, "novelty": 0.3, "made_up": 0.2}
    )
    path = tmp_path / "charter.yaml"
    path.write_text(bad_yaml, encoding="utf-8")

    with pytest.raises(ValidationError):
        load_charter(path)


def test_charter_thresholds_order(tmp_path):
    """reject >= admit is rejected (no gray zone would exist)."""
    bad_yaml = _charter_yaml_with(thresholds={"admit": 0.5, "reject": 0.5})
    path = tmp_path / "charter.yaml"
    path.write_text(bad_yaml, encoding="utf-8")

    with pytest.raises(ValidationError):
        load_charter(path)


def test_thresholds_route_bands():
    """Thresholds.route buckets composite scores at the boundaries."""
    thresholds = Thresholds(admit=0.75, reject=0.35)

    assert thresholds.route(0.75) == "admit"
    assert thresholds.route(0.9) == "admit"
    assert thresholds.route(0.35) == "gray"
    assert thresholds.route(0.5) == "gray"
    assert thresholds.route(0.34999) == "reject"
    assert thresholds.route(0.0) == "reject"


def test_examples_file_append(tmp_path, sample_charter):
    """append_example appends to examples_file and round-trips."""
    examples_file = tmp_path / "examples.jsonl"
    charter = load_charter(sample_charter)
    charter.examples_file = examples_file

    example = TriageExample(
        summary="Postmortem: DB outage root-caused to a missing index.",
        why="durable operational knowledge",
        destination="wiki",
    )
    result_path = append_example(charter, example)

    assert result_path == examples_file
    lines = examples_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1

    roundtripped = TriageExample.model_validate_json(lines[0])
    assert roundtripped == example

    # Appending a second example adds a new line, does not overwrite.
    example2 = TriageExample(summary="Another one", why="because", destination="archive")
    append_example(charter, example2)
    lines = examples_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2


def test_append_example_requires_target(sample_charter):
    """append_example raises when neither examples_file nor path is set."""
    charter = load_charter(sample_charter)
    assert charter.examples_file is None

    example = TriageExample(summary="x", why="y")
    with pytest.raises(ValueError):
        append_example(charter, example)
