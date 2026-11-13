-- MANUAL, LOSSY: intentionally clears language=en on ai_bots and users_bots.
-- Never run automatically through parrot self migration.
--
-- Take a backup before running this file. A deliberate English preference is
-- indistinguishable from the former default, so this operation intentionally
-- loses those values. Restore or reapply language = 'en' afterwards where it
-- remains an explicit preference.
DO $migration$
DECLARE
    relation_name TEXT;
    table_oid OID;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY['navigator.ai_bots', 'navigator.users_bots']
    LOOP
        table_oid := to_regclass(relation_name);
        IF table_oid IS NOT NULL
           AND EXISTS (
               SELECT 1 FROM pg_catalog.pg_attribute
               WHERE attrelid = table_oid AND attname = 'language' AND NOT attisdropped
           ) THEN
            EXECUTE format('ALTER TABLE %s ALTER COLUMN language DROP DEFAULT', table_oid::REGCLASS);
            EXECUTE format('UPDATE %s SET language = NULL WHERE language = ''en''', table_oid::REGCLASS);
        END IF;
    END LOOP;
END
$migration$;
