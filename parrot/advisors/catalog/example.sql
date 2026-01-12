-- Main products table
CREATE TABLE IF NOT EXISTS gorillashed.products (
    -- Primary identification
    id VARCHAR(255) PRIMARY KEY,
    catalog_id VARCHAR(100) NOT NULL DEFAULT 'default',
    
    -- Core product info (indexed for fast filtering)
    name VARCHAR(500) NOT NULL,
    product_url VARCHAR(1000),            -- Product page URL
    category VARCHAR(100),
    subcategory VARCHAR(100),
    description TEXT,                     -- Short product description
    
    -- Pricing (NUMERIC for accurate comparisons)
    price NUMERIC(12, 2),
    price_min NUMERIC(12, 2),  -- For price ranges
    price_max NUMERIC(12, 2),
    currency VARCHAR(3) DEFAULT 'USD',
    
    -- Dimensions (pre-computed for spatial filtering)
    width_ft NUMERIC(8, 2),
    depth_ft NUMERIC(8, 2),
    height_ft NUMERIC(8, 2),
    footprint_sqft NUMERIC(10, 2),  -- Computed: width * depth
    
    -- Media
    image_url VARCHAR(1000),              -- Main product image URL
    
    -- Status
    is_active BOOLEAN DEFAULT TRUE,
    
    -- Vector search columns
    embedding vector(1024),
    document TEXT,  -- Markdown version of product brochure for vectorization
    
    -- Flexible JSONB columns
    specs JSONB DEFAULT '{{}}',           -- Technical specifications (nested object)
    features JSONB DEFAULT '[]',          -- Feature list with metadata
    faqs JSONB DEFAULT '[]',              -- FAQ list [{question, answer}]
    product_variants JSONB DEFAULT '[]',  -- Variant list with pricing/options
    product_json JSONB DEFAULT '{{}}',    -- Raw Shopify/source product JSON
    product_data JSONB DEFAULT '{{}}',    -- Additional product metadata
    use_cases JSONB DEFAULT '[]',         -- Applicable use cases
    metadata JSONB DEFAULT '{{}}',        -- Extra data for extensibility
    
    -- Comparison helpers
    unique_selling_points JSONB DEFAULT '[]',
    comparison_tags JSONB DEFAULT '[]',   -- Tags for grouping comparisons
    
    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for fast filtering
CREATE INDEX IF NOT EXISTS idx_gorillashed_products_catalog 
    ON gorillashed.products(catalog_id);

CREATE INDEX IF NOT EXISTS idx_gorillashed_products_category 
    ON gorillashed.products(catalog_id, category);

CREATE INDEX IF NOT EXISTS idx_gorillashed_products_price 
    ON gorillashed.products(catalog_id, price) 
    WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_gorillashed_products_footprint 
    ON gorillashed.products(catalog_id, footprint_sqft) 
    WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_gorillashed_products_active 
    ON gorillashed.products(catalog_id, is_active);

-- Vector similarity index (IVFFlat for large catalogs, HNSW for small)
CREATE INDEX IF NOT EXISTS idx_gorillashed_products_embedding_cosine 
    ON gorillashed.products 
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- GIN index for JSONB specs queries
CREATE INDEX IF NOT EXISTS idx_gorillashed_products_specs 
    ON gorillashed.products 
    USING GIN (specs);

CREATE INDEX IF NOT EXISTS idx_gorillashed_products_features 
    ON gorillashed.products 
    USING GIN (features);

CREATE INDEX IF NOT EXISTS idx_gorillashed_products_use_cases 
    ON gorillashed.products 
    USING GIN (use_cases);

-- Full-text search on document
CREATE INDEX IF NOT EXISTS idx_gorillashed_products_document_fts 
    ON gorillashed.products 
    USING GIN (to_tsvector('english', document));

-- Composite index for common filter patterns
CREATE INDEX IF NOT EXISTS idx_gorillashed_products_filter_combo 
    ON gorillashed.products(catalog_id, category, footprint_sqft, price) 
    WHERE is_active = TRUE;