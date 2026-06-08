"""
Job Requisition parsers for Workday Get_Job_Requisitions operation.
"""

from typing import Dict, List, Optional, Any, Union
import logging
from ..utils import ensure_list, extract_by_type

logger = logging.getLogger(__name__)


def safe_get_nested(data: Dict, *keys, default=None) -> Any:
    """
    Safely get nested dictionary values.

    Args:
        data: Dictionary to traverse
        *keys: Keys to traverse
        default: Default value if key path doesn't exist

    Returns:
        Value at key path or default
    """
    current = data
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default
    return current


def parse_integration_id_data(integration_data: Union[List, Dict, None]) -> Dict[str, Any]:
    """
    Parse Integration ID Data from Job Requisition response.

    Args:
        integration_data: Integration ID data from the response

    Returns:
        Dictionary with parsed integration data
    """
    result = {
        "integration_ids": [],
        "external_integration_id": None
    }

    if not integration_data:
        return result

    # Handle both dict and list cases
    id_items = []
    if isinstance(integration_data, dict):
        id_items = integration_data.get("ID", [])
        if not isinstance(id_items, list):
            id_items = [id_items]
    elif isinstance(integration_data, list):
        id_items = integration_data

    for id_item in id_items:
        if isinstance(id_item, dict):
            # Handle structured ID objects
            id_value = id_item.get("_value_1") or id_item.get("ID")
            system_id = id_item.get("System_ID")

            if id_value:
                result["integration_ids"].append(str(id_value))
                if system_id == "WD-WID" and not result["external_integration_id"]:
                    result["external_integration_id"] = str(id_value)
        elif id_item:
            # Handle direct text IDs
            result["integration_ids"].append(str(id_item))
            if not result["external_integration_id"]:
                result["external_integration_id"] = str(id_item)

    return result


def parse_job_requisition_reference(jr_ref: Dict) -> Dict[str, str]:
    """
    Parse Job Requisition Reference to extract WID and ID.

    Args:
        jr_ref: Job Requisition Reference data

    Returns:
        Dictionary with job_requisition_wid and job_requisition_id
    """
    result = {"job_requisition_wid": None, "job_requisition_id": None, "job_requisition_name": None}

    if not jr_ref or not isinstance(jr_ref, dict):
        return result

    id_list = ensure_list(jr_ref.get("ID", []))
    if isinstance(id_list, list):
        result["job_requisition_wid"] = extract_by_type(id_list, "WID")
        result["job_requisition_id"] = (
            extract_by_type(id_list, "Job_Requisition_ID") or
            extract_by_type(id_list, "Requisition_ID")
        )

    result["job_requisition_name"] = jr_ref.get("Descriptor")

    return result


def parse_job_profile_data(job_profile_ref: Dict) -> Dict[str, Any]:
    """
    Parse Job Profile Reference data.

    Args:
        job_profile_ref: Job Profile Reference from the response

    Returns:
        Dictionary with parsed job profile information
    """
    if not job_profile_ref or not isinstance(job_profile_ref, dict):
        return {}

    id_list = ensure_list(job_profile_ref.get("ID", []))

    return {
        "job_profile_id": extract_by_type(id_list, "Job_Profile_ID"),
        "job_profile_wid": extract_by_type(id_list, "WID"),
        "job_profile_name": job_profile_ref.get("Descriptor")
    }


def parse_worker_type_data(worker_type_ref: Dict) -> Dict[str, Any]:
    """
    Parse Worker Type Reference data.

    Args:
        worker_type_ref: Worker Type Reference from the response

    Returns:
        Dictionary with parsed worker type information
    """
    if not worker_type_ref or not isinstance(worker_type_ref, dict):
        return {}

    id_list = ensure_list(worker_type_ref.get("ID", []))

    return {
        "worker_type_id": extract_by_type(id_list, "Worker_Type_ID") or extract_by_type(id_list, "Employee_Type_ID"),
        "worker_type_wid": extract_by_type(id_list, "WID"),
        "worker_type_name": worker_type_ref.get("Descriptor")
    }


def parse_jr_location_data(location_ref: Dict) -> Dict[str, Any]:
    """
    Parse Location Reference data for Job Requisitions.

    Args:
        location_ref: Location Reference from the response

    Returns:
        Dictionary with parsed location information (simplified for job requisitions)
    """
    if not location_ref or not isinstance(location_ref, dict):
        return {}

    id_list = ensure_list(location_ref.get("ID", []))

    return {
        "location_id": extract_by_type(id_list, "Location_ID"),
        "location_wid": extract_by_type(id_list, "WID"),
        "location_name": location_ref.get("Descriptor")
    }


def parse_supervisory_organization_data(org_ref: Dict) -> Dict[str, Any]:
    """
    Parse Supervisory Organization Reference data.

    Args:
        org_ref: Organization Reference from the response

    Returns:
        Dictionary with parsed organization information
    """
    if not org_ref or not isinstance(org_ref, dict):
        return {}

    id_list = ensure_list(org_ref.get("ID", []))

    return {
        "supervisory_organization_id": extract_by_type(id_list, "Organization_Reference_ID"),
        "supervisory_organization_wid": extract_by_type(id_list, "WID"),
        "supervisory_organization_name": org_ref.get("Descriptor")
    }


def parse_position_data(position_ref: Dict) -> Dict[str, Any]:
    """
    Parse Position Reference data.

    Args:
        position_ref: Position Reference from the response

    Returns:
        Dictionary with parsed position information
    """
    if not position_ref or not isinstance(position_ref, dict):
        return {}

    id_list = ensure_list(position_ref.get("ID", []))

    return {
        "position_id": extract_by_type(id_list, "Position_ID"),
        "position_wid": extract_by_type(id_list, "WID"),
        "position_title": position_ref.get("Descriptor")
    }


def parse_hiring_manager_data(manager_ref: Dict) -> Dict[str, Any]:
    """
    Parse Hiring Manager Reference data.

    Args:
        manager_ref: Worker Reference from the response

    Returns:
        Dictionary with parsed hiring manager information
    """
    if not manager_ref or not isinstance(manager_ref, dict):
        return {}

    id_list = ensure_list(manager_ref.get("ID", []))

    return {
        "hiring_manager_id": extract_by_type(id_list, "Employee_ID"),
        "hiring_manager_wid": extract_by_type(id_list, "WID"),
        "hiring_manager_name": manager_ref.get("Descriptor")
    }


def parse_recruiter_data(recruiter_ref: Dict) -> Dict[str, Any]:
    """
    Parse Recruiter Reference data (single recruiter).

    Args:
        recruiter_ref: Worker Reference from the response

    Returns:
        Dictionary with parsed recruiter information
    """
    if not recruiter_ref or not isinstance(recruiter_ref, dict):
        return {}

    id_list = ensure_list(recruiter_ref.get("ID", []))

    return {
        "recruiter_id": extract_by_type(id_list, "Employee_ID"),
        "recruiter_wid": extract_by_type(id_list, "WID"),
        "recruiter_name": recruiter_ref.get("Descriptor")
    }


def parse_role_assignment_data(role_assignment_data: Union[List, Dict, None]) -> Dict[str, List[Dict[str, str]]]:
    """
    Parse Role Assignment Data to extract recruiters and other role assignees.

    Args:
        role_assignment_data: Role Assignment Data from the response

    Returns:
        Dictionary with lists of recruiters and other role assignments
    """
    result = {
        "recruiters": [],
        "hiring_managers": [],
        "other_roles": []
    }

    if not role_assignment_data:
        return result

    # Ensure it's a list
    role_assignments = ensure_list(role_assignment_data)

    for role_assignment in role_assignments:
        if not isinstance(role_assignment, dict):
            continue

        # Get role type
        role_ref = role_assignment.get("Role_Reference", {})
        if not isinstance(role_ref, dict):
            continue

        role_id_list = ensure_list(role_ref.get("ID", []))
        role_id = extract_by_type(role_id_list, "Organization_Role_ID")

        # Get role assignees
        role_assignees = ensure_list(role_assignment.get("Role_Assignee", []))

        for assignee in role_assignees:
            if not isinstance(assignee, dict):
                continue

            worker_ref = assignee.get("Worker_Reference", {})
            if not isinstance(worker_ref, dict):
                continue

            worker_id_list = ensure_list(worker_ref.get("ID", []))

            assignee_data = {
                "employee_id": extract_by_type(worker_id_list, "Employee_ID"),
                "wid": extract_by_type(worker_id_list, "WID"),
                "name": worker_ref.get("Descriptor")
            }

            # Categorize by role
            if role_id == "Primary_Recruiter":
                result["recruiters"].append(assignee_data)
            elif role_id == "Hiring_Manager":
                result["hiring_managers"].append(assignee_data)
            else:
                result["other_roles"].append({
                    **assignee_data,
                    "role_id": role_id
                })

    return result


def parse_organization_assignments_data(org_assignments: Dict) -> Dict[str, Any]:
    """
    Parse Organization Assignments Data (Company, Cost Center, etc.).

    Args:
        org_assignments: Organization Assignments Data from the response

    Returns:
        Dictionary with parsed organization assignments
    """
    result = {
        "company_id": None,
        "company_wid": None,
        "company_name": None,
        "cost_center_id": None,
        "cost_center_wid": None,
        "cost_center_name": None
    }

    if not org_assignments or not isinstance(org_assignments, dict):
        return result

    # Parse Company Assignment
    company_ref = org_assignments.get("Company_Assignment_Reference", {})
    if isinstance(company_ref, dict):
        company_id_list = ensure_list(company_ref.get("ID", []))
        result["company_id"] = (
            extract_by_type(company_id_list, "Company_Reference_ID") or
            extract_by_type(company_id_list, "Organization_Reference_ID")
        )
        result["company_wid"] = extract_by_type(company_id_list, "WID")
        result["company_name"] = company_ref.get("Descriptor")

    # Parse Cost Center Assignment
    cost_center_ref = org_assignments.get("Cost_Center_Assignment_Reference", {})
    if isinstance(cost_center_ref, dict):
        cost_center_id_list = ensure_list(cost_center_ref.get("ID", []))
        result["cost_center_id"] = (
            extract_by_type(cost_center_id_list, "Cost_Center_Reference_ID") or
            extract_by_type(cost_center_id_list, "Organization_Reference_ID")
        )
        result["cost_center_wid"] = extract_by_type(cost_center_id_list, "WID")
        result["cost_center_name"] = cost_center_ref.get("Descriptor")

    return result


def _first_dict(value: Any) -> Dict[str, Any]:
    """
    Helper to obtain the first non-empty dict from a value that can be a dict or a list of dicts.
    """
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and item:
                return item
    return {}


def _coerce_numeric(value: Any) -> Optional[Union[int, float]]:
    """
    Convert incoming numeric-like values (Decimal, str, etc.) to int/float when possible.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        numeric = float(value)
        return int(numeric) if numeric.is_integer() else numeric
    except (TypeError, ValueError):
        return None


def parse_compensation_data(compensation_data: Dict) -> Dict[str, Any]:
    """
    Parse Requisition Compensation Data.

    Args:
        compensation_data: Requisition Compensation Data from the response

    Returns:
        Dictionary with parsed compensation information
    """
    result = {
        "primary_compensation_basis": None,
        "compensation_package_id": None,
        "compensation_package_wid": None,
        "compensation_package_name": None,
        "compensation_grade_id": None,
        "compensation_grade_wid": None,
        "compensation_grade_name": None,
        "compensation_grade_profile_id": None,
        "compensation_grade_profile_wid": None,
        "compensation_grade_profile_name": None,
        "pay_plan_id": None,
        "pay_plan_wid": None,
        "pay_plan_name": None,
        "pay_rate_amount": None,
        "pay_rate_currency": None,
        "pay_rate_frequency": None
    }

    comp_root = _first_dict(compensation_data)
    if not comp_root:
        if compensation_data:
            logger.debug("Workday job requisition: unexpected compensation payload keys=%s", list(compensation_data.keys()) if isinstance(compensation_data, dict) else type(compensation_data))
        return result

    result["primary_compensation_basis"] = _coerce_numeric(comp_root.get("Primary_Compensation_Basis"))

    # Parse Compensatable Guidelines Data
    guidelines_data = _first_dict(comp_root.get("Compensatable_Guidelines_Data"))
    if guidelines_data:
        package_ref = _first_dict(guidelines_data.get("Compensation_Package_Reference"))
        package_ids = ensure_list(package_ref.get("ID", [])) if package_ref else []
        result["compensation_package_id"] = extract_by_type(package_ids, "Compensation_Package_ID")
        result["compensation_package_wid"] = extract_by_type(package_ids, "WID")
        result["compensation_package_name"] = package_ref.get("Descriptor") if package_ref else None

        grade_ref = _first_dict(guidelines_data.get("Compensation_Grade_Reference"))
        grade_ids = ensure_list(grade_ref.get("ID", [])) if grade_ref else []
        result["compensation_grade_id"] = extract_by_type(grade_ids, "Compensation_Grade_ID")
        result["compensation_grade_wid"] = extract_by_type(grade_ids, "WID")
        result["compensation_grade_name"] = grade_ref.get("Descriptor") if grade_ref else None

        profile_ref = _first_dict(guidelines_data.get("Compensation_Grade_Profile_Reference"))
        profile_ids = ensure_list(profile_ref.get("ID", [])) if profile_ref else []
        result["compensation_grade_profile_id"] = extract_by_type(profile_ids, "Compensation_Grade_Profile_ID")
        result["compensation_grade_profile_wid"] = extract_by_type(profile_ids, "WID")
        result["compensation_grade_profile_name"] = profile_ref.get("Descriptor") if profile_ref else None

    # Parse Pay Plan Data
    pay_plan_data = _first_dict(comp_root.get("Pay_Plan_Data"))
    if pay_plan_data:
        pay_plan_sub_list = ensure_list(pay_plan_data.get("Pay_Plan_Sub_Data", []))
        chosen_sub = None
        first_valid_sub = None

        for pay_plan_sub in pay_plan_sub_list:
            if not isinstance(pay_plan_sub, dict):
                continue
            if first_valid_sub is None:
                first_valid_sub = pay_plan_sub
            if pay_plan_sub.get("Amount") is not None:
                chosen_sub = pay_plan_sub
                break

        if chosen_sub is None:
            chosen_sub = first_valid_sub

        if isinstance(chosen_sub, dict):
            plan_ref = _first_dict(chosen_sub.get("Pay_Plan_Reference"))
            plan_ids = ensure_list(plan_ref.get("ID", [])) if plan_ref else []
            result["pay_plan_id"] = extract_by_type(plan_ids, "Compensation_Plan_ID")
            result["pay_plan_wid"] = extract_by_type(plan_ids, "WID")
            result["pay_plan_name"] = plan_ref.get("Descriptor") if plan_ref else None

            if chosen_sub.get("Amount") is not None:
                result["pay_rate_amount"] = _coerce_numeric(chosen_sub.get("Amount"))

            currency_ref = _first_dict(chosen_sub.get("Currency_Reference"))
            currency_ids = ensure_list(currency_ref.get("ID", [])) if currency_ref else []
            currency_id = extract_by_type(currency_ids, "Currency_ID")
            if currency_id:
                result["pay_rate_currency"] = currency_id

            frequency_ref = _first_dict(chosen_sub.get("Frequency_Reference"))
            frequency_ids = ensure_list(frequency_ref.get("ID", [])) if frequency_ref else []
            frequency_id = extract_by_type(frequency_ids, "Frequency_ID")
            if frequency_id:
                result["pay_rate_frequency"] = frequency_id

    return result


def parse_questionnaire_references(questionnaire_data: Dict) -> Dict[str, Any]:
    """
    Parse Questionnaire Reference data.

    Args:
        questionnaire_data: Questionnaire Reference data from the response

    Returns:
        Dictionary with parsed questionnaire information
    """
    result = {
        "internal_questionnaire_id": None,
        "internal_questionnaire_wid": None,
        "internal_questionnaire_name": None,
        "external_questionnaire_id": None,
        "external_questionnaire_wid": None,
        "external_questionnaire_name": None
    }

    if not questionnaire_data or not isinstance(questionnaire_data, dict):
        return result

    # Internal Career Site Questionnaire
    internal_ref = questionnaire_data.get("Questionnaire_for_Internal_Career_Site_Reference", {})
    if isinstance(internal_ref, dict):
        internal_id_list = ensure_list(internal_ref.get("ID", []))
        result["internal_questionnaire_id"] = extract_by_type(internal_id_list, "Questionnaire_ID")
        result["internal_questionnaire_wid"] = extract_by_type(internal_id_list, "WID")
        result["internal_questionnaire_name"] = internal_ref.get("Descriptor")

    # External Career Site Questionnaire
    external_ref = questionnaire_data.get("Questionnaire_for_External_Career_Site_Reference", {})
    if isinstance(external_ref, dict):
        external_id_list = ensure_list(external_ref.get("ID", []))
        result["external_questionnaire_id"] = extract_by_type(external_id_list, "Questionnaire_ID")
        result["external_questionnaire_wid"] = extract_by_type(external_id_list, "WID")
        result["external_questionnaire_name"] = external_ref.get("Descriptor")

    return result


def parse_qualifications_data(qualifications_data: Union[List, Dict, None]) -> Dict[str, List[str]]:
    """
    Parse Qualifications data (competencies, certifications, education, etc.).

    Args:
        qualifications_data: Qualifications data from the response

    Returns:
        Dictionary with lists of qualifications
    """
    result = {
        "competencies": [],
        "certifications": [],
        "education_requirements": [],
        "language_skills": [],
        "work_experience": [],
        "training_requirements": []
    }

    if not qualifications_data:
        return result

    # Parse Competency_Data (can be list or dict)
    competency_data = qualifications_data.get("Competency_Data") if isinstance(qualifications_data, dict) else None
    if competency_data:
        if isinstance(competency_data, dict):
            competency_data = [competency_data]

        for comp_item in competency_data:
            if isinstance(comp_item, dict):
                # Navigate to Competency_Profile_Data
                profile_data = comp_item.get("Competency_Profile_Data", {})
                if isinstance(profile_data, dict):
                    comp_ref = profile_data.get("Competency_Reference", {})
                    if isinstance(comp_ref, dict):
                        # Try to get ID with type Competency_ID
                        id_list = ensure_list(comp_ref.get("ID", []))
                        competency_name = extract_by_type(id_list, "Competency_ID")
                        if not competency_name:
                            # Fallback to Descriptor
                            competency_name = comp_ref.get("Descriptor")
                        if competency_name:
                            result["competencies"].append(competency_name)

    # Parse Training_Data (can be list or dict)
    training_data = qualifications_data.get("Training_Data") if isinstance(qualifications_data, dict) else None
    if training_data:
        if isinstance(training_data, dict):
            training_data = [training_data]

        for train_item in training_data:
            if isinstance(train_item, dict):
                # Navigate to Training_Profile_Data
                profile_data = train_item.get("Training_Profile_Data", {})
                if isinstance(profile_data, dict):
                    training_name = profile_data.get("Training_Name")
                    if training_name:
                        result["training_requirements"].append(training_name)

    # Parse Certification_Data
    cert_data = qualifications_data.get("Certification_Data") if isinstance(qualifications_data, dict) else None
    if cert_data:
        if isinstance(cert_data, dict):
            cert_data = [cert_data]

        for cert_item in cert_data:
            if isinstance(cert_item, dict):
                cert_ref = cert_item.get("Certification_Reference", {})
                if isinstance(cert_ref, dict):
                    cert_name = cert_ref.get("Descriptor")
                    if not cert_name:
                        id_list = ensure_list(cert_ref.get("ID", []))
                        cert_name = extract_by_type(id_list, "Certification_ID")
                    if cert_name:
                        result["certifications"].append(cert_name)

    # Parse Education_Data
    edu_data = qualifications_data.get("Education_Data") if isinstance(qualifications_data, dict) else None
    if edu_data:
        if isinstance(edu_data, dict):
            edu_data = [edu_data]

        for edu_item in edu_data:
            if isinstance(edu_item, dict):
                edu_ref = edu_item.get("Education_Reference") or edu_item.get("Education_Level_Reference", {})
                if isinstance(edu_ref, dict):
                    edu_name = edu_ref.get("Descriptor")
                    if edu_name:
                        result["education_requirements"].append(edu_name)

    # Parse Language_Data
    lang_data = qualifications_data.get("Language_Data") if isinstance(qualifications_data, dict) else None
    if lang_data:
        if isinstance(lang_data, dict):
            lang_data = [lang_data]

        for lang_item in lang_data:
            if isinstance(lang_item, dict):
                lang_ref = lang_item.get("Language_Reference", {})
                if isinstance(lang_ref, dict):
                    lang_name = lang_ref.get("Descriptor")
                    if lang_name:
                        result["language_skills"].append(lang_name)

    return result


def parse_job_requisition_data(job_requisition: Dict) -> Dict[str, Any]:
    """
    Parse complete Job Requisition data from Workday response.

    Args:
        job_requisition: Job Requisition data from Get_Job_Requisitions response

    Returns:
        Dictionary with all parsed job requisition information
    """
    if not job_requisition or not isinstance(job_requisition, dict):
        return {}

    # Extract Job Requisition Reference
    jr_reference = job_requisition.get("Job_Requisition_Reference", {})
    jr_ref_data = parse_job_requisition_reference(jr_reference)

    # Extract Job Requisition Data
    jr_data = job_requisition.get("Job_Requisition_Data", {})
    if not isinstance(jr_data, dict):
        jr_data = {}

    # Parse Job Requisition Status
    status_ref = jr_data.get("Job_Requisition_Status_Reference", {})
    status_id_list = ensure_list(status_ref.get("ID", [])) if isinstance(status_ref, dict) else []
    # Get status from ID if Descriptor is not available
    status_value = status_ref.get("Descriptor") if isinstance(status_ref, dict) else None
    if not status_value:
        status_value = extract_by_type(status_id_list, "Job_Requisition_Status_ID")

    # Parse Job Requisition Detail/Definition Data
    detail_data = jr_data.get("Job_Requisition_Detail_Data", {})
    if not isinstance(detail_data, dict):
        # Try alternative name
        detail_data = jr_data.get("Job_Requisition_Definition_Data", {})
        if not isinstance(detail_data, dict):
            detail_data = {}

    # Parse Hiring Requirement Data (note: singular, not plural)
    hiring_data = jr_data.get("Hiring_Requirement_Data", {})
    if not isinstance(hiring_data, dict):
        # Try alternative plural name for compatibility
        hiring_data = jr_data.get("Hiring_Requirements_Data", {})
        if not isinstance(hiring_data, dict):
            hiring_data = {}

    # Parse references from hiring data
    job_profile_data = parse_job_profile_data(hiring_data.get("Job_Profile_Reference", {}))
    worker_type_data = parse_worker_type_data(hiring_data.get("Worker_Type_Reference", {}))

    primary_location_ref = hiring_data.get("Primary_Location_Reference", {})
    primary_location_id_list = ensure_list(primary_location_ref.get("ID", [])) if isinstance(primary_location_ref, dict) else []
    primary_location_data = {
        "primary_location_id": extract_by_type(primary_location_id_list, "Location_ID"),
        "primary_location_wid": extract_by_type(primary_location_id_list, "WID"),
        "primary_location_name": primary_location_ref.get("Descriptor") if isinstance(primary_location_ref, dict) else None,
    }

    # Supervisory Organization is at the root level of Job_Requisition_Data
    supervisory_org_data = parse_supervisory_organization_data(
        jr_data.get("Supervisory_Organization_Reference", {})
    )

    # Position is in Position_Data at the root level
    position_data_obj = jr_data.get("Position_Data", {})
    if isinstance(position_data_obj, dict):
        position_data = parse_position_data(position_data_obj.get("Position_Reference", {}))
    else:
        position_data = {}

    # Parse Time Type
    time_type_ref = hiring_data.get("Time_Type_Reference", {})
    time_type_id_list = ensure_list(time_type_ref.get("ID", [])) if isinstance(time_type_ref, dict) else []

    # Parse Job Family
    job_family_ref = hiring_data.get("Job_Family_Reference", {})
    job_family_id_list = ensure_list(job_family_ref.get("ID", [])) if isinstance(job_family_ref, dict) else []

    # Parse Employment Type
    employment_type_ref = hiring_data.get("Employment_Type_Reference", {})
    employment_type_id_list = ensure_list(employment_type_ref.get("ID", [])) if isinstance(employment_type_ref, dict) else []

    # Parse Hiring Manager
    hiring_manager_data = parse_hiring_manager_data(hiring_data.get("Hiring_Manager_Reference", {}))

    # Parse Recruiter (legacy single recruiter field for backward compatibility)
    recruiter_data = parse_recruiter_data(hiring_data.get("Recruiter_Reference", {}))

    # Parse Role Assignment Data (for multiple recruiters)
    raw_role_assignment = jr_data.get("Role_Assignment_Data")
    role_assignment_data = parse_role_assignment_data(raw_role_assignment)
    recruiters_list = role_assignment_data.get("recruiters", [])

    # If no recruiters from Role_Assignment_Data but we have legacy recruiter, use it
    if not recruiters_list and recruiter_data.get("recruiter_id"):
        recruiters_list = [{
            "employee_id": recruiter_data.get("recruiter_id"),
            "wid": recruiter_data.get("recruiter_wid"),
            "name": recruiter_data.get("recruiter_name")
        }]

    # If we have recruiters from Role_Assignment_Data, also populate the single recruiter fields
    # with the first recruiter for backward compatibility
    if recruiters_list and not recruiter_data.get("recruiter_id"):
        first_recruiter = recruiters_list[0]
        recruiter_data = {
            "recruiter_id": first_recruiter.get("employee_id"),
            "recruiter_wid": first_recruiter.get("wid"),
            "recruiter_name": first_recruiter.get("name")
        }

    # Parse Organization Assignments Data
    org_data = jr_data.get("Organization_Data", {})
    org_assignments = {}
    if isinstance(org_data, dict):
        org_assignments = parse_organization_assignments_data(
            org_data.get("Organization_Assignments_Data", {})
        )

    # Parse Compensation Data
    compensation_data = parse_compensation_data(jr_data.get("Requisition_Compensation_Data", {}))

    # Parse Questionnaire References
    questionnaire_data = parse_questionnaire_references(jr_data.get("Questionnaire_Reference", {}))

    # Parse Position Worker Type (Employee Type like Seasonal, Full-time, etc.)
    position_worker_type_ref = hiring_data.get("Position_Worker_Type_Reference", {})
    position_worker_type_id_list = ensure_list(position_worker_type_ref.get("ID", [])) if isinstance(position_worker_type_ref, dict) else []

    # Parse Primary Job Posting Location
    primary_job_posting_location_ref = hiring_data.get("Primary_Job_Posting_Location_Reference", {})
    primary_job_posting_location_data = parse_jr_location_data(primary_job_posting_location_ref)
    # Prefix the keys to avoid collision with location_data
    primary_job_posting_location_prefixed = {
        f"primary_job_posting_{k}": v
        for k, v in primary_job_posting_location_data.items()
    }

    # Parse Job Application Template
    job_app_template_ref = detail_data.get("Job_Application_Template_Reference", {})
    job_app_template_id_list = ensure_list(job_app_template_ref.get("ID", [])) if isinstance(job_app_template_ref, dict) else []

    # Parse Qualifications (try both possible names)
    qual_data = jr_data.get("Qualification_Data") or jr_data.get("Qualifications_Data")
    qualifications = parse_qualifications_data(qual_data)

    # Parse Integration ID Data
    integration_data = parse_integration_id_data(jr_data.get("Integration_ID_Data"))

    effective_date_override = None
    for role_assignment in ensure_list(raw_role_assignment):
        if isinstance(role_assignment, dict):
            effective_date_candidate = role_assignment.get("Effective_Date")
            if effective_date_candidate:
                effective_date_override = effective_date_candidate
                break

    effective_date_value = effective_date_override or jr_data.get("Effective_Date")

    scheduled_weekly_hours_value = None
    scheduled_weekly_hours_raw = hiring_data.get("Scheduled_Weekly_Hours")
    if scheduled_weekly_hours_raw is not None:
        try:
            scheduled_weekly_hours_value = int(float(scheduled_weekly_hours_raw))
        except (ValueError, TypeError):
            scheduled_weekly_hours_value = scheduled_weekly_hours_raw

    parsed_data = {
        **jr_ref_data,
        "job_requisition_status": status_value,
        "job_requisition_status_id": extract_by_type(status_id_list, "Job_Requisition_Status_ID"),
        "job_requisition_status_wid": extract_by_type(status_id_list, "WID"),

        # Job posting details from Detail/Definition Data
        "job_posting_title": detail_data.get("Job_Posting_Title"),
        "job_description": detail_data.get("Job_Description"),
        "recruiting_instructions": detail_data.get("Recruiting_Instructions"),

        # Job Requisition Flags
        "academic_tenure_eligible": detail_data.get("Academic_Tenure_Eligible"),
        "available_for_recruiting": detail_data.get("Available_for_Recruiting"),
        "confidential_job_requisition": detail_data.get("Confidential_Job_Requisition"),
        "spotlight_job": hiring_data.get("Spotlight_Job"),

        # Job Application Template
        "job_application_template_id": extract_by_type(job_app_template_id_list, "Job_Application_Template_Reference_ID"),
        "job_application_template_wid": extract_by_type(job_app_template_id_list, "WID"),
        "job_application_template_name": job_app_template_ref.get("Descriptor") if isinstance(job_app_template_ref, dict) else None,

        # Positions from Detail/Definition Data (note: Number_of_Openings might not exist)
        "number_of_openings": detail_data.get("Number_of_Openings") or detail_data.get("Positions_Allocated"),
        "positions_allocated": detail_data.get("Positions_Allocated"),
        "positions_filled": detail_data.get("Positions_Filled"),
        "positions_available": detail_data.get("Positions_Available"),

        # Dates
        "recruiting_start_date": hiring_data.get("Recruiting_Start_Date"),
        "target_hire_date": hiring_data.get("Target_Hire_Date"),
        "earliest_hire_date": hiring_data.get("Earliest_Hire_Date"),
        "created_date": jr_data.get("Created_Date"),
        "last_updated_date": jr_data.get("Last_Updated_Date"),
        "effective_date": effective_date_value,

        # Job Profile, Worker Type, Location, etc.
        **job_profile_data,
        **worker_type_data,
        **supervisory_org_data,
        **position_data,

        # Position Worker Type (Employee Type)
        "position_worker_type_id": extract_by_type(position_worker_type_id_list, "Employee_Type_ID"),
        "position_worker_type_wid": extract_by_type(position_worker_type_id_list, "WID"),
        "position_worker_type_name": position_worker_type_ref.get("Descriptor") if isinstance(position_worker_type_ref, dict) else None,

        # Primary Job Posting Location
        **primary_job_posting_location_prefixed,
        **primary_location_data,

        # Time Type (can be Position_Time_Type_ID or Time_Type_ID)
        "time_type_id": extract_by_type(time_type_id_list, "Position_Time_Type_ID") or extract_by_type(time_type_id_list, "Time_Type_ID"),
        "time_type_wid": extract_by_type(time_type_id_list, "WID"),
        "time_type_name": time_type_ref.get("Descriptor") if isinstance(time_type_ref, dict) else None,

        # Scheduled Weekly Hours
        "scheduled_weekly_hours": scheduled_weekly_hours_value,

        # Job Family
        "job_family_id": extract_by_type(job_family_id_list, "Job_Family_ID"),
        "job_family_name": job_family_ref.get("Descriptor") if isinstance(job_family_ref, dict) else None,

        # Employment Type
        "employment_type_id": extract_by_type(employment_type_id_list, "Employment_Type_ID"),
        "employment_type_name": employment_type_ref.get("Descriptor") if isinstance(employment_type_ref, dict) else None,

        # Hiring Manager and Recruiter (single for backward compatibility)
        **hiring_manager_data,
        **recruiter_data,

        # Recruiters (multiple from Role_Assignment_Data)
        "recruiters": recruiters_list,

        # Organization Assignments
        **org_assignments,

        # Compensation Data
        **compensation_data,

        # Questionnaires
        **questionnaire_data,

        # Posting Information from Detail/Definition Data
        "is_posted": detail_data.get("Is_Posted"),
        "posting_date": detail_data.get("Posting_Date"),
        "removal_date": detail_data.get("Removal_Date"),

        # Qualifications
        **qualifications,

        # Integration IDs
        **integration_data
    }

    return parsed_data


__all__ = [
    "parse_job_requisition_data",
    "parse_job_requisition_reference",
    "parse_job_profile_data",
    "parse_worker_type_data",
    "parse_jr_location_data",
    "parse_supervisory_organization_data",
    "parse_position_data",
    "parse_hiring_manager_data",
    "parse_recruiter_data",
    "parse_role_assignment_data",
    "parse_organization_assignments_data",
    "parse_compensation_data",
    "parse_questionnaire_references",
    "parse_qualifications_data",
    "parse_integration_id_data",
    "extract_by_type",
    "safe_get_nested"
]
