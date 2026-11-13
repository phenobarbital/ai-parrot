-- No stored-language data invariant: en/es/NULL are all preserved.
SELECT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = trim(BOTH '"' FROM '{schema}')
      AND table_name = trim(BOTH '"' FROM '{bots_table}')
      AND column_name = 'language'
      AND is_nullable = 'YES'
      AND column_default IS NULL
);
