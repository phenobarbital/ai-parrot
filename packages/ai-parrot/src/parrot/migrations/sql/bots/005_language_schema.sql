-- Only the schema portion of FEAT-638; stored values are intentionally unchanged.
ALTER TABLE {schema}.{bots_table} ALTER COLUMN language DROP DEFAULT;
ALTER TABLE {schema}.{bots_table} ALTER COLUMN language DROP NOT NULL;
