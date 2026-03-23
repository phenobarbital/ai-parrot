from __future__ import annotations
from typing import Any, Optional, Union
from dataclasses import is_dataclass, asdict
from pydantic import BaseModel
try:
    from . import yaml_rs as _yaml  # type: ignore[attr-defined]
    _dumps = _yaml.dumps
    _loads = _yaml.loads
    dumps_formatted = _yaml.dumps_formatted
    RUST_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only when the wheel lacks Rust
    import yaml as _yaml
    RUST_AVAILABLE = False


def _prepare_object(obj: Any) -> Any:
    """Convert dataclasses and pydantic models to dictionaries before dumping."""
    if isinstance(obj, BaseModel):
        return obj.model_dump()
    return asdict(obj) if is_dataclass(obj) else obj


def dumps(
    obj: Any,
    indent: int = 2,
    default_flow_style: bool = False,
    sort_keys: bool = False
) -> str:
    """
    Serialize Python object to YAML string.
    Args:
        obj: Python object (dict, list, BaseModel, dataclass)
        indent: Indentation spaces (default: 2)
        default_flow_style: Use flow style (default: False)
        sort_keys: Sort dictionary keys (default: False)

    Returns:
        YAML string

    Performance:
        - Rust implementation: 10-50x faster than PyYAML
        - Falls back to PyYAML if Rust extension not available
    """
    # Convert BaseModel or dataclass to dict
    obj = _prepare_object(obj)
    if RUST_AVAILABLE:
        return dumps_formatted(
            obj,
            indent=indent,
            flow_style=default_flow_style,
            sort_keys=sort_keys
        )
    else:
        # Fallback to PyYAML
        return _yaml.dump(
            obj,
            indent=indent,
            default_flow_style=default_flow_style,
            sort_keys=sort_keys
        )

def loads(yaml_str: str, loader: Optional[Any] = None) -> Any:
    """
    Deserialize YAML string to Python object.

    Args:
        yaml_str: YAML formatted string

    Returns:
        Python object (dict, list, etc.)

    Performance:
        - Rust implementation: 5-20x faster than PyYAML
        - Falls back to PyYAML if Rust extension not available
    """
    if RUST_AVAILABLE:
        return _loads(yaml_str)
    kwargs = {"Loader": loader} if loader is not None else {}
    return _yaml.safe_load(yaml_str) if loader is None else _yaml.load(yaml_str, **kwargs)

__all__ = ["dumps", "loads", "RUST_AVAILABLE"]
