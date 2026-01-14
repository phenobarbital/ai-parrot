# parrot/advisors/catalog/catalog.py
"""
ProductCatalog - Abstraction over PgVectorStore for product management.

Provides:
- Product CRUD with automatic embedding generation
- Structured filtering + semantic search
- Comparison utilities
- Multi-tenant support via catalog_id
"""
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import json
from dataclasses import dataclass
import re
from navconfig.logging import logging
from sqlalchemy import text
from ..models import ProductSpec, ProductFeature, ProductDimensions, FeatureType
from ...stores.postgres import PgVectorStore
from ...stores.models import SearchResult


@dataclass
class ProductSearchResult:
    """Enhanced search result with product-specific fields."""
    product: ProductSpec
    score: float
    match_reason: str = ""  # "semantic", "filter", "hybrid"


class ProductCatalog:
    """
    Product catalog with hybrid search capabilities.

    Combines:
    - Structured filtering (price, dimensions, category)
    - Semantic search (embeddings)
    - JSONB queries (specs, features)

    Usage:
        catalog = ProductCatalog(
            catalog_id="sheds_2024",
            table="products_catalog",
            embedding_model="BAAI/bge-base-en-v1.5"
        )
        await catalog.initialize()

        # Add products
        await catalog.add_product(product_spec)

        # Search
        results = await catalog.search(
            query="storage shed for lawn equipment",
            filters={"max_footprint": 120, "max_price": 2000}
        )
    """

    def __init__(
        self,
        catalog_id: str = "default",
        table: str = "products_catalog",
        schema: str = "public",
        embedding_model: str = "BAAI/bge-base-en-v1.5",
        vector_store: Optional[PgVectorStore] = None,
        use_query_prefix: bool = True,  # BGE models benefit from this
        **kwargs
    ):
        """
        Initialize ProductCatalog.

        Args:
            catalog_id: Identifier for multi-tenant isolation
            table: PostgreSQL table name
            schema: PostgreSQL schema
            embedding_model: HuggingFace model for embeddings
            vector_store: Optional pre-configured PgVectorStore
            use_query_prefix: Whether to use "query:" prefix for BGE models
        """
        self.catalog_id = catalog_id
        self.table = table
        self.schema = schema
        self.embedding_model = embedding_model
        self.use_query_prefix = use_query_prefix and "bge" in embedding_model.lower()

        self._store = vector_store
        self._store_kwargs = kwargs
        self._initialized = False
        self.logger = logging.getLogger(f"ProductCatalog.{catalog_id}")

    async def initialize(self, create_table: bool = True) -> None:
        """
        Initialize the catalog store and create table if needed.

        Args:
            create_table: Whether to create the table schema
        """
        if self._initialized:
            return

        # Initialize store if not provided
        if self._store is None:
            self._store = PgVectorStore(
                table=self.table,
                schema=self.schema,
                embedding_model=self.embedding_model,
                id_column="id",
                embedding_column="embedding",
                document_column="document",
                **self._store_kwargs
            )

        # Connect to database
        await self._store.connection()

        # Create table schema if requested
        if create_table:
            await self._create_schema()

        self._initialized = True
        self.logger.info(f"ProductCatalog '{self.catalog_id}' initialized")

    async def _create_schema(self) -> None:
        """Create the products table with optimized schema."""
        from .schema import PRODUCTS_TABLE_SCHEMA  # pylint: disable=C0415

        # Get dimension from embedding model
        dimension = self._store.dimension

        schema_sql = PRODUCTS_TABLE_SCHEMA.format(
            schema=self.schema,
            table=self.table,
            dimension=dimension
        )

        async with self._store._connection.begin() as conn:
            # Split and execute each statement
            for statement in schema_sql.split(';'):
                if statement := statement.strip():
                    try:
                        await conn.execute(text(statement))
                    except Exception as e:
                        # Ignore "already exists" errors
                        if "already exists" not in str(e).lower():
                            self.logger.warning(f"Schema creation warning: {e}")

        self.logger.info(f"Schema created/verified for {self.schema}.{self.table}")

    # ─────────────────────────────────────────────────────────────────────────
    # Product CRUD
    # ─────────────────────────────────────────────────────────────────────────

    async def add_product(
        self,
        product: ProductSpec,
        generate_embedding: bool = True
    ) -> str:
        """
        Add a product to the catalog.

        Args:
            product: ProductSpec instance
            generate_embedding: Whether to generate embedding from content

        Returns:
            Product ID
        """
        # Build searchable document text
        document = self._build_document_text(product)

        # Generate embedding
        embedding = None
        if generate_embedding:
            # BGE models work better with passage prefix for indexing
            embed_text = document
            if self.use_query_prefix:
                embed_text = f"passage: {document}"
            embedding = self._store._embed_.embed_query(embed_text)

        # Prepare row data with new schema columns
        row_data = {
            "id": product.product_id,
            "catalog_id": self.catalog_id,
            "name": product.name,
            "product_url": product.url,
            "category": product.category,
            "description": getattr(product, "description", None),
            "price": product.price,
            "image_url": product.image_url,
            "document": document,
            "specs": json.dumps(self._features_to_specs(product.features)),
            "features": json.dumps([f.model_dump() for f in product.features]),
            "faqs": json.dumps(getattr(product, "faqs", []) or []),
            "product_variants": json.dumps(getattr(product, "product_variants", []) or []),
            "product_json": json.dumps(getattr(product, "product_json", {}) or {}),
            "product_data": json.dumps(getattr(product, "product_data", {}) or {}),
            "use_cases": json.dumps(product.use_cases),
            "unique_selling_points": json.dumps(product.unique_selling_points),
            "cmetadata": json.dumps({
                "brochure_url": product.brochure_url,
                "price_range": product.price_range,
            }),
            "is_active": True,
            "updated_at": datetime.utcnow(),
        }

        # Add dimensions if available
        if product.dimensions:
            row_data.update({
                "width_ft": product.dimensions.width,
                "depth_ft": product.dimensions.depth,
                "height_ft": product.dimensions.height,
                "footprint_sqft": product.dimensions.footprint,
            })

        # Add embedding

        if embedding:
            row_data["embedding"] = f"[{','.join(str(v) for v in embedding)}]"

        # Insert or update
        await self._upsert_product(row_data)

        self.logger.info(f"Added product: {product.product_id}")
        return product.product_id

    async def _upsert_product(self, row_data: Dict[str, Any]) -> None:
        """Insert or update a product row."""
        columns = list(row_data.keys())
        values_placeholder = ", ".join(f":{col}" for col in columns)
        update_set = ", ".join(
            f"{col} = EXCLUDED.{col}"
            for col in columns
            if col != "id"
        )

        sql = f"""
            INSERT INTO {self.schema}.{self.table} ({', '.join(columns)})
            VALUES ({values_placeholder})
            ON CONFLICT (id) DO UPDATE SET {update_set}
        """

        async with self._store._connection.begin() as conn:
            await conn.execute(text(sql), row_data)

    async def get_product(self, product_id: str) -> Optional[ProductSpec]:
        """Get a single product by ID."""
        sql = f"""
            SELECT * FROM {self.schema}.{self.table}
            WHERE id = :id AND catalog_id = :catalog_id
        """

        async with self._store.session() as session:
            result = await session.execute(
                text(sql),
                {"id": product_id, "catalog_id": self.catalog_id}
            )
            row = result.fetchone()
            return self._row_to_product(row._mapping) if row else None

    async def get_products(
        self,
        product_ids: List[str]
    ) -> List[ProductSpec]:
        """Get multiple products by IDs."""
        if not product_ids:
            return []

        placeholders = ", ".join(f":id_{i}" for i in range(len(product_ids)))
        sql = f"""
            SELECT * FROM {self.schema}.{self.table}
            WHERE id IN ({placeholders})
            AND catalog_id = :catalog_id
            AND is_active = TRUE
        """

        params = {"catalog_id": self.catalog_id}
        params.update({f"id_{i}": pid for i, pid in enumerate(product_ids)})

        async with self._store.session() as session:
            result = await session.execute(text(sql), params)
            rows = result.fetchall()
            return [self._row_to_product(row._mapping) for row in rows]

    async def get_all_products(
        self,
        category: Optional[str] = None,
        active_only: bool = True
    ) -> List[ProductSpec]:
        """Get all products in catalog."""
        conditions = ["catalog_id = :catalog_id"]
        params = {"catalog_id": self.catalog_id}

        if active_only:
            conditions.append("is_active = TRUE")

        if category:
            cat_val = category.strip()

            # Heuristic: If plural, allow matching singular root
            if cat_val.lower().endswith('s') and len(cat_val) > 3:
                root = cat_val[:-1]
                conditions.append("(category ILIKE :category OR category ILIKE :category_root)")
                params["category"] = f"%{cat_val}%"
                params["category_root"] = f"%{root}%"
            else:
                # Standard partial match
                conditions.append("category ILIKE :category")
                params["category"] = f"%{cat_val}%"

        sql = f"""
            SELECT * FROM {self.schema}.{self.table}
            WHERE {' AND '.join(conditions)}
            ORDER BY name
        """

        async with self._store.session() as session:
            result = await session.execute(text(sql), params)
            rows = result.fetchall()
            return [self._row_to_product(row._mapping) for row in rows]

    async def get_all_product_ids(
        self,
        category: Optional[str] = None
    ) -> List[str]:
        """Get all product IDs (lightweight query)."""
        conditions = ["catalog_id = :catalog_id", "is_active = TRUE"]
        params = {"catalog_id": self.catalog_id}

        if category:
            cat_val = category.strip()

            # Heuristic: If plural, allow matching singular root
            if cat_val.lower().endswith('s') and len(cat_val) > 3:
                root = cat_val[:-1]
                conditions.append("(category ILIKE :category OR category ILIKE :category_root)")
                params["category"] = f"%{cat_val}%"
                params["category_root"] = f"%{root}%"
            else:
                # Standard partial match
                conditions.append("category ILIKE :category")
                params["category"] = f"%{cat_val}%"

        sql = f"""
            SELECT id FROM {self.schema}.{self.table}
            WHERE {' AND '.join(conditions)}
        """

        async with self._store.session() as session:
            result = await session.execute(text(sql), params)
            return [row[0] for row in result.fetchall()]

    # ─────────────────────────────────────────────────────────────────────────
    # Search Methods
    # ─────────────────────────────────────────────────────────────────────────

    async def search(
        self,
        query: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 10,
        score_threshold: float = 0.3,
        search_type: str = "hybrid"  # "semantic", "filter", "hybrid"
    ) -> List[ProductSearchResult]:
        """
        Search products with hybrid capabilities.

        Args:
            query: Natural language search query
            filters: Structured filters (max_price, max_footprint, category, use_case, etc.)
            limit: Maximum results
            score_threshold: Minimum similarity score
            search_type: "semantic" (embedding only), "filter" (SQL only), "hybrid" (both)

        Returns:
            List of ProductSearchResult
        """
        filters = filters or {}

        if search_type == "filter" or not query:
            # Pure filter search
            return await self._filter_search(filters, limit)

        elif search_type == "semantic":
            # Pure semantic search
            return await self._semantic_search(query, limit, score_threshold)

        else:
            # Hybrid: filter first, then rank by similarity
            return await self._hybrid_search(query, filters, limit, score_threshold)

    async def _filter_search(
        self,
        filters: Dict[str, Any],
        limit: int
    ) -> List[ProductSearchResult]:
        """Search using only structured filters."""
        conditions, params = self._build_filter_conditions(filters)

        sql = f"""
            SELECT * FROM {self.schema}.{self.table}
            WHERE {' AND '.join(conditions)}
            ORDER BY name
            LIMIT :limit
        """
        params["limit"] = limit

        async with self._store.session() as session:
            result = await session.execute(text(sql), params)
            rows = result.fetchall()

            return [
                ProductSearchResult(
                    product=self._row_to_product(row._mapping),
                    score=1.0,
                    match_reason="filter"
                )
                for row in rows
            ]

    async def _semantic_search(
        self,
        query: str,
        limit: int,
        score_threshold: float
    ) -> List[ProductSearchResult]:
        """Search using semantic similarity."""
        # Add query prefix for BGE models
        search_query = query
        if self.use_query_prefix:
            search_query = f"query: {query}"

        results = await self._store.similarity_search(
            query=search_query,
            table=self.table,
            schema=self.schema,
            limit=limit,
            score_threshold=score_threshold,
            metadata_filters={"catalog_id": self.catalog_id}
        )

        # Convert to ProductSearchResult
        product_results = []
        for r in results:
            product = await self.get_product(r.id)
            if product:
                product_results.append(ProductSearchResult(
                    product=product,
                    score=1.0 - r.score,  # Convert distance to similarity
                    match_reason="semantic"
                ))

        return product_results

    async def _hybrid_search(
        self,
        query: str,
        filters: Dict[str, Any],
        limit: int,
        score_threshold: float
    ) -> List[ProductSearchResult]:
        """
        Hybrid search: filter + semantic ranking.

        Strategy:
        1. Apply structural filters to get candidate set
        2. Compute semantic similarity for candidates
        3. Rank by similarity score
        """
        # Build filter conditions
        conditions, params = self._build_filter_conditions(filters)

        # Generate query embedding
        search_query = f"query: {query}" if self.use_query_prefix else query
        query_embedding = self._store._embed_.embed_query(search_query)
        embedding_str = f"[{','.join(str(v) for v in query_embedding)}]"

        # Hybrid SQL with vector similarity
        sql = f"""
            SELECT
                *,
                1 - (embedding <=> :query_embedding::vector) as similarity
            FROM {self.schema}.{self.table}
            WHERE {' AND '.join(conditions)}
            ORDER BY embedding <=> :query_embedding::vector
            LIMIT :limit
        """
        params["query_embedding"] = embedding_str
        params["limit"] = limit

        async with self._store.session() as session:
            result = await session.execute(text(sql), params)
            rows = result.fetchall()

            return [
                ProductSearchResult(
                    product=self._row_to_product(row._mapping),
                    score=row.similarity if hasattr(row, 'similarity') else 0.5,
                    match_reason="hybrid"
                )
                for row in rows
                if not score_threshold or (hasattr(row, 'similarity') and row.similarity >= score_threshold)
            ]

    def _build_filter_conditions(
        self,
        filters: Dict[str, Any]
    ) -> Tuple[List[str], Dict[str, Any]]:
        """Build SQL WHERE conditions from filters dict."""
        conditions = [
            "catalog_id = :catalog_id",
            "is_active = TRUE"
        ]
        params = {"catalog_id": self.catalog_id}

        # Price filters
        if "max_price" in filters:
            conditions.append("price <= :max_price")
            params["max_price"] = filters["max_price"]

        if "min_price" in filters:
            conditions.append("price >= :min_price")
            params["min_price"] = filters["min_price"]

        # Dimension filters
        if "max_footprint" in filters:
            conditions.append("footprint_sqft <= :max_footprint")
            params["max_footprint"] = filters["max_footprint"]

        if "max_width" in filters:
            conditions.append("width_ft <= :max_width")
            params["max_width"] = filters["max_width"]

        if "max_depth" in filters:
            conditions.append("depth_ft <= :max_depth")
            params["max_depth"] = filters["max_depth"]

        # Category filter
        if "category" in filters:
            conditions.append("category = :category")
            params["category"] = filters["category"]

        # Use case filter (JSONB contains)
        if "use_case" in filters:
            conditions.append("use_cases @> :use_case::jsonb")
            params["use_case"] = json.dumps([filters["use_case"]])

        # Spec filters (JSONB)
        if "specs" in filters and isinstance(filters["specs"], dict):
            for spec_key, spec_value in filters["specs"].items():
                param_name = f"spec_{spec_key}"
                if isinstance(spec_value, dict):
                    # Range filter: {"min": x, "max": y}
                    if "min" in spec_value:
                        conditions.append(
                            f"(specs->>'{spec_key}')::numeric >= :{param_name}_min"
                        )
                        params[f"{param_name}_min"] = spec_value["min"]
                    if "max" in spec_value:
                        conditions.append(
                            f"(specs->>'{spec_key}')::numeric <= :{param_name}_max"
                        )
                        params[f"{param_name}_max"] = spec_value["max"]
                else:
                    # Exact match
                    conditions.append(f"specs->>'{spec_key}' = :{param_name}")
                    params[param_name] = str(spec_value)

        # Product IDs filter (for filtering within candidates)
        if "product_ids" in filters and filters["product_ids"]:
            placeholders = ", ".join(
                f":pid_{i}" for i in range(len(filters["product_ids"]))
            )
            conditions.append(f"id IN ({placeholders})")
            params.update({
                f"pid_{i}": pid
                for i, pid in enumerate(filters["product_ids"])
            })

        return conditions, params

    # ─────────────────────────────────────────────────────────────────────────
    # Filtering for Selection Wizard
    # ─────────────────────────────────────────────────────────────────────────

    async def filter_products(
        self,
        product_ids: List[str],
        criteria: Dict[str, Any],
        soft_match: bool = True
    ) -> Tuple[List[str], Dict[str, str]]:
        """
        Filter products by criteria, return matching IDs and elimination reasons.

        Used by the selection wizard to narrow down candidates.

        Args:
            product_ids: Current candidate product IDs
            criteria: Filter criteria to apply
            soft_match: If True, products with empty use_cases are treated as
                       "general purpose" and match any use_case criteria

        Returns:
            Tuple of (matching_ids, eliminated_dict)
            where eliminated_dict = {product_id: "reason"}
        """
        if not product_ids:
            return [], {}

        self.logger.debug(
            f"🔍 Filtering {len(product_ids)} products with criteria: {criteria}"
        )

        # Get full product data for filtering
        products = await self.get_products(product_ids)

        matching = []
        eliminated = {}

        for product in products:
            passes, reason = self._product_matches_criteria(
                product, criteria, soft_match=soft_match
            )
            if passes:
                matching.append(product.product_id)
                self.logger.debug(f"  ✅ {product.name} ({product.product_id}) - PASSED")
            else:
                eliminated[product.product_id] = reason
                self.logger.debug(
                    f"  ❌ {product.name} ({product.product_id}) - ELIMINATED: {reason}"
                )

        self.logger.info(
            f"Filter result: {len(matching)} passed, {len(eliminated)} eliminated "
            f"(criteria: {list(criteria.keys())})"
        )

        return matching, eliminated

    def _product_matches_criteria(
        self,
        product: ProductSpec,
        criteria: Dict[str, Any],
        soft_match: bool = True
    ) -> Tuple[bool, str]:
        """
        Check if a product matches criteria, return (passes, failure_reason).

        Args:
            product: Product to check
            criteria: Filter criteria to apply
            soft_match: If True, products with empty use_cases are treated as
                "general purpose" and match any use_case criteria
        """

        # Check footprint/space
        if "max_footprint" in criteria and product.dimensions:
            if product.dimensions.footprint > criteria["max_footprint"]:
                return False, f"Too large ({product.dimensions.footprint:.0f} sqft > {criteria['max_footprint']} sqft)"

        if "available_space" in criteria and product.dimensions:
            space = criteria["available_space"]
            if isinstance(space, dict):
                if not product.dimensions.fits_in(space.get("width", 999), space.get("depth", 999)):
                    return False, f"Doesn't fit in {space['width']}x{space['depth']} space"

        # Check price
        if "max_price" in criteria and product.price:
            if product.price > criteria["max_price"]:
                return False, f"Over budget (${product.price:,.0f} > ${criteria['max_price']:,.0f})"

        if "min_price" in criteria and product.price:
            if product.price < criteria["min_price"]:
                return False, f"Under minimum (${product.price:,.0f} < ${criteria['min_price']:,.0f})"

        # Handle generic 'price' key - LLM may send various formats
        if "price" in criteria and product.price:
            from ..tools.utils import normalize_price_value
            price_val = criteria["price"]

            # Handle string formats like "<=5000", "<5000", "5000", "5K"
            if isinstance(price_val, str):
                # Match patterns like "<=5000", "<= 5000", "< 5000", ">5000", "<=5K"
                if match := re.match(r'([<>]=?)\s*\$?\s*([\d.,]+\s*[kKmM]?)', price_val):
                    op, num_str = match.groups()
                    num = normalize_price_value(num_str)
                    if op == '<=' or op == '<':
                        if product.price > num:
                            return False, f"Over budget (${product.price:,.0f} > ${num:,.0f})"
                    elif op == '>=' or op == '>':
                        if product.price < num:
                            return False, f"Under minimum (${product.price:,.0f} < ${num:,.0f})"
                else:
                    # Try to normalize (handles 5K, 2.5k, etc.)
                    num = normalize_price_value(price_val)
                    if num > 0 and product.price > num:
                        return False, f"Over budget (${product.price:,.0f} > ${num:,.0f})"

            # Handle dict format like {"max": 5000} or {"min": 1000, "max": 5000}
            elif isinstance(price_val, dict):
                max_val = price_val.get("max")
                min_val = price_val.get("min")
                if max_val:
                    max_num = normalize_price_value(str(max_val)) if isinstance(max_val, str) else max_val
                    if product.price > max_num:
                        return False, f"Over budget (${product.price:,.0f} > ${max_num:,.0f})"
                if min_val:
                    min_num = normalize_price_value(str(min_val)) if isinstance(min_val, str) else min_val
                    if product.price < min_num:
                        return False, f"Under minimum (${product.price:,.0f} < ${min_num:,.0f})"

            # Handle raw number (treat as max price)
            elif isinstance(price_val, (int, float)):
                if product.price > price_val:
                    return False, f"Over budget (${product.price:,.0f} > ${price_val:,.0f})"

        # Check subcategory (e.g., commercial, home, pool, farm, backyard)
        if "subcategory" in criteria:
            required_subcat = criteria["subcategory"]
            if isinstance(required_subcat, str):
                required_subcat = [required_subcat]

            # Soft match: products with no subcategory pass the filter
            if soft_match and not product.subcategory:
                self.logger.debug(
                    f"  ↳ {product.name}: No subcategory defined, soft match enabled - "
                    f"treating as general (matches '{criteria['subcategory']}')"
                )
            else:
                # Check if product subcategory matches any required
                matches = False
                if product.subcategory:
                    prod_subcat_lower = product.subcategory.lower()
                    for req in required_subcat:
                        req_lower = req.lower()
                        # Allow partial matching (e.g., "back" matches "backyard")
                        if req_lower in prod_subcat_lower or prod_subcat_lower in req_lower:
                            matches = True
                            break

                if not matches and product.subcategory:
                    return False, f"Wrong subcategory: {product.subcategory} (wanted: {criteria['subcategory']})"

        # Check use case with soft match support
        if "use_case" in criteria:
            required_use = criteria["use_case"]
            if isinstance(required_use, str):
                required_use = [required_use]

            # Soft match: products with no defined use_cases are considered "general purpose"
            # and match any use_case criteria
            if soft_match and not product.use_cases:
                self.logger.debug(
                    f"  ↳ {product.name}: No use_cases defined, soft match enabled - "
                    f"treating as general purpose (matches '{criteria['use_case']}')"
                )
                # Passes - empty use_cases = general purpose
            else:
                # Strict matching: must have a matching use_case
                matches = False
                for req in required_use:
                    req_lower = req.lower()
                    for prod_uc in product.use_cases:
                        # Allow partial match (e.g. "garden" matches "garden tools")
                        # and case-insensitive matching
                        if req_lower in prod_uc.lower() or prod_uc.lower() in req_lower:
                            matches = True
                            break
                    if matches:
                        break

                if not matches and product.use_cases:
                    return False, f"Not suitable for {criteria['use_case']} (has: {product.use_cases})"

        # Check specific features
        if "required_features" in criteria:
            for req_feature in criteria["required_features"]:
                has_feature = any(
                    f.name.lower() == req_feature.lower() or
                    req_feature.lower() in f.name.lower()
                    for f in product.features
                )
                if not has_feature:
                    return False, f"Missing required feature: {req_feature}"

        # Check specs-based criteria (roof_material, floor_type, etc.)
        # Specs structure: {misc: {...}, roof: {...}, floor: {...}, wall: {...}, door: {...}}
        specs_criteria_keys = [
            "roof_material", "floor_type", "stud_spacing", "door_type",
            "ventilation", "threshold", "wall_framing", "rafter_spacing",
            # Allow direct spec category.key lookups like "roof.material"
        ]

        for key, value in criteria.items():
            # Check if this is a specs-related key
            if key in specs_criteria_keys or "." in key:
                if not product.specs:
                    # No specs, can't match
                    if soft_match:
                        continue  # Skip - no specs to compare
                    return False, f"No specs available to check {key}"

                # Handle dotted keys like "roof.material"
                if "." in key:
                    category, spec_key = key.split(".", 1)
                    category_specs = product.specs.get(category, {})
                    spec_value = category_specs.get(spec_key, "")
                else:
                    # Search across all spec categories for the key
                    spec_value = None
                    for cat, cat_specs in product.specs.items():
                        if isinstance(cat_specs, dict):
                            # Map criteria key to spec key (e.g., roof_material -> roof material)
                            spec_key_normalized = key.replace("_", " ")
                            for sk, sv in cat_specs.items():
                                if spec_key_normalized in sk.lower() or sk.lower() in spec_key_normalized:
                                    spec_value = sv
                                    break
                        if spec_value:
                            break

                if spec_value:
                    # Check if the required value matches (partial, case-insensitive)
                    req_lower = str(value).lower()
                    spec_lower = str(spec_value).lower()
                    if req_lower not in spec_lower and spec_lower not in req_lower:
                        return False, f"Spec mismatch for {key}: has '{spec_value}', wanted '{value}'"

        # NOTE: The following criteria are stored for tracking but don't filter products:
        # - size_category: Informational only (e.g., "small", "large")
        # - price_range: Informational only (e.g., "budget", "premium")
        # These are handled by the QuestionSet and used for question flow, not product filtering

        return True, ""

    # ─────────────────────────────────────────────────────────────────────────
    # Comparison Utilities
    # ─────────────────────────────────────────────────────────────────────────

    async def compare_products(
        self,
        product_ids: List[str],
        comparison_aspects: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Generate a comparison matrix for products.

        Args:
            product_ids: Products to compare
            comparison_aspects: Specific aspects to compare (default: all common features)

        Returns:
            Comparison dict with products and feature matrix
        """
        products = await self.get_products(product_ids)

        if not products:
            return {"products": [], "comparison": {}}

        # Collect all feature names
        all_features = set()
        for p in products:
            all_features.update(f.name for f in p.features)

        # Filter to requested aspects if specified
        if comparison_aspects:
            all_features = all_features.intersection(set(comparison_aspects))

        # Build comparison matrix
        comparison = {}
        for feature_name in sorted(all_features):
            comparison[feature_name] = {}
            for p in products:
                if feature := p.get_feature(feature_name):
                    value = feature.value
                    if feature.unit:
                        value = f"{value} {feature.unit}"
                    comparison[feature_name][p.product_id] = value
                else:
                    comparison[feature_name][p.product_id] = "N/A"

        # Add standard comparisons
        standard_comparisons = {
            "Price": {p.product_id: f"${p.price:,.0f}" if p.price else "N/A" for p in products},
            "Dimensions": {
                p.product_id: f"{p.dimensions.width}x{p.dimensions.depth}x{p.dimensions.height} ft"
                if p.dimensions else "N/A"
                for p in products
            },
            "Footprint": {
                p.product_id: f"{p.dimensions.footprint:.0f} sq ft"
                if p.dimensions else "N/A"
                for p in products
            },
        }

        # Merge standard comparisons
        for key, values in standard_comparisons.items():
            if key not in comparison:
                comparison[key] = values

        # Add key features summary (top 5 features from features column)
        key_features_comparison = {}
        for p in products:
            features_list = []
            for f in p.features[:5]:  # Top 5 features
                if hasattr(f, 'name') and f.name:
                    features_list.append(f.name)
            key_features_comparison[p.product_id] = ", ".join(features_list) if features_list else "N/A"

        if key_features_comparison:
            comparison["Key Features"] = key_features_comparison

        return {
            "products": [
                {
                    "id": p.product_id,
                    "name": p.name,
                    "category": p.category,
                    "unique_selling_points": p.unique_selling_points,
                    "features_count": len(p.features),
                    "image_url": p.image_url,
                }
                for p in products
            ],
            "comparison": comparison
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Document Building (for Embeddings)
    # ─────────────────────────────────────────────────────────────────────────

    def _build_document_text(self, product: ProductSpec) -> str:
        """
        Build optimized searchable text for embedding.

        Strategy:
        - Emphasize discriminating features
        - Include use cases for intent matching
        - Structure for BGE model understanding
        """
        parts = []

        # Product identity
        parts.append(f"Product: {product.name}")
        parts.append(f"Category: {product.category}")

        # Use cases (important for intent matching)
        if product.use_cases:
            parts.append(f"Best for: {', '.join(product.use_cases)}")

        # Dimensions (common search criteria)
        if product.dimensions:
            parts.append(
                f"Size: {product.dimensions.width}x{product.dimensions.depth} feet "
                f"({product.dimensions.footprint:.0f} square feet)"
            )

        # Price
        if product.price:
            parts.append(f"Price: ${product.price:,.0f}")

        # Key features
        filterable_features = [f for f in product.features if f.is_filterable]
        if filterable_features:
            feature_texts = []
            for f in filterable_features[:10]:  # Limit to avoid too long text
                if f.unit:
                    feature_texts.append(f"{f.display_name or f.name}: {f.value} {f.unit}")
                else:
                    feature_texts.append(f"{f.display_name or f.name}: {f.value}")
            parts.append(f"Features: {'; '.join(feature_texts)}")

        # Unique selling points
        if product.unique_selling_points:
            parts.append(f"Highlights: {'; '.join(product.unique_selling_points)}")

        # Full markdown content (for detailed semantic search)
        if product.markdown_content:
            # Truncate if too long
            content = product.markdown_content[:2000]
            parts.append(f"Description: {content}")

        return "\n".join(parts)

    def _features_to_specs(self, features: List[ProductFeature]) -> Dict[str, Any]:
        """Convert features list to flat specs dict for JSONB."""
        return {
            f.name: f.value
            for f in features
            if f.feature_type != FeatureType.TEXT
        }

    def _row_to_product(self, row: Dict[str, Any]) -> ProductSpec:
        """Convert database row to ProductSpec."""
        # Parse JSONB columns
        features_data = row.get("features", [])
        if isinstance(features_data, str):
            features_data = json.loads(features_data)

        # Build dimensions from individual columns or dimensions_raw
        dimensions_data = row.get("dimensions_raw", {})
        if isinstance(dimensions_data, str):
            dimensions_data = json.loads(dimensions_data)

        # If dimensions_raw is empty, build from individual columns
        if not dimensions_data:
            width = row.get("width_ft")
            depth = row.get("depth_ft")
            height = row.get("height_ft")
            footprint = row.get("footprint_sqft")
            if width or depth or height or footprint:
                dimensions_data = {
                    "width": width or 0,
                    "depth": depth or 0,
                    "height": height or 0,
                    "footprint": footprint or (width * depth if width and depth else 0)
                }

        use_cases = row.get("use_cases", [])
        if isinstance(use_cases, str):
            use_cases = json.loads(use_cases)

        usp = row.get("unique_selling_points", [])
        if isinstance(usp, str):
            usp = json.loads(usp)

        metadata = row.get("cmetadata", {})
        if isinstance(metadata, str):
            metadata = json.loads(metadata)

        specs = row.get("specs", {})
        if isinstance(specs, str):
            specs = json.loads(specs)

        dimensions = ProductDimensions(**dimensions_data) if dimensions_data else None

        return ProductSpec(
            product_id=row["id"],
            name=row["name"],
            category=row.get("category", ""),
            subcategory=row.get("subcategory"),
            dimensions=dimensions,
            features=[ProductFeature(**f) for f in features_data] if features_data else [],
            use_cases=use_cases,
            price=float(row["price"]) if row.get("price") else None,
            price_range=metadata.get("price_range"),
            url=row.get("product_url") or metadata.get("url"),
            image_url=row.get("image_url") or metadata.get("image_url"),
            brochure_url=metadata.get("brochure_url"),
            markdown_content=row.get("document", ""),
            unique_selling_points=usp,
            specs=specs,
            catalog_id=row.get("catalog_id", "default"),
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────────────────────────────────

    async def close(self) -> None:
        """Close database connections."""
        if self._store:
            await self._store.disconnect()
