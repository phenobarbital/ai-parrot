# parrot/advisors/catalog/loaders.py
"""
Loaders for ingesting product data into ProductCatalog.

Supports:
- JSON with embedded markdown
- JSON + separate markdown files
- Structured JSON only
"""
from typing import List, Dict, Any, Optional, Union
from pathlib import Path
import json
import re
from dataclasses import dataclass
from navconfig.logging import logging
from ..models import (
    ProductSpec,
    ProductFeature,
    ProductDimensions,
    FeatureType
)

@dataclass
class LoadResult:
    """Result of a load operation."""
    loaded: int
    errors: List[str]
    product_ids: List[str]


class ProductLoader:
    """
    Base loader for product data.
    
    Override _parse_product() for custom formats.
    """
    
    def __init__(
        self,
        catalog: "ProductCatalog",
        category_default: str = "general",
        auto_detect_features: bool = True,
    ):
        self.catalog = catalog
        self.category_default = category_default
        self.auto_detect_features = auto_detect_features
        self.logger = logging.getLogger("ProductLoader")
    
    async def load_file(self, file_path: Union[str, Path]) -> LoadResult:
        """Load products from a JSON file."""
        path = Path(file_path)
        
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Handle both single product and array
        if isinstance(data, list):
            products_data = data
        elif isinstance(data, dict) and "products" in data:
            products_data = data["products"]
        else:
            products_data = [data]
        
        return await self.load_products(products_data)
    
    async def load_products(
        self, 
        products_data: List[Dict[str, Any]]
    ) -> LoadResult:
        """Load multiple products from parsed data."""
        loaded = 0
        errors = []
        product_ids = []
        
        for i, data in enumerate(products_data):
            try:
                product = self._parse_product(data)
                await self.catalog.add_product(product)
                product_ids.append(product.product_id)
                loaded += 1
            except Exception as e:
                errors.append(f"Product {i}: {str(e)}")
                self.logger.error(f"Error loading product {i}: {e}")
        
        self.logger.info(f"Loaded {loaded}/{len(products_data)} products")
        return LoadResult(loaded=loaded, errors=errors, product_ids=product_ids)
    
    def _parse_product(self, data: Dict[str, Any]) -> ProductSpec:
        """
        Parse product data dict into ProductSpec.
        
        Expected format (new CSV structure):
        {
            "product_url": "https://...",
            "product_name": "Imperial",
            "price": 2499.99,
            "description": "Short product description",
            "image_url": "https://...",
            "features": [{"title": "...", "bullets": [...]}],
            "faqs": [{"question": "...", "answer": "..."}],
            "footprint_sqft": 64.0,
            "product_variants": [{"id": ..., "title": "8x8", ...}],
            "specs": {"misc": {...}, "roof": {...}, "floor": {...}},
            "product_json": {"title": "...", "vendor": "..."},
            "product_data": {"title": "...", "vendor": "..."},
            "document": "# Full markdown content..."
        }
        
        Also supports legacy format:
        {
            "id": "shed-001",
            "name": "Classic Storage Shed",
            "category": "sheds",
            "url": "https://...",
            "image": "https://...",
            "price": 1299.99,
            "specs": {...},
            "use_cases": ["storage", "workshop"],
            "highlights": ["Easy assembly", "Weather resistant"],
            "description": "# Full markdown description..."
        }
        """
        # Extract basic fields - support both new and legacy field names
        # Note: column_mapping may have mapped 'product_name' -> 'name'
        name = (
            data.get("name") or 
            data.get("product_name") or 
            data.get("title") or 
            ""
        )
        
        product_id = (
            data.get("id") or 
            data.get("product_id") or 
            data.get("sku") or
            # Generate from name if no explicit ID
            (name.lower().replace(" ", "-") if name else None) or
            None
        )
        if not product_id:
            raise ValueError("Product must have 'id', 'product_id', 'sku', or 'name'/'product_name'")
        
        # Use name or fallback to product_id
        if not name:
            name = product_id
        category = data.get("category") or self.category_default
        
        # Parse dimensions from specs or direct fields
        dimensions = self._parse_dimensions(data)
        
        # Handle footprint_sqft directly from CSV (overrides computed value)
        footprint = data.get("footprint_sqft")
        if footprint and dimensions:
            # Update dimensions with actual footprint if provided
            pass  # footprint is computed property, we'll use it from DB column
        
        # Parse features - can be pre-parsed JSON list or from specs dict
        features_data = data.get("features")
        if isinstance(features_data, list):
            # Already parsed as JSON array - keep as-is for storage
            features = []  # Will be stored directly in JSONB
        else:
            # Parse from specs dict (legacy format)
            features = self._parse_features(data.get("specs", {}) if isinstance(data.get("specs"), dict) else {})
        
        # Get use cases
        use_cases = data.get("use_cases", [])
        if isinstance(use_cases, str):
            use_cases = [uc.strip() for uc in use_cases.split(",")]
        
        # Get price
        price = data.get("price")
        if isinstance(price, str):
            # Handle "$1,299.99" format
            price = float(re.sub(r'[^\d.]', '', price))
        
        # Get markdown content - 'document' is the markdown version of product brochure
        markdown_content = (
            data.get("document", "") or  # New format: document column
            data.get("markdown", "") or  # Alternative
            data.get("content", "") or   # Alternative
            ""
        )
        
        # Get short description (distinct from markdown_content/document)
        description = data.get("description", "")
        
        # URL: support product_url (new) and url (legacy)
        url = data.get("product_url") or data.get("url")
        
        # Image URL
        image_url = data.get("image_url") or data.get("image")
        
        # Get new JSONB fields - ensure they are lists/dicts
        faqs = data.get("faqs", [])
        if not isinstance(faqs, list):
            faqs = []
        
        product_variants = data.get("product_variants", [])
        if not isinstance(product_variants, list):
            product_variants = []
        
        product_json = data.get("product_json", {})
        if not isinstance(product_json, dict):
            product_json = {}
        
        product_data = data.get("product_data", {})
        if not isinstance(product_data, dict):
            product_data = {}
        
        # Specs - ensure it's a dict for storage
        specs = data.get("specs", {})
        if not isinstance(specs, dict):
            specs = {}
        
        return ProductSpec(
            product_id=str(product_id),
            name=name,
            category=category,
            description=description,
            dimensions=dimensions,
            features=features,
            use_cases=use_cases,
            price=price,
            price_range=self._determine_price_range(price),
            url=url,
            image_url=image_url,
            brochure_url=data.get("brochure") or data.get("brochure_url"),
            markdown_content=markdown_content,
            unique_selling_points=data.get("highlights", []) or data.get("unique_selling_points", []),
            faqs=faqs,
            product_variants=product_variants,
            product_json=product_json,
            product_data=product_data,
            catalog_id=self.catalog.catalog_id,
        )
    
    def _parse_dimensions(self, data: Dict[str, Any]) -> Optional[ProductDimensions]:
        """Extract dimensions from product data."""
        specs = data.get("specs", {})
        
        # If specs is a string (failed to parse), try to parse it here
        if isinstance(specs, str):
            import ast
            try:
                # Clean up escaped quotes first
                cleaned = specs.replace('\\"', '"').replace("\\'", "'")
                specs = ast.literal_eval(cleaned)
            except (ValueError, SyntaxError):
                specs = {}  # Fall back to empty dict
        
        if not isinstance(specs, dict):
            specs = {}
        
        # Try different field naming conventions
        width = (
            specs.get("width_ft") or 
            specs.get("width") or 
            data.get("width_ft") or
            data.get("width")
        )
        depth = (
            specs.get("depth_ft") or 
            specs.get("depth") or 
            specs.get("length_ft") or
            specs.get("length") or
            data.get("depth_ft") or
            data.get("depth")
        )
        height = (
            specs.get("height_ft") or 
            specs.get("height") or 
            data.get("height_ft") or
            data.get("height")
        )
        
        if width and depth:
            return ProductDimensions(
                width=float(width),
                depth=float(depth),
                height=float(height) if height else 0,
                unit="ft"  # Assume feet, adjust as needed
            )
        
        return None
    
    def _parse_features(self, specs: Dict[str, Any]) -> List[ProductFeature]:
        """Convert specs dict to ProductFeature list."""
        features = []
        
        # Known dimension fields to skip (handled separately)
        skip_fields = {
            "width", "width_ft", "depth", "depth_ft", "length", "length_ft",
            "height", "height_ft"
        }
        
        # Feature type detection
        type_hints = {
            "material": FeatureType.CATEGORICAL,
            "door_type": FeatureType.CATEGORICAL,
            "roof_type": FeatureType.CATEGORICAL,
            "foundation": FeatureType.CATEGORICAL,
            "warranty_years": FeatureType.NUMERIC,
            "weight_lbs": FeatureType.NUMERIC,
            "wall_thickness": FeatureType.NUMERIC,
            "has_": FeatureType.BOOLEAN,
            "is_": FeatureType.BOOLEAN,
            "includes_": FeatureType.BOOLEAN,
        }
        
        for key, value in specs.items():
            if key.lower() in skip_fields:
                continue
            
            # Determine feature type
            feature_type = FeatureType.TEXT
            if self.auto_detect_features:
                # Check type hints
                for hint_prefix, hint_type in type_hints.items():
                    if key.lower().startswith(hint_prefix) or key.lower() == hint_prefix:
                        feature_type = hint_type
                        break
                
                # Auto-detect from value type
                if feature_type == FeatureType.TEXT:
                    if isinstance(value, bool):
                        feature_type = FeatureType.BOOLEAN
                    elif isinstance(value, (int, float)):
                        feature_type = FeatureType.NUMERIC
                    elif isinstance(value, str) and value.lower() in ("yes", "no", "true", "false"):
                        feature_type = FeatureType.BOOLEAN
                        value = value.lower() in ("yes", "true")
            
            # Create display name
            display_name = key.replace("_", " ").title()
            
            features.append(ProductFeature(
                name=key,
                value=value,
                feature_type=feature_type,
                display_name=display_name,
                is_filterable=feature_type != FeatureType.TEXT,
            ))
        
        return features
    
    def _determine_price_range(self, price: Optional[float]) -> Optional[str]:
        """Categorize price into ranges."""
        if price is None:
            return None
        
        if price < 500:
            return "budget"
        elif price < 1500:
            return "mid-range"
        elif price < 3000:
            return "premium"
        else:
            return "luxury"


class JSONMarkdownLoader(ProductLoader):
    """
    Loader for JSON files with embedded markdown descriptions.
    
    Format:
    {
        "products": [
            {
                "id": "shed-001",
                "name": "Classic Shed",
                "specs": {...},
                "description": "# Full Markdown Content\n\n..."
            }
        ]
    }
    """
    pass  # Uses base implementation


class SeparateMarkdownLoader(ProductLoader):
    """
    Loader for JSON specs + separate markdown files.
    
    Expects:
    - products.json with basic specs
    - products/{id}.md for each product's full description
    """
    
    def __init__(
        self,
        catalog: "ProductCatalog",
        markdown_dir: Union[str, Path],
        **kwargs
    ):
        super().__init__(catalog, **kwargs)
        self.markdown_dir = Path(markdown_dir)
    
    async def load_file(self, file_path: Union[str, Path]) -> LoadResult:
        """Load products and their markdown descriptions."""
        path = Path(file_path)
        
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        products_data = data if isinstance(data, list) else data.get("products", [data])
        
        # Enrich with markdown content
        for product_data in products_data:
            product_id = product_data.get("id") or product_data.get("product_id")
            if product_id:
                md_path = self.markdown_dir / f"{product_id}.md"
                if md_path.exists():
                    with open(md_path, 'r', encoding='utf-8') as f:
                        product_data["description"] = f.read()
        
        return await self.load_products(products_data)


class CSVLoader(ProductLoader):
    """
    Loader for CSV product data.
    
    Supports column mapping from CSV headers to ProductSpec fields.
    Automatically parses JSON columns (features, faqs, specs, product_variants, etc.).
    
    Example CSV (new format):
        product_url,product_name,price,description,image_url,features,faqs,footprint_sqft,
        product_variants,specs,product_json,product_data,document
    
    Usage:
        loader = CSVLoader(
            catalog=my_catalog,
            column_mapping={
                "product_name": "name",
                "product_url": "url",
            },
            json_columns=["features", "faqs", "specs", "product_variants", "product_json", "product_data"]
        )
        result = await loader.load_file("products.csv")
    """
    
    # Default columns that should be parsed as JSON
    DEFAULT_JSON_COLUMNS = {
        "features", "faqs", "specs", "product_variants", 
        "product_json", "product_data", "use_cases", "metadata",
        "unique_selling_points", "comparison_tags"
    }
    
    def __init__(
        self,
        catalog: "ProductCatalog",
        column_mapping: Dict[str, str] = None,
        delimiter: str = ",",
        encoding: str = "utf-8",
        json_columns: List[str] = None,
        **kwargs
    ):
        """
        Initialize CSV loader.
        
        Args:
            catalog: ProductCatalog instance to load products into
            column_mapping: Maps CSV columns to ProductSpec fields
                           Use "specs.field" for nested specs fields
            delimiter: CSV delimiter (default: comma)
            encoding: File encoding (default: utf-8)
            json_columns: List of column names that contain JSON data
                         Defaults to common JSON columns if not specified
        """
        super().__init__(catalog, **kwargs)
        self.column_mapping = column_mapping or {}
        self.delimiter = delimiter
        self.encoding = encoding
        self.json_columns = set(json_columns) if json_columns else self.DEFAULT_JSON_COLUMNS
    
    async def load_file(self, file_path: Union[str, Path]) -> LoadResult:
        """Load products from a CSV file."""
        import csv
        
        path = Path(file_path)
        products_data = []
        
        with open(path, 'r', encoding=self.encoding, newline='') as f:
            reader = csv.DictReader(f, delimiter=self.delimiter)
            
            for row in reader:
                product_data = self._map_row(row)
                products_data.append(product_data)
        
        return await self.load_products(products_data)
    
    def _map_row(self, row: Dict[str, str]) -> Dict[str, Any]:
        """
        Map CSV row to product data dict.
        
        Handles:
        - Direct field mapping
        - JSON column parsing (features, faqs, specs, product_variants, etc.)
        - Nested specs fields (specs.material -> {"specs": {"material": ...}})
        - Type conversion (numeric, boolean)
        """
        product_data = {"specs": {}}
        
        for csv_col, value in row.items():
            # Skip empty values - handle both string and non-string types
            if value is None:
                continue
            if isinstance(value, str):
                if value.strip() == "":
                    continue
                value = value.strip()
            
            # Get target field from mapping or use column name
            # Ensure csv_col is not None and handle mapping returning None
            if csv_col is None:
                continue
            target_field = self.column_mapping.get(csv_col) or csv_col
            if not target_field:
                continue
            
            # Check if this is a JSON column and value is still a string
            if isinstance(value, str) and (csv_col in self.json_columns or target_field in self.json_columns):
                parsed_value = self._parse_json_column(value)
            elif isinstance(value, str):
                parsed_value = self._convert_value(value)
            else:
                # Value is already parsed (list, dict, etc.)
                parsed_value = value
            
            # Handle nested specs fields
            if target_field.startswith("specs."):
                spec_name = target_field[6:]  # Remove "specs." prefix
                product_data["specs"][spec_name] = parsed_value
            elif "." in target_field:
                # Handle other nested fields if needed
                parts = target_field.split(".", 1)
                if parts[0] not in product_data:
                    product_data[parts[0]] = {}
                product_data[parts[0]][parts[1]] = parsed_value
            else:
                product_data[target_field] = parsed_value
        
        # Handle use_cases as comma-separated (if not already parsed as JSON)
        if "use_cases" in product_data and isinstance(product_data["use_cases"], str):
            product_data["use_cases"] = [
                uc.strip() for uc in product_data["use_cases"].split(",")
            ]
        
        # Handle highlights/unique_selling_points as pipe-separated (if not already parsed as JSON)
        if "highlights" in product_data and isinstance(product_data["highlights"], str):
            product_data["highlights"] = [
                h.strip() for h in product_data["highlights"].split("|")
            ]
        
        return product_data
    
    def _parse_json_column(self, value: str) -> Any:
        """
        Parse a JSON string column.
        
        Handles both:
        - Standard JSON with double quotes: {"key": "value"}
        - Python-style dicts with single quotes: {'key': 'value'}
        
        Returns the parsed JSON object/array, or the original string if parsing fails.
        """
        import ast
        
        if not value:
            return None
        
        # Check if value looks like JSON/dict/list
        value_stripped = value.strip()
        if value_stripped.startswith('[') or value_stripped.startswith('{'):
            # Try standard JSON first
            try:
                return json.loads(value_stripped)
            except json.JSONDecodeError:
                pass
            
            # Try cleaning up escaped quotes before literal_eval
            try:
                # Handle escaped quotes that may appear in CSV exports
                cleaned = value_stripped.replace('\\"', '"').replace("\\'", "'")
                return ast.literal_eval(cleaned)
            except (ValueError, SyntaxError):
                pass
            
            # Last resort: try the original with literal_eval
            try:
                return ast.literal_eval(value_stripped)
            except (ValueError, SyntaxError) as e:
                self.logger.warning(f"Failed to parse JSON/Python column: {e}")
        
        return value
    
    def _convert_value(self, value: str) -> Any:
        """Convert string value to appropriate type."""
        # Boolean detection
        if value.lower() in ("true", "yes", "1"):
            return True
        if value.lower() in ("false", "no", "0"):
            return False
        
        # Numeric detection
        try:
            # Handle currency format "$1,299.99"
            clean_value = re.sub(r'[$,]', '', value)
            if '.' in clean_value:
                return float(clean_value)
            return int(clean_value)
        except (ValueError, TypeError):
            pass
        
        return value