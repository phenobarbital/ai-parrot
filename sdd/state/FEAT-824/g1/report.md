# SurrealDB G1 Spike Report

- **Server Image**: `surrealdb/surrealdb@sha256:681c6c22c287421b5c7d99e0fde79b6e0d32c36c1ddeaab2762a1661cb04cd20`
- **SDK Version**: `3.0.0`

## Checks

| ID | Check | Blocking | Status | Fallback | Evidence |
|----|-------|----------|--------|----------|----------|
| G1-01 | AsyncSurreal connects, authenticates, and reconnects over WebSocket | Yes | pass |  | RETURN [session::ns(), session::db()]; first=['g1', 'g1_01']; reconnect=['g1', 'g1_01'] |
| G1-02 | Draft KnowledgeStore schema applies | Yes | pass |  | INFO FOR DB; CREATE bundle:test SET repo = 'r', path = 'p', commit = 'c', frontmatter = {extra: true}, updated_at = time::now(); tables=['bundle', 'chunk', 'document', 'entity', 'mentions', 'next_chunk', 'related', 'section', 'synth'] bundle=[{'commit': 'c', 'frontmatter': {'extra': True}, 'id': RecordID(table_name=bundle, record_id='test'), 'path': 'p', 'repo': 'r', 'updated_at': PreciseDatetime(2026, 11, 7, 0, 42, 48, 13461, tzinfo=datetime.timezone.utc)}] |
| G1-03 | BM25 full-text search with a Spanish snowball analyzer | Yes | pass |  | SELECT id, search::score(1) AS score FROM chunk WHERE text @1@ $term ORDER BY score DESC; rows=[{'id': RecordID(table_name=chunk, record_id='legal'), 'score': 0.0}] |
| G1-04 | HNSW 1024-dimensional cosine KNN search | Yes | pass |  | SELECT id, vector::distance::knn() AS distance FROM chunk WHERE embedding <|1, COSINE|> $vector ORDER BY distance; rows=[{'distance': 0.0, 'id': RecordID(table_name=chunk, record_id='legal')}] |
| G1-05 | BM25 and KNN support CONTAINSANY IRI filters | Yes | pass |  | BM25=SELECT id FROM chunk WHERE text @1@ $term AND concept_iris CONTAINSANY $iris; rows=[{'id': RecordID(table_name=chunk, record_id='legal')}]; KNN=SELECT id FROM chunk WHERE embedding <|1, COSINE|> $vector AND concept_iris CONTAINSANY $iris; rows=[{'id': RecordID(table_name=chunk, record_id='legal')}] |
| G1-06 | search::rrf availability and signature | No | pass |  | RETURN search::rrf([[{id: chunk:legal}], [{id: chunk:other}]], 20); rows=[{'id': RecordID(table_name=chunk, record_id='legal'), 'rrf_score': 0.01639344262295082}, {'id': RecordID(table_name=chunk, record_id='other'), 'rrf_score': 0.01639344262295082}] |
| G1-07 | LIVE SELECT delivers changes after reconnect | Yes | pass |  | LIVE SELECT live_event; CREATE first/second; first={'action': 'CREATE', 'id': UUID('d359503b-f2a0-4a3c-97c7-54b8149d1ade'), 'record': RecordID(table_name=live_event, record_id='first'), 'result': {'id': RecordID(table_name=live_event, record_id='first'), 'value': 'first'}, 'session': UUID('3666add0-3f9f-4af9-be58-7aa63cffe180')}; reconnect={'action': 'CREATE', 'id': UUID('9bebbc2c-45e4-47f5-bf5e-2b7246f92a72'), 'record': RecordID(table_name=live_event, record_id='second'), 'result': {'id': RecordID(table_name=live_event, record_id='second'), 'value': 'second'}, 'session': UUID('dce91163-3388-485f-8013-152fa9fee388')} |
| G1-08 | Transaction commits mutation, outbox, and counter atomically | Yes | pass |  | BEGIN/COMMIT mutation+outbox+counter rows=[[{'id': RecordID(table_name=mutation, record_id='atomic'), 'request_id': 'atomic'}], [{'id': RecordID(table_name=outbox, record_id='atomic'), 'request_id': 'atomic'}], [{'id': RecordID(table_name=stream_counter, record_id='main'), 'value': 1}]] |
| G1-09 | Eight writers preserve unique mutation identities | Yes | pass |  | spawn eight writers messages=[{'index': 6, 'ok': True}, {'index': 3, 'ok': True}, {'index': 4, 'ok': True}, {'index': 7, 'ok': True}, {'index': 0, 'ok': True}, {'index': 1, 'ok': True}, {'index': 2, 'ok': True}, {'index': 5, 'ok': True}] rows=[{'db': 'g1_09', 'id': RecordID(table_name=mutation, record_id='writer-0'), 'ns': 'g1', 'origin': 'writer', 'request_id': 'writer-0', 'seq': 0}, {'db': 'g1_09', 'id': RecordID(table_name=mutation, record_id='writer-1'), 'ns': 'g1', 'origin': 'writer', 'request_id': 'writer-1', 'seq': 1}, {'db': 'g1_09', 'id': RecordID(table_name=mutation, record_id='writer-2'), 'ns': 'g1', 'origin': 'writer', 'request_id': 'writer-2', 'seq': 2}, {'db': 'g1_09', 'id': RecordID(table_name=mutation, record_id='writer-3'), 'ns': 'g1', 'origin': 'writer', 'request_id': 'writer-3', 'seq': 3}, {'db': 'g1_09', 'id': RecordID(table_name=mutation, record_id='writer-4'), 'ns': 'g1', 'origin': 'writer', 'request_id': 'writer-4', 'seq': 4}, {'db': 'g1_09', 'id': RecordID(table_name=mutation, record_id='writer-5'), 'ns': 'g1', 'origin': 'writer', 'request_id': 'writer-5', 'seq': 5}, {'db': 'g1_09', 'id': RecordID(table_name=mutation, record_id='writer-6'), 'ns': 'g1', 'origin': 'writer', 'request_id': 'writer-6', 'seq': 6}, {'db': 'g1_09', 'id': RecordID(table_name=mutation, record_id='writer-7'), 'ns': 'g1', 'origin': 'writer', 'request_id': 'writer-7', 'seq': 7}] |
| G1-10 | Injected failure replay converges | Yes | pass |  | replay outcomes={'before_local_commit': [[{'id': RecordID(table_name=mutation, record_id='replay'), 'request_id': 'replay'}], [{'id': RecordID(table_name=outbox, record_id='replay'), 'request_id': 'replay'}]], 'after_local_commit_before_dispatch': [[{'id': RecordID(table_name=mutation, record_id='replay'), 'request_id': 'replay'}], [{'id': RecordID(table_name=outbox, record_id='replay'), 'request_id': 'replay'}]], 'after_central_commit_before_ack': [[{'id': RecordID(table_name=mutation, record_id='replay'), 'request_id': 'replay'}], [{'id': RecordID(table_name=outbox, record_id='replay'), 'request_id': 'replay'}]], 'after_ack_before_local_persistence': [[{'id': RecordID(table_name=mutation, record_id='replay'), 'request_id': 'replay'}], [{'id': RecordID(table_name=outbox, record_id='replay'), 'request_id': 'replay'}]]} |
| G1-11 | Relation traversal, reachability, and safe dynamic reads | Yes | pass |  | SELECT ->linked->node.name AS reachable FROM node:a; rows=[{'reachable': ['b']}]; allow-list permitted SELECT name FROM node WHERE name = $name; rows=[{'name': 'b'}] and rejected DELETE node:a; |
| G1-12 | Runtime documents are isolated by tenant namespace/database | Yes | pass |  | 
DEFINE TABLE runtime_document SCHEMAFULL;
DEFINE FIELD key ON runtime_document TYPE string;
DEFINE FIELD kind ON runtime_document TYPE string;
DEFINE FIELD deleted_at ON runtime_document TYPE option<datetime>;
DEFINE INDEX runtime_document_key ON runtime_document FIELDS key UNIQUE;
UPSERT runtime_document:one SET key = $key, kind = 'note', deleted_at = NONE;
UPDATE runtime_document:one SET deleted_at = time::now();
 SELECT * FROM runtime_document WHERE key = $key AND deleted_at = NONE; soft-delete=[]; tenant-b cross-read='table absent in tenant b (NotFoundError)' |
| G1-13 | SDK licence, image digest, and multi-process server sharing | No | pass |  | sdk=3.0.0; image=surrealdb/surrealdb@sha256:681c6c22c287421b5c7d99e0fde79b6e0d32c36c1ddeaab2762a1661cb04cd20; G1-09 uses eight spawned clients against one server |

## Measurements

### G1-05: BM25 and KNN support CONTAINSANY IRI filters
- **bm25_200_iris_ms**: 1.5355760042439215
- **knn_200_iris_ms**: 1.9599049992393702
### G1-09: Eight writers preserve unique mutation identities
- **writers**: 8.0
- **mutations**: 8.0

**Verdict: GO**