-- ============================================================
-- FEAT-096: Migrate planogram_id=15 → endcap_backlit_multitier
-- ============================================================
-- Table  : troc.planograms_configurations
-- Columns verified:
--   planogram_type   varchar(100)   — separate column
--   planogram_config jsonb          — JSON config column
--
-- Safe   : data-only UPDATE, no schema change
-- Status : APPLIED 2026-04-13
-- ============================================================
-- Context:
--   planogram_id=15 is the Epson scanner backlit endcap
--   (config_name: epson_scanner_backlit_planogram_config,
--    account: Office Depot).
--
--   Change: product_on_shelves → endcap_backlit_multitier
--   The top shelf (multi-riser with 2 tiers) is subdivided
--   into 3 horizontal sections to prevent cross-tier
--   hallucinations during LLM product detection.
--
--   Sections layout (all span full shelf height y=0→1):
--     left   (0.00–0.35): ES-60W  / ES-C320W / ES-50
--     center (0.35–0.65): ES-580W / FF-680W
--     right  (0.65–1.00): RR-70W  / RR-600W
--
--   Middle and bottom shelves remain flat (sections = null).
-- ============================================================

BEGIN;

UPDATE troc.planograms_configurations
SET
    planogram_type   = 'endcap_backlit_multitier',
    planogram_config = jsonb_set(
        planogram_config,
        '{shelves}',
        (
            SELECT jsonb_agg(
                CASE
                    WHEN shelf->>'level' = 'top' THEN
                        shelf
                        || '{"section_padding": 0.05}'::jsonb
                        || jsonb_build_object(
                            'sections', '[
                                {
                                  "id": "left",
                                  "region": {
                                    "x_start": 0.00, "x_end": 0.35,
                                    "y_start": 0.0,  "y_end": 1.0
                                  },
                                  "products": ["ES-60W", "ES-C320W", "ES-50"]
                                },
                                {
                                  "id": "center",
                                  "region": {
                                    "x_start": 0.35, "x_end": 0.65,
                                    "y_start": 0.0,  "y_end": 1.0
                                  },
                                  "products": ["ES-580W", "FF-680W"]
                                },
                                {
                                  "id": "right",
                                  "region": {
                                    "x_start": 0.65, "x_end": 1.00,
                                    "y_start": 0.0,  "y_end": 1.0
                                  },
                                  "products": ["RR-70W", "RR-600W"]
                                }
                            ]'::jsonb
                        )
                    ELSE shelf   -- header / middle / bottom unchanged
                END
                ORDER BY ord
            )
            FROM jsonb_array_elements(planogram_config->'shelves')
            WITH ORDINALITY AS t(shelf, ord)
        )
    )
WHERE planogram_id = 15;

-- ============================================================
-- VERIFICATION  (review before COMMIT)
-- ============================================================
SELECT
    planogram_id,
    planogram_type,
    planogram_config->'shelves'->0->>'level'          AS shelf_0_level,
    planogram_config->'shelves'->1->>'level'          AS shelf_1_level,
    planogram_config->'shelves'->1->'section_padding' AS top_padding,
    planogram_config->'shelves'->1->'sections'        AS top_sections,
    planogram_config->'shelves'->2->>'level'          AS shelf_2_level,
    planogram_config->'shelves'->2->'sections'        AS middle_sections,   -- expect NULL
    planogram_config->'shelves'->3->>'level'          AS shelf_3_level,
    planogram_config->'shelves'->3->'sections'        AS bottom_sections    -- expect NULL
FROM troc.planograms_configurations
WHERE planogram_id = 15;

COMMIT;
-- ROLLBACK;

-- ============================================================
-- ROLLBACK SCRIPT (if needed after COMMIT)
-- ============================================================
-- UPDATE troc.planograms_configurations
-- SET
--     planogram_type   = 'product_on_shelves',
--     planogram_config = jsonb_set(
--         planogram_config,
--         '{shelves}',
--         (
--             SELECT jsonb_agg(
--                 shelf - 'sections' - 'section_padding'
--                 ORDER BY ord
--             )
--             FROM jsonb_array_elements(planogram_config->'shelves')
--             WITH ORDINALITY AS t(shelf, ord)
--         )
--     )
-- WHERE planogram_id = 15;
