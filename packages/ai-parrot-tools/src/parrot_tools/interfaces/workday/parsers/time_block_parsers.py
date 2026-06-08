# workday/parsers/time_block_parsers.py

from typing import Any, Dict, List, Optional
from datetime import date, datetime
from decimal import Decimal
from ..utils import ensure_list

def parse_time_block_data(time_block_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse the main time block data from Workday response.
    """
    if not time_block_data:
        return {}
    
    # Extract time block reference
    time_block_ref = time_block_data.get("Worker_Time_Block_Reference", {})
    time_block_id = None
    time_block_wid = None
    if isinstance(time_block_ref, dict):
        # Look for both Worker_Time_Block_ID and WID
        ids = time_block_ref.get("ID", [])
        if isinstance(ids, list):
            for id_item in ids:
                if isinstance(id_item, dict):
                    if id_item.get("type") == "Worker_Time_Block_ID":
                        time_block_id = id_item.get("_value_1")
                    elif id_item.get("type") == "WID":
                        time_block_wid = id_item.get("_value_1")
    
    # Extract worker information
    calculated_data = time_block_data.get("Calculated_Time_Block_Data", {})
    worker_ref = calculated_data.get("Worker_Reference", {})
    worker_id = None
    worker_name = None
    worker_ref_full = None
    
    if isinstance(worker_ref, dict):
        # Look for Employee_ID
        ids = worker_ref.get("ID", [])
        if isinstance(ids, list):
            for id_item in ids:
                if isinstance(id_item, dict) and id_item.get("type") == "Employee_ID":
                    worker_id = id_item.get("_value_1")
                    break
        
        # Try to locate full worker data to extract name
        candidates = [
            worker_ref,
            worker_ref.get("Worker_Data"),
            worker_ref.get("Worker"),
            worker_ref.get("Worker_Detail_Data"),
        ]
        for candidate in candidates:
            if isinstance(candidate, dict) and candidate.get("Personal_Data"):
                worker_ref_full = candidate
                break

    if worker_ref_full:
        worker_name = _extract_worker_name(worker_ref_full)

    # Date information - handle both string and datetime.date
    calculated_date_raw = calculated_data.get("Calculated_Date")
    calculated_date = _parse_date(calculated_date_raw)
    if calculated_date is None and hasattr(calculated_date_raw, 'isoformat'):
        # Fallback for unexpected objects exposing isoformat
        calculated_date = calculated_date_raw

    # Additional fields when available
    calculated_in_time = _parse_datetime(calculated_data.get("In_Time"))
    calculated_out_time = _parse_datetime(calculated_data.get("Out_Time"))
    calculated_quantity = _parse_quantity(calculated_data.get("Calculated_Quantity"))
    shift_date = _parse_date(calculated_data.get("Shift_Date"))
    
    # Status information
    status_ref = calculated_data.get("Status_Reference")
    status = None
    if status_ref and isinstance(status_ref, dict):
        status_ids = status_ref.get("ID", [])
        if isinstance(status_ids, list):
            for id_item in status_ids:
                if isinstance(id_item, dict) and id_item.get("type") == "Time_Tracking_Set_Up_Option_ID":
                    status = id_item.get("_value_1")
                    break
    
    is_deleted = _to_bool(calculated_data.get("Is_Deleted", False))
    calculation_tags = _parse_calculation_tags(calculated_data.get("Calculation_Tag_Reference"))
    last_updated = _parse_datetime(calculated_data.get("Last_Updated"))
    worktags = _parse_worktags(calculated_data)
    
    return {
        "time_block_id": time_block_id,
        "time_block_wid": time_block_wid,
        "worker_id": worker_id,
        "worker_name": worker_name,
        "calculated_date": calculated_date,
        "calculated_in_time": calculated_in_time,
        "calculated_out_time": calculated_out_time,
        "calculated_quantity": calculated_quantity,
        "status": status,
        "shift_date": shift_date,
        "is_deleted": is_deleted,
        "calculation_tags": calculation_tags,
        "last_updated": last_updated,
        "worktags": worktags,
    }

def _extract_worker_name(worker_data: Dict[str, Any]) -> Optional[str]:
    """Extract worker name from worker data"""
    if not worker_data:
        return None
    
    personal_data = worker_data.get("Personal_Data", {}) or {}
    name_data = personal_data.get("Name_Data", {}) or {}
    legal_name = name_data.get("Legal_Name_Data", {}) or {}
    name_detail = legal_name.get("Name_Detail_Data", {}) or {}
    
    first_name = name_detail.get("First_Name", "")
    last_name = name_detail.get("Last_Name", "")
    
    if first_name or last_name:
        return f"{first_name} {last_name}".strip()
    
    return name_detail.get("Formatted_Name")

def _parse_date(date_value: Any) -> Optional[date]:
    """Parse date value from Workday response"""
    if not date_value:
        return None
    
    try:
        if isinstance(date_value, datetime):
            return date_value.date()
        if isinstance(date_value, date):
            return date_value
        if isinstance(date_value, str):
            return datetime.strptime(date_value, "%Y-%m-%d").date()
        if hasattr(date_value, 'date'):
            return date_value.date()
        return None
    except (ValueError, AttributeError):
        return None

def _parse_datetime(datetime_value: Any) -> Optional[datetime]:
    """Parse datetime value from Workday response"""
    if not datetime_value:
        return None
    
    try:
        if isinstance(datetime_value, str):
            normalized = datetime_value.strip()
            if normalized.endswith("Z"):
                normalized = normalized[:-1] + "+00:00"
            for fmt in [
                "%Y-%m-%dT%H:%M:%S.%f%z",
                "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S.%f",
            ]:
                try:
                    return datetime.strptime(normalized, fmt)
                except ValueError:
                    continue
            # Try common datetime formats
            try:
                return datetime.fromisoformat(normalized)
            except ValueError:
                return None
        elif hasattr(datetime_value, 'replace'):
            return datetime_value
        return None
    except (ValueError, AttributeError):
        return None

def _parse_quantity(quantity_data: Any) -> Optional[float]:
    """Parse quantity value from Workday response"""
    if quantity_data is None:
        return None
    
    try:
        if isinstance(quantity_data, (int, float, Decimal)):
            return float(quantity_data)
        elif isinstance(quantity_data, str):
            return float(quantity_data)
        elif isinstance(quantity_data, dict):
            # Sometimes quantity comes as a complex object
            return float(quantity_data.get("_value_1", 0))
        return None
    except (ValueError, TypeError):
        return None

def _parse_calculation_tags(tags_data: Any) -> List[str]:
    """Parse calculation tags from Workday response"""
    if not tags_data:
        return []
    
    tags = ensure_list(tags_data)
    result = []
    
    for tag in tags:
        if isinstance(tag, dict):
            # Look for ID structure like in the raw data
            ids = tag.get("ID", [])
            if isinstance(ids, list):
                for id_item in ids:
                    if isinstance(id_item, dict) and id_item.get("type") == "Time_Calculation_Tag_ID":
                        tag_value = id_item.get("_value_1")
                        if tag_value:
                            result.append(str(tag_value))
                            break
            else:
                # Fallback to old method
                tag_value = tag.get("Calculation_Tag") or tag.get("_value_1")
                if tag_value:
                    result.append(str(tag_value))
        elif tag:
            result.append(str(tag))
    
    return result

def _to_bool(value: Any) -> bool:
    """Normalize various truthy/falsy representations to bool."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in ("1", "true", "t", "yes", "y")

def _parse_worktags(calculated_data: Dict[str, Any]) -> Dict[str, Any]:
    """Parse worktags from Workday response"""
    if not calculated_data:
        return {}
    
    result = {}
    
    # Look for worktag references in the calculated data
    worktag_fields = [
        'Allocation_Pool_Reference', 'Appropriation_Reference', 'Business_Unit_Reference',
        'Cost_Center_Reference', 'Fund_Reference', 'Gift_Reference', 'Grant_Reference',
        'Job_Profile_Reference', 'Location_Reference', 'Program_Reference', 'Region_Reference',
        'Custom_Worktag_01_Reference', 'Custom_Worktag_02_Reference', 'Custom_Worktag_03_Reference',
        'Custom_Worktag_04_Reference', 'Custom_Worktag_05_Reference', 'Custom_Worktag_06_Reference',
        'Custom_Worktag_07_Reference', 'Custom_Worktag_08_Reference', 'Custom_Worktag_09_Reference',
        'Custom_Worktag_10_Reference', 'Custom_Worktag_11_Reference', 'Custom_Worktag_12_Reference',
        'Custom_Worktag_13_Reference', 'Custom_Worktag_14_Reference', 'Custom_Worktag_15_Reference',
        'Custom_Organization_01_Reference', 'Custom_Organization_02_Reference', 'Custom_Organization_03_Reference',
        'Custom_Organization_04_Reference', 'Custom_Organization_05_Reference', 'Custom_Organization_06_Reference',
        'Custom_Organization_07_Reference', 'Custom_Organization_08_Reference', 'Custom_Organization_09_Reference',
        'Custom_Organization_10_Reference'
    ]
    
    for field in worktag_fields:
        ref_data = calculated_data.get(field)
        
        if ref_data and isinstance(ref_data, dict):
            # Extract ID from reference
            ids = ref_data.get("ID", [])
            
            if isinstance(ids, list):
                # Look for the most meaningful ID (not WID)
                best_id = None
                
                for id_item in ids:
                    if isinstance(id_item, dict):
                        ref_id = id_item.get("_value_1")
                        ref_type = id_item.get("type")
                        
                        if ref_id and ref_type != "WID":
                            # Prefer non-WID types
                            best_id = ref_id
                            break
                        elif ref_id and best_id is None:
                            # Use WID only as fallback
                            best_id = ref_id
                
                if best_id:
                    # Convert field name to lowercase with underscores for easier access
                    field_key = field.lower().replace('_reference', '_id')
                    result[field_key] = best_id
    
    return result
