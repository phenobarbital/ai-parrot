from typing import Dict, Any


def parse_time_request_data(time_request_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse time request data from the SOAP response.
    """
    if not time_request_data:
        return {}
    
    parsed = {}
    
    # Basic identification
    parsed["time_request_id"] = time_request_data.get("ID")
    
    # Worker information
    worker_ref = time_request_data.get("Worker_Reference", {})
    if worker_ref:
        worker_ids = worker_ref.get("ID", [])
        if isinstance(worker_ids, list):
            for worker_id in worker_ids:
                if isinstance(worker_id, dict) and worker_id.get("type") == "Employee_ID":
                    parsed["worker_id"] = worker_id.get("_value_1")
                    break
        parsed["worker_name"] = worker_ref.get("Descriptor")
    
    # Time request code information
    time_request_code_ref = time_request_data.get("Time_Request_Code_Reference", {})
    if time_request_code_ref:
        code_ids = time_request_code_ref.get("ID", [])
        if isinstance(code_ids, list):
            for code_id in code_ids:
                if isinstance(code_id, dict) and code_id.get("type") == "Time_Request_Code_ID":
                    parsed["time_request_code_id"] = code_id.get("_value_1")
                    break
        parsed["time_request_code_name"] = time_request_code_ref.get("Descriptor")
    
    # Time request flags
    parsed["delete_time_request"] = time_request_data.get("Delete_Time_Request")
    
    # Date and time information
    parsed["start_date"] = time_request_data.get("Start_Date")
    parsed["end_date"] = time_request_data.get("End_Date")
    parsed["start_time"] = time_request_data.get("Start_Time")
    parsed["end_time"] = time_request_data.get("End_Time")
    parsed["total_hours"] = time_request_data.get("Total_Hours")
    
    # Additional information
    parsed["comment"] = time_request_data.get("Comment")
    
    # Status information
    status_ref = time_request_data.get("Status_Reference", {})
    if status_ref:
        status_ids = status_ref.get("ID", [])
        if isinstance(status_ids, list):
            for status_id in status_ids:
                if isinstance(status_id, dict) and status_id.get("type") == "Time_Tracking_Set_Up_Option_ID":
                    parsed["status"] = status_id.get("_value_1")
                    break
    
    # Parse worktags (similar to time blocks)
    parsed["worktags"] = _parse_worktags(time_request_data)
    
    return parsed


def _parse_worktags(time_request_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse worktags from time request data.
    """
    worktags = {}
    
    # Define worktag fields to look for
    worktag_fields = [
        "Allocation_Pool_Reference",
        "Appropriation_Reference", 
        "Business_Unit_Reference",
        "Cost_Center_Reference",
        "Fund_Reference",
        "Gift_Reference",
        "Grant_Reference",
        "Job_Profile_Reference",
        "Location_Reference",
        "Program_Reference",
        "Region_Reference",
        "Custom_Worktag_01_Reference",
        "Custom_Worktag_02_Reference",
        "Custom_Worktag_03_Reference",
        "Custom_Worktag_04_Reference",
        "Custom_Worktag_05_Reference",
        "Custom_Worktag_06_Reference",
        "Custom_Worktag_07_Reference",
        "Custom_Worktag_08_Reference",
        "Custom_Worktag_09_Reference",
        "Custom_Worktag_10_Reference",
        "Custom_Worktag_11_Reference",
        "Custom_Worktag_12_Reference",
        "Custom_Worktag_13_Reference",
        "Custom_Worktag_14_Reference",
        "Custom_Worktag_15_Reference",
        "Custom_Organization_01_Reference",
        "Custom_Organization_02_Reference",
        "Custom_Organization_03_Reference",
        "Custom_Organization_04_Reference",
        "Custom_Organization_05_Reference",
        "Custom_Organization_06_Reference",
        "Custom_Organization_07_Reference",
        "Custom_Organization_08_Reference",
        "Custom_Organization_09_Reference",
        "Custom_Organization_10_Reference"
    ]
    
    for field_name in worktag_fields:
        field_data = time_request_data.get(field_name)
        if field_data:
            # Extract ID from reference
            ids = field_data.get("ID", [])
            if isinstance(ids, list):
                for id_item in ids:
                    if isinstance(id_item, dict):
                        # Prefer readable IDs over WID
                        if id_item.get("type") != "WID":
                            worktags[field_name] = {
                                "id": id_item.get("_value_1"),
                                "type": id_item.get("type")
                            }
                            break
                else:
                    # If no readable ID found, use WID
                    for id_item in ids:
                        if isinstance(id_item, dict) and id_item.get("type") == "WID":
                            worktags[field_name] = {
                                "id": id_item.get("_value_1"),
                                "type": id_item.get("type")
                            }
                            break
    
    return worktags 