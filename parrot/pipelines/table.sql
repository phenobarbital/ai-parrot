DROP TABLE IF EXISTS troc.planograms_configurations;

CREATE TABLE troc.planograms_configurations (
    -- Primary key
    planogram_id SERIAL PRIMARY KEY,

    -- Basic configuration info
    config_name VARCHAR(255) NOT NULL UNIQUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    -- Core planogram configuration (stored as JSONB for flexibility)
    planogram_config JSONB NOT NULL,

    -- Prompts (can be quite long)
    roi_detection_prompt TEXT NOT NULL,
    object_identification_prompt TEXT NOT NULL,

    -- Reference images (stored as JSONB with paths/references, not actual image data)
    reference_images JSONB DEFAULT '{}',

    -- Detection parameters
    confidence_threshold DECIMAL(3,2) NOT NULL DEFAULT 0.25 CHECK (confidence_threshold >= 0.0 AND confidence_threshold <= 1.0),
    detection_model VARCHAR(100) NOT NULL DEFAULT 'yolo11l.pt',

    -- EndcapGeometry fields (flattened for better queryability)
    -- Basic geometry
    aspect_ratio DECIMAL(4,2) NOT NULL DEFAULT 1.35,
    left_margin_ratio DECIMAL(4,3) NOT NULL DEFAULT 0.010,
    right_margin_ratio DECIMAL(4,3) NOT NULL DEFAULT 0.030,
    top_margin_ratio DECIMAL(4,3) NOT NULL DEFAULT 0.020,
    bottom_margin_ratio DECIMAL(4,3) NOT NULL DEFAULT 0.050,
    inter_shelf_padding DECIMAL(4,3) NOT NULL DEFAULT 0.020,

    -- ROI detection margins
    width_margin_percent DECIMAL(4,3) NOT NULL DEFAULT 0.250,
    height_margin_percent DECIMAL(4,3) NOT NULL DEFAULT 0.300,
    top_margin_percent DECIMAL(4,3) NOT NULL DEFAULT 0.050,
    side_margin_percent DECIMAL(4,3) NOT NULL DEFAULT 0.050,

    -- Optional metadata
    description TEXT,
    brand VARCHAR(100),
    program_slug VARCHAR,
    version VARCHAR(20) DEFAULT '1.0',
    is_active BOOLEAN DEFAULT TRUE
);

-- Indexes for better query performance
CREATE INDEX idx_planograms_config_name ON troc.planograms_configurations(config_name);
CREATE INDEX idx_planograms_brand ON troc.planograms_configurations(brand);
CREATE INDEX idx_planograms_active ON troc.planograms_configurations(is_active);
CREATE INDEX idx_planograms_created_at ON troc.planograms_configurations(created_at);

-- GIN index for JSONB fields to enable efficient JSON queries
CREATE INDEX idx_planograms_config_gin ON troc.planograms_configurations USING GIN (planogram_config);
CREATE INDEX idx_planograms_ref_images_gin ON troc.planograms_configurations USING GIN (reference_images);

-- Trigger to automatically update the updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_planograms_configurations_updated_at
    BEFORE UPDATE ON troc.planograms_configurations
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Comments for documentation
COMMENT ON TABLE troc.planograms_configurations IS 'Stores planogram analysis pipeline configurations including prompts, reference images, and geometry parameters';
COMMENT ON COLUMN troc.planograms_configurations.planogram_config IS 'Complete planogram description as JSONB (shelves, products, compliance rules, etc.)';
COMMENT ON COLUMN troc.planograms_configurations.reference_images IS 'Reference images stored as JSONB with image paths/URLs, not binary data';
COMMENT ON COLUMN troc.planograms_configurations.roi_detection_prompt IS 'Prompt used for ROI detection phase by _find_poster method';
COMMENT ON COLUMN troc.planograms_configurations.object_identification_prompt IS 'Prompt used for Phase 2 object identification by _identify_objects method';

-- Example insert statement
-- INSERT INTO planograms_configurations (
--     config_name,
--     planogram_config,
--     roi_detection_prompt,
--     object_identification_prompt,
--     reference_images,
--     brand,
--     description
-- ) VALUES (
--     'hisense_tv_display_v1',
--     '{"brand": "Hisense", "shelves": [...]}',
--     'Find the Hisense promotional poster...',
--     'Identify the TV models and promotional graphics...',
--     '{"poster_ref": "/images/hisense_poster.jpg", "u7_ref": "/images/u7_tv.jpg"}',
--     'Hisense',
--     'Hisense TV display configuration for retail endcaps'
-- );
