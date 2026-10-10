# Plan — Brainstorm `audio-form-interaction-workflow` (evolución de FEAT-224 / FEAT-236)

## Context

FEAT-224 (`sdd/specs/formdesigner-audio-renderer.spec.md`) y FEAT-236
(`sdd/specs/audio-renderer-form.spec.md`) están **implementados y cerrados** (índices
`sdd/tasks/index/formdesigner-audio-renderer.json`, `audio-renderer-form.json`, todas las
tareas `done`). El usuario pide un **brainstorm SDD** (no implementación) que defina la
siguiente evolución del formulario en modo audio (turnos TTS→STT con hints, pre-síntesis,
ayudas visuales, selectores ítem-por-ítem con respuesta por voz, STT por WS con el modelo ML
local, fallbacks HTML, persistir texto+audio de cada respuesta, compatibilidad con secciones y
dependencias pre/post, paso final de auditoría, runtime 100 % determinista con plantillas,
optimizador LLM opcional en design-time) y la explicación de cómo construir el renderer de
audio en el frontend `navigator-svelte` (repo externo).

Todo vive en `packages/parrot-formdesigner/src/parrot_formdesigner/` (paths relativos a él
salvo indicación). Verificado en `dev` HEAD `c1ec3fd40` (nota: `wikitoolkit` no está
instalado en este contenedor; se usó grep/read — decirlo en el brainstorm).

### Estado actual (verificado)

- `renderers/audio.py` — `split_into_questions()` L277 aplana `form.iter_all_fields()`
  (solo HIDDEN se salta, GROUP se expande); `classify_voice_mode()` L95 → `VoiceMode`
  VOICE | PROMPT_SELECT | VISUAL_FALLBACK con override `meta["voice_mode"]`;
  `build_audio_synthesizer()` L131 / `synthesize_with_fallback()` L164 SuperTonic→Google→None;
  `_resolve()` L218 (LocalizedString → locale → `en`).
- `audio/models.py` — `VoiceMode` L18, `AudioSessionConfig` L38, `AudioQuestion` L72,
  `AudioFormManifest` L128, `AudioAnswer` L153 (`value: str`, `source: text|speech|selection`),
  `AudioSessionState` L179 (solo memoria, `current_index: int`).
- `api/audio_ws.py` — `AudioFormWSHandler` L102 (1467 líneas). JWT por
  `Sec-WebSocket-Protocol` o mensaje `auth` (L282-343, `parrot.core.ws_auth.TokenValidator`);
  dispatch L368; `MAX_QUESTIONS = 10` L59 trunca en silencio L489-494; `_sniff_audio_suffix`
  L71 (EBML/OggS/ftyp/RIFF), `_MIN_AUDIO_BYTES = 256` L68; `max_msg_size` 10 MB L151;
  `_presynthize_to_cache` L1414 (solo con synthesizer inyectado; cache `dict[int,str]` L230);
  `_narration_text` L1333 (label + "Options: …"); `_handle_answer_audio` L691 → temp file →
  `transcribe(Path)` → gate `stt_confirm_threshold` L793-817 → `_accept_answer` L1009 guarda
  solo el string, audio descartado; `_handle_answer_selection` L560 (`",".join(values)` L595);
  `_advance_session` L1072 y `_advance_session_no_request` L1094 (dos copias, `index += 1`,
  sin dependencias); `_finish_session` L1115 construye `FormSubmission(form_version="1",
  data={fid: a.value})` y llama `FormSubmissionStorage.store()` **saltando**
  `FormAPIHandler.submit_data` (`api/handlers.py:1498`; sinks FEAT-457 exclusivos
  L1824-1830, forwarder L1887, eventos FEAT-188), con `registry.get(..., tenant=None)`.
- Ruta WS `GET /api/v1/{tenant}/forms/{form_uid}/audio/ws` en `api/routes.py:479-496`, solo si
  el host pasa `synthesizer`/`transcriber`/`token_validator` (`setup_form_api` L192, también
  recibe `blob_storage` L200 y `partial_store` L202 que el handler de audio **no** recibe).
- `core/schema.py` — `FormField` L65-140 (`label`, `description`, `placeholder`, `depends_on`,
  `post_depends`, `meta`, `content_type`, `accept_content_types`, `answer_envelope`), **sin
  `hint`**; bloques tipados en `FormSchema`: `events` L465, `persistence` L473,
  `unknown_fields` L475; `iter_all_fields()` L477 **no recurre en GROUP children**
  (usar `iter_fields_recursive()`/`walk_fields`).
- `core/constraints.py` — `DependencyRule` L216, `PostDependency` L334 (`set|calc|
  reload_options|show|hide|require|cascade_clear`). `services/rule_evaluator.py:555`
  `RuleEvaluator.resolve(form, answers, *, locale, location_vars, visit_context) ->
  RuleResolution{visible, required, computed, cleared}` (itera `iter_all_fields()` L598 ⇒ reglas
  en hijos de GROUP nunca se evalúan; sección gating L642-683). **Nunca se invoca desde audio.**
- `core/voice_answer.py:13` `VoiceAnswerEnvelope{answer: str, blob_ref, data_url}` (FEAT-488);
  `services/validators.py:542-548` solo lo acepta en TEXT/TEXT_AREA con `answer_envelope="voice"`
  (coerción L623-634).
- `services/blob_storage.py:119` `AbstractBlobStorage.put(stream, *, metadata: BlobMetadata) ->
  blob_ref` / `get` / `delete`; `BlobMetadata` L55 (`form_uid, form_id, field_uid, field_id,
  submission_id?, tenant, content_type, size_bytes, blob_id` regex `^[A-Za-z0-9_-]{1,128}$` L93).
- `services/partial_saves.py:24` `PartialSaveStore(ttl_seconds, redis_url)` `.save/.get/.delete`
  (merge-only, key `parrot:partial:{form_id}:{session_id}`, no-op sin Redis).
- `services/submissions.py:50` `FormSubmission` (`data` JSONB, `context`, `extra_data`,
  revisiones), `FormSubmissionStorage` L122 (DDL L188-210). FEAT-457 sinks:
  `services/sinks/mapper.py:142` `flatten_submission` / `_extract_value` L176 (solo ARRAY se
  `json.dumps`), `postgres_table.py:79` `_DEFAULT_DDL_TYPE = "TEXT"`, `jsonb_columns` L322-331
  ⇒ un dict en columna TEXT falla en asyncpg. `migrations/` 001–008 (`008_snippet_store.sql`,
  `README.md`; patrón py = `003_migrate_form_data.py`: asyncpg, `--dsn --schema --batch-size
  --dry-run`, idempotente).
- Voz (`packages/ai-parrot-integrations/src/parrot/voice/`): `tts/synthesizer.py:23`
  `VoiceSynthesizer.synthesize(text, *, language) -> SynthesisResult{audio, mime_format,
  duration_s}`, `get_shared_synthesizer` L186 / `close_shared_synthesizers` L213;
  `tts/models.py` `TTSConfig.backend Literal[google, elevenlabs, openai, supertonic, polly]`;
  SuperTonic WAV 44.1 kHz mono, sin SSML; `transcriber/backend.py:18`
  `AbstractTranscriberBackend.transcribe(Path, language) -> TranscriptionResult{text, language,
  duration_seconds, confidence: Optional, processing_time_ms}`; `TranscriberBackend` enum
  faster_whisper|openai_whisper|moonshine; sin streaming parcial; env
  `WHISPER_MODEL_SIZE/DEVICE/COMPUTE_TYPE` (root `app.py:278-282`), `SUPERTONIC_MODEL_PATH`.
- Frontend: admin UI `packages/ai-parrot-server/ui/src/lib/utils/voice-recorder.ts`
  (MediaRecorder webm→ogg→mp4), `VoiceNotePlayer.svelte`; **no existe cliente Svelte del WS de
  formularios en ningún repo**; `docs/audio-form-voice-modes.md` §7 protocolo, §9.10/9.11
  clientes JS/React de referencia. navigator-svelte solo se cita desde aquí
  (`constraints.py:203` `LogicGroup` ↔ `formbuilder/types/schema.ts`, `src/lib/api/ai-parrot.ts`,
  copia del renderer A2UI; handoff patrón `sdd/state/FEAT-430/handoff/navigator-svelte-brief.md`).
- Otros: `tools/` (`CreateFormTool`, `EditToolkit` L63, `api/operations.py`),
  `handlers.py:197` `_get_llm_client()`; `jinja2>=3.1` ya es dep del paquete
  (`pyproject.toml:41`), `redis` extra L61; `rapidfuzz` solo en core/pipelines/tools (opcional).

**Prometido en FEAT-224/236 y NO construido**: `audio_hint`; `MAX_QUESTIONS` por form; resume
Redis; matching voz→opción; `blob_storage` en VISUAL_FALLBACK; dependencias/secciones;
`FormValidator` inyectado pero nunca llamado; audio de respuesta nunca persistido;
`description`/`placeholder` nunca narrados. **Bugs adicionales encontrados**: binario sobre
PROMPT_SELECT guarda el transcript crudo como valor (no valida `options`); submit de audio
salta sinks/eventos/forwarder y pierde tenant; MULTI_SELECT se guarda como string con comas.

### Decisiones del usuario (no re-litigar)

| Tema | Decisión |
|---|---|
| Audio pre-sintetizado | **Solo WebSocket**: pre-síntesis en `start_session` + *prefetch* que empuja todos los audios al conectar. Sin audio en el HTTP manifest. |
| Config de voz por campo | **`FormField.hint: LocalizedString \| None`** de primer nivel; otros ajustes de voz en `FormField.meta`. |
| Texto+audio de la respuesta | **Envelope por campo en `data`**: `VoiceAnswerEnvelope {answer, blob_ref, …}` en `FormSubmission.data[field_id]`, audio en blob storage. |
| Alcance del envelope | **Toda respuesta hablada** (cualquier tipo contestado por voz); respuestas tecleadas/seleccionadas en UI quedan planas. |
| Selectores ítem-por-ítem | **Lista completa, luego escuchar**: cada opción es un segmento de audio; al final se abre el micro; el usuario dice label/ordinal/número; `option_matched` marca la opción en UI. |
| Migración `form_data` | **DDL por-form + normalizar legacy**: tablas FEAT-457 → columnas de campos voice a JSONB (`jsonb_build_object('answer', col)`); `form_data.data` strings legacy de campos declarados voice → `{answer, blob_ref: null}`; DDL del sink produce JSONB para voice en adelante. |
| Confirmación del review | **Voz o botón**: "OK/sí/enviar" por voz (matching determinista por locale) o botón Send → `confirm_submit`; "cambiar la N" vuelve a esa pregunta y regresa al review. |
| Extras en alcance | Resume Redis (`PartialSaveStore`), límite por form (nunca truncar required), optimizador LLM design-time, handoff frontend separado, migración. |

---

## Deliverables (docs-only, sin worktree, commit en `dev`)

1. `sdd/proposals/audio-form-interaction-workflow.brainstorm.md` — plantilla
   `sdd/templates/brainstorm.md`; estilo header `**Related**` de
   `sdd/proposals/parrot-installer.brainstorm.md`; Code Context dividido por repo como
   `sdd/proposals/report-builder.brainstorm.md` (§"Verified — ai-parrot" / "— navigator-svelte").
2. `sdd/proposals/audio-form-interaction-workflow.handoff-navigator-svelte.md` — brief para abrir
   sesión en navigator-svelte (patrón FEAT-430; NO usar `sdd/state/FEAT-224/`, pertenece a
   intent-router).
3. Commit solo de esos dos archivos: `sdd: add brainstorm for audio-form-interaction-workflow`;
   `git push -u origin dev` (retry 2s/4s/8s/16s si falla red).

Frontmatter:
```yaml
type: feature
base_branch: dev
projects: [parrot-formdesigner, ai-parrot-integrations, ai-parrot-server, docs]
tags: [formdesigner, audio-form, tts, stt, websocket, voice, navigator-svelte, migration]
```
Header: `**Status**: exploration`, `**Recommended Option**: B`, `**Related**:` FEAT-224 y
FEAT-236 (completed, base), FEAT-395 (fix tests WS), FEAT-234 (`RuleEvaluator`), FEAT-186
(partial saves), FEAT-457 (persistencia por form), FEAT-488 (`VoiceAnswerEnvelope`),
FEAT-389/393 (form_uid/field_uid), FEAT-231 (SuperTonic), FEAT-421 (tenant en URL), FEAT-544
(A2UI form renderer), FEAT-081/551 (renderers Telegram/Teams, reutilizadores futuros).

---

## Contenido del brainstorm

### Problem Statement
Gaps verificados + bugs adicionales (arriba) + requisitos nuevos del usuario (citar su lista
textual como "User-Provided" en prosa). Afectados: usuarios de campo/accesibilidad, autores de
formularios, navigator-svelte, operadores de datos (`form_data`).

### Constraints & Requirements
Runtime determinista (sin LLM en el loop); protocolo WS aditivo (`extra="forbid"` ⇒ el cliente
no envía claves desconocidas); `parrot.voice.*` opcional (`TYPE_CHECKING` guards
`audio_ws.py:41-54`); STT por archivo completo (no streaming), Moonshine solo WAV/inglés y
`confidence` puede ser `None`; SuperTonic WAV sin SSML ⇒ pausa como segmento separado;
un tenant por URL; nunca truncar required; nunca narrar `sensitive`; las decisiones del usuario.

### Options Explored
- **A — Evolución in-place de `audio_ws.py`** (patrón FEAT-236). Pros: diff pequeño, fixtures
  actuales. Cons: ya 1467 líneas con dos copias de advance y I/O mezclado con transiciones (origen
  del deadlock FEAT-395); review + re-planificación + resume lo llevan a >2500; intestable sin WS;
  el bypass del pipeline se arreglaría copiando ~90 líneas de `handlers.py`; nada reutilizable
  por Telegram/Teams. Effort: Medium-High.
- **B — Motor `AudioFormSession` agnóstico de transporte + adaptador WS delgado** (*recomendada*).
  Layout propuesto (nuevos salvo "modify"):
  ```
  core/voice.py                 VoiceFormConfig (bloque por form — ver Open Q1)
  core/voice_answer.py          modify: VoiceEvidenceEnvelope(answer: Any) + is_voice_envelope/unwrap_voice/wrap_voice
  core/schema.py                modify: FormField.hint (+ FormSchema.voice si Q1=typed)
  audio/models.py               modify: FieldVoiceMeta, UiCue, NarrationPlan, OptionMatch; deltas en AudioQuestion/AudioAnswer/AudioSessionState
  audio/voice_meta.py           field_voice_meta(field) desde meta["voice"] (extra=ignore, warning+default)
  audio/planner.py              QuestionPlanner: manifest + RuleEvaluator → plan visible, cap, cleared, next cursor
  audio/option_matcher.py       match_option() determinista + lexicon (ordinales, sí/no, conjunciones)
  audio/option_refiner.py       OptionRefiner protocol + impl LLM opcional (AbstractClient)
  audio/narration/{engine,lexicon}.py + templates/{en,es}/narration.yaml   Narrator (Jinja2 sandbox)
  audio/segments.py             AudioSegmentCache + síntesis (mueve _presynthize_to_cache/_synthesize/_auto_synthesize_cached)
  audio/engine.py               AudioFormSession: handle(event) -> list[Outbound], fases §estado
  audio/events.py               modelos Pydantic inbound/outbound discriminados por `type`
  audio/session_store.py        AudioSessionStore sobre PartialSaveStore (resume)
  audio/recordings.py           put/delete de grabaciones vía AbstractBlobStorage
  services/submission_pipeline.py  SubmissionPipeline.submit(...) extraído de handlers.py:1824-1909, usado por HTTP y motor
  services/sinks/mapper.py, postgres_table.py   modify: DDL/INSERT JSONB para campos voice (decisión migración)
  services/validators.py        modify: unwrap→validate→rewrap para envelopes en cualquier tipo contestado por voz
  api/audio_ws.py               modify → adaptador (~300 líneas): auth, tenant, decode JSON/binario, engine.handle(), encode
  api/handlers.py, api/routes.py  modify: endpoint optimize; HTTP submit usa SubmissionPipeline; pasar blob_storage/partial_store al audio
  tools/edit_toolkit.py         modify: `hint` en update_field; propose_voice_hints
  renderers/audio.py            modify: section/hint/ui_cue/narration en AudioQuestion
  renderers/{html5,jsonschema,adaptive_card,a2ui}.py   modify: exponer `hint` (x-hint / small.hint)
  migrations/009_voice_envelope_form_data.{sql,py}, 010_voice_envelope_report.py
  docs/audio-form-voice-modes.md  modify: protocolo v2
  ```
  Pros: cada requisito es un componente puro testeable; el adaptador no espera I/O dentro de
  transiciones (deadlocks FEAT-395 estructuralmente imposibles); arregla los bugs de submit y
  PROMPT_SELECT una sola vez; reutilizable por Telegram/Teams. Cons: diff mayor; refactor de
  ~90 líneas del submit HTTP (tarea propia con tests de paridad). Effort: High.
- **C (no convencional) — Audio form como superficie A2UI / linked-surfaces** (`renderers/a2ui.py`
  FEAT-544, `api/a2ui_wire.py`, FEAT-598). Pros: una familia de renderer; cues visuales gratis.
  Cons: A2UI no tiene primitiva de voz (`a2ui.py:248` baja AUDIO a `notice`), es acción
  request/response no stream con binarios; igual necesitaría el WS; FEAT-598 no shipped;
  `ai-parrot` es opcional para formdesigner. Effort: muy alto. Rechazar, anotar como convergencia
  futura (los `audio/events.py` de B podrían bajarse a envelopes A2UI).

Tablas 📦: `jinja2` (ya dep), `difflib` stdlib (matching; `rapidfuzz` opcional si importable),
`redis` (extra existente), `asyncpg` (migración), `unicodedata` (normalización). 🔗 reuse:
`RuleEvaluator`, `PartialSaveStore`, `AbstractBlobStorage`, `FormValidator`, `submit_data`,
`VoiceSynthesizer`/`get_shared_synthesizer`, `voice-recorder.ts`, `_sniff_audio_suffix`.

### Recommendation → B (explicar como arriba).

### Feature Description

**User-Facing (turno a turno)**
1. `start_session` → `session_started{protocol_version: 2, sections, review, tts_mime,
   prefetch_count, max_recording_seconds, warnings?}` → lote **`audio_segment`** (header JSON
   `{key, mime, bytes, kind: label|hint|options|review|system}` + 1 frame binario; sin base64)
   para todas las preguntas del plan inicial + frases de sistema; el cliente bufferiza por `key`.
2. `question` (claves v1 + `field_uid, section{uid,title}, hint?, prompt?, position{index,total},
   audio_keys ["q:<uid>:label","pause:600","q:<uid>:hint"], ui_cue{control, focus, highlight,
   submit_via}, answer_modes[], options[{value,label,ordinal}], required dinámico,
   computed_default?`). Narración: label → pausa (cliente) → frase puente ("Sugerencia:") → hint
   (si no hay hint, `description` opcional). `audio` base64 solo si el cliente pidió
   `prefetch:false` (compat v1).
3. VOICE: binario → `transcription{+language}` → gate → `answer_accepted{+blob_ref, matched?}`.
4. PROMPT_SELECT: segmentos `q:<uid>:options` ítem por ítem con ordinal; al terminar, micro; el
   binario pasa por el matcher → `answer_accepted{matched{value,label,method,score}}` (UI marca la
   opción) o `confirm_request{candidate, alternatives}` o `answer_rejected{code: NO_MATCH}` +
   re-enumerar una vez. `answer_selection` sigue siendo canónica y siempre disponible.
5. VISUAL_FALLBACK: `fallback_html` + `ui_cue{control: uploader, focus, highlight}` + frase puente
   ("Usa el control resaltado…"); `answer_payload` como hoy, y archivos vía `blob_storage`.
6. Secciones/dependencias: tras cada `answer_accepted` el planner ejecuta
   `RuleEvaluator.resolve(form, unwrap(answers))`; emite `plan_updated{order, hidden, cleared,
   required_changed}`; `question_skipped`/`answer_cleared` (y borrado del blob) según
   `cascade_clear`; `section_enter{section_uid, title, audio_key}` al cambiar de sección; `go_back
   {to_field_id?}` sobre el plan efectivo; campos `computed` read_only se narran como afirmación y
   se auto-aceptan.
7. **Review**: `review_start{items[{position, field_id, label, answer_text, has_audio,
   audio_key|blob}]}` → `review_item` (TTS "Pregunta N: … Respuesta: …" o la grabación vía
   `audio_segment{kind: review}`) → `review_prompt` "¿Está todo correcto?" → `review_confirm
   {confirmed}` (botón Send) o binario con "sí/ok/enviar" (lexicon) → `form_complete`;
   "cambiar la N" (matcher sobre los ítems) → `review_edit{field_id}` → pregunta → vuelve al review.
   `sensitive` se narra como "[hidden]".
8. `validation_errors{errors, first_field_id}` si `FormValidator` falla en submit → vuelve a esa
   pregunta con `return_to_review`.
9. `start_session{resume_session_id}` → `session_resumed{answers, phase, cursor, plan}` +
   prefetch + pregunta/review actual; errores `RESUME_FORBIDDEN|RESUME_UNAVAILABLE|RESUME_STALE`.

**Internal**
- Modelos: `FormField.hint`; `meta["voice"]` → `FieldVoiceMeta{prompt, enumerate: auto|always|
  never|count_only, confirm: auto|always|never, pause_ms, ui_cue, match_threshold,
  skip_in_review}` (se conserva `meta["voice_mode"]`); por form `VoiceFormConfig{enabled,
  max_questions=10|None, hint_pause_ms=600, enumerate_options, stt_confirm_threshold=0.6,
  option_match_threshold=0.8, review: always|never|ask, review_playback: tts|recording|both,
  store_recordings, resume_ttl_seconds, llm_refine_options=False, tts_backend, tts_voice,
  max_recording_seconds=60}`; resolución session ≤ form ≤ defaults (la sesión solo endurece).
  `AudioQuestion` += `section_uid/section_title/subsection_title, hint, prompt, narration,
  ui_cue, answer_modes, voice_meta`; `AudioAnswer.value: Any` (listas para MULTI_SELECT, bool para
  BOOLEAN) += `blob_ref, audio_mime, audio_bytes_len, duration_ms, matched, stt_language,
  answered_at`; `AudioSessionState`: `cursor: field_id`, `history`, `plan`, `phase: idle|asking|
  confirming|review|review_editing|submitting|complete|aborted`, `return_to_review`,
  `review_cursor`, `resolution`, `tenant`, `locale`, `submission_id` (pre-generado),
  `protocol_version`. `VoiceEvidenceEnvelope(VoiceAnswerEnvelope)` con `answer: Any` +
  `confidence, source, audio_mime, duration_ms, language` (FEAT-488 `answer: str` intacto en
  TEXT).
- Máquina de estados: CONNECTED → PLANNING → ASKING(cursor) → ACCEPTING → [CONFIRMING] →
  re-plan → siguiente | REVIEW → (review_edit → ASKING → REVIEW) → SUBMITTING → validate →
  errores → ASKING | COMPLETE. Invariante: el motor nunca hace I/O; `(state, event) → (state',
  outbound[])`. Planner: cursor = primer `fid` del plan visible sin respuesta aceptada; cap
  aplicado al plan visible manteniendo siempre los required (warning `required_exceeds_cap`,
  `hidden_by_cap` en `plan_updated`); re-planificación tras skip/go_back/cascade.
- Narración: `audio/narration/templates/<locale>/narration.yaml` (valores Jinja2 en
  `ImmutableSandboxedEnvironment`, `StrictUndefined`); claves `question, question_with_prompt,
  hint_bridge, options_intro, option_item, options_count_only, boolean_prompt, required_mark,
  confirm_readback, confirm_option, no_match, required_reject, skipped, section_intro,
  computed_statement, review_intro, review_item, review_item_skipped, review_all_correct,
  review_edit_ack, submitted, resume_welcome`; fallback `es-MX → es → en`; test de conformidad de
  claves por locale. `meta.voice.prompt` del autor NO es Jinja: `str.format_map` con whitelist
  `{label, hint, section, n, total}`. Pausa = segmento `pause:<ms>` (cliente); concat WAV
  opcional server-side solo para clientes de un solo archivo.
- Prefetch: síntesis secuencial por sesión (ONNX no concurrente) de label/hint/options por
  pregunta + `sys:*`, keyed `(form_uid, version, locale, voice, hash(text))`, cache por sesión +
  LRU cross-sesión en proceso; acotado a `max_questions`; el resto lazy en `_send_question`.
  Considerar `get_shared_synthesizer` + `asyncio.Lock` en vez de un synth por sesión.
- Matching (`audio/option_matcher.py`, puro): normalizar (NFKD, casefold, puntuación, fillers del
  lexicon) → exacto value/label → ordinal/cardinal ("la segunda", "opción 3", "última") →
  sí/no (BOOLEAN) → numérico (LIKERT/NPS/RANKING) → contains único → fuzzy `difflib` (≥0.8
  acepta; 0.6–0.8 `confirm_request`; <0.6 `NO_MATCH`); multi: split por conjunciones, "todas/
  ninguna"; aceptación efectiva `stt_confidence(None→1.0) × score ≥ threshold`. LLM
  (`OptionRefiner`, `_get_llm_client`) solo si `llm_refine_options` y método fuzzy/none; su
  resultado siempre pasa por `confirm_request` (nunca commit directo). Mismo motor para comandos
  de review.
- Persistencia de audio: en accept (no en finish) `blob_storage.put(iter([bytes]),
  metadata=BlobMetadata(form_uid, form_id, field_uid, field_id, submission_id, tenant,
  content_type, size_bytes, blob_id=f"voice-{session_id}-{field_uid}"))` (id determinista ⇒
  re-responder sobrescribe); pendientes (sin confirmar) solo en memoria; `blob_storage=None` o
  `store_recordings=False` ⇒ `blob_ref=None` (nunca `data_url`); borrar blob en cascade_clear /
  end_session sin submit; huérfanos por TTL = gap operativo (reporte 010).
- Submit (`_finish_session` nuevo): scalars = unwrap(answers) → `FormValidator.validate(form,
  scalars, locale, auth_context)` (re-ejecuta RuleEvaluator, hidden-required relax, FEAT-458) →
  errores ⇒ `validation_errors` (nunca guardar `is_valid=False`) → rewrap: cada campo con
  `source=="speech"` ⇒ `{answer: <escalar saneado>, blob_ref, confidence, source, audio_mime,
  duration_ms, language}` → `FormSubmission(submission_id=session.submission_id, form_version=
  form.version, tenant, user_id, locale, context={channel:"audio", session_id, stt_backend,
  tts_backend, protocol_version:2}, extra_data)` → `SubmissionPipeline.submit()` (sink-o-genérico,
  eventos, forwarder con escalares + `voice_data`, limpieza de partial) → `form_complete
  {stored_in}`.
- Migración (decisión del usuario; `migrations/009_voice_envelope_form_data.sql` +
  `009b/010_*.py` patrón 003): (a) tablas FEAT-457: para cada campo cuyo valor puede ser
  envelope, `ALTER TABLE … ALTER COLUMN <field_id> TYPE JSONB USING jsonb_build_object('answer',
  <field_id>)` (parametrizado por tabla, listado desde `form_schemas.persistence`); el mapa DDL
  del sink produce JSONB y `jsonb_columns` incluye esos campos (`postgres_table.py:322-331`);
  (b) `form_data.data`: strings legacy de campos con `answer_envelope="voice"` en el schema
  vigente → `{"answer": <str>, "blob_ref": null}` por lotes, idempotente, `--dry-run`; (c) función
  SQL `fd_unwrap_voice(jsonb)` + vista `form_data_scalar` para consumidores SQL que esperan
  escalares; (d) `010_voice_envelope_report.py`: inventario de envelopes, `blob_ref` huérfanos
  (`--blob-url`), y `--apply --downgrade` reversible. **Fricción a documentar**: no existen filas
  legacy con envelope (hoy se guardan strings) y las respuestas habladas legacy no son
  distinguibles salvo por `answer_envelope`; CSV/GSheet reciben el envelope JSON-serializado como
  ARRAY — alternativa evaluada y descartada por el usuario: columna reservada `voice_data JSONB`
  (patrón `extra_data`) con escalares planos; anotarla en Open Questions por si se reconsidera.
  Lectores a adaptar con `unwrap_voice()`: `list_revisions`, forwarder, `prefilled` en renderers
  HTML5/PDF, renderers Telegram/Teams, `_row_to_submission` (re-fold en lectura).
- Resume: respuestas (escalares, key `field_uid`) en el partial store normal (`save`; nuevo
  `remove_keys` para cascade_clear) ⇒ una sesión iniciada por voz puede terminarse en HTML
  (`/partial` + `merge_partials`); snapshot de cursor en `parrot:audio:{form_uid}:{session_id}`
  (`AudioSessionStore` reutilizando el cliente Redis/TTL del `PartialSaveStore`): `phase, cursor,
  history, review_cursor, return_to_review, locale, config, blob_refs, answer_meta, submission_id,
  user_id, tenant, saved_at, expires_at`. Autosave tras cada transición y en `finally` del WS.
  Al resumir: verificar `user_id` y tenant (sin oráculo de existencia), re-resolver el form
  (descartar `field_uid` inexistentes, re-validar opciones), **re-planificar** (no confiar en
  `plan` guardado), descartar `pending`, reutilizar `session_id` (blob ids estables); una sesión
  activa por usuario (`parrot:audio:active:{user_id}`).
- Límites: `max_questions` (default 10, `None` ilimitado) sobre el plan visible, required siempre
  dentro; `max_recording_seconds` reportado al cliente; cap de prefetch.
- Optimizador LLM (design-time): `POST /api/v1/{tenant}/forms/{form_uid}/voice/optimize`
  (`_wrap_auth`) + `EditToolkit.propose_voice_hints`; input `{locale, fields?, apply:false,
  style, max_hint_words}`; output `proposals[{field_uid, hint{locale}, prompt?, enumerate,
  rationale, warnings}]` + `narration_preview`; `apply:true` mapea a `update_field` vía
  `api/operations.py` (identidad `field_uid`, versión, validación); cliente
  `_get_llm_client()` con salida estructurada. Incluir un **self-test determinista del matcher**
  (colisiones de labels ≥0.8) que corre aun sin LLM.

**Edge Cases**: sin TTS → texto-solo con `narration` igual; STT falla → `AUDIO_DECODE_ERROR` y
re-grabar; `confidence=None` (Moonshine) → gate débil, auditar `stt_backend` en `context`;
desconexión en review → resume en `review`; form editado entre sesiones → `RESUME_STALE`/re-ask;
GROUP children: `RuleEvaluator` no recurre (`iter_all_fields`) ⇒ el planner hereda la
visibilidad del GROUP padre (o abrir decisión de `iter_fields_recursive` en el evaluador);
memoria ONNX con M sesiones concurrentes.

### Capabilities
New: `audio-form-interaction-workflow`, `formfield-hint`, `voice-answer-attachments`,
`audio-form-session-resume`, `audio-form-llm-optimizer`, `form-data-voice-envelope-migration`,
`submission-pipeline-extraction`. Modified: `formdesigner-audio-renderer` (FEAT-224),
`audio-renderer-form` (FEAT-236), `formfield-content-type` (FEAT-488), `formbuilder-formschema-
persistency` (FEAT-457), `formdesigner-partial-saves` (FEAT-186), `formdesigner-conditional-
sections` (FEAT-234, solo si se recurre en GROUP).

### Impact & Integration — tabla con los módulos del layout B (extends/modifies/depends on).

### Code Context
- User-Provided Code: ninguno; citar la lista de requisitos del usuario textual.
- Verified — ai-parrot: todas las firmas/paths:líneas de "Estado actual" (reproducirlas en los
  bloques `#### Classes & Signatures`, `#### Verified Imports`, `#### Key Attributes & Constants`).
- Verified — navigator-svelte: solo lo citado desde este repo, marcado "no verificado aquí".
- Does NOT Exist: `FormField.hint`, `FormField.audio_hint`, `meta["audio_hint"]` en runtime,
  `FormSchema.voice`, `core/voice.py`, `AudioQuestion.hint/narration/ui_cue/section_uid`,
  `AudioAnswer.blob_ref/matched`, `AudioSessionState.phase/cursor/plan`, mensajes
  `audio_segment/plan_updated/section_enter/question_skipped/answer_cleared/review_*/
  session_resumed/validation_errors/goto_question/save_session`, `audio/{engine,planner,
  option_matcher,option_refiner,narration,segments,events,session_store,recordings}.py`,
  `services/submission_pipeline.py`, `migrations/009_*`/`010_*`, `PartialSaveStore.remove_keys`,
  uso de `RuleEvaluator` en audio, `AbstractTranscriberBackend.transcribe_bytes()`/streaming, SSML
  en SuperTonic, `VoiceSynthesizer.synthesize_to_base64()`, primitiva de voz en A2UI, cliente
  Svelte del WS de formularios, `wikitoolkit` en este contenedor.

### Parallelism Assessment
Internal: tras "modelos+schema", 3 lanes — (1) planner+matcher+narrator, (2) persistencia+
pipeline+sinks+migraciones, (3) resume; luego engine+adaptador integra; optimizador y handoff al
final. Cross-feature: `schema.py`/`validators.py`/`handlers.py` (verificar FEAT-636 en vuelo:
`git log` reciente muestra solo merge #1304); `audio_ws.py` (FEAT-395 cerrado). Recomendado
`mixed`.

### Open Questions (`[x]` resueltas con *Owner: Jesus*; `[ ]` abiertas)
Resueltas: entrega solo WS; `hint` plano; envelope en data; alcance "toda respuesta hablada";
lista-completa-luego-escuchar; migración DDL por-form + legacy; review voz-o-botón; extras.
Abiertas:
1. Bloque por form: `FormSchema.voice` tipado (precedente `persistence`/`events`, recomendado) vs
   `meta["voice"]`.
2. ¿MULTI_SELECT por voz se guarda como lista (recomendado; `form_complete` sigue mostrando string)?
3. Review de campos `sensitive`: narrar "[hidden]" o saltar el ítem.
4. ¿Los endpoints HTTP `/partial` conocen el snapshot de audio (resume cross-canal) o solo respuestas?
5. `VoiceEvidenceEnvelope.answer: Any` como subclase (recomendado, FEAT-488 intacto) vs un solo
   modelo.
6. Refinamiento LLM en runtime: off por defecto (recomendado) vs on con baja confianza.
7. Optimizador: `apply:true` directo o siempre staging con aceptación humana en el designer.
8. Migración: ventana de mantenimiento para `ALTER COLUMN` en tablas por-form; ¿reconsiderar
   `voice_data` sidecar para CSV/GSheet?
9. GROUP children en `RuleEvaluator` (`iter_fields_recursive`): ¿cambiar también la validación HTTP?
10. Umbrales (0.8/0.6) y lexicons `pt`/`fr`: owners.
11. Synth compartido con lock vs uno por sesión (memoria ONNX).

---

## Handoff `…handoff-navigator-svelte.md` (patrón FEAT-430)

1. Qué entregar: renderer de audio con `VoiceFormSession` (clase con runes `$state` en
   `.svelte.ts`; estados `idle → connecting → prefetching → asking{listening|recording|
   transcribing|confirming|visual} → review{playing|awaiting} → submitting → complete|error|
   resuming`), `VoiceSegmentCache` (AudioContext, buffers por `key`, `pause:<ms>` = timeout,
   barge-in al grabar), `VoiceRecorder` (portar `voice-recorder.ts`: MediaRecorder
   webm→ogg→mp4, **un contenedor completo por respuesta**, ≥256 bytes, Safari → mp4), componentes
   `VoiceFormShell`, `VoiceQuestionCard` (hint tras pausa, transcript `aria-live`),
   `VoiceControlCue` (monta el control propio del formbuilder según `render_mode`/`ui_cue`,
   uploader → `answer_payload`), `VoiceOptionList` (badges ordinales = lo narrado),
   `VoiceConfirmBar`, `VoiceReviewList` (play TTS/grabación, "Cambiar", botón Send),
   `VoiceResumeBanner`; atajos (espacio push-to-talk, R repetir, B atrás); fallback texto/sin micro.
2. Contrato backend verificado: URL WS tenant-qualified vía `apiAiUrl`, JWT en
   `Sec-WebSocket-Protocol` o mensaje `auth`, protocolo v2 completo (tabla cliente→servidor /
   servidor→cliente), `audio_segment` header+binario, `audio/wav` SuperTonic, códigos de error
   (`EMPTY_AUDIO`, `UNSUPPORTED_AUDIO`, `AUDIO_DECODE_ERROR`, `WRONG_FIELD`, `NO_MATCH`,
   `RESUME_*`, `TOO_MANY_QUESTIONS`), persistencia de `session_id` (localStorage por form_uid).
3. Constraints: determinismo, `sensitive`, `extra="forbid"`, prefetch obligatorio, pausa en
   cliente, `hidden_by_cap`.
4. Prior art a localizar allí: renderer del formbuilder, copia A2UI, `ai-parrot.ts`, specs de
   voz propias.
5. Open questions sugeridas: dónde monta (form público vs preview del formbuilder), "más
   preguntas" para `hidden_by_cap`, Capacitor/mime, playback por defecto en review, alcance del
   session_id.
6. Coordinación: FEAT propio allí; `sdd/BACKEND-REQUEST-audio-form.md` si necesitan cambios.

---

## Pasos de ejecución

1. `cd /home/user/ai-parrot && git checkout dev && git pull origin dev`.
2. Re-verificar justo antes de citar (spot-check ≥10 refs con `sed -n`): líneas de
   `audio_ws.py`, `schema.py`, `rule_evaluator.py`, `validators.py:542-548`, `mapper.py:176`,
   `postgres_table.py:79,322`, `handlers.py:1824,1887,197`, `routes.py:192,479`,
   `blob_storage.py:93,119`, `partial_saves.py:24`, `pyproject.toml:41`.
3. Escribir el brainstorm (todas las secciones de la plantilla, en el orden de la plantilla, con
   `**Related**` en el header; español como el resto de la conversación es aceptable pero el
   repo mezcla idiomas — usar **inglés** para el cuerpo técnico como los brainstorms recientes,
   salvo que el usuario pida español).
4. Escribir el handoff.
5. `git add` solo los dos archivos → `git diff --cached --name-only` debe listar solo esos →
   commit `sdd: add brainstorm for audio-form-interaction-workflow` → `git push -u origin dev`.

## Verificación

- `source .venv/bin/activate && python -m scripts.sdd.doc_taxonomy --kind brainstorm --json`
  lista el nuevo archivo con `projects`/`tags` válidos (si `.venv` no existe, `python3 -m
  scripts.sdd.doc_taxonomy ...` desde la raíz).
- Cada `path:línea` citado existe (spot-check); ninguna referencia de "Does NOT Exist" aparece en
  el código.
- El brainstorm no contradice las 8 decisiones del usuario; todas las Open Questions resueltas
  van en formato `[x] … — *Owner: Jesus*: …`.
- `git status` limpio tras el commit; push confirmado. Siguiente: `/sdd-spec
  audio-form-interaction-workflow`.
