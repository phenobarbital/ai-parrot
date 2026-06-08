"""
Parsers for Workday Get_References (Integrations service) responses.
"""
from typing import Any, Dict
from ..utils import ensure_list, extract_by_type


def parse_reference_data(reference: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse one ``Reference_ID`` element from a Get_References response.

    The Workday payload looks like::

        <wd:Reference_ID wd:Descriptor="Time Calculation Tag">
          <wd:Reference_ID_Reference>
            <wd:ID wd:type="WID">…</wd:ID>
            <wd:ID wd:type="Time_Calculation_Tag_ID">CAN_Statutory_Holiday</wd:ID>
          </wd:Reference_ID_Reference>
          <wd:Reference_ID_Data>
            <wd:ID>CAN_Statutory_Holiday</wd:ID>
            <wd:Reference_ID_Type>Time_Calculation_Tag_ID</wd:Reference_ID_Type>
            <wd:Referenced_Object_Descriptor>CAN Statutory Holiday</wd:Referenced_Object_Descriptor>
          </wd:Reference_ID_Data>
        </wd:Reference_ID>
    """
    if not isinstance(reference, dict):
        return {}

    ref_data = reference.get("Reference_ID_Data") or {}
    if isinstance(ref_data, list):
        ref_data = ref_data[0] if ref_data else {}

    ref_ref = reference.get("Reference_ID_Reference") or {}
    ids = ensure_list(ref_ref.get("ID", [])) if isinstance(ref_ref, dict) else []

    reference_id_type = ref_data.get("Reference_ID_Type") if isinstance(ref_data, dict) else None
    return {
        "reference_type": reference.get("Descriptor") or (
            ref_ref.get("Descriptor") if isinstance(ref_ref, dict) else None
        ),
        "reference_id_type": reference_id_type,
        "reference_id": (
            extract_by_type(ids, reference_id_type) if reference_id_type else None
        ) or (ref_data.get("ID") if isinstance(ref_data, dict) else None),
        "wid": extract_by_type(ids, "WID"),
        "descriptor": ref_data.get("Referenced_Object_Descriptor") if isinstance(ref_data, dict) else None,
    }


__all__ = ["parse_reference_data"]
