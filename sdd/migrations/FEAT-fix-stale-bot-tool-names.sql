-- ============================================================
-- Remap stale bot tool names to canonical TOOL_REGISTRY keys
-- ============================================================
-- Table  : navigator.ai_bots
-- Column : tools (jsonb — array of tool-name strings)
--          NOTE: the CREATE TABLE string in parrot/handlers/models/bots.py
--          names this column ``available_tools``, but the live schema uses
--          ``tools`` (matching the BotModel.tools field). This migration
--          targets the live column name.
--
-- Purpose:
--   Several bots list tool names that were never valid TOOL_REGISTRY
--   keys, so tool loading logged "Unknown tool or toolkit" and the bots
--   silently ran without those tools:
--
--     ReviewsAgent    : "WebScraperTool"  -> "web_scraping"  (toolkit)
--     key_statistics  : "Ibis"            -> "ibisworld"
--     financial_data  : "Tickertool"      -> "yfinance"
--
--   The companion code fix (ToolManager.load_tool now resolves the
--   discovered TOOL_REGISTRY) makes the canonical names loadable; this
--   migration rewrites the stored names so the existing bots pick them up.
--
--   The individual WebScrapingTool is deprecated in favour of the
--   WebScrapingToolkit, so "WebScraperTool" is remapped to the toolkit
--   name "web_scraping" rather than "web_scraping_tool".
--
-- Scope:
--   Generic — remaps every occurrence of the three legacy names across
--   all rows, not just the three known bots, so any other bot carrying
--   the same stale names is fixed too.
--
-- Safe   : order-preserving and idempotent. The WHERE clause only matches
--          rows that still contain a legacy name, so re-running is a no-op.
--          Validated 2026-07-14 against the live navigator.ai_bots schema
--          with synthetic rows in a rolled-back transaction (order kept,
--          unrelated tools untouched, clean rows skipped, re-run = 0 rows).
-- Status : pending. NOTE: navigator.ai_bots on dev has 0 rows — the bots
--          that logged the errors (ReviewsAgent / key_statistics /
--          financial_data) live in another environment (staging/prod).
--          Apply there; on dev this is a harmless no-op.
-- ============================================================

BEGIN;

-- Rewrite the tools array element-by-element, preserving array order.
-- Only rows that still reference a legacy name are touched.
UPDATE navigator.ai_bots AS b
SET tools = (
        SELECT jsonb_agg(
                   CASE elem #>> '{}'
                       WHEN 'WebScraperTool' THEN '"web_scraping"'::jsonb
                       WHEN 'Ibis'           THEN '"ibisworld"'::jsonb
                       WHEN 'Tickertool'     THEN '"yfinance"'::jsonb
                       ELSE elem
                   END
                   ORDER BY ord
               )
        FROM jsonb_array_elements(b.tools) WITH ORDINALITY AS t(elem, ord)
    )
WHERE b.tools ?| array['WebScraperTool', 'Ibis', 'Tickertool'];

-- Verification (run manually after apply — should return zero rows):
--   SELECT name, tools
--   FROM navigator.ai_bots
--   WHERE tools ?| array['WebScraperTool', 'Ibis', 'Tickertool'];

COMMIT;

-- ============================================================
-- Rollback
-- ============================================================
-- CAUTION: this reverse-maps the canonical names back to the legacy
-- names. It cannot distinguish bots migrated by this script from bots
-- that legitimately use "web_scraping" / "ibisworld" / "yfinance", so it
-- will rename those too. Prefer restoring the tools column from a backup.
--
-- BEGIN;
--
-- UPDATE navigator.ai_bots AS b
-- SET tools = (
--         SELECT jsonb_agg(
--                    CASE elem #>> '{}'
--                        WHEN 'web_scraping' THEN '"WebScraperTool"'::jsonb
--                        WHEN 'ibisworld'    THEN '"Ibis"'::jsonb
--                        WHEN 'yfinance'     THEN '"Tickertool"'::jsonb
--                        ELSE elem
--                    END
--                    ORDER BY ord
--                )
--         FROM jsonb_array_elements(b.tools) WITH ORDINALITY AS t(elem, ord)
--     )
-- WHERE b.tools ?| array['web_scraping', 'ibisworld', 'yfinance'];
--
-- COMMIT;
