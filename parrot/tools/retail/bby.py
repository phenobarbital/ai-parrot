"""
BestBuy API Toolkit - Unified toolkit for BestBuy operations.

Provides methods for:
- Product search and information
- Store availability checking
- Inventory lookup
"""
import os
import random
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from navconfig import config
from ...interfaces.http import HTTPService, UA_LIST
from ..toolkit import AbstractToolkit
from ..decorators import tool_schema


# ============================================================================
# Configuration
# ============================================================================

BESTBUY_API_KEY = config.get('BESTBUY_APIKEY')

# BestBuy cookies and headers for web scraping
CTT_LIST = [
    "f3dbf688e45146555bb2b8604a993601",
    "06f4dfe367e87866397ef32302f5042e",
    "4e07e03ff03f5debc4e09ac4db9239ac"
]

SID_LIST = [
    "d4fa1142-2998-4b68-af78-46d821bb3e1f",
    "9627390e-b423-459f-83ee-7964dd05c9a8"
]


# ============================================================================
# Input Schemas
# ============================================================================

class ProductSearchInput(BaseModel):
    """Input schema for product search."""
    search_terms: Optional[str] = Field(
        default=None,
        description="Search terms separated by commas (e.g., 'oven,stainless,steel')"
    )
    product_name: Optional[str] = Field(
        default=None,
        description="Specific product name to search for"
    )


class ProductAvailabilityInput(BaseModel):
    """Input schema for checking product availability."""
    zipcode: str = Field(
        description="ZIP code to check availability in"
    )
    sku: str = Field(
        description="Product SKU to check"
    )
    location_id: str = Field(
        description="Store location ID to check"
    )
    show_only_in_stock: bool = Field(
        default=False,
        description="Whether to only show stores with product in stock"
    )


class StoreLocatorInput(BaseModel):
    """Input schema for finding stores."""
    zipcode: str = Field(
        description="ZIP code to search near"
    )
    radius: int = Field(
        default=25,
        description="Search radius in miles"
    )


# ============================================================================
# BestBuy Toolkit
# ============================================================================

class BestBuyToolkit(AbstractToolkit):
    """
    Toolkit for interacting with BestBuy API and services.

    Provides methods for:
    - Searching for products
    - Getting product information
    - Checking store availability
    - Finding nearby stores
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        use_proxy: bool = True,
        **kwargs
    ):
        """
        Initialize the BestBuy toolkit.

        Args:
            api_key: BestBuy API key. If None, uses config.get('BESTBUY_APIKEY')
            use_proxy: Whether to use proxy for requests
            **kwargs: Additional toolkit configuration
        """
        super().__init__(**kwargs)

        self.api_key = api_key or BESTBUY_API_KEY
        if not self.api_key:
            raise ValueError(
                "BestBuy API key is required. "
                "Set BESTBUY_APIKEY in config or pass api_key parameter."
            )

        # Initialize HTTPService for BestBuy website (availability checks)
        self.http_web = HTTPService(
            use_proxy=use_proxy,
            cookies={
                "CTT": random.choice(CTT_LIST),
                "SID": random.choice(SID_LIST),
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
            },
            accept='application/json',
            timeout=30
        )

        # Initialize HTTPService for BestBuy API (product search)
        self.http_api = HTTPService(
            use_proxy=True,
            accept='application/json',
            timeout=30
        )

    @tool_schema(ProductSearchInput)
    async def search_products(
        self,
        search_terms: Optional[str] = None,
        product_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Search for products on BestBuy using product names or search terms.

        Returns detailed product information including:
        - SKU (needed for availability checks)
        - Product name
        - Sale price
        - Customer reviews and ratings
        - Manufacturer and model number

        Args:
            search_terms: Comma-separated search terms (e.g., "oven,stainless,steel")
            product_name: Specific product name to search for

        Returns:
            Dictionary with list of matching products or error message
        """
        # Build query string
        if search_terms:
            # Parse comma-separated terms
            terms = [term.strip() for term in search_terms.split(',')]
            query = '&'.join([f"search={term}" for term in terms])
        elif product_name:
            # Handle product name (can be comma-separated too)
            if ',' in product_name:
                terms = [term.strip() for term in product_name.split(',')]
                query = '&'.join([f"search={term}" for term in terms])
            else:
                query = f"name={product_name.strip()}"
        else:
            return {
                "error": "Either search_terms or product_name must be provided"
            }

        # Build API URL
        url = (
            f"https://api.bestbuy.com/v1/products({query})"
            f"?format=json"
            f"&show=sku,name,salePrice,customerReviewAverage,customerReviewCount,manufacturer,modelNumber"
            f"&apiKey={self.api_key}"
        )

        self.logger.debug(f"Searching BestBuy API: {url}")

        try:
            # Make request using HTTPService
            result, error = await self.http_api.request(
                url=url,
                method="GET",
                client='httpx',
                use_ssl=True,
                follow_redirects=True
            )

            if error:
                self.logger.error(f"Error searching products: {error}")
                return {"error": str(error)}

            # Extract products
            products = result.get('products', [])

            if not products:
                return {
                    "message": "No products found",
                    "products": []
                }

            return {
                "total": len(products),
                "products": products
            }

        except Exception as e:
            self.logger.error(f"Failed to search products: {e}")
            return {"error": str(e)}

    @tool_schema(ProductAvailabilityInput)
    async def check_availability(
        self,
        zipcode: str,
        sku: str,
        location_id: str,
        show_only_in_stock: bool = False
    ) -> Dict[str, Any]:
        """
        Check product availability at a specific BestBuy store.

        Returns detailed availability information including:
        - Store information (name, address, hours)
        - Product in-stock status
        - Pickup eligibility
        - On-shelf display status
        - Available quantity

        Args:
            zipcode: ZIP code to check availability in
            sku: Product SKU to check
            location_id: Store location ID
            show_only_in_stock: Whether to only show in-stock items

        Returns:
            Dictionary with availability information or error message
        """
        # Validate inputs
        if not zipcode:
            return {"error": "ZIP code is required"}
        if not sku:
            return {"error": "Product SKU is required"}
        if not location_id:
            return {"error": "Store location ID is required"}

        # Build request payload
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

        url = "https://www.bestbuy.com/productfulfillment/c/api/2.0/storeAvailability"

        self.logger.debug(
            f"Checking availability: SKU={sku}, Location={location_id}, ZIP={zipcode}"
        )

        try:
            # Make request using HTTPService
            result, error = await self.http_web.request(
                url=url,
                method="POST",
                data=payload,
                use_json=True,
                client='httpx',
                headers={
                    "User-Agent": random.choice(UA_LIST)
                },
                use_ssl=True,
                follow_redirects=True
            )

            if error:
                self.logger.error(f"Error checking availability: {error}")
                return {"error": str(error)}

            if not result:
                return {
                    "error": "No data returned from BestBuy. Service may be unavailable."
                }

            # Format the response
            formatted = self._format_availability_response(
                result,
                location_id,
                sku,
                show_only_in_stock
            )

            return formatted

        except Exception as e:
            self.logger.error(f"Failed to check availability: {e}")
            return {"error": str(e)}

    async def find_stores(
        self,
        zipcode: str,
        radius: int = 25
    ) -> Dict[str, Any]:
        """
        Find BestBuy stores near a ZIP code.

        Args:
            zipcode: ZIP code to search near
            radius: Search radius in miles

        Returns:
            Dictionary with list of stores
        """
        # Build API URL
        url = (
            f"https://api.bestbuy.com/v1/stores"
            f"(area({zipcode},{radius}))"
            f"?format=json"
            f"&show=storeId,name,address,city,region,postalCode,phone,lat,lng,hours"
            f"&apiKey={self.api_key}"
        )

        self.logger.debug(f"Finding stores near {zipcode} within {radius} miles")

        try:
            result, error = await self.http_api.request(
                url=url,
                method="GET",
                client='httpx',
                use_ssl=True
            )

            if error:
                self.logger.error(f"Error finding stores: {error}")
                return {"error": str(error)}

            stores = result.get('stores', [])

            return {
                "total": len(stores),
                "stores": stores
            }

        except Exception as e:
            self.logger.error(f"Failed to find stores: {e}")
            return {"error": str(e)}

    async def get_product_details(self, sku: str) -> Dict[str, Any]:
        """
        Get detailed information for a specific product by SKU.

        Args:
            sku: Product SKU

        Returns:
            Dictionary with detailed product information
        """
        url = (
            f"https://api.bestbuy.com/v1/products/{sku}.json"
            f"?apiKey={self.api_key}"
        )

        self.logger.debug(f"Getting product details for SKU: {sku}")

        try:
            result, error = await self.http_api.request(
                url=url,
                method="GET",
                client='httpx',
                use_ssl=True
            )

            if error:
                self.logger.error(f"Error getting product details: {error}")
                return {"error": str(error)}

            return result

        except Exception as e:
            self.logger.error(f"Failed to get product details: {e}")
            return {"error": str(e)}

    def _format_availability_response(
        self,
        result: Dict[str, Any],
        location_id: str,
        sku: str,
        show_only_in_stock: bool = False
    ) -> Dict[str, Any]:
        """
        Format availability response into structured data.

        Args:
            result: Raw API response
            location_id: Store location ID
            sku: Product SKU
            show_only_in_stock: Filter flag

        Returns:
            Formatted availability dictionary
        """
        try:
            # Extract store information from ISPU locations
            locations = result.get("ispu", {}).get("locations", [])
            store = next(
                (loc for loc in locations if loc.get("id") == location_id),
                None
            )

            if not store:
                return {
                    "error": "No matching store location found",
                    "location_id": location_id
                }

            # Extract store details
            store_info = {
                "store_id": location_id,
                "name": store.get("name", "N/A"),
                "address": store.get("address", "N/A"),
                "city": store.get("city", "N/A"),
                "state": store.get("state", "N/A"),
                "zip_code": store.get("zipCode", "N/A"),
                "latitude": store.get("latitude", "N/A"),
                "longitude": store.get("longitude", "N/A"),
                "hours": store.get("openTimesMap", {})
            }

            # Extract product availability from ISPU items
            items = result.get("ispu", {}).get("items", [])
            item = next(
                (it for it in items if it.get("sku") == sku),
                None
            )

            if not item:
                return {
                    "error": "No matching product found",
                    "sku": sku,
                    "store": store_info
                }

            # Extract item-level availability
            item_locations = item.get("locations", [])
            availability = next(
                (loc for loc in item_locations if loc.get("locationId") == location_id),
                None
            )

            if not availability:
                return {
                    "error": "No availability data for this product at this location",
                    "sku": sku,
                    "store": store_info
                }

            # Build product availability info
            in_store_availability = availability.get("inStoreAvailability", {})
            product_info = {
                "sku": sku,
                "in_store_available": item.get("inStoreAvailable", False),
                "pickup_eligible": item.get("pickupEligible", False),
                "on_shelf_display": availability.get("onShelfDisplay", False),
                "available_quantity": in_store_availability.get("availableInStoreQuantity", 0),
                "available_from": in_store_availability.get("minDate"),
                "pickup_types": item.get("pickupTypes", [])
            }

            # Check if we should filter out of stock
            if show_only_in_stock and product_info["available_quantity"] == 0:
                return {
                    "message": "Product not in stock at this location",
                    "sku": sku,
                    "store": store_info,
                    "product": product_info
                }

            return {
                "store": store_info,
                "product": product_info,
                "status": "available" if product_info["available_quantity"] > 0 else "unavailable"
            }

        except Exception as e:
            self.logger.error(f"Error formatting availability response: {e}")
            return {
                "error": f"Failed to format response: {str(e)}"
            }
