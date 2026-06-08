from typing import Dict, Any, Optional
from datetime import date, datetime


def to_date_string(value: Any) -> Optional[str]:
    """Convert datetime/date objects to ISO format string (YYYY-MM-DD)"""
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, str):
        return value
    return str(value)


def extract_id_by_type(id_list: Any, id_type: str) -> Optional[str]:
    """Helper function to extract ID value by type from ID list"""
    if not id_list:
        return None

    if isinstance(id_list, dict):
        if id_list.get("type") == id_type:
            return id_list.get("_value_1")
        return None

    if isinstance(id_list, list):
        for id_item in id_list:
            if isinstance(id_item, dict) and id_item.get("type") == id_type:
                return id_item.get("_value_1")

    return None


def safe_get_dict(data: Any, key: str, default: Any = None) -> Any:
    """
    Safely get a value from data, handling cases where data might be a list.
    If data is a list, try to get from the first dict item.
    """
    if default is None:
        default = {}

    if not data:
        return default

    if isinstance(data, dict):
        result = data.get(key, default)
        # If result is a list with one dict item, return that dict
        if isinstance(result, list) and len(result) == 1 and isinstance(result[0], dict):
            return result[0]
        # If result is a list but we expected a dict, return default
        if isinstance(result, list) and not isinstance(default, list):
            return default
        return result if result is not None else default

    if isinstance(data, list) and data and isinstance(data[0], dict):
        result = data[0].get(key, default)
        # If result is a list with one dict item, return that dict
        if isinstance(result, list) and len(result) == 1 and isinstance(result[0], dict):
            return result[0]
        # If result is a list but we expected a dict, return default
        if isinstance(result, list) and not isinstance(default, list):
            return default
        return result if result is not None else default

    return default


def parse_applicant_reference(applicant_data: Dict[str, Any]) -> Dict[str, Any]:
    """Parse Applicant Reference data"""
    parsed = {}
    
    if not applicant_data:
        return parsed
    
    applicant_ref = applicant_data.get("Applicant_Reference", {})
    if applicant_ref:
        ids = applicant_ref.get("ID", [])
        parsed["applicant_id"] = extract_id_by_type(ids, "Applicant_ID")
        parsed["applicant_wid"] = extract_id_by_type(ids, "WID")
    
    return parsed


def parse_applicant_personal_data(applicant_data: Dict[str, Any]) -> Dict[str, Any]:
    """Parse Personal Data for Applicant"""
    parsed = {}
    
    if not applicant_data:
        return parsed
    
    personal_data = applicant_data.get("Personal_Data", {})
    if not personal_data:
        return parsed
    
    # Name data
    name_data = safe_get_dict(personal_data, "Name_Data", {})
    if name_data and isinstance(name_data, dict):
        legal_name_data = safe_get_dict(name_data, "Legal_Name_Data", {})
        if isinstance(legal_name_data, dict):
            legal_name_detail = safe_get_dict(legal_name_data, "Name_Detail_Data", {})
            if isinstance(legal_name_detail, dict):
                parsed["first_name"] = legal_name_detail.get("First_Name")
                parsed["middle_name"] = legal_name_detail.get("Middle_Name")
                parsed["last_name"] = legal_name_detail.get("Last_Name")
                parsed["formatted_name"] = legal_name_detail.get("Formatted_Name")

        preferred_name_data = safe_get_dict(name_data, "Preferred_Name_Data", {})
        if isinstance(preferred_name_data, dict):
            preferred_name_detail = safe_get_dict(preferred_name_data, "Name_Detail_Data", {})
            if isinstance(preferred_name_detail, dict):
                parsed["preferred_name"] = preferred_name_detail.get("Formatted_Name")
    
    # Birth date - can be in Personal_Data or Personal_Information_Data
    birth_date_raw = personal_data.get("Birth_Date")
    if not birth_date_raw:
        personal_info_data = personal_data.get("Personal_Information_Data", {})
        if isinstance(personal_info_data, list):
            personal_info_data = personal_info_data[0] if personal_info_data else {}
        birth_date_raw = personal_info_data.get("Birth_Date")
    parsed["birth_date"] = to_date_string(birth_date_raw)
    
    # Tobacco use
    parsed["tobacco_use"] = personal_data.get("Tobacco_Use")
    
    # Gender - can be in multiple places
    gender_ref = personal_data.get("Gender_Reference", {})
    if gender_ref:
        parsed["gender"] = gender_ref.get("Descriptor")
    
    # Try to get gender from Personal_Information_Data if not found above
    if not parsed.get("gender"):
        personal_info_data = personal_data.get("Personal_Information_Data", {})
        if isinstance(personal_info_data, list):
            personal_info_data = personal_info_data[0] if personal_info_data else {}
        
        for_country_data = personal_info_data.get("Personal_Information_For_Country_Data", {})
        if isinstance(for_country_data, list):
            for_country_data = for_country_data[0] if for_country_data else {}
        
        country_personal_data = for_country_data.get("Country_Personal_Information_Data", {})
        if isinstance(country_personal_data, list):
            country_personal_data = country_personal_data[0] if country_personal_data else {}
        
        if country_personal_data:
            gender_ref = country_personal_data.get("Gender_Reference", {})
            if gender_ref:
                # Extract gender from ID list
                gender_ids = gender_ref.get("ID", [])
                parsed["gender"] = extract_id_by_type(gender_ids, "Gender_Code") or gender_ref.get("Descriptor")
            
            # Also get ethnicity from here if available
            ethnicity_refs = country_personal_data.get("Ethnicity_Reference", [])
            if ethnicity_refs:
                if isinstance(ethnicity_refs, list) and ethnicity_refs and isinstance(ethnicity_refs[0], dict):
                    parsed["ethnicity"] = ethnicity_refs[0].get("Descriptor")
                elif isinstance(ethnicity_refs, dict):
                    parsed["ethnicity"] = ethnicity_refs.get("Descriptor")
            
            # Hispanic or Latino
            hispanic = country_personal_data.get("Hispanic_or_Latino")
            if hispanic is not None:
                parsed["hispanic_or_latino"] = bool(int(hispanic)) if isinstance(hispanic, str) else bool(hispanic)
    
    # Ethnicity (if not already set from Personal_Information_Data)
    if not parsed.get("ethnicity"):
        ethnicity_ref = personal_data.get("Ethnicity_Reference", {})
        if ethnicity_ref:
            parsed["ethnicity"] = ethnicity_ref.get("Descriptor")
    
    # Hispanic or Latino (if not already set)
    if parsed.get("hispanic_or_latino") is None:
        hispanic = personal_data.get("Hispanic_or_Latino")
        if hispanic is not None:
            parsed["hispanic_or_latino"] = bool(int(hispanic)) if isinstance(hispanic, str) else bool(hispanic)
    
    return parsed


def parse_applicant_contact_data(applicant_data: Dict[str, Any]) -> Dict[str, Any]:
    """Parse Contact Information for Applicant"""
    parsed = {}
    
    if not applicant_data:
        return parsed
    
    # Contact_Data is inside Personal_Data
    personal_data = applicant_data.get("Personal_Data", {})
    if not personal_data:
        return parsed
    
    contact_data = personal_data.get("Contact_Data", {})
    if not contact_data:
        return parsed
    
    # Email addresses - Parse personal vs corporate emails based on Public attribute
    emails = []
    personal_email = None
    corporate_email = None
    email_usage_public = None
    email_id = None
    
    email_data_list = contact_data.get("Email_Address_Data", [])
    if isinstance(email_data_list, dict):
        email_data_list = [email_data_list]

    for email_data in email_data_list:
        # Skip if email_data is not a dict
        if not isinstance(email_data, dict):
            continue

        email_address = email_data.get("Email_Address")
        if email_address:
            emails.append(email_address)
            
            # Check Usage_Data for Public attribute
            usage_data_list = email_data.get("Usage_Data", [])
            if isinstance(usage_data_list, dict):
                usage_data_list = [usage_data_list]

            is_public = False
            if usage_data_list and isinstance(usage_data_list[0], dict):
                is_public = bool(usage_data_list[0].get("Public"))
            
            # Assign based on Public attribute
            if is_public:  # Public=1 means corporate/work email
                corporate_email = email_address
            else:  # Public=0 means personal email
                personal_email = email_address
    
    # Keep original logic for backward compatibility - use first email as primary
    if emails:
        parsed["email"] = emails[0]
        # Get usage data and email_id from first email
        first_email_data = email_data_list[0] if email_data_list else {}
        if isinstance(first_email_data, dict):
            usage_data_list = first_email_data.get("Usage_Data", [])
            if isinstance(usage_data_list, dict):
                usage_data_list = [usage_data_list]
            if usage_data_list and isinstance(usage_data_list[0], dict):
                email_usage_public = bool(usage_data_list[0].get("Public"))
            email_id = first_email_data.get("ID")
    
    parsed["emails"] = emails if emails else None
    parsed["personal_email"] = personal_email
    parsed["corporate_email"] = corporate_email
    parsed["email_usage_public"] = email_usage_public
    parsed["email_id"] = email_id
    
    # Phone numbers
    phones = []
    phone_data_list = contact_data.get("Phone_Data", [])
    if isinstance(phone_data_list, dict):
        phone_data_list = [phone_data_list]

    for phone_data in phone_data_list:
        # Skip if phone_data is not a dict
        if not isinstance(phone_data, dict):
            continue

        # Try different phone number formats in order of preference
        phone_number = (
            phone_data.get("Tenant_Formatted_Phone") or
            phone_data.get("International_Formatted_Phone") or
            phone_data.get("National_Formatted_Phone") or
            phone_data.get("E164_Formatted_Phone") or
            phone_data.get("Phone_Number")
        )
        if phone_number:
            phones.append(phone_number)
            if not parsed.get("phone"):  # Set primary phone
                parsed["phone"] = phone_number
    
    parsed["phones"] = phones if phones else None
    
    # Address
    address_data_list = contact_data.get("Address_Data", [])
    if isinstance(address_data_list, dict):
        address_data_list = [address_data_list]

    if address_data_list:
        # Get primary address
        primary_address = address_data_list[0]
        if isinstance(primary_address, dict):
            parsed["address"] = primary_address.get("Formatted_Address")
            parsed["address_city"] = primary_address.get("Municipality")
            parsed["address_state"] = primary_address.get("Country_Region_Descriptor")
            parsed["address_postal_code"] = primary_address.get("Postal_Code")

            country_ref = primary_address.get("Country_Reference", {})
            if isinstance(country_ref, dict):
                parsed["address_country"] = country_ref.get("Descriptor")
    
    return parsed


def parse_applicant_recruitment_data(applicant_data: Dict[str, Any]) -> Dict[str, Any]:
    """Parse Recruitment specific data for Applicant"""
    parsed = {}
    
    if not applicant_data:
        return parsed
    
    # Job Application Data
    job_app_data = safe_get_dict(applicant_data, "Job_Application_Data", {})
    if job_app_data and isinstance(job_app_data, dict):
        # Job Requisition
        job_req_ref = safe_get_dict(job_app_data, "Job_Requisition_Reference", {})
        if job_req_ref and isinstance(job_req_ref, dict):
            ids = job_req_ref.get("ID", [])
            parsed["job_requisition_id"] = extract_id_by_type(ids, "Job_Requisition_ID")
            parsed["job_requisition_title"] = job_req_ref.get("Descriptor")

        # Application date
        parsed["application_date"] = to_date_string(job_app_data.get("Applied_Date"))

        # Candidate status
        status_ref = safe_get_dict(job_app_data, "Candidate_Status_Reference", {})
        if status_ref and isinstance(status_ref, dict):
            parsed["candidate_status"] = status_ref.get("Descriptor")

        # Candidate stage
        stage_ref = safe_get_dict(job_app_data, "Recruiting_Step_Reference", {})
        if stage_ref and isinstance(stage_ref, dict):
            parsed["candidate_stage"] = stage_ref.get("Descriptor")

        # Source
        source_ref = safe_get_dict(job_app_data, "Job_Application_Source_Reference", {})
        if source_ref and isinstance(source_ref, dict):
            parsed["source"] = source_ref.get("Descriptor")

        # Recruiter
        recruiter_ref = safe_get_dict(job_app_data, "Recruiter_Reference", {})
        if recruiter_ref and isinstance(recruiter_ref, dict):
            ids = recruiter_ref.get("ID", [])
            parsed["recruiter_id"] = extract_id_by_type(ids, "Employee_ID")
            parsed["recruiter_name"] = recruiter_ref.get("Descriptor")
    
    # Pre-hire data
    pre_hire_data = safe_get_dict(applicant_data, "Pre-Hire_Data", {})
    if pre_hire_data and isinstance(pre_hire_data, dict):
        parsed["is_pre_hire"] = True
        parsed["expected_hire_date"] = to_date_string(pre_hire_data.get("Expected_Hire_Date"))
        parsed["original_hire_date"] = to_date_string(pre_hire_data.get("Original_Hire_Date"))

        # Position
        position_ref = safe_get_dict(pre_hire_data, "Position_Reference", {})
        if position_ref and isinstance(position_ref, dict):
            parsed["position_title"] = position_ref.get("Descriptor")

        parsed["business_title"] = pre_hire_data.get("Business_Title")
    else:
        parsed["is_pre_hire"] = False
    
    return parsed


def parse_applicant_organization_data(applicant_data: Dict[str, Any]) -> Dict[str, Any]:
    """Parse Organization/Location data for Applicant"""
    parsed = {}
    
    if not applicant_data:
        return parsed
    
    # This might be in different places depending on pre-hire status
    position_data = safe_get_dict(applicant_data, "Position_Data", {})
    if not position_data or not isinstance(position_data, dict):
        position_data = safe_get_dict(applicant_data, "Pre-Hire_Data", {})

    if position_data and isinstance(position_data, dict):
        # Location
        location_ref = safe_get_dict(position_data, "Location_Reference", {})
        if location_ref and isinstance(location_ref, dict):
            ids = location_ref.get("ID", [])
            parsed["location_id"] = extract_id_by_type(ids, "Location_ID")
            parsed["location"] = location_ref.get("Descriptor")

        # Supervisory Organization
        sup_org_ref = safe_get_dict(position_data, "Supervisory_Organization_Reference", {})
        if sup_org_ref and isinstance(sup_org_ref, dict):
            ids = sup_org_ref.get("ID", [])
            parsed["supervisory_organization_id"] = extract_id_by_type(ids, "Organization_Reference_ID")
            parsed["supervisory_organization"] = sup_org_ref.get("Descriptor")

        # Company
        company_ref = safe_get_dict(position_data, "Company_Reference", {})
        if company_ref and isinstance(company_ref, dict):
            ids = company_ref.get("ID", [])
            parsed["company_id"] = extract_id_by_type(ids, "Company_Reference_ID")
            parsed["company"] = company_ref.get("Descriptor")

        # Cost Center
        cost_center_ref = safe_get_dict(position_data, "Cost_Center_Reference", {})
        if cost_center_ref and isinstance(cost_center_ref, dict):
            ids = cost_center_ref.get("ID", [])
            parsed["cost_center_id"] = extract_id_by_type(ids, "Cost_Center_Reference_ID")
            parsed["cost_center"] = cost_center_ref.get("Descriptor")
    
    return parsed


def parse_applicant_education_data(applicant_data: Dict[str, Any]) -> Dict[str, Any]:
    """Parse Education data for Applicant"""
    parsed = {}
    
    if not applicant_data:
        return parsed
    
    education_data = applicant_data.get("Education_Data", {})
    if not education_data:
        return parsed
    
    # Highest education level
    highest_ed_ref = education_data.get("Highest_Level_of_Education_Reference", {})
    if highest_ed_ref:
        parsed["highest_education_level"] = highest_ed_ref.get("Descriptor")
    
    # Schools
    schools = []
    school_data_list = education_data.get("School_Data", [])
    if isinstance(school_data_list, dict):
        school_data_list = [school_data_list]

    for school_data in school_data_list:
        if not isinstance(school_data, dict):
            continue
        school_ref = school_data.get("School_Reference", {})
        if isinstance(school_ref, dict):
            school_name = school_ref.get("Descriptor")
            if school_name:
                schools.append(school_name)
    
    parsed["schools"] = schools if schools else None
    
    return parsed


def parse_applicant_experience_data(applicant_data: Dict[str, Any]) -> Dict[str, Any]:
    """Parse Experience data for Applicant"""
    parsed = {}
    
    if not applicant_data:
        return parsed
    
    experience_data = applicant_data.get("Experience_Data", {})
    if not experience_data:
        return parsed
    
    # Years of experience
    parsed["years_of_experience"] = experience_data.get("Years_of_Experience")
    
    # Previous employers
    employers = []
    work_exp_list = experience_data.get("Work_Experience_Data", [])
    if isinstance(work_exp_list, dict):
        work_exp_list = [work_exp_list]

    for work_exp in work_exp_list:
        if not isinstance(work_exp, dict):
            continue
        company = work_exp.get("Company")
        if company:
            employers.append(company)
    
    parsed["previous_employers"] = employers if employers else None
    
    return parsed


def parse_applicant_skills_data(applicant_data: Dict[str, Any]) -> Dict[str, Any]:
    """Parse Skills and Competencies data for Applicant"""
    parsed = {}
    
    if not applicant_data:
        return parsed
    
    # Skills
    skills = []
    skill_data_list = applicant_data.get("Skill_Data", [])
    if isinstance(skill_data_list, dict):
        skill_data_list = [skill_data_list]

    for skill_data in skill_data_list:
        if not isinstance(skill_data, dict):
            continue
        skill_ref = skill_data.get("Skill_Reference", {})
        if isinstance(skill_ref, dict):
            skill_name = skill_ref.get("Descriptor")
            if skill_name:
                skills.append(skill_name)
    
    parsed["skills"] = skills if skills else None
    
    # Competencies - store as list of dicts with more details
    competencies = []
    comp_data_list = applicant_data.get("Competency_Data", [])
    if isinstance(comp_data_list, dict):
        comp_data_list = [comp_data_list]

    for comp_data in comp_data_list:
        if not isinstance(comp_data, dict):
            continue
        comp_ref = comp_data.get("Competency_Reference", {})
        if isinstance(comp_ref, dict):
            competency = {
                "name": comp_ref.get("Descriptor"),
                "proficiency": comp_data.get("Proficiency_Level")
            }
            competencies.append(competency)
    
    parsed["competencies"] = competencies if competencies else None
    
    return parsed


def parse_applicant_identification_data(applicant_data: Dict[str, Any]) -> Dict[str, Any]:
    """Parse Identification data for Applicant"""
    parsed = {}
    
    if not applicant_data:
        return parsed
    
    # Identification_Data is inside Personal_Data
    personal_data = applicant_data.get("Personal_Data", {})
    if not personal_data:
        return parsed
    
    id_data = personal_data.get("Identification_Data", {})
    if not id_data:
        return parsed
    
    # National ID - can be in National_ID list or National_ID_Data
    national_id_list = id_data.get("National_ID", [])
    if isinstance(national_id_list, dict):
        national_id_list = [national_id_list]
    
    if national_id_list:
        primary_nat_id = national_id_list[0]
        if isinstance(primary_nat_id, dict):
            nat_id_data = primary_nat_id.get("National_ID_Data", {})
            if isinstance(nat_id_data, dict):
                parsed["national_id"] = nat_id_data.get("ID")

                id_type_ref = nat_id_data.get("ID_Type_Reference", {})
                if isinstance(id_type_ref, dict):
                    parsed["national_id_type"] = id_type_ref.get("Descriptor")
    
    # Passport - can be in Passport_ID list or Passport_Data
    passport_list = id_data.get("Passport_ID", [])
    if isinstance(passport_list, dict):
        passport_list = [passport_list]
    
    if passport_list:
        primary_passport = passport_list[0]
        if isinstance(primary_passport, dict):
            passport_data = primary_passport.get("Passport_ID_Data", {})
            if isinstance(passport_data, dict):
                parsed["passport_number"] = passport_data.get("Passport_Number")
    
    # Driver's License
    license_list = id_data.get("License_ID", [])
    if isinstance(license_list, dict):
        license_list = [license_list]
    
    if license_list:
        primary_license = license_list[0]
        if isinstance(primary_license, dict):
            license_data = primary_license.get("License_ID_Data", {})
            if isinstance(license_data, dict):
                parsed["license_id"] = license_data.get("ID")
                parsed["license_expiration_date"] = to_date_string(license_data.get("Expiration_Date"))

                # License state
                region_ref = license_data.get("Country_Region_Reference", {})
                if isinstance(region_ref, dict):
                    parsed["license_state"] = region_ref.get("Descriptor")

                # License type
                license_type_ref = license_data.get("ID_Type_Reference", {})
                if isinstance(license_type_ref, dict):
                    parsed["license_type"] = license_type_ref.get("Descriptor")
    
    # Custom IDs (ADP Payroll ID, Associate OID, Old Corporate Email, etc.)
    custom_id_list = id_data.get("Custom_ID", [])
    if isinstance(custom_id_list, dict):
        custom_id_list = [custom_id_list]
    
    for custom_id_item in custom_id_list:
        if not isinstance(custom_id_item, dict):
            continue
        custom_id_data = custom_id_item.get("Custom_ID_Data", {})
        if isinstance(custom_id_data, dict):
            id_type_ref = custom_id_data.get("ID_Type_Reference", {})
            if isinstance(id_type_ref, dict):
                id_type_ids = id_type_ref.get("ID", [])
                id_type = extract_id_by_type(id_type_ids, "Custom_ID_Type_ID")
                id_value = custom_id_data.get("ID")

                # Map custom ID types to fields
                if id_type == "ADP Payroll ID":
                    parsed["adp_payroll_id"] = id_value
                elif id_type == "ADP Payroll Group":
                    parsed["adp_payroll_group"] = id_value
                elif id_type == "Old Corporate Email":
                    parsed["old_corporate_email"] = id_value
                elif id_type == "Associate OID":
                    parsed["associate_oid"] = id_value
                elif id_type == "ICIMS ID":
                    parsed["icims_id"] = id_value
                elif id_type == "MSO Dealer Code":
                    parsed["mso_dealer_code"] = id_value
                elif id_type == "NetSuite Internal ID":
                    parsed["netsuite_internal_id"] = id_value
    
    return parsed


def parse_applicant_background_check_data(applicant_data: Dict[str, Any]) -> Dict[str, Any]:
    """Parse Background Check data for Applicant"""
    parsed = {}
    
    if not applicant_data:
        return parsed
    
    bg_check_data = safe_get_dict(applicant_data, "Background_Check_Data", {})
    if not bg_check_data or not isinstance(bg_check_data, dict):
        return parsed

    # Background check status
    status_ref = safe_get_dict(bg_check_data, "Background_Check_Status_Reference", {})
    if status_ref and isinstance(status_ref, dict):
        parsed["background_check_status"] = status_ref.get("Descriptor")

    parsed["background_check_date"] = to_date_string(bg_check_data.get("Background_Check_Date"))
    
    return parsed


def parse_applicant_document_data(applicant_data: Dict[str, Any]) -> Dict[str, Any]:
    """Parse Document/Attachment data for Applicant"""
    parsed = {}
    
    if not applicant_data:
        return parsed
    
    # Check for resume
    documents = []
    document_data_list = applicant_data.get("Attachment_Data", [])
    if isinstance(document_data_list, dict):
        document_data_list = [document_data_list]

    for doc_data in document_data_list:
        # Skip if doc_data is not a dict
        if not isinstance(doc_data, dict):
            continue

        doc_category_ref = safe_get_dict(doc_data, "Document_Category_Reference", {})
        if doc_category_ref and isinstance(doc_category_ref, dict):
            doc_type = doc_category_ref.get("Descriptor")
            if doc_type:
                documents.append(doc_type)

                # Check if it's a resume
                if "resume" in doc_type.lower() or "cv" in doc_type.lower():
                    parsed["resume_attached"] = True
    
    parsed["documents"] = documents if documents else None
    
    if "resume_attached" not in parsed:
        parsed["resume_attached"] = False
    
    return parsed 