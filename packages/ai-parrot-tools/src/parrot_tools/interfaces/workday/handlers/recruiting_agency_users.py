"""
Handler for the Workday Get_Recruiting_Agency_Users operation.
Uses serialize_object for dynamic field mapping.
"""
import asyncio
import math
from typing import List, Dict, Any
import pandas as pd

from .base import WorkdayTypeBase
from ..utils import safe_serialize


class RecruitingAgencyUsersType(WorkdayTypeBase):
    """
    Handler for Get_Recruiting_Agency_Users operation from Recruiting API.

    Uses serialize_object to dynamically map all fields from SOAP response without
    requiring manual parsers. All fields are preserved in the DataFrame.
    """

    def _get_default_payload(self) -> Dict[str, Any]:
        """
        Default payload for Get_Recruiting_Agency_Users.
        """
        return {
            "Response_Filter": {},
            "Response_Group": {
                "Include_Reference": True,
            },
        }

    def _flatten_dict(self, data: Dict[str, Any], parent_key: str = '', sep: str = '_') -> Dict[str, Any]:
        """
        Flatten nested dictionaries to single level.
        Example: {'a': {'b': 1}} -> {'a_b': 1}
        """
        items = []
        for k, v in data.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k

            if isinstance(v, dict):
                # Check if it's a Reference object with ID and Descriptor
                if 'ID' in v or 'Descriptor' in v:
                    # Extract just the Descriptor and ID values
                    if 'Descriptor' in v:
                        items.append((new_key, v['Descriptor']))
                    if 'ID' in v:
                        id_val = v['ID']
                        # If ID is a list, extract _value_1 from first item
                        if isinstance(id_val, list) and id_val:
                            if isinstance(id_val[0], dict) and '_value_1' in id_val[0]:
                                items.append((f"{new_key}_id", id_val[0]['_value_1']))
                        elif isinstance(id_val, dict) and '_value_1' in id_val:
                            items.append((f"{new_key}_id", id_val['_value_1']))
                else:
                    # Recursively flatten
                    items.extend(self._flatten_dict(v, new_key, sep=sep).items())
            elif isinstance(v, list):
                # Convert lists to JSON strings for storage
                items.append((new_key, safe_serialize(v)))
            else:
                items.append((new_key, v))
        return dict(items)

    async def execute(self, **kwargs) -> pd.DataFrame:
        """
        Execute Get_Recruiting_Agency_Users operation.

        Supported parameters:
        - recruiting_agency_user_id: Specific user ID to fetch
        - recruiting_agency_user_id_type: Type of ID (default: "Recruiting_Agency_User_ID")
        - flatten_response: Whether to flatten nested dicts (default: True)
        """
        # Extract parameters
        user_id = kwargs.pop("recruiting_agency_user_id", None)
        user_id_type = kwargs.pop("recruiting_agency_user_id_type", "Recruiting_Agency_User_ID")
        flatten_response = kwargs.pop("flatten_response", True)

        # Build request payload
        payload = {**self.request_payload}

        # Add Request_References for specific user
        if user_id:
            payload["Request_References"] = {
                "Recruiting_Agency_User_Reference": [
                    {
                        "ID": [
                            {
                                "type": user_id_type,
                                "_value_1": user_id
                            }
                        ]
                    }
                ]
            }

        try:
            if user_id:
                # Fetch specific user
                self._logger.info(f"Fetching specific recruiting agency user: {user_id}")

                response = None
                for attempt in range(1, self.max_retries + 1):
                    try:
                        response = await self.service.call_operation(
                            operation="Get_Recruiting_Agency_Users",
                            **payload
                        )
                        self._logger.info(f"✅ Successfully fetched user {user_id}")
                        break
                    except Exception as exc:
                        self._logger.warning(
                            f"[Get_Recruiting_Agency_Users] Error fetching user {user_id} "
                            f"(attempt {attempt}/{self.max_retries}): {exc}"
                        )
                        if attempt == self.max_retries:
                            self._logger.error(
                                f"[Get_Recruiting_Agency_Users] Failed to fetch user {user_id} after "
                                f"{self.max_retries} attempts."
                            )
                            raise
                        delay = min(self.retry_delay * (2 ** (attempt - 1)), 8.0)
                        self._logger.info(f"⏳ Waiting {delay:.1f}s before retry...")
                        await asyncio.sleep(delay)

                # Convert SOAP response to dict using serialize_object
                serialized = self.service.serialize_object(response)
                response_data = serialized.get("Response_Data") or {}

                # Extract Recruiting_Agency_User elements
                users_raw = response_data.get("Recruiting_Agency_User", []) if response_data else []
                if isinstance(users_raw, dict):
                    users_raw = [users_raw]

                self._logger.info(f"Retrieved {len(users_raw)} user(s)")

            else:
                # Fetch all users with pagination
                self._logger.info("🔍 Fetching first page to determine totals...")

                first_payload = {
                    **payload,
                    "Response_Filter": {
                        **payload.get("Response_Filter", {}),
                        "Page": 1,
                        "Count": 100
                    }
                }

                # Fetch first page with retry
                raw1 = None
                for attempt in range(1, self.max_retries + 1):
                    try:
                        self._logger.info(f"📡 Attempting to fetch first page (attempt {attempt}/{self.max_retries})...")
                        raw1 = await self.service.call_operation(operation="Get_Recruiting_Agency_Users", **first_payload)
                        self._logger.info("✅ Successfully fetched first page")
                        break
                    except Exception as exc:
                        self._logger.warning(
                            f"[Get_Recruiting_Agency_Users] Error on first page "
                            f"(attempt {attempt}/{self.max_retries}): {exc}"
                        )
                        if attempt == self.max_retries:
                            self._logger.error(
                                f"[Get_Recruiting_Agency_Users] Failed first page after {self.max_retries} attempts."
                            )
                            raise
                        delay = min(self.retry_delay * (2 ** (attempt - 1)), 8.0)
                        self._logger.info(f"⏳ Waiting {delay:.1f}s before retry...")
                        await asyncio.sleep(delay)

                # Parse first page using serialize_object
                data1 = self.service.serialize_object(raw1)

                # Debug: log the keys in the response
                if not data1:
                    self._logger.error("serialize_object returned None or empty dict")
                    self._logger.debug(f"raw1 type: {type(raw1)}, raw1 value: {raw1}")
                    data1 = {}
                else:
                    self._logger.debug(f"Response keys: {list(data1.keys())}")

                # Extract data from first page
                response_data = data1.get("Response_Data") or {}
                page1 = response_data.get("Recruiting_Agency_User", []) if response_data else []
                if isinstance(page1, dict):
                    page1 = [page1]

                # Get pagination info
                results = data1.get("Response_Results") or {}
                total_pages = int(float(results.get("Total_Pages", 1)))
                total_results = int(float(results.get("Total_Results", 0)))
                page_results = int(float(results.get("Page_Results", 0)))

                self._logger.info(
                    f"📊 Pagination: Total={total_results}, Pages={total_pages}, PageSize={page_results}"
                )
                self._logger.info(f"📄 Page 1/{total_pages} fetched: {len(page1)} users")

                all_users: List[dict] = list(page1)

                # Fetch remaining pages
                max_parallel = 10
                if total_pages > 1:
                    pages = list(range(2, total_pages + 1))
                    num_batches = math.ceil(len(pages) / max_parallel)
                    batches = self.service.split_parts(pages, num_parts=num_batches)

                    for batch in batches:
                        self._logger.info(f"🔄 Processing batch of {len(batch)} pages: {batch}")
                        tasks = [self._fetch_user_page(p, payload) for p in batch]
                        results_list = await asyncio.gather(*tasks, return_exceptions=True)

                        for res in results_list:
                            if isinstance(res, Exception):
                                self._logger.error(f"❌ Error fetching page: {res}")
                            else:
                                all_users.extend(res)

                        self._logger.info(
                            f"✅ Progress: {len(all_users)}/{total_results} users "
                            f"({(len(all_users)/total_results*100 if total_results else 0):.1f}%)"
                        )

                users_raw = all_users
                self._logger.info(f"✨ Completed: {len(users_raw)} users retrieved")

            # Process users - flatten or keep nested
            users_processed = []
            for user in users_raw:
                try:
                    if flatten_response:
                        # Flatten nested dicts
                        flattened = self._flatten_dict(user)
                        users_processed.append(flattened)
                    else:
                        # Keep original structure but serialize complex types
                        processed = {}
                        for k, v in user.items():
                            if isinstance(v, (dict, list)):
                                processed[k] = safe_serialize(v)
                            else:
                                processed[k] = v
                        users_processed.append(processed)

                except Exception as e:
                    self._logger.warning(f"⚠️ Error processing user: {e}")
                    continue

            # Create DataFrame
            if users_processed:
                df = pd.DataFrame(users_processed)
                self._logger.info(f"✅ Created DataFrame with {len(df)} rows and {len(df.columns)} columns")
                return df
            else:
                self._logger.warning("No users found or processed successfully")
                return pd.DataFrame()

        except Exception as e:
            self._logger.error(f"Error in Get_Recruiting_Agency_Users operation: {e}")
            import traceback
            self._logger.error(f"Traceback: {traceback.format_exc()}")
            raise

    async def _fetch_user_page(self, page_num: int, base_payload: dict) -> List[dict]:
        """
        Fetch a single page of Get_Recruiting_Agency_Users.
        Returns list of user dicts.
        """
        self._logger.debug(f"📄 Starting fetch for page {page_num}")

        payload = {
            **base_payload,
            "Response_Filter": {
                **base_payload.get("Response_Filter", {}),
                "Page": page_num,
                "Count": 100
            }
        }

        raw = None
        for attempt in range(1, self.max_retries + 1):
            try:
                raw = await self.service.call_operation(operation="Get_Recruiting_Agency_Users", **payload)
                break
            except Exception as exc:
                self._logger.warning(
                    f"[Get_Recruiting_Agency_Users] Error on page {page_num} "
                    f"(attempt {attempt}/{self.max_retries}): {exc}"
                )
                if attempt == self.max_retries:
                    self._logger.error(
                        f"[Get_Recruiting_Agency_Users] Failed page {page_num} after {self.max_retries} attempts."
                    )
                    raise
                delay = min(self.retry_delay * (2 ** (attempt - 1)), 8.0)
                await asyncio.sleep(delay)

        # Parse using serialize_object
        data = self.service.serialize_object(raw)
        response_data = data.get("Response_Data") or {}

        # Extract users
        items = response_data.get("Recruiting_Agency_User", []) if response_data else []
        if isinstance(items, dict):
            items = [items]

        self._logger.debug(f"✅ Page {page_num} completed: {len(items) if items else 0} users fetched")
        return items or []
