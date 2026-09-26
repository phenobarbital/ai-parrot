"""Golden DSL fixtures — the cross-executor contract (FEAT-598 AC7)."""

import json
from pathlib import Path

import pytest

import parrot.outputs.a2ui.linked
from parrot.outputs.a2ui.linked.dsl import TransformError, apply_transform, frame_from_records, frame_to_records
from parrot.outputs.a2ui.linked.models import TransformSpec

DSL_DIR = Path(parrot.outputs.a2ui.linked.__file__).parent / "contract" / "fixtures" / "dsl"
FIXTURES = sorted(DSL_DIR.glob("*.json"))


@pytest.mark.parametrize("path", FIXTURES, ids=[path.stem for path in FIXTURES])
def test_dsl_golden(path: Path) -> None:
    """Execute each shared fixture and assert its exact order-sensitive result."""
    case = json.loads(path.read_text())
    spec = TransformSpec.model_validate({"ops": case["ops"]})
    frames = {key: frame_from_records(rows) for key, rows in (case.get("frames") or {}).items()}
    if "error" in case:
        with pytest.raises(TransformError) as caught:
            apply_transform(frame_from_records(case["input"]), spec, frames=frames)
        assert caught.value.op_index == case["error"]["op_index"]
    else:
        actual = frame_to_records(apply_transform(frame_from_records(case["input"]), spec, frames=frames))
        assert actual == case["expected"]


def test_fixture_dir_not_empty() -> None:
    """Protect wildcard parametrisation from silently collecting no fixtures."""
    assert len(FIXTURES) >= 10
