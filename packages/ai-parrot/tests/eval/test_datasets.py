"""Unit tests for DatasetLoader (JSONL + YAML + HF stub) (TASK-1424)."""
import json
import pytest

from parrot.eval import JSONLDatasetLoader, YAMLDatasetLoader
from parrot.eval.datasets import HFDatasetLoader


async def test_jsonl_roundtrip(tmp_path):
    """JSONLDatasetLoader reads a JSONL file into a valid EvalDataset."""
    p = tmp_path / "d.jsonl"
    p.write_text('{"task_id": "t1", "inputs": {"q": "hi"}}\n')
    ds = await JSONLDatasetLoader().load(str(p))
    assert len(ds.tasks) == 1
    assert ds.tasks[0].task_id == "t1"


async def test_jsonl_multiple_tasks(tmp_path):
    """JSONLDatasetLoader reads multiple lines."""
    p = tmp_path / "multi.jsonl"
    lines = [
        '{"task_id": "t1", "inputs": {"q": "a"}}',
        '{"task_id": "t2", "inputs": {"q": "b"}}',
    ]
    p.write_text("\n".join(lines) + "\n")
    ds = await JSONLDatasetLoader().load(str(p))
    assert len(ds.tasks) == 2
    assert ds.name == "multi"


async def test_jsonl_skips_blank_lines(tmp_path):
    """JSONLDatasetLoader skips empty lines."""
    p = tmp_path / "blanks.jsonl"
    p.write_text('\n{"task_id": "t1", "inputs": {}}\n\n')
    ds = await JSONLDatasetLoader().load(str(p))
    assert len(ds.tasks) == 1


async def test_jsonl_missing_file():
    """JSONLDatasetLoader raises FileNotFoundError for missing file."""
    with pytest.raises(FileNotFoundError):
        await JSONLDatasetLoader().load("/nonexistent/path/d.jsonl")


async def test_yaml_roundtrip(tmp_path):
    """YAMLDatasetLoader reads a YAML file into a valid EvalDataset."""
    p = tmp_path / "tasks.yaml"
    p.write_text(
        "name: my-dataset\ntasks:\n"
        "  - task_id: t1\n    inputs:\n      query: hello\n"
    )
    ds = await YAMLDatasetLoader().load(str(p))
    assert ds.name == "my-dataset"
    assert len(ds.tasks) == 1
    assert ds.tasks[0].task_id == "t1"


async def test_yaml_defaults_name_to_stem(tmp_path):
    """YAMLDatasetLoader uses filename stem when 'name' is absent."""
    p = tmp_path / "jira_triage.yaml"
    p.write_text("tasks:\n  - task_id: t1\n    inputs:\n      query: go\n")
    ds = await YAMLDatasetLoader().load(str(p))
    assert ds.name == "jira_triage"


async def test_yaml_missing_file():
    """YAMLDatasetLoader raises FileNotFoundError for missing file."""
    with pytest.raises(FileNotFoundError):
        await YAMLDatasetLoader().load("/nonexistent/path/t.yaml")


async def test_hf_loader_raises_not_implemented():
    """HFDatasetLoader raises NotImplementedError."""
    with pytest.raises(NotImplementedError, match="HFDatasetLoader"):
        await HFDatasetLoader().load("some/hf/dataset")


async def test_jsonl_malformed_json_raises(tmp_path):
    """JSONLDatasetLoader raises ValueError on invalid JSON."""
    p = tmp_path / "bad.jsonl"
    p.write_text("not_valid_json\n")
    with pytest.raises(ValueError, match="Invalid JSON"):
        await JSONLDatasetLoader().load(str(p))


async def test_jsonl_with_sandbox_spec(tmp_path):
    """JSONLDatasetLoader round-trips sandbox_spec through SandboxSpec."""
    p = tmp_path / "spec.jsonl"
    task_dict = {
        "task_id": "s1",
        "inputs": {"query": "x"},
        "sandbox_spec": {"kind": "in_memory_state", "seed_state": {"issues": {}}},
    }
    p.write_text(json.dumps(task_dict) + "\n")
    ds = await JSONLDatasetLoader().load(str(p))
    assert ds.tasks[0].sandbox_spec is not None
