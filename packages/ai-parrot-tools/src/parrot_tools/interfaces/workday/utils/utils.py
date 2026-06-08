import json
from typing import Any, Dict, Optional, List
from decimal import Decimal

def safe_serialize(val: Any) -> str:
    """
    Serialize Decimal, list or dict into JSON-friendly string,
    or return empty string if None.
    """
    if val is None:
        return ""
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, (list, dict)):
        def default(o: Any):
            if isinstance(o, Decimal):
                return float(o)
            return str(o)
        return json.dumps(val, default=default, ensure_ascii=False)
    return str(val)

def ensure_list(val: Any) -> List:
    """
    Convert a potentially singular value to a list.
    """
    if isinstance(val, list):
        return val
    if val is None:
        return []
    return [val]

def extract_by_type(
    ids: Any,
    desired_type: str
) -> Optional[str]:
    """
    Given a list of {'_value_1':…, 'type':…} dicts (or a single dict),
    return the value whose type matches `desired_type`, or None.
    """
    lst = ids if isinstance(ids, list) else [ids]
    for node in lst:
        if not isinstance(node, dict):
            continue
        node_type = (
            node.get("type")
            or node.get("@wd:type")
            or node.get("wd:type")
            or node.get("Type")
        )
        if node_type != desired_type:
            continue

        for value_key in ("_value_1", "value", "Value", "ID", "$", "#text", "text"):
            value = node.get(value_key)
            if value is not None:
                return str(value)

        # Some payloads embed the value directly as the only non-type entry.
        for key, value in node.items():
            if key in {"type", "@wd:type", "wd:type", "Type"}:
                continue
            if value is not None:
                return str(value)
    return None

def extract_nested(data: Dict[str, Any], path: list) -> Any:
    """
    Helper to extract nested data from a dict given a list of keys.
    """
    for key in path:
        if not isinstance(data, dict):
            return None
        data = data.get(key, {})
    return data

def first(v: Any) -> Dict[str, Any]:
    """
    Helper to get first item of a list or dict, or empty dict if neither.
    """
    if isinstance(v, list):
        return v[0] if v else {}
    if isinstance(v, dict):
        return v
    return {} 
