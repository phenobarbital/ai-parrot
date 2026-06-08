# workday/parsers/worker_parsers.py

from typing import Any, Dict, List, Optional
import re
import base64
import os
from pathlib import Path
import logging

from ..utils import extract_by_type, first, ensure_list

logger = logging.getLogger(__name__)


def save_worker_document(file_content_base64: str, filename: str, worker_id: str, storage_path: Optional[str] = None) -> Optional[str]:
    """
    Save worker document file from base64 content to disk.

    Args:
        file_content_base64: Base64 encoded file content
        filename: Original filename
        worker_id: Worker/Employee ID for organizing files
        storage_path: Base directory path to save files (defaults to /tmp/workday_worker_documents)
                     Files will be saved to: {storage_path}/{worker_id}/{filename}

    Returns:
        Path to saved file or None if failed
    """
    if not file_content_base64 or not filename or not worker_id:
        return None

    try:
        # Check if content is already bytes (decoded) or string (base64 encoded)
        if isinstance(file_content_base64, bytes):
            # Already decoded binary content
            print(f"🔍 Content is already binary ({len(file_content_base64)} bytes) for {filename}")
            file_content = file_content_base64
        else:
            # Base64 string that needs decoding
            base64_length = len(file_content_base64)
            print(f"🔍 Base64 content length: {base64_length} chars for {filename}")

            # Decode base64
            file_content = base64.b64decode(file_content_base64)

        # Create storage directory: {storage_path}/{worker_id}/
        if not storage_path:
            storage_path = "/tmp/workday_worker_documents"

        storage_dir = Path(storage_path) / worker_id
        storage_dir.mkdir(parents=True, exist_ok=True)

        # Sanitize filename to avoid path traversal
        safe_filename = os.path.basename(filename)

        # Save file
        file_path = storage_dir / safe_filename
        with open(file_path, 'wb') as f:
            f.write(file_content)

        # Get file size for logging
        file_size_kb = len(file_content) / 1024
        print(f"✅ Saved document: {safe_filename} ({file_size_kb:.1f} KB) -> {file_path}")

        # Show first bytes to verify file header
        if len(file_content) > 4:
            header = file_content[:4]
            print(f"🔍 File header: {header}")

        return str(file_path)
    except Exception as e:
        print(f"❌ Error saving document {filename} for worker {worker_id}: {e}")
        import traceback
        traceback.print_exc()
        return None


def format_phone_number(phone_raw: Optional[str]) -> Dict[str, Optional[str]]:
    """
    Formats a phone number from various formats to the required standards.

    Args:
        phone_raw: Phone number in any format

    Returns:
        Dict with the following fields:
        - phone: Number in E164 format without spaces (e.g. 19392726591)
        - phone_area_code: Area code (e.g. 939)
        - phone_number_wo_area: Number without area code (e.g. 2726591)
        - phone_traditional: Traditional format +X (XXX) XXXXXXX
        - phone_national: National format (XXX) XXX-XXXX
        - phone_international: International format +X XXX-XXX-XXXX
        - phone_tenant: Same as phone_traditional
    """
    if not phone_raw or phone_raw == "None":
        return {
            "phone": None,
            "phone_area_code": None,
            "phone_number_wo_area": None,
            "phone_traditional": None,
            "phone_national": None,
            "phone_international": None,
            "phone_tenant": None,
        }

    # Clean the number: extract only digits, keep extensions
    phone_str = str(phone_raw).strip()

    # Detect and separate extension
    extension = None
    ext_patterns = [r'\s*x\s*(\d+)', r'\s*ext\.?\s*(\d+)', r'\s*extension\s*(\d+)']
    for pattern in ext_patterns:
        match = re.search(pattern, phone_str, re.IGNORECASE)
        if match:
            extension = match.group(1)
            phone_str = phone_str[:match.start()]
            break

    # Extract only digits from the base number
    digits = re.sub(r'\D', '', phone_str)

    if not digits:
        return {
            "phone": None,
            "phone_area_code": None,
            "phone_number_wo_area": None,
            "phone_traditional": None,
            "phone_national": None,
            "phone_international": None,
            "phone_tenant": None,
        }

    # Determine country and format
    country_code = None
    area_code = None
    local_number = None

    # Case 1: US/Canada numbers (country code 1)
    # Format: 1 + 3 area digits + 7 local digits = 11 digits
    if len(digits) == 11 and digits[0] == '1':
        country_code = '1'
        area_code = digits[1:4]
        local_number = digits[4:11]
        # Check if extension is the duplicated area code
        if extension == area_code:
            extension = None
    elif len(digits) == 10:
        # Assume US/Canada without country code
        country_code = '1'
        area_code = digits[0:3]
        local_number = digits[3:10]
        # Check if extension is the duplicated area code
        if extension == area_code:
            extension = None

    # Case 2: Romania numbers (country code 40)
    # Example: 0744589243 or 40744589243
    elif len(digits) == 10 and digits[0] == '0':
        # Romanian national format: 0 + 3 digits + 6 digits
        country_code = '40'
        area_code = digits[1:4]
        local_number = digits[4:10]
    elif len(digits) == 12 and digits[:2] == '40':
        country_code = '40'
        area_code = digits[2:5]
        local_number = digits[5:12]
    elif len(digits) == 11 and digits[0] == '4' and digits[1] == '0':
        country_code = '40'
        area_code = digits[2:5]
        local_number = digits[5:11]

    # Case 3: Guatemala numbers (country code 502)
    # Example: 51656335 or 44580469
    elif len(digits) == 8:
        # 8-digit numbers probably Guatemala
        country_code = '502'
        area_code = digits[0:4]
        local_number = digits[4:8]
    elif len(digits) == 11 and digits[:3] == '502':
        country_code = '502'
        area_code = digits[3:7]
        local_number = digits[7:11]

    # Case 4: India numbers (country code 91)
    # Example: 9980913628
    elif len(digits) == 10 and digits[0] in ['6', '7', '8', '9']:
        # India mobile starts with 6-9
        country_code = '91'
        area_code = digits[0:5]
        local_number = digits[5:10]
    elif len(digits) == 12 and digits[:2] == '91':
        country_code = '91'
        area_code = digits[2:7]
        local_number = digits[7:12]

    # Default case: treat as US number
    else:
        if len(digits) >= 10:
            country_code = '1'
            area_code = digits[-10:-7]
            local_number = digits[-7:]
        else:
            # Number too short, cannot format correctly
            return {
                "phone": digits,
                "phone_area_code": None,
                "phone_number_wo_area": None,
                "phone_traditional": digits,
                "phone_national": digits,
                "phone_international": digits,
                "phone_tenant": digits,
            }

    # Build formats
    phone_e164 = f"{country_code}{area_code}{local_number}"

    # Format numbers by length and country
    if country_code == '1':
        # US/Canada format
        phone_national = f"({area_code}) {local_number[:3]}-{local_number[3:]}"
        phone_international = f"+{country_code} {area_code}-{local_number[:3]}-{local_number[3:]}"
    elif country_code == '40':
        # Romania format
        phone_national = f"0{area_code} {local_number[:3]} {local_number[3:]}"
        phone_international = f"+{country_code} ({area_code}) {local_number[:3]}{local_number[3:]}"
    elif country_code == '502':
        # Guatemala format
        phone_national = f"{area_code} {local_number}"
        phone_international = f"+{country_code} ({area_code}) {local_number}"
    elif country_code == '91':
        # India format
        phone_national = f"0{area_code} {local_number}"
        phone_international = f"+{country_code} ({area_code}) {local_number}"
    else:
        phone_national = f"{area_code}{local_number}"
        phone_international = f"+{country_code} {area_code}{local_number}"

    phone_traditional = f"+{country_code} ({area_code}) {local_number}"
    phone_tenant = phone_traditional

    # Add extension if exists
    if extension:
        ext_suffix = f" x{extension}"
        phone_traditional += ext_suffix
        phone_national += ext_suffix
        phone_international += ext_suffix
        phone_tenant += ext_suffix

    return {
        "phone": phone_e164,
        "phone_area_code": area_code,
        "phone_number_wo_area": local_number,
        "phone_traditional": phone_traditional,
        "phone_national": phone_national,
        "phone_international": phone_international,
        "phone_tenant": phone_tenant,
    }


def parse_worker_reference(worker_response: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extracts the main Worker_Reference WID from a Worker SOAP response.
    Ignores nested references in roles, managers, or organizations.
    """
    worker_wid = None

    # 1) Direct Worker_Reference
    worker_ref = worker_response.get("Worker_Reference") or {}
    ids = worker_ref.get("ID", [])
    if isinstance(ids, dict):  # sometimes comes as dict, not list
        ids = [ids]
    for id_item in ids:
        if isinstance(id_item, dict) and id_item.get("type") == "WID":
            worker_wid = id_item.get("_value_1")
            break
        elif hasattr(id_item, "type") and getattr(id_item, "type", None) == "WID":
            worker_wid = getattr(id_item, "_value_1", None)
            break

    # 2) Fallback: si no hay Worker_Reference, buscar Universal_Identifier_Reference
    if not worker_wid:
        uni_ref = worker_response.get("Universal_Identifier_Reference") or {}
        ids = uni_ref.get("ID", [])
        if isinstance(ids, dict):
            ids = [ids]
        for id_item in ids:
            if isinstance(id_item, dict) and id_item.get("type") == "WID":
                worker_wid = id_item.get("_value_1")
                break

    return {"worker_wid": worker_wid}


def parse_personal_data(worker_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse the personal information of the worker.
    """
    personal = worker_data.get("Personal_Data", {}) or {}
    name_data = personal.get("Name_Data", {}) or {}
    legal = name_data.get("Legal_Name_Data", {}).get("Name_Detail_Data", {}) or {}
    preferred = name_data.get("Preferred_Name_Data", {}).get("Name_Detail_Data", {}) or {}

    # Names
    first_name            = legal.get("First_Name")
    middle_name           = legal.get("Middle_Name")
    last_name             = legal.get("Last_Name")
    formatted_name        = legal.get("Formatted_Name")
    reporting_name        = legal.get("Reporting_Name")
    pref_formatted_name   = preferred.get("Formatted_Name")
    pref_reporting_name   = preferred.get("Reporting_Name")

    # Pronouns
    pronoun_id = None
    pron_refs = personal.get("Pronoun_Reference", []) or []
    if pron_refs:
        for entry in ensure_list(pron_refs[0].get("ID")):
            if entry.get("type") == "Pronoun_ID":
                pronoun_id = entry.get("_value_1")
                break

    # Demographics & birth_date
    birth_date                       = None
    gender                           = None
    ethnicity                        = None
    hispanic_or_latino               = None
    hispanic_or_latino_visual_survey = None

    personal_info_nodes = personal.get("Personal_Information_Data", []) or []
    if personal_info_nodes:
        # Birth date
        bd = personal_info_nodes[0].get("Birth_Date")
        birth_date = str(bd) if bd else None

        # Search for gender, ethnicity, hispanic flags
        for info in personal_info_nodes:
            for country_info in ensure_list(info.get("Personal_Information_For_Country_Data")):
                # ignoramos valores nulos o no‐dict
                if not isinstance(country_info, dict):
                    continue
                # Gender
                try_g = _extract_gender(country_info)
                if try_g and not gender:
                    gender = try_g
                # Ethnicity
                try_e = _extract_ethnicity(country_info)
                if try_e and not ethnicity:
                    ethnicity = try_e
                # Hispanic flags
                for cp in ensure_list(country_info.get("Country_Personal_Information_Data", [])):
                    if not isinstance(cp, dict):
                        continue
                    his = cp.get("Hispanic_or_Latino")
                    if his is not None and hispanic_or_latino is None:
                        hispanic_or_latino = bool(his)
                    hisv = cp.get("Hispanic_or_Latino_Visual_Survey")
                    if hisv is not None and hispanic_or_latino_visual_survey is None:
                        hispanic_or_latino_visual_survey = bool(hisv)

                if all(v is not None for v in [gender, ethnicity, hispanic_or_latino, hispanic_or_latino_visual_survey]):
                    break
            if all(v is not None for v in [gender, ethnicity, hispanic_or_latino, hispanic_or_latino_visual_survey]):
                break

    # Tobacco use
    tobacco_use = None
    tu = personal.get("Tobacco_Use")
    if tu is not None:
        tobacco_use = bool(tu)

    return {
        "first_name": first_name,
        "middle_name": middle_name,
        "last_name": last_name,
        "formatted_name": formatted_name,
        "reporting_name": reporting_name,
        "pref_formatted_name": pref_formatted_name,
        "pref_reporting_name": pref_reporting_name,
        "pronoun_id": pronoun_id,
        "birth_date": birth_date,
        "gender": gender,
        "hispanic_or_latino": hispanic_or_latino,
        "hispanic_or_latino_visual_survey": hispanic_or_latino_visual_survey,
        "ethnicity": ethnicity,
        "tobacco_use": tobacco_use,
    }

def _select_preferred_address(addr_entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Select the preferred address from a list of addresses.
    Priority order:
    1. Address with Primary="1" in Usage_Data > Type_Data
    2. Personal address (Defaulted_Business_Site_Address="0" or "false")
    3. Most recent address by Effective_Date
    4. First address as fallback
    """
    if not addr_entries:
        return {}

    # Convert to list if it's a single dict
    if isinstance(addr_entries, dict):
        addr_entries = [addr_entries]

    # Priority 1: Look for PERSONAL address with Primary="1" and HOME type
    # First, filter only personal addresses (non-business)
    for addr in addr_entries:
        defaulted_business = addr.get("Defaulted_Business_Site_Address")

        # Check if it's a personal address (Defaulted_Business_Site_Address="0" or "false")
        is_personal = (
            defaulted_business == "0" or
            defaulted_business == 0 or
            defaulted_business == "false" or
            defaulted_business is False
        )

        # Skip business addresses in this priority check
        if not is_personal:
            continue

        usage_data_raw = addr.get("Usage_Data", [])

        # Usage_Data can be a single dict or a list of dicts
        usage_data_list = ensure_list(usage_data_raw) if usage_data_raw else []

        for usage_data in usage_data_list:
            if not isinstance(usage_data, dict):
                continue

            type_data_raw = usage_data.get("Type_Data", {}) or {}

            # Type_Data can also be a list or a dict
            type_data_list = ensure_list(type_data_raw) if type_data_raw else []

            for type_data in type_data_list:
                if not isinstance(type_data, dict):
                    continue

                # Check if Type_Data has Primary="1"
                primary_value = (
                    type_data.get("Primary") or
                    type_data.get("@Primary") or
                    type_data.get("_attr_Primary") or
                    getattr(type_data, "Primary", None)
                )

                # Check if it's HOME type (not WORK)
                type_ref = type_data.get("Type_Reference", {}) or {}
                type_ids = ensure_list(type_ref.get("ID", [])) if type_ref else []
                usage_type = None
                for type_id in type_ids:
                    if isinstance(type_id, dict) and type_id.get("type") == "Communication_Usage_Type_ID":
                        usage_type = type_id.get("_value_1")
                        break

                is_primary = (
                    primary_value == "1" or
                    primary_value == 1 or
                    primary_value is True or
                    str(primary_value) == "1"
                )

                # Priority: Primary=1 AND HOME type (personal address)
                if is_primary and usage_type == "HOME":
                    return addr

    # Priority 2: Filter for personal addresses (non-business)
    personal_addresses = []
    business_addresses = []

    for addr in addr_entries:
        defaulted_business = addr.get("Defaulted_Business_Site_Address")

        # Check if it's a personal address (Defaulted_Business_Site_Address="0" or "false")
        is_personal = (
            defaulted_business == "0" or
            defaulted_business == 0 or
            defaulted_business == "false" or
            defaulted_business is False
        )

        if is_personal:
            personal_addresses.append(addr)
        else:
            business_addresses.append(addr)

    # Priority 3: Use personal address if available
    if personal_addresses:
        # If multiple personal addresses, pick the most recent
        if len(personal_addresses) > 1:
            personal_addresses.sort(
                key=lambda x: x.get("Effective_Date", ""),
                reverse=True
            )
        return personal_addresses[0]

    # Priority 4: If no personal address, use business address (most recent)
    if business_addresses:
        if len(business_addresses) > 1:
            business_addresses.sort(
                key=lambda x: x.get("Effective_Date", ""),
                reverse=True
            )
        return business_addresses[0]

    # Fallback: Return first address
    return addr_entries[0]


def parse_contact_data(worker_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse the contact information (email, address, phone) of the worker.
    Prioritizes personal addresses over business addresses.
    """
    contact = worker_data.get("Personal_Data", {}).get("Contact_Data", {}) or {}

    # Emails - Parse personal vs corporate emails based on Communication_Usage_Type_ID
    email_entries = contact.get("Email_Address_Data", []) or []
    emails = [e.get("Email_Address") for e in email_entries if e.get("Email_Address")]
    email = emails[0] if emails else None

    # Separate personal and corporate emails based on Communication_Usage_Type_ID
    personal_email = None
    corporate_email = None
    email_usage_public = None
    email_id = None

    for email_entry in email_entries:
        email_address = email_entry.get("Email_Address")
        if not email_address:
            continue

        # Extract Communication_Usage_Type_ID from Usage_Data -> Type_Data -> Type_Reference -> ID
        usage_data = ensure_list(email_entry.get("Usage_Data"))
        usage_type_id = None
        if usage_data:
            type_data = ensure_list(usage_data[0].get("Type_Data", []))
            if type_data:
                type_ref = type_data[0].get("Type_Reference", {}) or {}
                type_ids = ensure_list(type_ref.get("ID", []))
                usage_type_id = extract_by_type(type_ids, "Communication_Usage_Type_ID")

        # Assign based on Communication_Usage_Type_ID
        if usage_type_id == "HOME":  # HOME means personal email
            personal_email = email_address
        elif usage_type_id == "WORK":  # WORK means corporate/work email
            corporate_email = email_address
    
    # Keep original logic for backward compatibility
    if email_entries:
        usage = ensure_list(email_entries[0].get("Usage_Data"))
        if usage:
            email_usage_public = bool(usage[0].get("Public"))
        email_id = email_entries[0].get("ID")

    # Address - Now with smart selection logic
    addr_entries                  = contact.get("Address_Data", []) or []
    addr                          = _select_preferred_address(addr_entries)
    address                       = addr.get("Formatted_Address")
    if address and "NO STREET ADDRESS" in address:
        address = None
    address_effective_date        = addr.get("Effective_Date")
    address_format_type           = addr.get("Address_Format_Type")
    defaulted_business_site_address = addr.get("Defaulted_Business_Site_Address")
    if defaulted_business_site_address is not None:
        defaulted_business_site_address = bool(defaulted_business_site_address)

    alines                        = ensure_list(addr.get("Address_Line_Data", []))
    address_line                  = ", ".join(
        v for a in alines
        if (v := a.get("_value_1") or a.get("#text"))
    ) or None
    aline                         = first(alines)
    address_line_descriptor       = aline.get("Descriptor")
    municipality                  = addr.get("Municipality")
    country_region_descriptor     = addr.get("Country_Region_Descriptor")
    postal_code                   = addr.get("Postal_Code")
    addr_usage                    = ensure_list(addr.get("Usage_Data"))
    address_usage_public          = bool(addr_usage[0].get("Public")) if addr_usage else None
    address_number_of_days        = addr.get("Number_of_Days")
    address_id                    = addr.get("Address_ID")

    # Country and State
    country = None
    state_code = None
    country_ref = addr.get("Country_Reference", {}) or {}
    for c in ensure_list(country_ref.get("ID")):
        if c.get("type") == "ISO_3166-1_Alpha-2_Code":
            country = c.get("_value_1")
            break
    
    # Extract state code from Country_Region_Reference
    country_region_ref = addr.get("Country_Region_Reference", {}) or {}
    for cr in ensure_list(country_region_ref.get("ID")):
        if cr.get("type") == "ISO_3166-2_Code":
            state_code = cr.get("_value_1")
            break
    


    # Phone
    phone_entries             = contact.get("Phone_Data", []) or []
    p                         = phone_entries[0] if phone_entries else {}

    # Obtener el número telefónico raw (priorizar E164, luego otros formatos)
    phone_raw                 = (p.get("E164_Formatted_Phone") or
                                 p.get("Workday_Traditional_Formatted_Phone") or
                                 p.get("National_Formatted_Phone") or
                                 p.get("International_Formatted_Phone") or
                                 p.get("Tenant_Formatted_Phone"))

    # Formatear el número usando nuestra función
    phone_formatted = format_phone_number(phone_raw)

    # SIEMPRE usar valores formateados (para corregir datos mal formateados del origen)
    phone                     = phone_formatted["phone"]
    phone_area_code           = phone_formatted["phone_area_code"]
    phone_number_wo_area      = phone_formatted["phone_number_wo_area"]
    phone_traditional         = phone_formatted["phone_traditional"]
    phone_national            = phone_formatted["phone_national"]
    phone_international       = phone_formatted["phone_international"]
    phone_tenant              = phone_formatted["phone_tenant"]

    # Device type
    dev_ref = p.get("Phone_Device_Type_Reference", {}) or {}
    phone_device_type_id = None
    for entry in ensure_list(dev_ref.get("ID")):
        if entry.get("type") == "Phone_Device_Type_ID":
            phone_device_type_id = entry.get("_value_1")
            break

    ph_usage           = ensure_list(p.get("Usage_Data"))
    phone_usage_public = bool(ph_usage[0].get("Public")) if ph_usage else None
    phone_id           = p.get("ID")

    return {
        "email": email,
        "emails": emails or None,
        "personal_email": personal_email,
        "corporate_email": corporate_email,
        "email_usage_public": email_usage_public,
        "email_id": email_id,
        "address": address,
        "address_effective_date": str(address_effective_date) if address_effective_date else None,
        "address_format_type": address_format_type,
        "defaulted_business_site_address": defaulted_business_site_address,
        "address_line": address_line,
        "address_line_descriptor": address_line_descriptor,
        "municipality": municipality,
        "country_region_descriptor": country_region_descriptor,
        "postal_code": postal_code,
        "address_usage_public": address_usage_public,
        "address_number_of_days": address_number_of_days,
        "address_id": address_id,
        "country_code": country,
        "state_code": state_code,
        "phone": phone,
        "phone_area_code": phone_area_code,
        "phone_number_wo_area": phone_number_wo_area,
        "phone_traditional": phone_traditional,
        "phone_national": phone_national,
        "phone_international": phone_international,
        "phone_tenant": phone_tenant,
        "phone_device_type_id": phone_device_type_id,
        "phone_usage_public": phone_usage_public,
        "phone_id": phone_id,
    }


def parse_worker_organization_data(worker_data: Dict[str, Any]) -> Dict[str, Any]:
    """Parse worker organization information from worker data"""
    organization_data = worker_data.get("Organization_Data", {}) or {}
    worker_orgs = organization_data.get("Worker_Organization_Data", []) or []
    
    organizations = []
    primary_org = None
    company_org = None
    cost_center_org = None
    cost_center_hierarchy_org = None
    pay_group_org = None
    supervisory_org = None
    
    for org in worker_orgs:
        org_ref = org.get("Organization_Reference", {}) or {}
        org_data = org.get("Organization_Data", {}) or {}
        
        # Extract organization IDs
        org_ids = org_ref.get("ID", []) or []
        org_ref_id = extract_by_type(org_ids, "Organization_Reference_ID")
        company_id = extract_by_type(org_ids, "Company_Reference_ID")
        cost_center_id = extract_by_type(org_ids, "Cost_Center_Reference_ID")
        custom_org_id = extract_by_type(org_ids, "Custom_Organization_Reference_ID")
        
        # Organization details
        org_name = org_data.get("Organization_Name")
        org_code = org_data.get("Organization_Code")
        
        # Organization type
        org_type_ref = org_data.get("Organization_Type_Reference", {}) or {}
        org_type_ids = org_type_ref.get("ID", []) or []
        org_type = extract_by_type(org_type_ids, "Organization_Type_ID")
        
        # Organization subtype
        org_subtype_ref = org_data.get("Organization_Subtype_Reference", {}) or {}
        org_subtype_ids = org_subtype_ref.get("ID", []) or []
        org_subtype = extract_by_type(org_subtype_ids, "Organization_Subtype_ID")
        
        # Used in assignments
        used_in_assignments = org_data.get("Used_in_Change_Organization_Assignments", "0") == "1"
        
        org_info = {
            "organization_reference_id": org_ref_id,
            "organization_name": org_name,
            "organization_code": org_code,
            "organization_type": org_type,
            "organization_subtype": org_subtype,
            "company_id": company_id,
            "cost_center_id": cost_center_id,
            "custom_organization_id": custom_org_id,
            "used_in_assignments": used_in_assignments,
        }
        
        organizations.append(org_info)
        
        # Identify specific organization types
        if org_type == "Company" and org_subtype == "Company":
            company_org = org_info
        elif org_type == "Cost_Center" and org_subtype == "Cost_Center":
            cost_center_org = org_info
        elif org_type == "Cost_Center_Hierarchy":
            cost_center_hierarchy_org = org_info
        elif org_type == "Pay_Group" and org_subtype == "Pay_Group":
            pay_group_org = org_info
        elif org_type == "Supervisory" and org_subtype == "Department":
            supervisory_org = org_info
        
        # Set primary organization (first one or most relevant)
        if not primary_org:
            primary_org = org_info
    
    return {
        "organizations": organizations,
        "primary_organization_id": primary_org.get("organization_reference_id") if primary_org else None,
        "primary_organization_name": primary_org.get("organization_name") if primary_org else None,
        "primary_organization_type": primary_org.get("organization_type") if primary_org else None,
        "primary_organization_code": primary_org.get("organization_code") if primary_org else None,
        "company_id": company_org.get("organization_reference_id") if company_org else None,
        "company_name": company_org.get("organization_name") if company_org else None,
        "cost_center_id": cost_center_org.get("organization_reference_id") if cost_center_org else None,
        "cost_center_name": cost_center_org.get("organization_name") if cost_center_org else None,
        "cost_center_hierarchy_name": cost_center_hierarchy_org.get("organization_name") if cost_center_hierarchy_org else None,
        "pay_group_id": pay_group_org.get("organization_reference_id") if pay_group_org else None,
        "pay_group_name": pay_group_org.get("organization_name") if pay_group_org else None,
        "supervisory_organization_id": supervisory_org.get("organization_reference_id") if supervisory_org else None,
        "supervisory_organization_name": supervisory_org.get("organization_name") if supervisory_org else None,
    }

def parse_compensation_data(worker_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse the compensation details of the worker.

    Extracts:
      - wage (float)
      - compensation_effective_date (str)
      - compensation_guidelines (package / grade / profile IDs)
      - salary_and_hourly (list of elements)
      - compensation_summary (nested summary)
      - reason_references (mapping of reason type → ID)
    """
    compensation = worker_data.get("Compensation_Data", {}) or {}

    # — Salary / hourly nodes —
    salary_nodes = ensure_list(compensation.get("Salary_and_Hourly_Data"))
    wage = next(
        (float(s.get("Amount")) for s in salary_nodes if s and s.get("Amount") is not None),
        None
    )
    salary_and_hourly = _parse_salary_nodes(salary_nodes)

    # — Compensation guidelines —
    guidelines_nodes = compensation.get("Compensation_Guidelines_Data", []) or []
    if guidelines_nodes:
        g0 = guidelines_nodes[0] or {}
        # Extract references safely
        package_ref = g0.get("Compensation_Package_Reference") or {}
        grade_ref = g0.get("Compensation_Grade_Reference") or {}
        profile_ref = g0.get("Compensation_Grade_Profile_Reference") or {}
        
        compensation_guidelines = {
            "package": extract_by_type(
                package_ref.get("ID", []) if isinstance(package_ref, dict) else [],
                "Compensation_Package_ID"
            ),
            "grade": extract_by_type(
                grade_ref.get("ID", []) if isinstance(grade_ref, dict) else [],
                "Compensation_Grade_ID"
            ),
            "profile": extract_by_type(
                profile_ref.get("ID", []) if isinstance(profile_ref, dict) else [],
                "Compensation_Grade_Profile_ID"
            ),
        }
    else:
        compensation_guidelines = {"package": None, "grade": None, "profile": None}

    # — Reason references (requerido por el modelo) —
    reason_refs: Dict[str, str] = {}
    for node in ensure_list(compensation.get("Reason_Reference")):
        for entry in ensure_list(node.get("ID")):
            t = entry.get("type")
            v = entry.get("_value_1")
            if t and v:
                reason_refs[t] = v

    # — Build and return —
    return {
        "wage": wage,
        "compensation_effective_date": (
            str(compensation.get("Compensation_Effective_Date"))
            if compensation.get("Compensation_Effective_Date") else None
        ),
        "compensation_guidelines": compensation_guidelines,
        "salary_and_hourly": salary_and_hourly,
        "compensation_summary": _parse_compensation_summary(compensation),
        "reason_references": reason_refs or None,
    }

def parse_identification_data(worker_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse identification details (national ID, license, custom IDs).
    """
    # Identification_Data está dentro de Personal_Data
    personal_data = worker_data.get("Personal_Data", {}) or {}
    ident = personal_data.get("Identification_Data", {}) or {}

    # National ID
    nat_list   = ident.get("National_ID", []) or []
    nat0       = nat_list[0] if nat_list else {}
    nid_data   = nat0.get("National_ID_Data", {}) or {}
    national_id = nid_data.get("ID")
    national_id_type_code = extract_by_type(
        nid_data.get("ID_Type_Reference", {}).get("ID", []),
        "National_ID_Type_Code"
    )
    nshr = first(nat0.get("National_ID_Shared_Reference", {})).get("ID", []) or []
    national_id_shared_reference = extract_by_type(
        nshr,
        "National_Identifier_Reference_ID"
    )

    # New: Verification fields
    national_id_verification_date = nid_data.get("Verification_Date")
    national_id_verified_by = None
    verified_by_ref = first(nid_data.get("Verified_By_Reference", {}))
    verified_by_ids = verified_by_ref.get("ID", []) or []
    national_id_verified_by = extract_by_type(verified_by_ids, "Employee_ID")

    # License
    lic_list  = ident.get("License_ID", []) or []
    license_data = first(lic_list).get("License_ID_Data", {}) or {}
    license_id = license_data.get("ID")
    
    # License Type ID
    id_type_ref = license_data.get("ID_Type_Reference", {}) or {}
    license_type_id = extract_by_type(
        id_type_ref.get("ID", []) or [],
        "License_ID_Type_ID"
    )
    
    # License State Code
    country_region_ref = license_data.get("Country_Region_Reference", {}) or {}
    license_state_code = extract_by_type(
        country_region_ref.get("ID", []) or [],
        "ISO_3166-2_Code"
    )
    
    license_issued_date = license_data.get("Issued_Date")
    license_expiration_date = license_data.get("Expiration_Date")

    # Custom IDs
    custom_ids       = {}
    custom_shared    = {}
    associate_oid    = None
    adp_payroll_id   = None
    adp_payroll_group = None
    old_corporate_email = None
    
    for cid in ident.get("Custom_ID", []) or []:
        data  = cid.get("Custom_ID_Data", {}) or {}
        cv    = data.get("ID")
        
        id_type_ref = data.get("ID_Type_Reference", {}) or {}
        id_list = id_type_ref.get("ID", []) or []
        
        ctype = extract_by_type(id_list, "Custom_ID_Type_ID")
        
        if ctype:
            custom_ids[ctype] = cv
            # Extract specific Custom IDs
            if ctype == "Associate OID":
                associate_oid = cv
            elif ctype == "ADP Payroll ID":
                adp_payroll_id = cv
            elif ctype == "ADP Payroll Group":
                adp_payroll_group = cv
            elif ctype == "Old Corporate Email":
                old_corporate_email = cv
            shared_ids = first(cid.get("Custom_ID_Shared_Reference", {})).get("ID", []) or []
            sref = extract_by_type(shared_ids, "Custom_Identifier_Reference_ID")
            if sref:
                custom_shared[ctype] = sref

    return {
        "national_id": national_id,
        "national_id_type_code": national_id_type_code,
        "national_id_shared_reference": national_id_shared_reference,
        "national_id_verification_date": national_id_verification_date,
        "national_id_verified_by": national_id_verified_by,
        "license_id": license_id,
        "license_type_id": license_type_id,
        "license_state_code": license_state_code,
        "license_issued_date": str(license_issued_date) if license_issued_date else None,
        "license_expiration_date": str(license_expiration_date) if license_expiration_date else None,
        "custom_ids": custom_ids or None,
        "custom_id_shared_references": custom_shared or None,
        "associate_oid": associate_oid,
        "adp_payroll_id": adp_payroll_id,
        "adp_payroll_group": adp_payroll_group,
        "old_corporate_email": old_corporate_email,
    }

def parse_benefits_and_roles(worker_data: Dict[str, Any], worker_id: Optional[str] = None, document_directory: Optional[str] = None) -> Dict[str, Any]:
    """
    Parse benefit enrollments, roles, and worker documents.

    Args:
        worker_data: Worker data dictionary
        worker_id: Worker/Employee ID for organizing saved files
        document_directory: Base directory to save document files

    Returns:
        Dictionary with benefits, roles, and document information
    """
    # Benefits
    ben_section         = worker_data.get("Benefit_Enrollment_Data", {}) or {}
    benefit_enrollments = [
        b.get("Benefit_Enrollment_Type")
        for b in ben_section.get("Benefit_Enrollment", [])
        if b and b.get("Benefit_Enrollment_Type")
    ] or None

    # Roles
    roles_section = worker_data.get("Roles_Data", {}) or {}
    roles         = [
        r.get("Role_Data", {}).get("Role_Name")
        for r in roles_section.get("Role", [])
        if r and r.get("Role_Data", {}).get("Role_Name")
    ] or None

    # Documents - Note: API returns "Worker_Document_Data" (singular), not "Worker_Documents_Data"
    docs_section = worker_data.get("Worker_Document_Data", {}) or {}
    worker_documents = [
        d.get("Worker_Document_Data", {}).get("Document_Reference")
        for d in docs_section.get("Worker_Document", [])
        if d and d.get("Worker_Document_Data", {}).get("Document_Reference")
    ] or None

    # New: Worker Documents Details (with filename and file content)
    worker_documents_details = []
    worker_docs = ensure_list(docs_section.get("Worker_Document", []))

    for d in worker_docs:
        if not d:
            continue

        # Get Worker_Document_Reference
        doc_ref = first(d.get("Worker_Document_Reference", {}))
        doc_ids = doc_ref.get("ID", []) or [] if doc_ref else []
        doc_wid = extract_by_type(doc_ids, "WID")
        doc_file_id = extract_by_type(doc_ids, "File_ID")

        # Get Worker_Document_Detail_Data
        doc_detail = first(d.get("Worker_Document_Detail_Data", {}))
        filename = doc_detail.get("Filename") if doc_detail else None
        file_content = doc_detail.get("File") if doc_detail else None  # Base64 encoded

        # Convert bytes to base64 string if needed
        file_content_for_save = file_content
        if isinstance(file_content, bytes):
            import base64
            file_content_for_save = base64.b64encode(file_content).decode('utf-8')

        # Save document to disk if directory is provided
        document_path = None
        if document_directory and worker_id and filename and file_content_for_save:
            document_path = save_worker_document(
                file_content_base64=file_content_for_save,
                filename=filename,
                worker_id=worker_id,
                storage_path=document_directory
            )

        if doc_wid or doc_file_id or filename:
            doc_entry = {
                "document_wid": doc_wid,
                "document_file_id": doc_file_id,
                "filename": filename,
                "document_path": document_path  # Path where file was saved, if applicable
            }

            # Only include file_content if document was NOT saved successfully
            if not document_path and file_content_for_save:
                # Truncate to first 100 chars for display purposes
                doc_entry["file_content_preview"] = file_content_for_save[:100] + "..." if len(file_content_for_save) > 100 else file_content_for_save
                doc_entry["file_content_length"] = len(file_content_for_save)

            worker_documents_details.append(doc_entry)

    if worker_docs:
        saved = sum(1 for d in worker_documents_details if d.get("document_path"))
        logger.debug(f"Worker documents: {len(worker_docs)} found, {len(worker_documents_details)} processed, {saved} saved")

    return {
        "benefit_enrollments": benefit_enrollments,
        "roles": roles,
        "worker_documents": worker_documents,
        "worker_documents_details": worker_documents_details or None,
    }


def parse_employment_data(worker_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse employment-related details (position, hours, job profile).
    """

    employment = worker_data.get("Employment_Data", {}) or {}
    wjd_list   = ensure_list(employment.get("Worker_Job_Data"))
    wjd        = wjd_list[0] if wjd_list else {}
    pos        = wjd.get("Position_Data", {}) or {}

    # Identificadores & títulos
    # position_id     = extract_by_type(
    #     pos.get("Position_Reference", {}).get("ID", []),
    #     "Position_ID"
    # )
    position_id = extract_by_type(pos.get("Position_Reference",{}).get("ID",[]), "Position_ID") or pos.get("Position_ID")

    position_title  = pos.get("Position_Title")
    business_title  = pos.get("Business_Title")

    # Fechas
    start_date              = pos.get("Start_Date")
    end_employment_date     = pos.get("End_Employment_Date")
    position_effective_date = pos.get("Effective_Date")

    # Tipos & clasificaciones
    wt_ref = pos.get("Worker_Type_Reference") or {}
    worker_type = extract_by_type(wt_ref.get("ID", []), "Employee_Type_ID")

    pt_ref = pos.get("Position_Time_Type_Reference") or {}
    position_time_type = extract_by_type(pt_ref.get("ID", []), "Position_Time_Type_ID")

    pr_ref = pos.get("Pay_Rate_Type_Reference") or {}
    pay_rate_type = extract_by_type(pr_ref.get("ID", []), "Pay_Rate_Type_ID")

    # Horas & exención
    job_exempt                      = pos.get("Job_Exempt")
    scheduled_weekly_hours          = float(pos.get("Scheduled_Weekly_Hours")) if pos.get("Scheduled_Weekly_Hours") is not None else None
    default_weekly_hours            = float(pos.get("Default_Weekly_Hours"))   if pos.get("Default_Weekly_Hours")   is not None else None
    full_time_equivalent_percentage = float(pos.get("Full_Time_Equivalent_Percentage")) if pos.get("Full_Time_Equivalent_Percentage") is not None else None

    # New: FTE fields
    working_time_value = float(pos.get("Working_Time_Value")) if pos.get("Working_Time_Value") is not None else None
    specify_paid_fte = pos.get("Specify_Paid_FTE")
    paid_fte = float(pos.get("Paid_FTE")) if pos.get("Paid_FTE") is not None else None
    specify_working_fte = pos.get("Specify_Working_FTE")
    working_fte = float(pos.get("Working_FTE")) if pos.get("Working_FTE") is not None else None
    exclude_from_headcount = pos.get("Exclude_from_Headcount")

    # Job Profile & Management Level
    jps = pos.get("Job_Profile_Summary_Data") or {}

    # Job Profile
    jpr = jps.get("Job_Profile_Reference") or {}
    job_profile_id   = extract_by_type(jpr.get("ID", []), "Job_Profile_ID")
    job_profile_name = jps.get("Job_Profile_Name")

    # Management Level
    mlr = jps.get("Management_Level_Reference") or {}
    management_level = extract_by_type(mlr.get("ID", []), "Management_Level_ID")

    # New: Job Category
    jcr = first(jps.get("Job_Category_Reference", {}))
    job_category = extract_by_type(jcr.get("ID", []), "Job_Category_ID")

    # New: Work Shift and Critical Job
    work_shift_required = jps.get("Work_Shift_Required")
    critical_job = jps.get("Critical_Job")

    # Job Family (pueden venir varias referencias)
    families = []
    for fam in ensure_list(jps.get("Job_Family_Reference", [])):
        fam_id = extract_by_type(fam.get("ID", []), "Job_Family_ID")
        if fam_id:
            families.append(fam_id)

    # New: Job Classifications
    job_classifications = []
    for jcs in ensure_list(pos.get("Job_Classification_Summary_Data", [])):
        jc_ref = jcs.get("Job_Classification_Reference", {}) or {}
        jc_id = extract_by_type(jc_ref.get("ID", []), "Job_Classification_Reference_ID")

        jg_ref = jcs.get("Job_Group_Reference", {}) or {}
        jg_id = extract_by_type(jg_ref.get("ID", []), "Job_Classification_Group_ID")

        if jc_id or jg_id:
            job_classifications.append({
                "classification_id": jc_id,
                "group_id": jg_id
            })

    # New: Position End Employment Reason
    position_end_employment_reason = None
    eer_ref = first(pos.get("End_Employment_Reason_Reference", {}))
    eer_ids = eer_ref.get("ID", []) or []
    position_end_employment_reason = extract_by_type(eer_ids, "Event_Classification_Subcategory_ID") or extract_by_type(eer_ids, "Termination_Subcategory_ID")

    return {
        "position_id": position_id,
        "position_title": position_title,
        "business_title": business_title,
        "start_date": start_date,
        "end_employment_date": end_employment_date,
        "position_effective_date": position_effective_date,
        "position_end_employment_reason": position_end_employment_reason,
        "worker_type": worker_type,
        "position_time_type": position_time_type,
        "pay_rate_type": pay_rate_type,
        "job_exempt": job_exempt,
        "scheduled_weekly_hours": scheduled_weekly_hours,
        "default_weekly_hours": default_weekly_hours,
        "full_time_equivalent_percentage": full_time_equivalent_percentage,
        "working_time_value": working_time_value,
        "specify_paid_fte": specify_paid_fte,
        "paid_fte": paid_fte,
        "specify_working_fte": specify_working_fte,
        "working_fte": working_fte,
        "exclude_from_headcount": exclude_from_headcount,
        "job_profile_id": job_profile_id,
        "job_profile_name": job_profile_name,
        "management_level": management_level,
        "job_category": job_category,
        "job_family": families or None,
        "job_classifications": job_classifications or None,
        "work_shift_required": work_shift_required,
        "critical_job": critical_job,
    }


def parse_worker_status(worker_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse worker status details (active, hire/termination dates, eligibility),
    asegurando no romper si algún _Reference es None.
    """
    employment = worker_data.get("Employment_Data", {}) or {}
    status     = employment.get("Worker_Status_Data", {}) or {}

    # — Campos básicos —
    active             = status.get("Active")
    active_status_date = status.get("Active_Status_Date")
    hire_date          = status.get("Hire_Date")
    original_hire_date = status.get("Original_Hire_Date")
    first_day_of_work  = status.get("First_Day_of_Work")
    seniority_date     = status.get("Seniority_Date")
    terminated         = status.get("Terminated")
    termination_date   = status.get("Termination_Date")
    pay_through_date   = status.get("Pay_Through_Date")

    # New: Hire reason
    hr_ref = first(status.get("Hire_Reason_Reference", {}))
    hr_ids = hr_ref.get("ID", []) or []
    hire_reason = extract_by_type(hr_ids, "Event_Classification_Subcategory_ID") or extract_by_type(hr_ids, "General_Event_Subcategory_ID")

    # New: Service dates and employment history
    continuous_service_date = status.get("Continuous_Service_Date")
    retired = status.get("Retired")
    days_unemployed = status.get("Days_Unemployed")
    months_continuous_prior_employment = status.get("Months_Continuous_Prior_Employment")

    # New: Hire and return flags
    hire_rescinded = status.get("Hire_Rescinded")
    not_returning = status.get("Not_Returning")
    return_unknown = status.get("Return_Unknown")
    rehire = status.get("Rehire")

    # — Razón y categoría de terminación —
    ptr_ref = status.get("Primary_Termination_Reason_Reference") or {}
    term_id_list = ptr_ref.get("ID") or []
    termination_reason = extract_by_type(term_id_list, "Event_Classification_Subcategory_ID")

    ptc_ref = status.get("Primary_Termination_Category_Reference") or {}
    cat_id_list = ptc_ref.get("ID") or []
    termination_category = extract_by_type(cat_id_list, "Termination_Category_ID")

    termination_involuntary = status.get("Termination_Involuntary")

    # — Elegibilidad —
    eh_ref = status.get("Eligible_for_Hire_Reference") or {}
    eh_id_list = eh_ref.get("ID") or []
    eligible_for_hire = extract_by_type(eh_id_list, "Yes_No_Type_ID") == "Yes"

    regrettable_termination = status.get("Regrettable_Termination")

    erh_ref = status.get("Eligible_for_Rehire_on_Latest_Termination_Reference") or {}
    erh_id_list = erh_ref.get("ID") or []
    eligible_for_rehire = extract_by_type(erh_id_list, "Yes_No_Type_ID") == "Yes"

    termination_last_day_of_work = status.get("Termination_Last_Day_of_Work")

    return {
        "active": active,
        "active_status_date": active_status_date,
        "hire_date": hire_date,
        "original_hire_date": original_hire_date,
        "hire_reason": hire_reason,
        "first_day_of_work": first_day_of_work,
        "continuous_service_date": continuous_service_date,
        "seniority_date": seniority_date,
        "retired": retired,
        "days_unemployed": days_unemployed,
        "months_continuous_prior_employment": months_continuous_prior_employment,
        "terminated": terminated,
        "termination_date": termination_date,
        "pay_through_date": pay_through_date,
        "termination_reason": termination_reason,
        "termination_category": termination_category,
        "termination_involuntary": termination_involuntary,
        "eligible_for_hire": eligible_for_hire,
        "regrettable_termination": regrettable_termination,
        "eligible_for_rehire": eligible_for_rehire,
        "termination_last_day_of_work": termination_last_day_of_work,
        "hire_rescinded": hire_rescinded,
        "not_returning": not_returning,
        "return_unknown": return_unknown,
        "rehire": rehire,
    }

def parse_business_site(worker_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse business site summary data.
    """
    employment = worker_data.get("Employment_Data", {}) or {}
    wjd_list   = ensure_list(employment.get("Worker_Job_Data"))
    wjd        = wjd_list[0] if wjd_list else {}
    pos        = wjd.get("Position_Data", {}) or {}

    bs = pos.get("Business_Site_Summary_Data", {}) or {}
    business_site_name        = bs.get("Name")
    business_site_location_id = extract_by_type(
        bs.get("Location_Reference", {}).get("ID", []),
        "Location_ID"
    )

    # New: Location Type
    lt_ref = first(bs.get("Location_Type_Reference", {}))
    business_site_location_type = extract_by_type(lt_ref.get("ID", []), "Location_Type_ID")

    # New: Locale
    locale_ref = first(bs.get("Local_Reference", {}))
    business_site_locale = extract_by_type(locale_ref.get("ID", []), "Locale_ID")

    # New: Time Profile
    tp_ref = first(bs.get("Time_Profile_Reference", {}))
    business_site_time_profile = extract_by_type(tp_ref.get("ID", []), "Time_Profile_ID")

    # New: Scheduled Hours
    business_site_scheduled_hours = float(bs.get("Scheduled_Weekly_Hours")) if bs.get("Scheduled_Weekly_Hours") is not None else None

    # El Address_Data completo lo guardamos tal cual
    bs_address_list = ensure_list(bs.get("Address_Data", []))
    business_site_address = bs_address_list[0] if bs_address_list else None

    return {
        "business_site_name": business_site_name,
        "business_site_location_id": business_site_location_id,
        "business_site_location_type": business_site_location_type,
        "business_site_locale": business_site_locale,
        "business_site_time_profile": business_site_time_profile,
        "business_site_scheduled_hours": business_site_scheduled_hours,
        "business_site_address": business_site_address,
    }

def parse_management_chain_data(worker_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse management chain data from Worker_Management_Chain_Data.
    """
    management_data = worker_data.get("Management_Chain_Data", {}) or {}
    
    # Supervisory Management Chain
    supervisory_chain = management_data.get("Worker_Supervisory_Management_Chain_Data", {}) or {}
    management_chain_data = supervisory_chain.get("Management_Chain_Data", [])
    
    management_chain = []
    direct_manager_id = None
    direct_manager_name = None
    
    if isinstance(management_chain_data, list):
        for level in management_chain_data:
            if isinstance(level, dict):
                # Extract organization info
                org_ref = level.get("Organization_Reference", {}) or {}
                org_ids = org_ref.get("ID", [])
                organization_id = extract_by_type(org_ids, "Organization_Reference_ID")
                organization_name = org_ref.get("Descriptor")
                
                # Extract manager info from Manager_Reference
                manager_ref = level.get("Manager_Reference", [])
                if isinstance(manager_ref, list) and manager_ref:
                    manager_ref = manager_ref[0]  # Take first manager reference
                
                manager_id = None
                manager_name = None
                
                if isinstance(manager_ref, dict):
                    manager_ids = manager_ref.get("ID", [])
                    # Try Employee_ID first, fallback to Contingent_Worker_ID
                    manager_id = extract_by_type(manager_ids, "Employee_ID") or extract_by_type(manager_ids, "Contingent_Worker_ID")
                    manager_name = manager_ref.get("Descriptor")

                # Extract manager name from Manager field (which has Worker_Descriptor)
                manager_data = level.get("Manager", [])
                if isinstance(manager_data, list) and manager_data:
                    manager_item = manager_data[0]
                    if isinstance(manager_item, dict):
                        # Get the name from Worker_Descriptor
                        manager_name = manager_item.get("Worker_Descriptor")

                # If this is the first level (direct manager), store it separately
                if direct_manager_id is None:
                    direct_manager_id = manager_id
                    direct_manager_name = manager_name

                # Add to management chain
                management_chain.append({
                    "organization_id": organization_id,
                    "organization_name": organization_name,
                    "manager_id": manager_id,
                    "manager_name": manager_name
                })

    # Matrix Management Chain
    matrix_chain = management_data.get("Worker_Matrix_Management_Chain_Data", {}) or {}
    matrix_management_chain_data = matrix_chain.get("Management_Chain_Data", [])

    matrix_management_chain = []

    if isinstance(matrix_management_chain_data, list):
        for level in matrix_management_chain_data:
            if isinstance(level, dict):
                # Extract organization info
                org_ref = level.get("Organization_Reference", {}) or {}
                org_ids = org_ref.get("ID", [])
                organization_id = extract_by_type(org_ids, "Organization_Reference_ID")
                organization_name = org_ref.get("Descriptor")

                # Extract manager info from Manager_Reference
                manager_ref = level.get("Manager_Reference", [])
                if isinstance(manager_ref, list) and manager_ref:
                    manager_ref = manager_ref[0]  # Take first manager reference

                manager_id = None
                manager_name = None

                if isinstance(manager_ref, dict):
                    manager_ids = manager_ref.get("ID", [])
                    # Try Employee_ID first, fallback to Contingent_Worker_ID
                    manager_id = extract_by_type(manager_ids, "Employee_ID") or extract_by_type(manager_ids, "Contingent_Worker_ID")
                    manager_name = manager_ref.get("Descriptor")
                
                # Extract manager name from Manager field (which has Worker_Descriptor)
                manager_data = level.get("Manager", [])
                if isinstance(manager_data, list) and manager_data:
                    manager_item = manager_data[0]
                    if isinstance(manager_item, dict):
                        # Get the name from Worker_Descriptor
                        manager_name = manager_item.get("Worker_Descriptor")
                
                # Add to matrix management chain
                matrix_management_chain.append({
                    "organization_id": organization_id,
                    "organization_name": organization_name,
                    "manager_id": manager_id,
                    "manager_name": manager_name
                })
    
    return {
        "management_chain": management_chain,
        "direct_manager_id": direct_manager_id,
        "direct_manager_name": direct_manager_name,
        "matrix_management_chain": matrix_management_chain,
    }

def parse_position_management_chain_data(worker_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse management chain data from Position_Management_Chains_Data.
    This is different from Worker_Management_Chain_Data and contains the actual management chain.
    """
    employment = worker_data.get("Employment_Data", {}) or {}
    wjd_list = ensure_list(employment.get("Worker_Job_Data"))
    wjd = wjd_list[0] if wjd_list else {}
    pos = wjd.get("Position_Data", {}) or {}
    
    # Get Position Management Chains Data
    position_management_chains = pos.get("Position_Management_Chains_Data", {}) or {}
    
    # Supervisory Management Chain
    supervisory_chain = position_management_chains.get("Position_Supervisory_Management_Chain_Data", {}) or {}
    management_chain_data = supervisory_chain.get("Management_Chain_Data", [])
    
    management_chain = []
    direct_manager_id = None
    direct_manager_name = None
    
    if isinstance(management_chain_data, list):
        for level in management_chain_data:
            if isinstance(level, dict):
                # Extract organization info
                org_ref = level.get("Organization_Reference", {}) or {}
                org_ids = org_ref.get("ID", [])
                organization_id = extract_by_type(org_ids, "Organization_Reference_ID")
                organization_name = org_ref.get("Descriptor")
                
                # Extract manager info from Manager_Reference
                manager_ref = level.get("Manager_Reference", [])
                if isinstance(manager_ref, list) and manager_ref:
                    manager_ref = manager_ref[0]  # Take first manager reference
                
                manager_id = None
                manager_name = None
                
                if isinstance(manager_ref, dict):
                    manager_ids = manager_ref.get("ID", [])
                    # Try Employee_ID first, fallback to Contingent_Worker_ID
                    manager_id = extract_by_type(manager_ids, "Employee_ID") or extract_by_type(manager_ids, "Contingent_Worker_ID")
                    manager_name = manager_ref.get("Descriptor")

                # Extract manager name from Manager field (which has Worker_Descriptor)
                manager_data = level.get("Manager", [])
                if isinstance(manager_data, list) and manager_data:
                    manager_item = manager_data[0]
                    if isinstance(manager_item, dict):
                        # Get the name from Worker_Descriptor
                        manager_name = manager_item.get("Worker_Descriptor")

                # If this is the first level (direct manager), store it separately
                if direct_manager_id is None:
                    direct_manager_id = manager_id
                    direct_manager_name = manager_name

                # Add to management chain
                management_chain.append({
                    "organization_id": organization_id,
                    "organization_name": organization_name,
                    "manager_id": manager_id,
                    "manager_name": manager_name
                })

    # Matrix Management Chain
    matrix_chain = position_management_chains.get("Position_Matrix_Management_Chain_Data", {}) or {}
    matrix_management_chain_data = matrix_chain.get("Management_Chain_Data", [])

    matrix_management_chain = []

    if isinstance(matrix_management_chain_data, list):
        for level in matrix_management_chain_data:
            if isinstance(level, dict):
                # Extract organization info
                org_ref = level.get("Organization_Reference", {}) or {}
                org_ids = org_ref.get("ID", [])
                organization_id = extract_by_type(org_ids, "Organization_Reference_ID")
                organization_name = org_ref.get("Descriptor")

                # Extract manager info from Manager_Reference
                manager_ref = level.get("Manager_Reference", [])
                if isinstance(manager_ref, list) and manager_ref:
                    manager_ref = manager_ref[0]  # Take first manager reference

                manager_id = None
                manager_name = None

                if isinstance(manager_ref, dict):
                    manager_ids = manager_ref.get("ID", [])
                    # Try Employee_ID first, fallback to Contingent_Worker_ID
                    manager_id = extract_by_type(manager_ids, "Employee_ID") or extract_by_type(manager_ids, "Contingent_Worker_ID")
                    manager_name = manager_ref.get("Descriptor")
                
                # Extract manager name from Manager field (which has Worker_Descriptor)
                manager_data = level.get("Manager", [])
                if isinstance(manager_data, list) and manager_data:
                    manager_item = manager_data[0]
                    if isinstance(manager_item, dict):
                        # Get the name from Worker_Descriptor
                        manager_name = manager_item.get("Worker_Descriptor")
                
                # Add to matrix management chain
                matrix_management_chain.append({
                    "organization_id": organization_id,
                    "organization_name": organization_name,
                    "manager_id": manager_id,
                    "manager_name": manager_name
                })
    
    return {
        "management_chain": management_chain,
        "direct_manager_id": direct_manager_id,
        "direct_manager_name": direct_manager_name,
        "matrix_management_chain": matrix_management_chain,
    }

def parse_payroll_and_tax_data(worker_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse payroll and tax related data from Position_Data.
    """
    employment = worker_data.get("Employment_Data", {}) or {}
    wjd_list = ensure_list(employment.get("Worker_Job_Data"))
    wjd = wjd_list[0] if wjd_list else {}
    pos = wjd.get("Position_Data", {}) or {}
    
    # Federal Withholding FEIN
    federal_withholding_fein = pos.get("Federal_Withholding_FEIN")
    
    # Workers Compensation Code
    workers_compensation_code = None
    wc_data = ensure_list(pos.get("Worker_Compensation_Code_Data", []))
    if wc_data:
        wc_item = first(wc_data)
        workers_compensation_code = wc_item.get("Workers_Compensation_Code")

    # Payroll Interface Processing Data
    payroll_frequency = None
    payroll_data = first(pos.get("Payroll_Interface_Processing_Data", {}))
    freq_ref = first(payroll_data.get("Frequency_Reference", {}))
    freq_ids = freq_ref.get("ID", []) or []
    payroll_frequency = extract_by_type(freq_ids, "Frequency_ID")

    # Manager as of last detected manager change
    last_detected_manager_id = None
    last_detected_manager_name = None
    manager_ref = first(pos.get("Manager_as_of_last_detected_manager_change_Reference", {}))
    manager_ids = manager_ref.get("ID", []) or []
    # Try Employee_ID first, fallback to Contingent_Worker_ID
    last_detected_manager_id = extract_by_type(manager_ids, "Employee_ID") or extract_by_type(manager_ids, "Contingent_Worker_ID")
    last_detected_manager_name = manager_ref.get("Descriptor")
    

    return {
        "federal_withholding_fein": federal_withholding_fein,
        "workers_compensation_code": workers_compensation_code,
        "payroll_frequency": payroll_frequency,
        "last_detected_manager_id": last_detected_manager_id,
        "last_detected_manager_name": last_detected_manager_name,
    }

def parse_position_organizations(worker_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse position organization data from Position_Organizations_Data.
    This includes support roles and detailed organization hierarchies.
    """
    employment = worker_data.get("Employment_Data", {}) or {}
    wjd_list = ensure_list(employment.get("Worker_Job_Data"))
    wjd = wjd_list[0] if wjd_list else {}
    pos = wjd.get("Position_Data", {}) or {}

    # Get Position Organizations Data
    pos_orgs_data = pos.get("Position_Organizations_Data", {}) or {}
    pos_org_entries = ensure_list(pos_orgs_data.get("Position_Organization_Data", []))

    position_organizations = []

    for org_entry in pos_org_entries:
        if not isinstance(org_entry, dict):
            continue

        # Extract organization reference
        org_ref = first(org_entry.get("Organization_Reference", {}))
        org_ids = org_ref.get("ID", []) or []
        org_ref_id = extract_by_type(org_ids, "Organization_Reference_ID")

        # Extract organization data
        org_data = first(org_entry.get("Organization_Data", {}))
        org_name = org_data.get("Organization_Name")
        org_code = org_data.get("Organization_Code")

        # Organization type
        org_type_ref = first(org_data.get("Organization_Type_Reference", {}))
        org_type_ids = org_type_ref.get("ID", []) or []
        org_type = extract_by_type(org_type_ids, "Organization_Type_ID")

        # Organization subtype
        org_subtype_ref = first(org_data.get("Organization_Subtype_Reference", {}))
        org_subtype_ids = org_subtype_ref.get("ID", []) or []
        org_subtype = extract_by_type(org_subtype_ids, "Organization_Subtype_ID")

        # Support roles for this organization
        support_roles = []
        org_support_role_data = first(org_data.get("Organization_Support_Role_Data", {}))
        support_role_entries = ensure_list(org_support_role_data.get("Organization_Support_Role", []))

        for role_entry in support_role_entries:
            if not isinstance(role_entry, dict):
                continue

            # Role reference
            role_ref = first(role_entry.get("Organization_Role_Reference", {}))
            role_ids = role_ref.get("ID", []) or []
            role_id = extract_by_type(role_ids, "Organization_Role_ID")

            # Workers assigned to this role
            role_data_entries = ensure_list(role_entry.get("Organization_Role_Data", []))
            assigned_workers = []

            for role_data in role_data_entries:
                if not isinstance(role_data, dict):
                    continue

                worker_ref = first(role_data.get("Worker_Reference", {}))
                worker_ids = worker_ref.get("ID", []) or []
                # Try Employee_ID first, fallback to Contingent_Worker_ID
                worker_id = extract_by_type(worker_ids, "Employee_ID") or extract_by_type(worker_ids, "Contingent_Worker_ID")
                assignment_from = role_data.get("Assignment_From")

                if worker_id:
                    assigned_workers.append({
                        "worker_id": worker_id,
                        "assignment_from": assignment_from
                    })

            if role_id:
                support_roles.append({
                    "role_id": role_id,
                    "assigned_workers": assigned_workers
                })

        position_organizations.append({
            "organization_reference_id": org_ref_id,
            "organization_name": org_name,
            "organization_code": org_code,
            "organization_type": org_type,
            "organization_subtype": org_subtype,
            "support_roles": support_roles
        })

    return {
        "position_organizations": position_organizations or None
    }

def parse_international_assignment_data(worker_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse international assignment summary data.
    """
    employment = worker_data.get("Employment_Data", {}) or {}
    intl_assignment = first(employment.get("International_Assignment_Summary_Data", {}))

    has_international_assignment = intl_assignment.get("Has_International_Assignment")
    if has_international_assignment is not None:
        has_international_assignment = bool(has_international_assignment)

    return {
        "has_international_assignment": has_international_assignment
    }

# ———————————————————————————————————————————————————————————————————
# Internal helpers for compensation
# ———————————————————————————————————————————————————————————————————

def _parse_salary_nodes(salary_nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for s in salary_nodes:
        if not s:
            continue

        plan_id = extract_by_type(
            s.get("Compensation_Plan_Reference", {}).get("ID", []),
            "Compensation_Plan_ID"
        )
        elem_id = extract_by_type(
            s.get("Compensation_Element_Reference", {}).get("ID", []),
            "Compensation_Element_ID"
        )
        curr_id = extract_by_type(
            s.get("Currency_Reference", {}).get("ID", []),
            "Currency_ID"
        )
        freq_id = extract_by_type(
            s.get("Frequency_Reference", {}).get("ID", []),
            "Frequency_ID"
        )

        eff = s.get("Assignment_Effective_Date")

        result.append({
            "plan":                      plan_id,
            "element":                   elem_id,
            "amount":                    s.get("Amount"),
            "currency":                  curr_id,
            "frequency":                 freq_id,
            "assignment_effective_date": str(eff) if eff else None,
        })
    return result


def _get_summary_section(comp_section: Dict[str, Any], key: str) -> Dict[str, Any]:
    """
    Extrae una sección de resumen asegurándose de:
      - Si viene como lista, tomar el primer elemento.
      - Si viene anidada bajo la misma clave, bajar un nivel.
    """
    sec = comp_section.get(key) or {}
    # si es lista, tomar primer elemento
    if isinstance(sec, list):
        sec = sec[0] if sec else {}
    # si es dict y contiene la misma clave, desanidar
    if isinstance(sec, dict) and key in sec:
        inner = sec[key]
        if isinstance(inner, list):
            sec = inner[0] if inner else {}
        elif isinstance(inner, dict):
            sec = inner
    return sec or {}

def _parse_compensation_summary(comp_section: Dict[str, Any]) -> Dict[str, Any]:
    """
    Devuelve los resúmenes de compensación en un dict con claves:
    employee, annualized, pay_group, annualized_reporting, hourly
    """
    def _parse_summary(sd: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        # Si sd es None o un dict vacío -> no hay summary
        if not sd:
            return None

        # Currency: protege Currency_Reference == None
        curr_ref = sd.get("Currency_Reference") or {}
        curr_ids = curr_ref.get("ID") or []
        currency = extract_by_type(curr_ids, "Currency_ID")

        # Frequency: protege Frequency_Reference == None
        freq_ref = sd.get("Frequency_Reference") or {}
        freq_ids = freq_ref.get("ID") or []
        frequency = extract_by_type(freq_ids, "Frequency_ID")

        return {
            "total_base_pay":              sd.get("Total_Base_Pay"),
            "total_salary_and_allowances": sd.get("Total_Salary_and_Allowances"),
            "primary_compensation_basis":  sd.get("Primary_Compensation_Basis"),
            "currency":                    currency,
            "frequency":                   frequency,
        }

    return {
        "employee":             _parse_summary(_get_summary_section(comp_section, "Employee_Compensation_Summary_Data")),
        "annualized":           _parse_summary(_get_summary_section(comp_section, "Annualized_Summary_Data")),
        "pay_group":            _parse_summary(_get_summary_section(comp_section, "Summary_Data_in_Pay_Group_Frequency")),
        "annualized_reporting": _parse_summary(_get_summary_section(comp_section, "Annualized_in_Reporting_Currency_Summary_Data")),
        "hourly":               _parse_summary(_get_summary_section(comp_section, "Summary_Data_in_Hourly_Frequency")),
    }

def _extract_gender(country_info: Dict[str, Any]) -> Optional[str]:

    if not isinstance(country_info, dict):
        return None
    for cp in ensure_list(country_info.get("Country_Personal_Information_Data")):
        if not isinstance(cp, dict):
            continue
        gender_ref = cp.get("Gender_Reference", {}) or {}
        for gid in ensure_list(gender_ref.get("ID")):
            if gid.get("type") == "Gender_Code":
                return gid.get("_value_1")
    return None

def _extract_ethnicity(country_info: Dict[str, Any]) -> Optional[str]:

    if not isinstance(country_info, dict):
        return None
    for cp in ensure_list(country_info.get("Country_Personal_Information_Data")):
        if not isinstance(cp, dict):
            continue
        for eth_ref in ensure_list(cp.get("Ethnicity_Reference")):
            if not isinstance(eth_ref, dict):
                continue
            for eid in ensure_list(eth_ref.get("ID")):
                if eid.get("type") == "Ethnicity_ID":
                    return eid.get("_value_1")
    return None

__all__ = [
    "parse_worker_reference",
    "parse_personal_data",
    "parse_contact_data",
    "parse_worker_organization_data",
    "parse_compensation_data",
    "parse_identification_data",
    "parse_benefits_and_roles",
    "parse_employment_data",
    "parse_worker_status",
    "parse_business_site",
    "parse_management_chain_data",
    "parse_position_management_chain_data",
    "parse_payroll_and_tax_data",
    "parse_position_organizations",
    "parse_international_assignment_data",
]
