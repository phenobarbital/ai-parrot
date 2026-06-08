"""
Parsers for Workday Custom Punch - Field Report.

This module provides parsing functions to extract all fields from the SOAP response.
"""
from typing import List, Dict, Any, Optional
from datetime import date, datetime
from decimal import Decimal


def _parse_float(value: Any) -> Optional[float]:
    """Parse a value to float, handling None and Decimal."""
    if value is None:
        return None
    if isinstance(value, (float, int, Decimal)):
        return float(value)
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _parse_date(value: Any) -> Optional[date]:
    """Parse a value to date."""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace('Z', '+00:00')).date()
    except (ValueError, AttributeError):
        pass
    return None


def _extract_reference_id_and_descriptor(ref_obj: Any, id_type: Optional[str] = None) -> tuple:
    """
    Extract ID and Descriptor from a Workday reference object.

    Args:
        ref_obj: The reference object (can be dict, OrderedDict, or None)
        id_type: Optional specific ID type to look for

    Returns:
        Tuple of (id_value, descriptor)
    """
    if not ref_obj or not isinstance(ref_obj, dict):
        return (None, None)

    # Extract descriptor
    descriptor = ref_obj.get('Descriptor') or ref_obj.get('@Descriptor')

    # Extract ID
    ids = ref_obj.get('ID', [])
    if not isinstance(ids, list):
        ids = [ids]

    id_value = None
    for id_obj in ids:
        if isinstance(id_obj, dict):
            # If specific type requested, look for it
            if id_type and id_obj.get('type') == id_type:
                id_value = id_obj.get('_value_1')
                break
            # Otherwise, take the first one
            if not id_value:
                id_value = id_obj.get('_value_1')

    return (id_value, descriptor)


def _extract_multiple_references(ref_objs: Any, id_type: Optional[str] = None) -> tuple:
    """
    Extract IDs and Descriptors from multiple reference objects.

    Returns:
        Tuple of (list of IDs, list of descriptors)
    """
    if not ref_objs:
        return ([], [])

    if not isinstance(ref_objs, list):
        ref_objs = [ref_objs]

    ids = []
    descriptors = []

    for ref_obj in ref_objs:
        id_val, desc = _extract_reference_id_and_descriptor(ref_obj, id_type)
        if id_val:
            ids.append(id_val)
        if desc:
            descriptors.append(desc)

    return (ids, descriptors)


def _parse_worker_group(worker_group: Dict[str, Any]) -> Dict[str, Any]:
    """Parse the Worker_group data."""
    if not worker_group:
        return {}

    return {
        'employee_id': worker_group.get('Employee_ID'),
        'worker_status': worker_group.get('Worker_Status'),
        'pay_rate': _parse_float(worker_group.get('Pay_Rate'))
    }


def parse_custom_punch_field_report_data(raw_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Parse the raw Custom Punch - Field Report data from SOAP response.

    Args:
        raw_data: List of Report_Entry dictionaries from the SOAP response

    Returns:
        List of parsed custom punch field report entry dictionaries
    """
    if not raw_data:
        return []

    if not isinstance(raw_data, list):
        raw_data = [raw_data]

    results = []

    for entry in raw_data:
        if not isinstance(entry, dict):
            continue

        parsed = {
            'raw_data': entry
        }

        # Time Block reference
        time_block_ref = entry.get('Time_Block')
        parsed['time_block_id'], parsed['time_block_name'] = \
            _extract_reference_id_and_descriptor(time_block_ref, 'Worker_Time_Block_ID')

        # Reference ID
        parsed['reference_id'] = entry.get('referenceID')

        # Worker reference
        worker_ref = entry.get('Worker')
        parsed['worker_id'], parsed['worker_name'] = \
            _extract_reference_id_and_descriptor(worker_ref, 'Employee_ID')

        # Worker group (nested structure)
        worker_group = entry.get('Worker_group', {})
        parsed['worker_group'] = _parse_worker_group(worker_group)

        # Primary Position reference
        position_ref = entry.get('Primary_Position')
        parsed['primary_position_id'], parsed['primary_position_name'] = \
            _extract_reference_id_and_descriptor(position_ref, 'Position_ID')

        # Default Cost Center
        default_cc_ref = entry.get('Default_Cost_Center')
        parsed['default_cost_center_id'], parsed['default_cost_center_name'] = \
            _extract_reference_id_and_descriptor(default_cc_ref, 'Cost_Center_Reference_ID')

        # Default Location
        default_loc_ref = entry.get('Default_Location')
        parsed['default_location_id'], parsed['default_location_name'] = \
            _extract_reference_id_and_descriptor(default_loc_ref, 'Location_ID')

        # Date and time
        parsed['reported_date'] = _parse_date(entry.get('Reported_Date'))
        parsed['in_time'] = entry.get('In_Time')
        parsed['out_time'] = entry.get('Out_Time')

        # Override Cost Center
        override_cc_ref = entry.get('Override_Cost_Center')
        parsed['override_cost_center_id'], parsed['override_cost_center_name'] = \
            _extract_reference_id_and_descriptor(override_cc_ref, 'Cost_Center_Reference_ID')

        # Override Location
        override_loc_ref = entry.get('Override_Location')
        parsed['override_location_id'], parsed['override_location_name'] = \
            _extract_reference_id_and_descriptor(override_loc_ref, 'Location_ID')

        # Time Entry Code
        time_entry_code_ref = entry.get('Time_Entry_Code')
        parsed['time_entry_code_id'], parsed['time_entry_code_name'] = \
            _extract_reference_id_and_descriptor(time_entry_code_ref, 'Time_Code_Reference_ID')

        # Calculated Tags (can be multiple)
        calc_tags = entry.get('Calculated_Tag', [])
        parsed['calculated_tag_ids'], parsed['calculated_tag_names'] = \
            _extract_multiple_references(calc_tags, 'Time_Calculation_Tag_ID')

        # Units
        units_ref = entry.get('Units')
        parsed['units_id'], parsed['units_name'] = \
            _extract_reference_id_and_descriptor(units_ref, 'Unit_of_Time_ID')

        # Calculated quantities and rates
        parsed['calculated_quantity'] = _parse_float(entry.get('Calculated_Quantity'))
        parsed['override_rate'] = _parse_float(entry.get('Override_Rate'))
        parsed['test_override_rate'] = _parse_float(entry.get('XMLNAME__TEST__Override_Rate'))
        parsed['total_wages'] = _parse_float(entry.get('Total_Wages'))

        results.append(parsed)

    return results
