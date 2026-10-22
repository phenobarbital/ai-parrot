-- FEAT-638: bot-level output language — `language` becomes nullable with no default.
--
-- NULL means "mirror the user" (today's behavior for LLM-authored text). Until now the
-- column defaulted to 'en' and the value was inert (it never reached a prompt), so an
-- existing 'en' is almost always the untouched default. It is reset to NULL.
--
-- LOSSY BY DESIGN: a row deliberately set to 'en' cannot be told apart from the default
-- and is reset too. Deployments that want English artifacts set language = 'en' again
-- after running this; the Spanish standup deployment sets language = 'es'.
BEGIN;

ALTER TABLE navigator.ai_bots ALTER COLUMN language DROP DEFAULT;
UPDATE navigator.ai_bots SET language = NULL WHERE language = 'en';

ALTER TABLE navigator.users_bots ALTER COLUMN language DROP DEFAULT;
UPDATE navigator.users_bots SET language = NULL WHERE language = 'en';

COMMIT;
