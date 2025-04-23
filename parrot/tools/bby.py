from typing import List, Dict, Any, Union
import random
from orjson import JSONDecodeError
from pydantic import BaseModel, Field
# from pydantic.v1 import BaseModel, Field
from langchain_core.tools import BaseTool, BaseToolkit, StructuredTool, ToolException, Tool
from datamodel.parsers.json import json_decoder, json_encoder  # pylint: disable=E0611
from datamodel.exceptions import ParserError  # pylint: disable=E0611
from navconfig import config
from ..interfaces.http import HTTPService, ua


ctt_list: list = [
    "f3dbf688e45146555bb2b8604a993601",
    "06f4dfe367e87866397ef32302f5042e",
    "4e07e03ff03f5debc4e09ac4db9239ac"
]

sid_list: list = [
    "d4fa1142-2998-4b68-af78-46d821bb3e1f",
    "9627390e-b423-459f-83ee-7964dd05c9a8"
]

class BestBuyProductAvailabilityInput(BaseModel):
    """Input for the BestBuy product availability tool."""
    zipcode: str = Field(..., description="The ZIP code to check availability in")
    sku: str = Field(..., description="The SKU of the product to check")
    location_id: str = Field(
        ..., description="Optional specific location ID to check"
    )
    show_only_in_stock: bool = Field(
        False, description="Whether to only show stores with product in stock"
    )

    model_config = {
        "arbitrary_types_allowed": True,
        "extra": "forbid",  # Helps with compatibility
        "json_schema_extra": {
            "required": ["zipcode", "sku", "location_id"]
        }
    }

class BestBuyToolkit(BaseToolkit):
    """Toolkit for interacting with BestBuy's API."""

    api_key: str = Field(default=config.get('BESTBUY_APIKEY'))

    http_service: HTTPService = Field(default_factory=lambda: HTTPService(
        use_proxy=True,
        cookies={
            "CTT": random.choice(ctt_list),
            "SID": random.choice(sid_list),
            "bby_rdp": "l",
            "bm_sz": "9F5ED0110AF18594E2347A89BB4AB998~YAAQxm1lX6EqYHGSAQAAw+apmhkhXIeGYEc4KnzUMsjeac3xEoQmTNz5+of62i3RXQL6fUI+0FvCb/jgSjiVQOcfaSF+LdLkOXP1F4urgeIcqp/dBAhu5MvZXaCQsT06bwr7j21ozhFfTTWhjz1HmZN8wecsE6WGbK6wXp/33ODKlLaGWkTutqHbkzvMiiHXBCs9hT8jVny0REfita4AfqTK85Y6/M6Uq4IaDLPBLnTtJ0cTlPHk1HmkG5EsnI46llghcx1KZnCGnvZfHdb2ME9YZJ2GmC2b7dNmAgyL/gSVpoNdCJOj5Jk6z/MCVhZ81OZfX4S01E2F1mBGq4uV5/1oK2KR4YgZP4dsTN8izEEPybUKGY3CyM1gOUc=~3556420~4277810",
            "bby_cbc_lb": "p-browse-e",
            "intl_splash": "false"
        },
        headers={
            "Host": "www.bestbuy.com",
            "Referer": "https://www.bestbuy.com/",
            "TE": "trailers",
            "Accept-Language": "en-US,en;q=0.5",
        }
    ))

    # Add this model_config to allow arbitrary types
    model_config = {
        "arbitrary_types_allowed": True
    }

    def get_tools(self) -> List[BaseTool]:
        """Get the tools in the toolkit."""
        return [
            self._get_availability_tool(),
            self._get_product_information()
        ]

    def _get_product_information(self) -> StructuredTool:
        """Create a tool for getting product information from BestBuy."""

        async def _product_information(tool_input: Union[str, dict]) -> List[dict]:
            """Get product information from BestBuy based on SKU, name, or search terms."""
            # https://api.bestbuy.com/v1/products(name={product_name})?format=json&show=sku,name,salePrice,customerReviewAverage,customerReviewCount,manufacturer,modelNumber&apiKey={api_key}
            if isinstance(tool_input, dict):
                # Direct call with dict
                input_data = tool_input
            elif isinstance(tool_input, str):
                # Might be a JSON string from LLM
                try:
                    # input_data = json.loads(tool_input)
                    input_data = json_decoder(tool_input)
                except (ParserError, JSONDecodeError):
                    # Not valid JSON, treat as zipcode with missing other params
                    input_data = {"product_name": tool_input}
            else:
                # Some other type that we don't expect
                input_data = {"product_name": str(tool_input)}

            # Product Name to be used in the search:
            print('PRODUCT > ', input_data)

            product_name = input_data.get("product_name", None)
            search_terms = input_data.get("search_terms", None)
            print(search_terms)
            if search_terms:
                search_terms = search_terms.split(',')
                # I need in format: search=oven&search=stainless&search=steel
                search_terms = '&'.join([f"search={term.strip()}" for term in search_terms])
                url = f"https://api.bestbuy.com/v1/products({search_terms})?format=json&show=sku,name,salePrice,customerReviewAverage,customerReviewCount,manufacturer,modelNumber&apiKey={self.api_key}"
            elif product_name:
                if ',' in product_name:
                    search_terms = product_name.split(',')
                    search_terms = '&'.join([f"search={term.strip()}" for term in search_terms])
                else:
                    search_terms = f"name={product_name.strip()}"
                url = f"https://api.bestbuy.com/v1/products({search_terms})?format=json&show=sku,name,salePrice,customerReviewAverage,customerReviewCount,manufacturer,modelNumber&apiKey={self.api_key}"
            else:
                raise ToolException(
                    "Either product_name or search_terms must be provided."
                )
            # URL for BestBuy's Product API
            result, error = await self.http_service._request(
                url=url,
                method="GET",
                use_json=True,
                use_proxy=True,
                headers={
                    "User-Agent": random.choice(ua)
                },
                use_ssl=True,
                follow_redirects=True,
                raise_for_status=True,
                full_response=False
            )
            products = result.get('products', [])
            if not products:
                return "No products found."

            return products


        return StructuredTool.from_function(
            name="product_information",
            description=(
                "Use this tool to search for product information. "
                "Input must be the search terms: "
                "- search terms: different words separated by commas "
                " Example input: {{\"search_terms\": \"oven,stainless\"}}"
            ),
            func=_product_information,
            coroutine=_product_information,
            infer_schema=False,
            return_direct=False,
            handle_tool_error=True
        )

    def _get_availability_tool(self) -> StructuredTool:
        """Create a tool for checking product availability at BestBuy."""

        async def _check_availability(tool_input: Union[str, dict]) -> str:
            """Check BestBuy product availability based on SKU and location."""

            # Input validation
            # tool_input: str
            try:
                if isinstance(tool_input, dict):
                    # Direct call with dict
                    input_data = tool_input
                elif isinstance(tool_input, str):
                    # Might be a JSON string from LLM
                    try:
                        # input_data = json.loads(tool_input)
                        input_data = json_decoder(tool_input)
                    except (ParserError, JSONDecodeError):
                        # Not valid JSON, treat as zipcode with missing other params
                        input_data = {"zipcode": tool_input}
                else:
                    # Some other type that we don't expect
                    input_data = {"zipcode": str(tool_input)}
                # Extract fields
                zipcode = input_data.get("zipcode")
                sku = input_data.get("sku")
                location_id = input_data.get("location_id")
                show_only_in_stock = input_data.get("show_only_in_stock", False)

            except Exception as e:
                # Final fallback - treat the entire input as a zipcode
                zipcode = str(tool_input)
                sku = None
                location_id = None
                show_only_in_stock = False

            # Input validation
            if not zipcode:
                raise ToolException("ZIP code is required to check product availability")
            if not sku:
                raise ToolException("Product SKU is required to check availability")
            if not location_id:
                raise ToolException("Store location ID is required to check availability")

            # Prepare the payload for the API call
            payload = {
                "locationId": location_id,
                "zipCode": zipcode,
                "showOnShelf": True,
                "lookupInStoreQuantity": True,
                "xboxAllAccess": False,
                "consolidated": True,
                "showOnlyOnShelf": False,
                "showInStore": True,
                "pickupTypes": [
                    "UPS_ACCESS_POINT",
                    "FEDEX_HAL"
                ],
                "onlyBestBuyLocations": True,
                # TODO: add more products
                "items": [
                    {
                        "sku": sku,
                        "condition": None,
                        "quantity": 1,
                        "itemSeqNumber": "1",
                        "reservationToken": None,
                        "selectedServices": [],
                        "requiredAccessories": [],
                        "isTradeIn": False,
                        "isLeased": False
                    }
                ]
            }

            # Make the API call using the HTTP service
            try:
                # URL for BestBuy's availability API
                url = "https://www.bestbuy.com/productfulfillment/c/api/2.0/storeAvailability"

                # Make POST request with JSON payload
                result, error = await self.http_service._request(
                    url=url,
                    method="POST",
                    data=payload,
                    use_json=True,
                    use_proxy=True,
                    headers={
                        "User-Agent": random.choice(ua)
                    },
                    use_ssl=True,
                    follow_redirects=True,
                    raise_for_status=True,
                    full_response=False
                )

                if error:
                    raise ToolException(
                        f"Error checking BestBuy availability: {error}"
                    )

                # Process and format the response
                if not result:
                    return "No data was returned from BestBuy. The service may be unavailable."

                # Extract relevant information from the result
                formatted_result = self._format_availability_response(result, location_id, sku, show_only_in_stock)
                return formatted_result

            except Exception as e:
                raise ToolException(f"Failed to check BestBuy product availability: {str(e)}")

        return StructuredTool.from_function(
            name="availability",
            description=(
                "Use this tool to check product availability at a specific Best Buy store or zipcode. "
                "Input must be a JSON object with the following fields: "
                "- zipcode (required): The ZIP code to check availability in. "
                "- sku (required): The SKU of the product to check. "
                "- location_id (required): The specific store location ID to check. "
                "- show_only_in_stock (optional): Whether to only show stores with product in stock. "
                "Example input: {{\"zipcode\": \"33928\", \"sku\": \"6428376\", \"location_id\": \"767\", \"show_only_in_stock\": false}}"
            ),
            func=_check_availability,
            # args_schema=BestBuyProductAvailabilityInput,
            coroutine=_check_availability,
            infer_schema=False,
            return_direct=False,
            handle_tool_error=True
        )

    def _format_availability_response(
        self, result: Dict[str, Any], location_id: str, sku: str, show_only_in_stock: bool = False
    ) -> str:
        try:
            # Extract store information from the "ispu" locations
            locations = result.get("ispu", {}).get("locations", [])
            # Match on the "id" key rather than "locationId"
            store = next((loc for loc in locations if loc.get("id") == location_id), None)
            if not store:
                return "No matching store location found."

            store_name = store.get("name", "N/A")
            store_address = store.get("address", "N/A")
            store_city = store.get("city", "N/A")
            store_zip = store.get("zipCode", "N/A")
            store_state = store.get("state", "N/A")
            store_lat = store.get("latitude", "N/A")
            store_long = store.get("longitude", "N/A")

            # Format store hours if available
            open_times = store.get("openTimesMap", {})
            store_hours_str = (
                "\n".join(f"{day}: {hours}" for day, hours in open_times.items())
                if open_times else "N/A"
            )

            # Extract product availability from "ispu" items
            items = result.get("ispu", {}).get("items", [])
            item = next((it for it in items if it.get("sku") == sku), None)
            if not item:
                return "No matching product found."

            print('ITEM > ', item)

            product_instore = item.get("inStoreAvailable", False)
            product_pickup = item.get("pickupEligible", False)

            # Extract the location-specific availability from the item's "locations" list
            item_locations = item.get("locations", [])
            availability = next(
                (loc for loc in item_locations if loc.get("locationId") == location_id), None
            )
            if not availability:
                return "No matching product availability found."

            on_shelf = availability.get("onShelfDisplay", False)
            in_store_quantity = availability.get("inStoreAvailability", {}).get("availableInStoreQuantity", 0)
            available_from = availability.get("inStoreAvailability", {}).get("minDate")

            # Build and return a formatted result string
            result_str = (
                f"Store Name: {store_name}\n"
                f"Address: {store_address}\n"
                f"City: {store_city}\n"
                f"Zip Code: {store_zip}\n"
                f"State: {store_state}\n"
                f"Latitude: {store_lat}\n"
                f"Longitude: {store_long}\n"
                f"Hours:\n{store_hours_str}\n"
                "--------------------------------\n"
                f"Product SKU: {sku}\n"
                f"In-store Available: {product_instore}\n"
                f"Pickup Eligible: {product_pickup}\n"
                f"On Shelf Display: {on_shelf}\n"
                f"Available Quantity: {in_store_quantity}\n"
                f"Available From: {available_from}\n"
                "--------------------------------\n"
            )
            return result_str

        except Exception as e:
            return f"Error formatting availability response: {str(e)}"
