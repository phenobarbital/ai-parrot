"""
BestBuy API Toolkit - Unified toolkit for BestBuy operations.

Provides methods for:
- Product search and information
- Store availability checking
- Inventory lookup
"""
import os
import asyncio
import time
import random
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from navconfig import config
from navconfig.logging import logging
from ..toolkit import AbstractToolkit
from ..decorators import tool_schema
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
from ...interfaces.http import UA_LIST, HTTPService


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
        proxy_type: str = 'oxylabs',
        **kwargs
    ):
        """
        Initialize the BestBuy toolkit.

        Args:
            api_key: BestBuy API key. If None, uses config.get('BESTBUY_APIKEY')
            use_proxy: Whether to use proxy for requests
            proxy_type: Type of proxy to use (default: oxylabs)
            **kwargs: Additional toolkit configuration
        """
        super().__init__(**kwargs)
        self.logger = logging.getLogger(__name__)
        self.api_key = api_key or BESTBUY_API_KEY
        if not self.api_key:
            raise ValueError(
                "BestBuy API key is required. "
                "Set BESTBUY_APIKEY in config or pass api_key parameter."
            )

        self.bby_url = "https://www.bestbuy.com"
        # Initialize HTTPService for BestBuy website (availability checks)
        self.cookies = {}
        self._driver = None
        self.user_agent = random.choice(UA_LIST)
        
        self.http_web = HTTPService(
            use_proxy=use_proxy,
            proxy_type=proxy_type,
            cookies=self.cookies,
            headers={
                "authority": "www.bestbuy.com",
                "Host": "www.bestbuy.com",
                "Referer": "https://www.bestbuy.com/",
                "X-Requested-With": "XMLHttpRequest",
                "TE": "trailers",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
                "Accept-Encoding": "gzip, deflate, br, zstd",
                "DNT": "1",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "User-Agent": self.user_agent,
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

    def _get_driver(self):
        """Initialize and return a headless Chrome driver."""
        if self._driver:
            return self._driver

        options = ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument(f"user-agent={self.user_agent}")
        
        # Suppress logging
        options.add_argument("--log-level=3")
        
        service = ChromeService(ChromeDriverManager().install())
        self._driver = webdriver.Chrome(service=service, options=options)
        return self._driver

    def _close_driver(self):
        """Close the Selenium driver if it exists."""
        if self._driver:
            try:
                self._driver.quit()
            except Exception as e:
                self.logger.warning(f"Error closing driver: {e}")
            finally:
                self._driver = None

    async def _ensure_cookies(self, force_refresh: bool = False):
        """
        Ensure session cookies are available via Selenium.
        """
        if self.cookies and not force_refresh:
            return

        print(f"Fetching fresh cookies (Force: {force_refresh})...")
        driver = None
        try:
            loop = asyncio.get_running_loop()
            driver = await loop.run_in_executor(None, self._get_driver)
            
            # Bypassing Splash Screen
            await loop.run_in_executor(None, driver.get, "https://www.bestbuy.com/?intl=nosplash")
            await loop.run_in_executor(None, time.sleep, 5) # wait for page load
            
            # Extract cookies
            selenium_cookies = await loop.run_in_executor(None, driver.get_cookies)
            for cookie in selenium_cookies:
                self.cookies[cookie['name']] = cookie['value']
            
            # Update HTTP client cookies
            self.http_web.cookies = self.cookies
            print(f"Cookies updated: {list(self.cookies.keys())}")
            
        except Exception as e:
            self.logger.error(f"Selenium error fetching cookies: {e}")
        finally:
            if driver:
                await loop.run_in_executor(None, self._close_driver)

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

        :param zipcode: ZIP code for the store.
        :param sku: Product SKU to check.
        :param location_id: Store location ID.
        :param show_only_in_stock: If True, only return if in stock.
        :return: Availability dictionary.
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
                    "quantity": 1
                }
            ]
        }
        
        # Ensure we have cookies before starting
        await self._ensure_cookies()

        url = f"{self.bby_url}/fulfillment/ispu/api/ispu/v2"
        
        try:
            # Use the new api_post method which handles retries and proxies
            response = await self.http_web.api_post(
                url,
                payload=payload,
                cookies=self.cookies, # Pass current cookies
                use_proxy=True, # Ensure proxy is used
            )
            
            # The result is already a dict or empty dict
            if not response:
                 return {"error": "Empty response from Best Buy API"}
                 
            return self._format_availability_response(response, location_id, sku, show_only_in_stock)

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
