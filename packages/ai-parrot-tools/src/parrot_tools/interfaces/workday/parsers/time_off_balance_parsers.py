from typing import Dict, Any, Optional, List
from datetime import date, datetime
from decimal import Decimal


def parse_time_off_balance_data(balance_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Parse time off plan balance data from the SOAP response.

    Note: The structure is:
    - Time_Off_Plan_Balance (one per worker)
      - Employee_Reference (worker info)
      - Time_Off_Plan_Balance_Data
        - Time_Off_Plan_Balance_Record[] (array of plans)

    Returns a list of parsed records (one per plan).
    """
    if not balance_data:
        return []

    results = []

    # Extract worker information from top level
    worker_id = None
    worker_name = None

    employee_ref = balance_data.get("Employee_Reference", {})
    if employee_ref:
        employee_ids = employee_ref.get("ID", [])
        if isinstance(employee_ids, list):
            for emp_id in employee_ids:
                if isinstance(emp_id, dict) and emp_id.get("type") == "Employee_ID":
                    worker_id = emp_id.get("_value_1")
                    break
        worker_name = employee_ref.get("Descriptor")

    # Get the balance data container
    balance_data_container = balance_data.get("Time_Off_Plan_Balance_Data", {})

    # Safety check: ensure it's a dict
    if not isinstance(balance_data_container, dict):
        balance_data_container = {}

    # Get the list of balance records
    balance_records = balance_data_container.get("Time_Off_Plan_Balance_Record", [])

    # Ensure it's a list
    if not isinstance(balance_records, list):
        balance_records = [balance_records] if balance_records else []

    # Parse each balance record (one per plan)
    for record in balance_records:
        if not isinstance(record, dict):
            continue

        parsed = {
            "worker_id": worker_id,
            "worker_name": worker_name,
        }

        # Time Off Plan information
        time_off_plan_ref = record.get("Time_Off_Plan_Reference", {})
        if time_off_plan_ref:
            plan_ids = time_off_plan_ref.get("ID", [])
            if isinstance(plan_ids, list):
                for plan_id in plan_ids:
                    if isinstance(plan_id, dict):
                        if plan_id.get("type") == "Absence_Plan_ID":
                            parsed["time_off_plan_id"] = plan_id.get("_value_1")
                        elif plan_id.get("type") == "WID" and not parsed.get("time_off_plan_id"):
                            parsed["time_off_plan_id"] = plan_id.get("_value_1")
            parsed["time_off_plan_name"] = time_off_plan_ref.get("Descriptor")

        # Unit of time
        unit_ref = record.get("Unit_of_Time_Reference", {})
        if unit_ref:
            unit_ids = unit_ref.get("ID", [])
            if isinstance(unit_ids, list):
                for unit_id in unit_ids:
                    if isinstance(unit_id, dict) and unit_id.get("type") == "Unit_of_Time_ID":
                        parsed["unit_of_time"] = unit_id.get("_value_1")
                        break

        # Balance from position record (it's a list, take the first item)
        position_records = record.get("Time_Off_Plan_Balance_Position_Record", [])
        if isinstance(position_records, list) and len(position_records) > 0:
            position_record = position_records[0]
            if isinstance(position_record, dict):
                # Extract balance
                parsed["balance"] = _parse_float(position_record.get("Time_Off_Plan_Balance"))

                # Extract position information (optional)
                position_ref = position_record.get("Position_Reference", {})
                if position_ref:
                    pos_ids = position_ref.get("ID", [])
                    if isinstance(pos_ids, list):
                        for pos_id in pos_ids:
                            if isinstance(pos_id, dict) and pos_id.get("type") == "Position_ID":
                                parsed["position_id"] = pos_id.get("_value_1")
                                break
                    parsed["position_title"] = position_ref.get("Descriptor")
        elif isinstance(position_records, dict):
            # Fallback if it's a single dict
            parsed["balance"] = _parse_float(position_records.get("Time_Off_Plan_Balance"))

            # Extract position information (optional)
            position_ref = position_records.get("Position_Reference", {})
            if position_ref:
                pos_ids = position_ref.get("ID", [])
                if isinstance(pos_ids, list):
                    for pos_id in pos_ids:
                        if isinstance(pos_id, dict) and pos_id.get("type") == "Position_ID":
                            parsed["position_id"] = pos_id.get("_value_1")
                            break
                parsed["position_title"] = position_ref.get("Descriptor")

        results.append(parsed)

    return results


def _parse_float(value: Any) -> Optional[float]:
    """Parse float value from Workday response"""
    if value is None:
        return None

    try:
        if isinstance(value, (int, float, Decimal)):
            return float(value)
        elif isinstance(value, str):
            return float(value)
        elif isinstance(value, dict):
            return float(value.get("_value_1", 0))
        return None
    except (ValueError, TypeError):
        return None


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


def _to_bool(value: Any) -> bool:
    """Normalize various truthy/falsy representations to bool."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in ("1", "true", "t", "yes", "y")
