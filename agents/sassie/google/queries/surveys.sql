WITH
/* ---------- 1 · Preguntas --------------------------------------------------------------------------- */
questions AS (
    SELECT
        fq.question_id,
        regexp_replace(fq.question_text,'<[^>]*>','','g') AS question_text,
        fq.question_order_number::int                     AS question_order
    FROM   sassie.form_questions fq
    WHERE  fq.formid                = 1400
      AND  fq.hide_from_clients     = 0
      AND  fq.hide_from_client_masters = 0
      AND  fq.question_format IN (9,10,12,13,20,24,25,31,33)
      ---AND  fq.question_id NOT IN ('1400:1', '1400:31', '1400:321', '1400:41','1400:51','1400:61','1400:71','1400:81','1400:91','1400:101','1400:111','1400:121','1400:261', '1400:11', '1400:311', '1400:241')
      AND fq.question_id IN ('{question}')
),

/* ---------- 2 · Diccionario de opciones ------------------------------------------------------------- */
opts AS (
  SELECT
      obj ->> 'answer_option_id'   AS answer_option_id,
      obj ->> 'answer_option_text' AS answer_option_text
  FROM  sassie.form_questions fq
  CROSS JOIN LATERAL
    -- nivel ① : garantiza que siempre partimos de un array JSON
    jsonb_array_elements(
      CASE
        WHEN jsonb_typeof(fq.answer_options) = 'array'
            THEN fq.answer_options
        ELSE jsonb_build_array(fq.answer_options)
      END
    ) AS mid_str
  CROSS JOIN LATERAL
    -- nivel ② : si cada elemento aún es string, lo vuelve a descomponer
    jsonb_array_elements(
      CASE
        WHEN jsonb_typeof(mid_str) = 'string' THEN mid_str::jsonb
        ELSE jsonb_build_array(mid_str)
      END
    ) AS obj
  WHERE fq.formid = 1400
),

/* ---------- 3 · Respuestas con texto normalizado ---------------------------------------------------- */
responses AS (
    SELECT
        fr.activity_item_id,
        fr.question_id,
        COALESCE(
          /* A · traducción mediante answer_option_id(s) ------------------- */
          ( SELECT string_agg(DISTINCT o.answer_option_text, ', ')
              FROM (
                    /* ids presentes en la columna jsonb ------------------- */
                    SELECT jsonb_array_elements_text(fr.answer_option_ids::jsonb) AS ans_id
                    WHERE fr.answer_option_ids IS NOT NULL

                    UNION ALL

                    /* id “sintético” si la lista está vacía pero existe mapping */
                    SELECT fr.question_id || ':' || fr.response_text
                    WHERE fr.response_text ~ '^[0-9]+$'
                      AND EXISTS (
                        SELECT 1 FROM opts o2
                                   WHERE o2.answer_option_id = fr.question_id || ':' || fr.response_text)
                   ) ids
              JOIN opts o ON o.answer_option_id = ids.ans_id ),
          /* B · texto libre ------------------------------------------------ */
          fr.response_text
        ) AS answer_text
    FROM   sassie.form_responses fr
    WHERE  fr.formid = 1400
    GROUP  BY fr.activity_item_id, fr.question_id,
              fr.response_text, fr.answer_option_ids
),


/* ---------- 4 · Visitas núcleo (filtrado por fechas) ----------------------------------------------- */
visits AS (
    SELECT
        actst.activity_item_id,
        act.shopper_id,
        actst.client_name,
        actst.store_id,
        actst.store_number,
        actst.store_name,
        actst.store_address,
        actst.city,
        actst.state_code,
        actst.country_code,
        actst.zipcode,
        act.account_name,
        actst.territory_name,
        actst.region_name,
        actst.district_name,
        actst.market_name,
        act.activity_item_actual_end
    FROM   sassie.activities_stores actst
    JOIN   sassie.activities act
           ON act.activity_item_id = actst.activity_item_id
    WHERE  act.formid      = 1400
      AND  act.status_code >= 3
    ---  AND  act.activity_item_updateddon BETWEEN 'firstdate' AND 'lastdate'
),
totals AS (
  SELECT
      COUNT(DISTINCT v.store_number)     AS qty_stores_visited,
      COUNT(DISTINCT v.account_name)     AS qty_retailers_visited,
      COUNT(DISTINCT v.activity_item_id) AS qty_total_visits,
      COUNT(DISTINCT v.state_code)       AS qty_states_visited,
      COUNT(DISTINCT v.shopper_id)       AS qty_mystery_shoppers
  FROM visits v
)
/* ---------- 5 · Resultado final --------------------------------------------------------------------- */
SELECT
    v.activity_item_id::text       AS "evaluation_id",
    v.client_name                  AS "client_name",
    v.shopper_id                   AS "shopper_id",
    v.activity_item_actual_end     AS "visit_date",
    v.store_number::text           AS "store_number",
    v.store_name                   AS "store_name",
    v.city                         AS "city",
    v.state_code                   AS "state_code",
    v.account_name                 AS "account_name",
    v.district_name                AS "district",
    v.region_name                  AS "region",
    v.territory_name               AS "division",
    v.market_name                  AS "market",
    jsonb_agg(jsonb_build_object('survey_id', v.activity_item_id, 'question_id', q.question_id, 'question', q.question_text, 'answer', r.answer_text)) as visit_data,
    t.qty_stores_visited,
    t.qty_retailers_visited,
    t.qty_total_visits,
    t.qty_states_visited,
    t.qty_mystery_shoppers
FROM   visits     v
CROSS  JOIN questions q
LEFT   JOIN responses r
       ON  r.activity_item_id = v.activity_item_id
       AND r.question_id      = q.question_id
CROSS  JOIN totals t
GROUP BY v.activity_item_id, v.client_name, v.shopper_id, v.activity_item_actual_end,
         v.store_number, v.store_name, v.store_address, v.city, v.state_code,
         v.country_code, v.zipcode, v.account_name, v.district_name, v.region_name, v.territory_name, v.market_name,
         t.qty_stores_visited, t.qty_retailers_visited, t.qty_total_visits, t.qty_states_visited, t.qty_mystery_shoppers
ORDER BY v.activity_item_id
