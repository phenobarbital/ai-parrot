"""Tests for deterministic complexity evaluation."""

import json
from typing import Dict, List, Optional

import pytest
from pydantic import ValidationError

from parrot.flows.dev_loop.sdd_coder.complexity import (
    ComplexityContractError,
    _canonical_hash,
    _normalize_path,
    evaluate_complexity,
    parse_complexity_contract,
)
from parrot.flows.dev_loop.sdd_coder.complexity_models import (
    ComplexityContract,
    ComplexityEvidence,
    ComplexityPolicy,
    ComplexityTarget,
    MetricEvidence,
)


class TestPathNormalization:
    """Test path normalization functionality."""

    def test_normalize_simple_path(self):
        """Test normalizing a simple path."""
        assert _normalize_path("packages/ai-parrot/src/file.py") == "packages/ai-parrot/src/file.py"

    def test_normalize_with_current_dir(self):
        """Test normalizing path with current directory components."""
        assert _normalize_path("./packages/ai-parrot/src/file.py") == "packages/ai-parrot/src/file.py"
        assert _normalize_path("././packages/ai-parrot/src/file.py") == "packages/ai-parrot/src/file.py"

    def test_normalize_with_multiple_slashes(self):
        """Test normalizing path with multiple slashes."""
        assert _normalize_path("packages//ai-parrot///src/file.py") == "packages/ai-parrot/src/file.py"

    def test_normalize_remove_trailing_slash(self):
        """Test removing trailing slash."""
        assert _normalize_path("packages/ai-parrot/src/") == "packages/ai-parrot/src"

    def test_reject_absolute_paths(self):
        """Test rejecting absolute paths."""
        with pytest.raises(ComplexityContractError):
            _normalize_path("/absolute/path/file.py")
        
        with pytest.raises(ComplexityContractError):
            _normalize_path("C:/windows/path/file.py")

    def test_reject_escape_sequences(self):
        """Test rejecting escape sequences."""
        with pytest.raises(ComplexityContractError):
            _normalize_path("../escape/path/file.py")

    def test_reject_glob_patterns(self):
        """Test rejecting glob patterns."""
        with pytest.raises(ComplexityContractError):
            _normalize_path("packages/*/file.py")
        
        with pytest.raises(ComplexityContractError):
            _normalize_path("packages/file?.py")
        
        with pytest.raises(ComplexityContractError):
            _normalize_path("packages/file[0-9].py")


class TestContractParsing:
    """Test complexity contract parsing."""

    def test_parse_valid_contract(self):
        """Test parsing a valid complexity contract."""
        task_text = """
## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/complexity.py",
      "action": "CREATE"
    },
    {
      "path": "./packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_complexity.py",
      "action": "create"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#RosterConfig",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py#TaskRef"
  ]
}
```
"""
        contract = parse_complexity_contract(task_text)
        assert contract.schema_version == 1
        assert len(contract.targets) == 2
        assert contract.targets[0].path == "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/complexity.py"
        assert contract.targets[0].action == "CREATE"
        assert contract.targets[1].path == "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_complexity.py"
        assert contract.targets[1].action == "CREATE"
        assert len(contract.contract_symbols) == 2

    def test_parse_contract_missing_section(self):
        """Test parsing when complexity contract section is missing."""
        task_text = """
## Some Other Section

This is not a complexity contract.
"""
        with pytest.raises(ComplexityContractError, match="No Complexity Contract section found"):
            parse_complexity_contract(task_text)

    def test_parse_contract_invalid_json(self):
        """Test parsing contract with invalid JSON."""
        task_text = """
## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "file.py",
      "action": "CREATE"
    ,
  ]
}
```
"""
        with pytest.raises(ComplexityContractError, match="Invalid JSON"):
            parse_complexity_contract(task_text)

    def test_parse_contract_wrong_schema_version(self):
        """Test parsing contract with wrong schema version."""
        task_text = """
## Complexity Contract

```json
{
  "schema_version": 2,
  "targets": []
}
```
"""
        with pytest.raises(ComplexityContractError, match="Unsupported schema version"):
            parse_complexity_contract(task_text)

    def test_parse_contract_missing_targets(self):
        """Test parsing contract missing targets."""
        task_text = """
## Complexity Contract

```json
{
  "schema_version": 1
}
```
"""
        with pytest.raises(ComplexityContractError, match="Missing targets"):
            parse_complexity_contract(task_text)

    def test_parse_contract_target_missing_fields(self):
        """Test parsing contract with target missing required fields."""
        task_text = """
## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "file.py"
    }
  ]
}
```
"""
        with pytest.raises(ComplexityContractError, match="Target missing path or action"):
            parse_complexity_contract(task_text)

    def test_parse_contract_invalid_action(self):
        """Test parsing contract with invalid action."""
        task_text = """
## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "file.py",
      "action": "DELETE"
    }
  ]
}
```
"""
        with pytest.raises(ComplexityContractError, match="Invalid action"):
            parse_complexity_contract(task_text)

    def test_parse_contract_invalid_path(self):
        """Test parsing contract with invalid path."""
        task_text = """
## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "../invalid/path.py",
      "action": "CREATE"
    }
  ]
}
```
"""
        with pytest.raises(ComplexityContractError, match="Invalid path components"):
            parse_complexity_contract(task_text)

    def test_parse_contract_null_symbols(self):
        """Test parsing contract with null contract_symbols."""
        task_text = """
## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "file.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": null
}
```
"""
        contract = parse_complexity_contract(task_text)
        assert contract.contract_symbols is None

    def test_parse_contract_empty_symbols(self):
        """Test parsing contract with empty contract_symbols."""
        task_text = """
## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "file.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```
"""
        contract = parse_complexity_contract(task_text)
        assert contract.contract_symbols == ()


class TestCanonicalHash:
    """Test canonical hash functionality."""

    def test_canonical_hash_dict(self):
        """Test canonical hash of dictionary."""
        data1 = {"b": 2, "a": 1}
        data2 = {"a": 1, "b": 2}
        # Should produce same hash regardless of key order
        assert _canonical_hash(data1) == _canonical_hash(data2)

    def test_canonical_hash_nested(self):
        """Test canonical hash of nested structure."""
        data1 = {"a": {"c": 3, "b": 2}, "d": 4}
        data2 = {"d": 4, "a": {"b": 2, "c": 3}}
        # Should produce same hash regardless of key order
        assert _canonical_hash(data1) == _canonical_hash(data2)


class TestComplexityEvaluation:
    """Test complexity evaluation."""

    @pytest.fixture
    def sample_policy(self) -> ComplexityPolicy:
        """Create a sample complexity policy."""
        return ComplexityPolicy()

    @pytest.fixture
    def sample_contract(self) -> ComplexityContract:
        """Create a sample complexity contract."""
        return ComplexityContract(
            schema_version=1,
            targets=(
                ComplexityTarget(
                    path="packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/complexity.py",
                    action="CREATE"
                ),
            ),
            contract_symbols=None
        )

    @pytest.fixture
    def base_evidence(self, sample_contract: ComplexityContract) -> ComplexityEvidence:
        """Create base evidence fixture."""
        return ComplexityEvidence(
            task_id="TASK-1234",
            contract=sample_contract,
            metrics={},
            head_sha="abc123",
            task_sha256="task_hash",
            index_sha256="index_hash",
            policy_sha256="policy_hash",
            target_hashes={"packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/complexity.py": None},
            wiki_evidence_hashes={},
            collector_versions={},
            details={}
        )

    def test_evaluate_standard_task(self, base_evidence: ComplexityEvidence, sample_policy: ComplexityPolicy):
        """Test evaluating a standard complexity task."""
        # All metrics below threshold
        metrics: Dict[str, MetricEvidence] = {
            "cyclomatic_max": MetricEvidence(
                state="ok", value=5, reason="Low complexity", source="ruff"
            ),
            "blast_symbols": MetricEvidence(
                state="ok", value=10, reason="Moderate symbols", source="wikitoolkit"
            ),
            "weighted_files": MetricEvidence(
                state="ok", value=2, reason="Few files", source="task_parser"
            ),
            "modules": MetricEvidence(
                state="ok", value=1, reason="Single module", source="task_parser"
            ),
            "acceptance_criteria": MetricEvidence(
                state="ok", value=3, reason="Few criteria", source="task_parser"
            ),
            "downstream_tasks": MetricEvidence(
                state="ok", value=1, reason="Few dependencies", source="task_parser"
            ),
        }
        
        evidence = base_evidence.model_copy(update={"metrics": metrics})
        assessment = evaluate_complexity(evidence, sample_policy)
        
        assert assessment.classification == "standard"
        assert assessment.total_points < sample_policy.score_threshold
        assert "score_below_threshold" in assessment.reason_codes

    def test_evaluate_complex_task_score_threshold(self, base_evidence: ComplexityEvidence, sample_policy: ComplexityPolicy):
        """Test evaluating a complex task based on score threshold."""
        # Metrics that sum to meet or exceed threshold
        metrics: Dict[str, MetricEvidence] = {
            "cyclomatic_max": MetricEvidence(
                state="ok", value=15, reason="High complexity", source="ruff"
            ),  # 2 points (above band 11-21)
            "blast_symbols": MetricEvidence(
                state="ok", value=20, reason="Many symbols", source="wikitoolkit"
            ),  # 2 points (above band 10-30)
            "weighted_files": MetricEvidence(
                state="ok", value=6, reason="Many files", source="task_parser"
            ),  # 2 points (above band 4-8)
            "modules": MetricEvidence(
                state="ok", value=2, reason="Multiple modules", source="task_parser"
            ),  # 1 point (above band 2-3)
            "acceptance_criteria": MetricEvidence(
                state="ok", value=7, reason="Many criteria", source="task_parser"
            ),  # 2 points (above band 5-8)
            "downstream_tasks": MetricEvidence(
                state="ok", value=3, reason="Several dependencies", source="task_parser"
            ),  # 2 points (above band 2-5)
        }
        
        evidence = base_evidence.model_copy(update={"metrics": metrics})
        assessment = evaluate_complexity(evidence, sample_policy)
        
        assert assessment.classification == "complex"
        assert assessment.total_points >= sample_policy.score_threshold
        assert "score_threshold_met" in assessment.reason_codes

    def test_evaluate_complex_task_hard_limit_cyclomatic(self, base_evidence: ComplexityEvidence, sample_policy: ComplexityPolicy):
        """Test evaluating a complex task based on cyclomatic hard limit."""
        metrics: Dict[str, MetricEvidence] = {
            "cyclomatic_max": MetricEvidence(
                state="ok", value=25, reason="Very high complexity", source="ruff"
            ),  # Exceeds hard limit of 21
        }
        
        evidence = base_evidence.model_copy(update={"metrics": metrics})
        assessment = evaluate_complexity(evidence, sample_policy)
        
        assert assessment.classification == "complex"
        assert "hard_limit_cyclomatic_max" in assessment.reason_codes

    def test_evaluate_complex_task_hard_limit_blast(self, base_evidence: ComplexityEvidence, sample_policy: ComplexityPolicy):
        """Test evaluating a complex task based on blast symbols hard limit."""
        metrics: Dict[str, MetricEvidence] = {
            "blast_symbols": MetricEvidence(
                state="ok", value=35, reason="Very many symbols", source="wikitoolkit"
            ),  # Exceeds hard limit of 30
        }
        
        evidence = base_evidence.model_copy(update={"metrics": metrics})
        assessment = evaluate_complexity(evidence, sample_policy)
        
        assert assessment.classification == "complex"
        assert "hard_limit_blast_symbols" in assessment.reason_codes

    def test_evaluate_complex_task_hard_limit_downstream(self, base_evidence: ComplexityEvidence, sample_policy: ComplexityPolicy):
        """Test evaluating a complex task based on downstream tasks hard limit."""
        metrics: Dict[str, MetricEvidence] = {
            "downstream_tasks": MetricEvidence(
                state="ok", value=7, reason="Many dependencies", source="task_parser"
            ),  # Exceeds hard limit of 5
        }
        
        evidence = base_evidence.model_copy(update={"metrics": metrics})
        assessment = evaluate_complexity(evidence, sample_policy)
        
        assert assessment.classification == "complex"
        assert "hard_limit_downstream_tasks" in assessment.reason_codes

    def test_evaluate_unknown_task(self, base_evidence: ComplexityEvidence, sample_policy: ComplexityPolicy):
        """Test evaluating a task with unknown metrics."""
        metrics: Dict[str, MetricEvidence] = {
            "cyclomatic_max": MetricEvidence(
                state="unknown", value=None, reason="Tool failed", source="ruff"
            ),
        }
        
        evidence = base_evidence.model_copy(update={"metrics": metrics})
        assessment = evaluate_complexity(evidence, sample_policy)
        
        assert assessment.classification == "unknown"
        assert "metric_unknown" in assessment.reason_codes

    def test_evaluate_not_applicable_metrics(self, base_evidence: ComplexityEvidence, sample_policy: ComplexityPolicy):
        """Test evaluating a task with not_applicable metrics."""
        metrics: Dict[str, MetricEvidence] = {
            "cyclomatic_max": MetricEvidence(
                state="not_applicable", value=None, reason="Not a code task", source="ruff"
            ),
        }
        
        evidence = base_evidence.model_copy(update={"metrics": metrics})
        assessment = evaluate_complexity(evidence, sample_policy)
        
        assert assessment.classification == "standard"
        assert assessment.component_points["cyclomatic_max"] == 0

    def test_evaluate_boundary_values(self, base_evidence: ComplexityEvidence, sample_policy: ComplexityPolicy):
        """Test evaluating tasks with boundary metric values."""
        # Test boundary values for cyclomatic complexity band (11-21)
        metrics_low: Dict[str, MetricEvidence] = {
            "cyclomatic_max": MetricEvidence(
                state="ok", value=10, reason="Below band", source="ruff"
            ),  # 0 points (below 11)
        }
        
        evidence_low = base_evidence.model_copy(update={"metrics": metrics_low})
        assessment_low = evaluate_complexity(evidence_low, sample_policy)
        assert assessment_low.component_points["cyclomatic_max"] == 0
        
        metrics_in_band: Dict[str, MetricEvidence] = {
            "cyclomatic_max": MetricEvidence(
                state="ok", value=15, reason="In band", source="ruff"
            ),  # 1 point (11-21)
        }
        
        evidence_in_band = base_evidence.model_copy(update={"metrics": metrics_in_band})
        assessment_in_band = evaluate_complexity(evidence_in_band, sample_policy)
        assert assessment_in_band.component_points["cyclomatic_max"] == 1
        
        metrics_high: Dict[str, MetricEvidence] = {
            "cyclomatic_max": MetricEvidence(
                state="ok", value=25, reason="Above band", source="ruff"
            ),  # 2 points (above 21)
        }
        
        evidence_high = base_evidence.model_copy(update={"metrics": metrics_high})
        assessment_high = evaluate_complexity(evidence_high, sample_policy)
        assert assessment_high.component_points["cyclomatic_max"] == 2

    def test_assessment_id_consistency(self, base_evidence: ComplexityEvidence, sample_policy: ComplexityPolicy):
        """Test that identical inputs produce identical assessment IDs."""
        metrics: Dict[str, MetricEvidence] = {
            "cyclomatic_max": MetricEvidence(
                state="ok", value=15, reason="High complexity", source="ruff"
            ),
        }
        
        evidence1 = base_evidence.model_copy(update={"metrics": metrics})
        evidence2 = base_evidence.model_copy(update={"metrics": metrics})
        
        assessment1 = evaluate_complexity(evidence1, sample_policy)
        assessment2 = evaluate_complexity(evidence2, sample_policy)
        
        assert assessment1.assessment_id == assessment2.assessment_id