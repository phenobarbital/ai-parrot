/**
 * Represents a dataset registered with an agent's DatasetManager.
 * Matches the DatasetManagerHandler API response schema.
 */
export interface DatasetEntry {
  name: string;
  description: string;
  /** [rows, cols] — absent for datasource-backed entries (table, smartsheet, etc.) */
  shape?: [number, number];
  is_active: boolean;
  loaded: boolean;
  /** Source type, e.g. "table", "smartsheet", "query_slug", "dataframe" */
  source_type?: string;
}

/**
 * Response from GET /api/v1/agents/datasets/{agent_id}
 */
export interface DatasetListResponse {
  datasets: DatasetEntry[];
  total: number;
  active_count: number;
}

// ---------------------------------------------------------------------------
// Datasource configuration types for POST /api/v1/agents/datasets/{agent_id}
// ---------------------------------------------------------------------------

export type DatasourceType =
  | "query_slug"
  | "sql"
  | "table"
  | "smartsheet"
  | "airtable"
  | "dataframe";

interface DatasetDatasourceBase {
  type: DatasourceType;
  cache_ttl?: number;
}

export interface TableDatasource extends DatasetDatasourceBase {
  type: "table";
  table: string;
  driver: string;
  dsn?: string;
  credentials?: Record<string, unknown>;
  strict_schema?: boolean;
}

export interface SmartsheetDatasource extends DatasetDatasourceBase {
  type: "smartsheet";
  sheet_id: string;
  access_token?: string;
}

export type DatasetDatasource = TableDatasource | SmartsheetDatasource;

/**
 * Body for POST /api/v1/agents/datasets/{agent_id}
 * Supports legacy query/query_slug fields and the new datasource object.
 */
export interface DatasetAddRequest {
  name?: string;
  description?: string;
  query?: string;
  query_slug?: string;
  /** Database driver for SQL query mode (pg, bigquery, mysql, sqlite) */
  driver?: string;
  datasource?: DatasetDatasource;
}

/**
 * Backward-compatible alias for DatasetAddRequest.
 * @deprecated Use DatasetAddRequest instead.
 */
export type DatasetQueryPayload = DatasetAddRequest;

/**
 * Response from POST /api/v1/agents/datasets/{agent_id}
 *
 * For legacy query/slug modes the backend returns a DatasetEntry-like object.
 * For datasource types (table, smartsheet) it returns { name, type, message }.
 * Use the presence of `shape` to distinguish between the two.
 */
export interface DatasetAddResponse {
  name: string;
  type?: string;
  message?: string;
  // DatasetEntry fields — present only for legacy query/slug/file responses
  description?: string;
  shape?: [number, number];
  is_active?: boolean;
  loaded?: boolean;
}
