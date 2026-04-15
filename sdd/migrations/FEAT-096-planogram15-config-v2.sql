-- ============================================================
-- FEAT-096 v2: Fix planogram_id=15 section layout & middle shelf products
-- ============================================================
-- Table  : troc.planograms_configurations
-- Columns: planogram_type varchar(100), planogram_config jsonb
--
-- Safe   : data-only UPDATE, no schema change
-- Status : PENDING
-- ============================================================
-- Context:
--   The v1 migration (APPLIED 2026-04-13) had incorrect product
--   placement based on assumed positions.  After comparing the
--   100%-compliance reference photo with each product's reference
--   image the REAL physical layout is:
--
--   TOP SHELF sections (all span full shelf height y=0→1):
--     left   (0.00–0.35): ES-580W / ES-C320W / ES-60W
--     center (0.35–0.58): FF-680W   (single product)
--     right  (0.58–1.00): RR-600W / RR-70W / RR-60
--
--   MIDDLE SHELF products (flat, no sections):
--     ES-C220, ES-400, ES-50
--     (was: ES-C220, RR-60, ES-400 — RR-60 is actually on top-right,
--      ES-50 is actually on the middle shelf)
--
--   Changes from v1:
--     1. ES-580W moved:   center → left
--     2. RR-60 moved:     middle shelf → top-right
--     3. ES-50 moved:     top-left → middle shelf
--     4. Center section:  narrowed (0.35–0.58), now FF-680W only
--     5. Right section:   widened  (0.58–1.00), now 3 products
-- ============================================================

BEGIN;

UPDATE troc.planograms_configurations
SET
    planogram_config = jsonb_set(
        planogram_config,
        '{shelves}',
        (
            SELECT jsonb_agg(
                CASE
                    -- ── TOP SHELF: fix section products & boundaries ──
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
                                  "products": ["ES-580W", "ES-C320W", "ES-60W"]
                                },
                                {
                                  "id": "center",
                                  "region": {
                                    "x_start": 0.35, "x_end": 0.58,
                                    "y_start": 0.0,  "y_end": 1.0
                                  },
                                  "products": ["FF-680W"]
                                },
                                {
                                  "id": "right",
                                  "region": {
                                    "x_start": 0.58, "x_end": 1.00,
                                    "y_start": 0.0,  "y_end": 1.0
                                  },
                                  "products": ["RR-600W", "RR-70W", "RR-60"]
                                }
                            ]'::jsonb
                        )

                    -- ── MIDDLE SHELF: replace RR-60 with ES-50 ──
                    WHEN shelf->>'level' = 'middle' THEN
                        jsonb_set(
                            shelf,
                            '{products}',
                            (
                                SELECT coalesce(
                                    jsonb_agg(
                                        CASE
                                            WHEN prod->>'name' = 'RR-60' THEN
                                                jsonb_set(prod, '{name}', '"ES-50"')
                                            ELSE prod
                                        END
                                        ORDER BY p_ord
                                    ),
                                    shelf->'products'
                                )
                                FROM jsonb_array_elements(shelf->'products')
                                WITH ORDINALITY AS p(prod, p_ord)
                            )
                        )

                    -- ── HEADER / BOTTOM: unchanged ──
                    ELSE shelf
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
    -- Top shelf sections
    planogram_config->'shelves'->1->>'level'          AS top_level,
    planogram_config->'shelves'->1->'sections'->0->'products' AS top_left_products,
    planogram_config->'shelves'->1->'sections'->1->'products' AS top_center_products,
    planogram_config->'shelves'->1->'sections'->2->'products' AS top_right_products,
    -- Section boundaries
    planogram_config->'shelves'->1->'sections'->1->'region'->>'x_start' AS center_x_start,
    planogram_config->'shelves'->1->'sections'->1->'region'->>'x_end'   AS center_x_end,
    planogram_config->'shelves'->1->'sections'->2->'region'->>'x_start' AS right_x_start,
    -- Middle shelf products
    planogram_config->'shelves'->2->>'level'          AS middle_level,
    planogram_config->'shelves'->2->'products'         AS middle_products
FROM troc.planograms_configurations
WHERE planogram_id = 15;

COMMIT;
-- ROLLBACK;

-- ============================================================
-- ROLLBACK to v1 state (if needed after COMMIT)
-- ============================================================
-- Re-run the original FEAT-096-planogram15-config.sql
