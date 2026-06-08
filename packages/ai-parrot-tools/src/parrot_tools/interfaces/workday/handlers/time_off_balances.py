from typing import Dict, Any, List
from datetime import datetime
import pandas as pd

from ..models.time_off_balance import TimeOffBalance
from ..parsers.time_off_balance_parsers import parse_time_off_balance_data
from .base import WorkdayTypeBase


class TimeOffBalanceType(WorkdayTypeBase):
    """
    Handles Get_Time_Off_Plan_Balances operation for Workday Absence Management API.
    """

    def _get_default_payload(self) -> Dict[str, Any]:
        """
        Get the default payload for Get_Time_Off_Plan_Balances operation.
        """
        return {
            "Response_Filter": {},
            "Response_Group": {
                "Include_Reference": True,
                "Include_Time_Off_Plan_Balance_Data": True,
            },
        }

    async def execute(self, **kwargs) -> pd.DataFrame:
        """
        Execute the Get_Time_Off_Plan_Balances operation.

        Supported parameters:
        - worker_id: Specific worker ID to fetch balances for (uses Employee_Reference)
        - time_off_plan_id: Specific time off plan ID (uses Time_Off_Plan_Reference)
        - organization_id: Organization ID to filter by (uses Organization_Reference)

        Note: This operation returns CURRENT balances only. There is no as_of_date parameter.
        """
        # Extract parameters from kwargs
        worker_id = kwargs.pop("worker_id", None)
        time_off_plan_id = kwargs.pop("time_off_plan_id", None)
        organization_id = kwargs.pop("organization_id", None)

        payload = self._get_default_payload()

        # Stable snapshot timestamp for pagination
        as_of_entry = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        payload["Response_Filter"]["As_Of_Entry_DateTime"] = as_of_entry

        # If searching by specific time off plan ID, use Request_References
        if time_off_plan_id and not worker_id and not organization_id:
            # Use Request_References when only searching by plan ID
            payload["Request_References"] = {
                "Time_Off_Plan_Reference": [
                    {
                        "ID": [
                            {
                                "_value_1": time_off_plan_id,
                                "type": "Time_Off_Plan_ID"
                            }
                        ]
                    }
                ]
            }
        else:
            # Otherwise, build Request_Criteria for filtering
            request_criteria = {}

            # Employee filter (uses Employee_Reference, not Worker_Reference)
            if worker_id:
                request_criteria["Employee_Reference"] = {
                    "ID": [
                        {
                            "_value_1": worker_id,
                            "type": "Employee_ID"
                        }
                    ]
                }

            # Time Off Plan filter
            if time_off_plan_id:
                request_criteria["Time_Off_Plan_Reference"] = {
                    "ID": [
                        {
                            "_value_1": time_off_plan_id,
                            "type": "Time_Off_Plan_ID"
                        }
                    ]
                }

            # Organization filter
            if organization_id:
                request_criteria["Organization_Reference"] = [
                    {
                        "ID": [
                            {
                                "_value_1": organization_id,
                                "type": "Organization_Reference_ID"
                            }
                        ]
                    }
                ]

            if request_criteria:
                payload["Request_Criteria"] = request_criteria

        # Keep current payload available for pagination helper
        self.request_payload = payload

        # Execute the operation with pagination
        try:
            # Note: data_path should only go to Response_Data, not Time_Off_Plan_Balance
            # because Time_Off_Plan_Balance can be a list or a single dict
            raw_response = await self._paginate_soap_operation(
                operation="Get_Time_Off_Plan_Balances",
                data_path=["Response_Data"],
                results_path=["Response_Results"],
                all_pages=True,
                **payload
            )

            # Extract Time_Off_Plan_Balance from the response
            balances_raw = []
            for item in raw_response:
                if isinstance(item, dict):
                    balance = item.get("Time_Off_Plan_Balance")
                    if balance:
                        # Ensure it's a list
                        if not isinstance(balance, list):
                            balance = [balance]
                        balances_raw.extend(balance)
                    else:
                        # The item itself might be the Time_Off_Plan_Balance
                        balances_raw.append(item)
        except Exception as e:
            self._logger.error(f"Error fetching time off balances: {e}")
            raise

        # Parse into Pydantic models
        parsed: List[TimeOffBalance] = []
        for i, balance in enumerate(balances_raw):
            try:
                # Parser returns a list of records (one per plan)
                parsed_records = parse_time_off_balance_data(balance)

                if not parsed_records:
                    self._logger.warning(f"No balance records found in response {i+1}")
                    continue

                # Create a TimeOffBalance for each plan
                for record in parsed_records:
                    record["raw_data"] = balance
                    time_off_balance = TimeOffBalance(**record)
                    parsed.append(time_off_balance)

            except Exception as e:
                self._logger.warning(f"Error parsing time off balance {i+1}: {e}")
                continue

        # Build DataFrame
        if parsed:
            df = pd.DataFrame([b.dict() for b in parsed])

            # Add metrics
            self.service.add_metric("NUM_TIME_OFF_BALANCES", len(parsed))

            return df
        else:
            return pd.DataFrame()

    async def get_balances_by_worker(self, worker_id: str) -> pd.DataFrame:
        """
        Convenience method to get current time off balances for a specific worker.
        """
        return await self.execute(worker_id=worker_id)

    async def get_balances_by_plan(self, time_off_plan_id: str) -> pd.DataFrame:
        """
        Convenience method to get current balances for a specific time off plan.
        """
        return await self.execute(time_off_plan_id=time_off_plan_id)

    async def get_balances_by_organization(self, organization_id: str) -> pd.DataFrame:
        """
        Convenience method to get current balances for a specific organization.
        """
        return await self.execute(organization_id=organization_id)
