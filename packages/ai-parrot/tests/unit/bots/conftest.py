"""Shared fixtures for the Flex A2UI dashboard agent tests (FEAT-491).

``flex_frames`` provides synthetic frames for all six Flex dataset aliases
(spec §2), shaped EXACTLY like the sample rows in
``sdd/state/FEAT-517/source.md``: currency strings, the three date-grain
conventions, and the ``catagory`` typo column — with a couple of extra rows
per frame (different months / pay codes / stores) so month-series and
per-section-filter tests (TASK-2694) have something to group and filter
over. No network/database access — everything here is inline data.
"""

from __future__ import annotations

import pandas as pd
import pytest


@pytest.fixture
def flex_frames() -> dict[str, pd.DataFrame]:
    """Synthetic frames for all six Flex dataset aliases (spec §2).

    Returns:
        A dict keyed by alias (``msl``, ``finance``, ``hours``,
        ``employees``, ``region_utilization``, ``rep_utilization``) mapping
        to a fresh :class:`pandas.DataFrame` per test.
    """
    msl = pd.DataFrame(
        [
            {
                "district_name": "IL - Chicago",
                "region_name": "Midwest Region",
                "market_name": "IL - Chicago - Oak Park",
                "account_name": "T-Mobile",
                "store_name": "T-Mobile 3SFD Norridge IL",
                "latitude": 41.95535,
                "longitude": -87.80886,
                "city": "Norridge",
                "state_code": "IL",
            },
            {
                "district_name": "PA - Philadelphia",
                "region_name": "Northeast Region",
                "market_name": "PA - Philadelphia - Media",
                "account_name": "T-Mobile",
                "store_name": "T-Mobile Media PA",
                "latitude": 39.9168,
                "longitude": -75.3902,
                "city": "Media",
                "state_code": "PA",
            },
            {
                "district_name": "CA - Los Angeles",
                "region_name": "West Region",
                "market_name": "CA - LA - Downtown",
                "account_name": "T-Mobile",
                "store_name": "T-Mobile Downtown LA",
                "latitude": 34.0407,
                "longitude": -118.2468,
                "city": "Los Angeles",
                "state_code": "CA",
            },
        ]
    )

    finance = pd.DataFrame(
        [
            {
                "project": "Flex - General",
                "month": "2025-09-30",
                "Revenue": "$120,000.00",
                "PC Revenue": "$40,000.00",
                "EBITDA": "$9,000.00",
                "Payroll": "$18,000.00",
                "Travel and Expenses": "$12,000.00",
                "Program Overhead Allocation": "$0.00",
                "Other Related Expenses": "-$40,000.00",
                "Total Hours": 2100.0,
                "FTE": 16.5,
                "Visits": 220,
            },
            {
                "project": "Flex - General",
                "month": "2025-10-31",
                "Revenue": "$137,456.85",
                "PC Revenue": "$51,229.85",
                "EBITDA": "$10,222.16",
                "Payroll": "$20,682.27",
                "Travel and Expenses": "$13,746.44",
                "Program Overhead Allocation": "$0.00",
                "Other Related Expenses": "-$44,621.24",
                "Total Hours": 2250.866693,
                "FTE": 17.278409301948,
                "Visits": 241,
            },
        ]
    )

    hours = pd.DataFrame(
        [
            {
                "month_start": "2025-09-01",
                "month_end": "2025-09-30",
                "program": "Flex - General",
                "pay_code": "Admin Time",
                "cost_center": "Flex",
                "hours": 25.0,
                "wages": 575.0,
            },
            {
                "month_start": "2025-09-01",
                "month_end": "2025-09-30",
                "program": "Flex - General",
                "pay_code": "Field Time",
                "cost_center": "Flex",
                "hours": 1800.0,
                "wages": 41000.0,
            },
            {
                "month_start": "2025-10-01",
                "month_end": "2025-10-31",
                "program": "Flex - General",
                "pay_code": "Admin Time",
                "cost_center": "Flex",
                "hours": 30.199996,
                "wages": 693.749909,
            },
            {
                "month_start": "2025-10-01",
                "month_end": "2025-10-31",
                "program": "Flex - General",
                "pay_code": "Field Time",
                "cost_center": "Flex",
                "hours": 1900.0,
                "wages": 43000.0,
            },
        ]
    )

    employees = pd.DataFrame(
        [
            {
                "display_name": "Abby Halladay",
                "start_date": "2025-12-31",
                "job_code_title": "Mobile Retail Display Technician",
                "referred_by": None,
                "legal_city": "MEDIA",
                "legal_state": "PA",
                "zipcode": "19063",
                "phone_mobile": "(267) 346-0701",
                "latitude": 39.9222285,
                "longitude": -75.414058,
                "Flex Employees": 1,
                "Flex Type": "Flex",
                "Years of Service": 1,
                "Months of Service": 8,
                "Days of Service": 244,
                "Days of Service Retention": 244,
            },
            {
                "display_name": "Jordan Reyes",
                "start_date": "2025-06-15",
                "job_code_title": "Retail Sales Associate",
                "referred_by": None,
                "legal_city": "Norridge",
                "legal_state": "IL",
                "zipcode": "60706",
                "phone_mobile": "(312) 555-0100",
                "latitude": 41.9600,
                "longitude": -87.8100,
                "Flex Employees": 1,
                "Flex Type": "Flex",
                "Years of Service": 2,
                "Months of Service": 3,
                "Days of Service": 825,
                "Days of Service Retention": 825,
            },
            {
                "display_name": "Casey Kim",
                "start_date": "2024-01-01",
                "job_code_title": "Store Manager",
                "referred_by": "Referral Program",
                "legal_city": "Los Angeles",
                "legal_state": "CA",
                "zipcode": "90012",
                "phone_mobile": "(213) 555-0199",
                "latitude": 34.0500,
                "longitude": -118.2500,
                "Flex Employees": 0,
                "Flex Type": "Core",
                "Years of Service": 3,
                "Months of Service": 0,
                "Days of Service": 1095,
                "Days of Service Retention": 1095,
            },
        ]
    )

    region_utilization = pd.DataFrame(
        [
            {
                "BOP Date": "2026-03-01",
                "EOP Date": "2026-03-31",
                "FM Region": "CA",
                "State Code": "CA",
                "State": "California",
                "Category": "Flex",
                "Employees Worked": 11,
                "Average Active Employees": 75.5,
                "Flex Employees": 68,
                "Employee Utilization": 0.145695364238411,
            },
            {
                "BOP Date": "2026-04-01",
                "EOP Date": "2026-04-30",
                "FM Region": "IL",
                "State Code": "IL",
                "State": "Illinois",
                "Category": "Flex",
                "Employees Worked": 15,
                "Average Active Employees": 60.0,
                "Flex Employees": 50,
                "Employee Utilization": 0.25,
            },
        ]
    )

    rep_utilization = pd.DataFrame(
        [
            {
                "bop_date": "2026-05-01",
                "eop_date": "2026-05-31",
                "region": "CA",
                "state": "CA",
                "catagory": "Flex",
                "hours_worked": 167.550001,
                "work_shifts": 76,
                "employees_worked": 12,
                "average_active": 63,
            },
            {
                "bop_date": "2026-06-01",
                "eop_date": "2026-06-30",
                "region": "IL",
                "state": "IL",
                "catagory": "Flex",
                "hours_worked": 140.0,
                "work_shifts": 60,
                "employees_worked": 10,
                "average_active": 50,
            },
        ]
    )

    return {
        "msl": msl,
        "finance": finance,
        "hours": hours,
        "employees": employees,
        "region_utilization": region_utilization,
        "rep_utilization": rep_utilization,
    }
