"""TimeOffEligibilityType — read handler for Get_Time_Off_Types.

Fetches the list of time-off types a worker is eligible to request from
Workday Absence Management and returns them as a list of
``TimeOffEligibility`` Pydantic models via the standard handler contract.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from zeep.helpers import serialize_object

from parrot_tools.interfaces.workday.handlers.base import WorkdayTypeBase
from parrot_tools.interfaces.workday.models.time_off_eligibility import TimeOffEligibility


class TimeOffEligibilityType(WorkdayTypeBase):
    """Handler for ``Get_Time_Off_Types`` (Absence Management read op)."""

    async def execute(self, *, worker_id: str, **kwargs: Any) -> pd.DataFrame:
        """Fetch eligible time-off types for a worker.

        Args:
            worker_id: Workday Employee ID.

        Returns:
            DataFrame with columns: time_off_type_id, name, description, unit.
        """
        raw = await self.service.call_operation(
            "Get_Time_Off_Types",
            Request_Criteria={
                "Employee_Reference": {
                    "ID": [{"type": "Employee_ID", "_value_1": worker_id}]
                }
            },
            Response_Filter={"Page": 1, "Count": 100},
            Response_Group={
                "Include_Reference": True,
                "Include_Time_Off_Plan_Data": True,
            },
        )

        rows: list[dict] = []
        if raw:
            try:
                serialized = serialize_object(raw)
            except Exception:
                serialized = {}
            types = (
                serialized.get("Response_Data", {}).get("Time_Off_Type", [])
                if isinstance(serialized, dict)
                else []
            )
            if types and not isinstance(types, list):
                types = [types]
            for t in types:
                if not isinstance(t, dict):
                    continue
                type_data = t.get("Time_Off_Type_Data") or {}
                id_list = t.get("Time_Off_Type_ID") or []
                if not isinstance(id_list, list):
                    id_list = [id_list] if id_list else []
                type_id = id_list[0] if id_list else None
                unit_ref = type_data.get("Unit_of_Time_Reference") or {}
                unit_ids = unit_ref.get("ID") or []
                if not isinstance(unit_ids, list):
                    unit_ids = [unit_ids] if unit_ids else []
                unit = unit_ids[0].get("_value_1") if unit_ids else None
                rows.append(
                    TimeOffEligibility(
                        time_off_type_id=str(type_id) if type_id else None,
                        name=type_data.get("Name"),
                        description=type_data.get("Description"),
                        unit=unit,
                    ).model_dump()
                )
        return pd.DataFrame(rows)
