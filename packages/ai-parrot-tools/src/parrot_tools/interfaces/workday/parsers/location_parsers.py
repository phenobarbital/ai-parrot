# workday/parsers/location_parsers.py

from typing import Any, Dict, List, Optional
from datetime import date
from decimal import Decimal
from ..utils import ensure_list

def parse_location_data(location_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse the main location data from Workday response.
    """
    if not location_data:
        return {}

    # Extract location reference
    location_ref = location_data.get("Location_Reference", {})
    location_id = None
    if isinstance(location_ref, dict):
        # Look for Location_ID
        ids = location_ref.get("ID", [])
        if isinstance(ids, list):
            for id_item in ids:
                if isinstance(id_item, dict) and id_item.get("type") == "Location_ID":
                    location_id = id_item.get("_value_1")
                    break

    # Extract location data
    location_info = location_data.get("Location_Data", {})

    # Fallback: Try to get location_id from Location_Data if not found in reference
    if not location_id and location_info:
        location_id = location_info.get("Location_ID")

    # Basic fields
    location_name = location_info.get("Location_Name")
    effective_date = _parse_date(location_info.get("Effective_Date"))
    inactive = location_info.get("Inactive", False)
    
    # Location type
    location_type = _parse_location_type(location_info.get("Location_Type_Reference"))
    
    # Location usage
    location_usage = _parse_location_usage(location_info.get("Location_Usage_Reference"))
    
    # Location attributes
    location_attributes = _parse_location_attributes(location_info.get("Location_Attribute_Reference"))
    
    # Superior location
    superior_location_id, superior_location_name = _parse_superior_location(
        location_info.get("Superior_Location_Reference")
    )
    
    # Coordinates
    latitude = _parse_coordinate(location_info.get("Latitude"))
    longitude = _parse_coordinate(location_info.get("Longitude"))
    altitude = _parse_coordinate(location_info.get("Altitude"))
    allow_duplicate_coordinates = location_info.get("Allow_Duplicate_Coordinates", False)
    
    # Address information
    contact_data = location_info.get("Contact_Data", {})
    
    # Handle Address_Data as list or dict
    address_data_list = contact_data.get("Address_Data", []) if contact_data else []
    if isinstance(address_data_list, list):
        # Take the first address if it's a list
        address_data = address_data_list[0] if address_data_list else {}
    else:
        # If it's already a dict, use it directly
        address_data = address_data_list
    
    formatted_address = address_data.get("Formatted_Address") if isinstance(address_data, dict) else None
    municipality = address_data.get("Municipality") if isinstance(address_data, dict) else None
    postal_code = address_data.get("Postal_Code") if isinstance(address_data, dict) else None
    
    # Try to get effective_date from address_data if not available in main
    if effective_date is None and isinstance(address_data, dict):
        address_effective_date = address_data.get("Effective_Date")
        if address_effective_date:
            effective_date = _parse_date(address_effective_date)
    
    # Address line data - get the actual content, not the descriptor
    address_line_1 = None
    if isinstance(address_data, dict):
        address_line_data = address_data.get("Address_Line_Data", [])
        if isinstance(address_line_data, list):
            for line in address_line_data:
                if isinstance(line, dict) and line.get("Type") == "ADDRESS_LINE_1":
                    # Get the actual content, not the descriptor
                    address_line_1 = line.get("_value_1") or line.get("Descriptor")
                    break
    
    # Country and region
    country = _parse_country(address_data.get("Country_Reference") if isinstance(address_data, dict) else None)
    country_region = _parse_country_region(address_data.get("Country_Region_Reference") if isinstance(address_data, dict) else None)
    
    # Additional fields
    time_profile = _parse_time_profile(location_info.get("Time_Profile_Reference"))
    locale = _parse_locale(location_info.get("Locale_Reference"))
    user_language = location_info.get("User_Language")
    time_zone = _parse_time_zone(location_info.get("Time_Zone_Reference"))
    currency = _parse_currency(location_info.get("Default_Currency_Reference"))
    trade_name = location_info.get("Trade_Name")
    worksite_id = location_info.get("Worksite_ID")
    default_job_posting_location = _parse_default_job_posting_location(
        location_info.get("Default_Job_Posting_Location_Reference")
    )
    location_hierarchy = _parse_location_hierarchy(
        location_info.get("Location_Hierarchy_Reference")
    )
    
    return {
        "location_id": location_id,
        "location_name": location_name,
        "effective_date": effective_date,
        "inactive": inactive,
        "location_type": location_type,
        "location_usage": location_usage,
        "location_attributes": location_attributes,
        "superior_location_id": superior_location_id,
        "superior_location_name": superior_location_name,
        "latitude": latitude,
        "longitude": longitude,
        "altitude": altitude,
        "allow_duplicate_coordinates": allow_duplicate_coordinates,
        "formatted_address": formatted_address,
        "address_line_1": address_line_1,
        "municipality": municipality,
        "postal_code": postal_code,
        "country": country,
        "country_region": country_region,
        "time_profile": time_profile,
        "locale": locale,
        "user_language": user_language,
        "time_zone": time_zone,
        "currency": currency,
        "trade_name": trade_name,
        "worksite_id": worksite_id,
        "default_job_posting_location": default_job_posting_location,
        "location_hierarchy": location_hierarchy,
    }

def _parse_date(date_value: Any) -> Optional[date]:
    """Parse date value from Workday response"""
    if not date_value:
        return None
    
    try:
        if isinstance(date_value, str):
            result = date.fromisoformat(date_value)
            return result
        elif isinstance(date_value, date):
            return date_value
        elif hasattr(date_value, 'date'):
            result = date_value.date()
            return result
        return None
    except (ValueError, AttributeError):
        return None

def _parse_location_type(type_ref: Any) -> Optional[str]:
    """Parse location type from reference"""
    if not type_ref:
        return None
    
    # Handle case where type_ref is a list
    if isinstance(type_ref, list):
        type_ref = type_ref[0] if type_ref else None
    
    if isinstance(type_ref, dict):
        ids = type_ref.get("ID", [])
        if isinstance(ids, list):
            for id_item in ids:
                if isinstance(id_item, dict) and id_item.get("type") == "Location_Type_ID":
                    result = id_item.get("_value_1")
                    return result
    return None

def _parse_location_usage(usage_ref: Any) -> List[str]:
    """Parse location usage from reference"""
    if not usage_ref:
        return []
    
    usages = ensure_list(usage_ref)
    result = []
    
    for usage in usages:
        if isinstance(usage, dict):
            ids = usage.get("ID", [])
            if isinstance(ids, list):
                for id_item in ids:
                    if isinstance(id_item, dict) and id_item.get("type") == "Location_Usage_ID":
                        result.append(id_item.get("_value_1"))
                        break
        elif usage:
            result.append(str(usage))
    
    return result

def _parse_location_attributes(attr_ref: Any) -> List[str]:
    """Parse location attributes from reference"""
    if not attr_ref:
        return []
    
    attrs = ensure_list(attr_ref)
    result = []
    
    for attr in attrs:
        if isinstance(attr, dict):
            ids = attr.get("ID", [])
            if isinstance(ids, list):
                for id_item in ids:
                    if isinstance(id_item, dict) and id_item.get("type") == "Location_Attribute_ID":
                        result.append(id_item.get("_value_1"))
                        break
        elif attr:
            result.append(str(attr))
    
    return result

def _parse_superior_location(superior_ref: Any) -> tuple[Optional[str], Optional[str]]:
    """Parse superior location from reference"""
    if not superior_ref or not isinstance(superior_ref, dict):
        return None, None
    
    location_id = None
    location_name = None
    
    ids = superior_ref.get("ID", [])
    if isinstance(ids, list):
        for id_item in ids:
            if isinstance(id_item, dict) and id_item.get("type") == "Location_ID":
                location_id = id_item.get("_value_1")
                break
    
    location_name = superior_ref.get("Descriptor")
    
    return location_id, location_name

def _parse_coordinate(coord_value: Any) -> Optional[float]:
    """Parse coordinate value from Workday response"""
    if coord_value is None:
        return None
    
    try:
        if isinstance(coord_value, (int, float, Decimal)):
            return float(coord_value)
        elif isinstance(coord_value, str):
            return float(coord_value)
        return None
    except (ValueError, TypeError):
        return None

def _parse_time_profile(profile_ref: Any) -> Optional[str]:
    """Parse time profile from reference"""
    if not profile_ref or not isinstance(profile_ref, dict):
        return None
    
    ids = profile_ref.get("ID", [])
    if isinstance(ids, list):
        for id_item in ids:
            if isinstance(id_item, dict) and id_item.get("type") == "Time_Profile_ID":
                return id_item.get("_value_1")
    return None

def _parse_locale(locale_ref: Any) -> Optional[str]:
    """Parse locale from reference"""
    if not locale_ref or not isinstance(locale_ref, dict):
        return None
    
    ids = locale_ref.get("ID", [])
    if isinstance(ids, list):
        for id_item in ids:
            if isinstance(id_item, dict) and id_item.get("type") == "Locale_ID":
                return id_item.get("_value_1")
    return None

def _parse_time_zone(timezone_ref: Any) -> Optional[str]:
    """Parse time zone from reference"""
    if not timezone_ref or not isinstance(timezone_ref, dict):
        return None
    
    ids = timezone_ref.get("ID", [])
    if isinstance(ids, list):
        for id_item in ids:
            if isinstance(id_item, dict) and id_item.get("type") == "Time_Zone_ID":
                return id_item.get("_value_1")
    return None

def _parse_currency(currency_ref: Any) -> Optional[str]:
    """Parse currency from reference"""
    if not currency_ref or not isinstance(currency_ref, dict):
        return None
    
    ids = currency_ref.get("ID", [])
    if isinstance(ids, list):
        for id_item in ids:
            if isinstance(id_item, dict) and id_item.get("type") == "Currency_ID":
                return id_item.get("_value_1")
    return None

def _parse_country(country_ref: Any) -> Optional[str]:
    """Parse country from reference"""
    if not country_ref or not isinstance(country_ref, dict):
        return None
    
    ids = country_ref.get("ID", [])
    if isinstance(ids, list):
        for id_item in ids:
            if isinstance(id_item, dict) and id_item.get("type") == "ISO_3166-1_Alpha-2_Code":
                return id_item.get("_value_1")
    return None

def _parse_country_region(region_ref: Any) -> Optional[str]:
    """Parse country region from reference"""
    if not region_ref or not isinstance(region_ref, dict):
        return None
    
    ids = region_ref.get("ID", [])
    if isinstance(ids, list):
        for id_item in ids:
            if isinstance(id_item, dict) and id_item.get("type") == "ISO_3166-2_Code":
                return id_item.get("_value_1")
    return None

def _parse_default_job_posting_location(location_ref: Any) -> Optional[str]:
    """Parse default job posting location from reference"""
    if not location_ref or not isinstance(location_ref, dict):
        return None
    
    ids = location_ref.get("ID", [])
    if isinstance(ids, list):
        for id_item in ids:
            if isinstance(id_item, dict) and id_item.get("type") == "Location_ID":
                return id_item.get("_value_1")
    return None

def _parse_location_hierarchy(hierarchy_ref: Any) -> List[str]:
    """Parse location hierarchy from reference"""
    if not hierarchy_ref:
        return []
    
    hierarchies = ensure_list(hierarchy_ref)
    result = []
    
    for hierarchy in hierarchies:
        if isinstance(hierarchy, dict):
            ids = hierarchy.get("ID", [])
            if isinstance(ids, list):
                for id_item in ids:
                    if isinstance(id_item, dict) and id_item.get("type") == "Organization_Reference_ID":
                        result.append(id_item.get("_value_1"))
                        break
        elif hierarchy:
            result.append(str(hierarchy))
    
    return result 