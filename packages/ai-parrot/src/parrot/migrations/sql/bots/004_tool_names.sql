-- Source: FEAT-fix-stale-bot-tool-names.sql; retain order and unrelated JSON elements.
UPDATE "{schema}"."{bots_table}" AS b
SET tools = (
    SELECT jsonb_agg(
        CASE elem #>> '{}'
            WHEN 'WebScraperTool' THEN '"web_scraping"'::JSONB
            WHEN 'Ibis' THEN '"ibisworld"'::JSONB
            WHEN 'Tickertool' THEN '"yfinance"'::JSONB
            ELSE elem
        END ORDER BY ord
    )
    FROM jsonb_array_elements(b.tools) WITH ORDINALITY AS t(elem, ord)
)
WHERE jsonb_typeof(b.tools) = 'array'
  AND b.tools ?| ARRAY['WebScraperTool', 'Ibis', 'Tickertool'];

-- Non-array values are incompatible with the application model but are deliberately left untouched.
