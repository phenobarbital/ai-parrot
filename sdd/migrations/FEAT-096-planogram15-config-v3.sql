-- ============================================================
-- FEAT-096 v3: Fix top shelf products array & middle shelf aliases
-- ============================================================
-- Table  : troc.planograms_configurations
-- Columns: planogram_config jsonb
--
-- Safe   : data-only UPDATE, no schema change
-- Status : PENDING
-- ============================================================
-- Context:
--   v2 fixed the top-shelf SECTIONS layout and renamed the
--   middle-shelf product RR-60 → ES-50 (name only).
--   But the top shelf's main PRODUCTS array (used for compliance
--   scoring) was never updated:
--     - Still has ES-50 ShelfProduct (belongs on middle shelf)
--     - Missing RR-60 ShelfProduct (belongs on top-right section)
--     - ES-50 Fact Tag should be RR-60 Fact Tag on top shelf
--   And the middle shelf:
--     - ES-50 still has stale aliases: ['RR-60','rr-60','rr60']
--     - RR-60 Fact Tag should be ES-50 Fact Tag
--
--   Changes:
--     1. Top shelf products: ES-50 → RR-60 (name + aliases + tier)
--     2. Top shelf fact tags: "ES-50 Fact Tag" → "RR-60 Fact Tag"
--     3. Middle shelf: fix ES-50 aliases to ['ES-50','es-50','es50']
--     4. Middle shelf fact tags: "RR-60 Fact Tag" → "ES-50 Fact Tag"
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
                    -- ── TOP SHELF: swap ES-50 → RR-60 in products array ──
                    WHEN shelf->>'level' = 'top' THEN
                        jsonb_set(
                            shelf,
                            '{products}',
                            (
                                SELECT coalesce(
                                    jsonb_agg(
                                        CASE
                                            -- Rename ES-50 product → RR-60
                                            WHEN prod->>'name' = 'ES-50'
                                                AND prod->>'product_type' = 'scanner'
                                            THEN (prod - 'tier' - 'aliases')
                                                || jsonb_build_object(
                                                    'name', 'RR-60',
                                                    'tier', 'lower',
                                                    'aliases', '["RR-60","rr-60","rr60"]'::jsonb
                                                )
                                            -- Rename ES-50 Fact Tag → RR-60 Fact Tag
                                            WHEN prod->>'name' = 'ES-50 Fact Tag'
                                            THEN jsonb_set(prod, '{name}', '"RR-60 Fact Tag"')
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

                    -- ── MIDDLE SHELF: fix ES-50 aliases & fact tag name ──
                    WHEN shelf->>'level' = 'middle' THEN
                        jsonb_set(
                            shelf,
                            '{products}',
                            (
                                SELECT coalesce(
                                    jsonb_agg(
                                        CASE
                                            -- Fix ES-50 aliases (were stale RR-60 aliases)
                                            WHEN prod->>'name' = 'ES-50'
                                                AND prod->>'product_type' = 'scanner'
                                            THEN jsonb_set(
                                                prod,
                                                '{aliases}',
                                                '["ES-50","es-50","es50"]'::jsonb
                                            )
                                            -- Rename RR-60 Fact Tag → ES-50 Fact Tag
                                            WHEN prod->>'name' = 'RR-60 Fact Tag'
                                            THEN jsonb_set(prod, '{name}', '"ES-50 Fact Tag"')
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
    -- Top shelf: verify RR-60 present, ES-50 absent
    (
        SELECT jsonb_agg(prod->>'name' ORDER BY p_ord)
        FROM jsonb_array_elements(planogram_config->'shelves'->1->'products')
        WITH ORDINALITY AS p(prod, p_ord)
        WHERE prod->>'product_type' = 'scanner'
    ) AS top_scanner_products,
    -- Top shelf: verify RR-60 Fact Tag present
    (
        SELECT jsonb_agg(prod->>'name' ORDER BY p_ord)
        FROM jsonb_array_elements(planogram_config->'shelves'->1->'products')
        WITH ORDINALITY AS p(prod, p_ord)
        WHERE prod->>'product_type' = 'fact_tag'
    ) AS top_fact_tags,
    -- Middle shelf: verify ES-50 aliases are correct
    (
        SELECT prod->'aliases'
        FROM jsonb_array_elements(planogram_config->'shelves'->2->'products')
        AS p(prod)
        WHERE prod->>'name' = 'ES-50'
        LIMIT 1
    ) AS middle_es50_aliases,
    -- Middle shelf: verify ES-50 Fact Tag (not RR-60 Fact Tag)
    (
        SELECT jsonb_agg(prod->>'name' ORDER BY p_ord)
        FROM jsonb_array_elements(planogram_config->'shelves'->2->'products')
        WITH ORDINALITY AS p(prod, p_ord)
        WHERE prod->>'product_type' = 'fact_tag'
    ) AS middle_fact_tags
FROM troc.planograms_configurations
WHERE planogram_id = 15;

COMMIT;
-- ROLLBACK;

-- ============================================================
-- ROLLBACK to v2 state (if needed after COMMIT)
-- ============================================================
-- Re-run FEAT-096-planogram15-config-v2.sql
