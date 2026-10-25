/**
 * Turn an agent upload report into the status line the data-management modal
 * shows.
 *
 * Pure and total: every exported function here is safe to call from a catch
 * block, so neither may throw for any input (FEAT-739 AC5). The same payload
 * shape arrives on a 200 and, via `ApiError.raw.response.data`, on the 400 the
 * handler returns when nothing was stored — which is why the entry points take
 * `unknown` and narrow it themselves.
 */
import type {
  AgentUploadFileError,
  AgentUploadFileRecord,
} from "$lib/api/agent";

export type UploadStatusType = "success" | "warning" | "error";

export interface UploadStatus {
  type: UploadStatusType;
  message: string;
}

/** The status shown when the payload tells us nothing usable. */
const UNKNOWN_FAILURE: UploadStatus = { type: "error", message: "Upload failed." };

function asArray(value: unknown): unknown[] | null {
  return Array.isArray(value) ? value : null;
}

/** Render one rejected file as `<filename>: <reason>`, tolerating a partial entry. */
function describeError(entry: unknown): string {
  if (entry === null || typeof entry !== "object") return "file: rejected";
  const e = entry as Record<string, unknown>;
  const filename =
    typeof e.filename === "string" && e.filename.length > 0 ? e.filename : "file";
  const reason =
    typeof e.error === "string" && e.error.length > 0 ? e.error : "rejected";
  return `${filename}: ${reason}`;
}

/**
 * Derive the status line from an upload payload.
 *
 * success  — at least one file stored and nothing rejected
 * warning  — files stored AND some rejected
 * error    — nothing stored
 *
 * A payload that is not an object, or whose `files` / `dataframes` / `errors`
 * are missing or not arrays, yields `UNKNOWN_FAILURE` rather than a throw.
 */
export function formatUploadStatus(payload: unknown): UploadStatus {
  if (payload === null || typeof payload !== "object") return UNKNOWN_FAILURE;
  const p = payload as Record<string, unknown>;
  const files = asArray(p.files) as AgentUploadFileRecord[] | null;
  const dataframes = asArray(p.dataframes);
  const errors = asArray(p.errors) as AgentUploadFileError[] | null;
  if (files === null || dataframes === null || errors === null) return UNKNOWN_FAILURE;

  const parts: string[] = [];
  if (files.length > 0) {
    parts.push(`Stored ${files.length} ${files.length === 1 ? "file" : "files"}`);
  }
  if (dataframes.length > 0) {
    const names = dataframes.map((name) => String(name)).join(", ");
    parts.push(
      `registered as ${dataframes.length === 1 ? "dataset" : "datasets"}: ${names}`,
    );
  }
  if (errors.length > 0) {
    parts.push(errors.map(describeError).join("; "));
  }
  if (parts.length === 0) return UNKNOWN_FAILURE;

  const type: UploadStatusType =
    files.length === 0 ? "error" : errors.length > 0 ? "warning" : "success";
  return { type, message: parts.join(" · ") };
}

/**
 * Return the response body an `ApiError` preserved, or `undefined`.
 *
 * `safeRaw` (http.ts) keeps the body at `raw.response.data` and nowhere else,
 * so that is the only path read here. Never throws.
 */
export function uploadPayloadFromError(error: unknown): unknown {
  if (error === null || typeof error !== "object") return undefined;
  const raw = (error as Record<string, unknown>).raw;
  if (raw === null || typeof raw !== "object") return undefined;
  const response = (raw as Record<string, unknown>).response;
  if (response === null || typeof response !== "object") return undefined;
  return (response as Record<string, unknown>).data;
}
