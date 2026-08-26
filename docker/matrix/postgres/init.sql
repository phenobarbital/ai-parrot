-- Creates the Synapse database (with the collation Synapse requires) plus
-- one database per mautrix bridge, for the AI-Parrot Matrix dev stack
-- (FEAT-463). Runs once via postgres:16-alpine's
-- /docker-entrypoint-initdb.d/ mechanism.

CREATE DATABASE synapse
    ENCODING 'UTF8'
    LC_COLLATE 'C'
    LC_CTYPE 'C'
    TEMPLATE template0
    OWNER synapse;

CREATE DATABASE mautrix_signal OWNER synapse;
CREATE DATABASE mautrix_slack OWNER synapse;
CREATE DATABASE mautrix_discord OWNER synapse;
