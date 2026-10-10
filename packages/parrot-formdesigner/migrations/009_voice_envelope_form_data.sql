-- Migration 009 (FEAT-649): voice answer envelopes in form_data.
-- Run once per physical schema:  psql "$DSN" -c "SET search_path TO navigator;" -f 009_voice_envelope_form_data.sql
-- Idempotent: CREATE OR REPLACE + string-only UPDATE guard.

CREATE OR REPLACE FUNCTION fd_unwrap_voice(doc jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE AS $$
    SELECT COALESCE(
        jsonb_object_agg(
            kv.key,
            CASE
                WHEN jsonb_typeof(kv.value) = 'object'
                     AND kv.value ? 'answer'
                     AND (kv.value->>'source' = 'speech' OR kv.value ? 'blob_ref')
                THEN kv.value->'answer'
                ELSE kv.value
            END
        ),
        '{}'::jsonb
    )
    FROM jsonb_each(COALESCE(doc, '{}'::jsonb)) AS kv
$$;

CREATE OR REPLACE VIEW form_data_scalar AS
    SELECT fd.*, fd_unwrap_voice(fd.data) AS data_scalar
    FROM form_data AS fd;

-- Legacy normalisation: string values on answer_envelope="voice" fields
-- become {"answer": <s>, "blob_ref": null}. Only values where
-- jsonb_typeof(...) = 'string' are touched, so re-running is a no-op.
-- Voice fields are discovered anywhere in form_schemas.schema_json (sections,
-- subsections, GROUP children); the join key is form_data.form_uid.
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT DISTINCT fs.form_uid AS form_uid, vf.fid AS fid
        FROM form_schemas AS fs,
             LATERAL (
                 SELECT jsonb_path_query(
                            fs.schema_json,
                            'strict $.** ? (@.answer_envelope == "voice").field_id'
                        ) #>> '{}' AS fid
             ) AS vf
        WHERE fs.form_uid IS NOT NULL
    LOOP
        UPDATE form_data AS fd
           SET data = jsonb_set(
                   fd.data,
                   ARRAY[r.fid],
                   jsonb_build_object('answer', fd.data -> r.fid, 'blob_ref', NULL)
               )
         WHERE fd.form_uid = r.form_uid
           AND jsonb_typeof(fd.data -> r.fid) = 'string';
    END LOOP;
END
$$;
