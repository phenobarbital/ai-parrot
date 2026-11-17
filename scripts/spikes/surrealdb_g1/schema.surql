DEFINE TABLE bundle SCHEMAFULL;
DEFINE FIELD repo ON bundle TYPE string;
DEFINE FIELD path ON bundle TYPE string;
DEFINE FIELD commit ON bundle TYPE string;
DEFINE FIELD frontmatter ON bundle TYPE object FLEXIBLE;
DEFINE FIELD updated_at ON bundle TYPE datetime;
DEFINE INDEX bundle_key ON bundle FIELDS repo, path UNIQUE;

DEFINE TABLE document SCHEMAFULL;
DEFINE FIELD bundle ON document TYPE record<bundle>;
DEFINE FIELD path ON document TYPE string;
DEFINE FIELD title ON document TYPE string;
DEFINE FIELD content_hash ON document TYPE string;
DEFINE FIELD frontmatter ON document TYPE object FLEXIBLE;
DEFINE INDEX document_key ON document FIELDS bundle, path UNIQUE;

DEFINE TABLE section SCHEMAFULL;
DEFINE FIELD document ON section TYPE record<document>;
DEFINE FIELD heading ON section TYPE string;
DEFINE FIELD level ON section TYPE int;
DEFINE FIELD ordinal ON section TYPE int;

DEFINE TABLE chunk SCHEMAFULL;
DEFINE FIELD section ON chunk TYPE record<section>;
DEFINE FIELD document ON chunk TYPE record<document>;
DEFINE FIELD ordinal ON chunk TYPE int;
DEFINE FIELD text ON chunk TYPE string;
DEFINE FIELD tokens ON chunk TYPE int;
DEFINE FIELD span ON chunk TYPE object;
DEFINE FIELD span.start ON chunk TYPE int;
DEFINE FIELD span.end ON chunk TYPE int;
DEFINE FIELD embedding ON chunk TYPE array<float>;
DEFINE FIELD concept_iris ON chunk TYPE array<string>;

DEFINE ANALYZER es_text TOKENIZERS class FILTERS lowercase, snowball(spanish);
DEFINE INDEX chunk_fts ON chunk FIELDS text FULLTEXT ANALYZER es_text BM25;
DEFINE INDEX chunk_vec ON chunk FIELDS embedding HNSW DIMENSION 1024 DIST COSINE;
DEFINE INDEX chunk_iris ON chunk FIELDS concept_iris;

DEFINE TABLE entity SCHEMAFULL;
DEFINE FIELD name ON entity TYPE string;
DEFINE FIELD kind ON entity TYPE string;
DEFINE FIELD concept_iri ON entity TYPE option<string>;
DEFINE FIELD ontology_version ON entity TYPE option<int>;
DEFINE FIELD embedding ON entity TYPE array<float>;
DEFINE FIELD aliases ON entity TYPE array<string>;
DEFINE INDEX entity_name_fts ON entity FIELDS name FULLTEXT ANALYZER es_text BM25;
DEFINE INDEX entity_aliases_fts ON entity FIELDS aliases FULLTEXT ANALYZER es_text BM25;
DEFINE INDEX entity_vec ON entity FIELDS embedding HNSW DIMENSION 1024 DIST COSINE;
DEFINE INDEX entity_iri ON entity FIELDS concept_iri;

DEFINE TABLE next_chunk TYPE RELATION FROM chunk TO chunk;
DEFINE TABLE mentions TYPE RELATION FROM chunk TO entity;
DEFINE FIELD spans ON mentions TYPE array<object>;
DEFINE FIELD confidence ON mentions TYPE float;
DEFINE FIELD source ON mentions TYPE string;
DEFINE TABLE related TYPE RELATION FROM entity TO entity;
DEFINE FIELD predicate ON related TYPE string;
DEFINE FIELD evidence ON related TYPE array<record<chunk>>;

DEFINE TABLE synth SCHEMAFULL;
DEFINE FIELD repo ON synth TYPE string;
DEFINE FIELD qualified_name ON synth TYPE string;
DEFINE FIELD content_hash ON synth TYPE string;
DEFINE FIELD summary ON synth TYPE string;
DEFINE FIELD model ON synth TYPE string;
DEFINE FIELD embedding ON synth TYPE array<float>;
DEFINE FIELD created_at ON synth TYPE datetime;
DEFINE INDEX synth_key ON synth FIELDS repo, qualified_name, content_hash UNIQUE;
DEFINE INDEX synth_fts ON synth FIELDS summary FULLTEXT ANALYZER es_text BM25;
DEFINE INDEX synth_vec ON synth FIELDS embedding HNSW DIMENSION 1024 DIST COSINE;
