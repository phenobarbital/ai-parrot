/**
 * navigator-auth PasskeyAuth client (FEAT-772, spec §3 Module 2).
 *
 * Public ceremony calls use bare axios to avoid the authenticated client's
 * 401 interceptor. Authenticated calls use apiClient so they receive Bearer
 * token injection.
 */
import axios from "axios";

import apiClient, { ApiError, extractServerMessage } from "$lib/api/http";
import { config } from "$lib/config";
import type { PublicKeyCredentialJSON } from "$lib/webauthn";

export interface PasskeyLoginOptions {
  challenge_id: string;
  publicKey: PublicKeyCredentialRequestOptionsJSON;
}

export interface PasskeyCredentialSummary {
  id: string;
  label: string | null;
  created_at: string | null;
  last_used_at: string | null;
  device_type: string | null;
  backed_up: boolean;
  rp_id: string;
}

type ErrorResponse = { status?: unknown; data?: unknown };
type ErrorWithResponse = { response?: ErrorResponse };

const prefix = (): string => `${config.apiBaseUrl}${config.passkeyApiPrefix}`;

function isLoginOptions(data: unknown): data is PasskeyLoginOptions {
  if (!data || typeof data !== "object") return false;
  const options = data as Record<string, unknown>;
  return (
    typeof options.challenge_id === "string" &&
    !!options.publicKey &&
    typeof options.publicKey === "object" &&
    !Array.isArray(options.publicKey)
  );
}

function trimmedOptionalLabel(label: string | undefined): string | undefined {
  const trimmed = label?.trim();
  return trimmed ? trimmed : undefined;
}

function responseOf(err: unknown): ErrorResponse | undefined {
  if (err instanceof ApiError) {
    return (err.raw as ErrorWithResponse | undefined)?.response;
  }
  return (err as ErrorWithResponse | undefined)?.response;
}

/** POST login/options via bare axios. Returns null on any failure or malformed response. */
export async function fetchLoginOptions(username?: string): Promise<PasskeyLoginOptions | null> {
  try {
    const { data } = await axios.post(`${prefix()}/login/options`, username ? { username } : {}, {
      withCredentials: config.apiWithCredentials,
    });
    return isLoginOptions(data) ? data : null;
  } catch {
    return null;
  }
}

/** POST config.loginUrl via bare axios with the navigator-auth PasskeyAuth header. */
export async function postPasskeyLogin(body: {
  challenge_id: string;
  credential: PublicKeyCredentialJSON;
}): Promise<Record<string, unknown>> {
  const { data } = await axios.post(`${config.apiBaseUrl}${config.loginUrl}`, body, {
    headers: { "X-Auth-Method": "PasskeyAuth" },
    withCredentials: config.apiWithCredentials,
  });
  return data as Record<string, unknown>;
}

/** POST register/options through the authenticated client. */
export async function fetchRegisterOptions(): Promise<PublicKeyCredentialCreationOptionsJSON> {
  const { data } = await apiClient.post(`${config.passkeyApiPrefix}/register/options`, {});
  return data as PublicKeyCredentialCreationOptionsJSON;
}

/** POST register/verify with an optional, normalized credential label. */
export async function verifyRegistration(
  credential: PublicKeyCredentialJSON,
  label?: string,
): Promise<{ status: "registered"; id: string }> {
  const normalizedLabel = trimmedOptionalLabel(label);
  const body = normalizedLabel ? { credential, label: normalizedLabel } : { credential };
  const { data } = await apiClient.post(`${config.passkeyApiPrefix}/register/verify`, body);
  return data as { status: "registered"; id: string };
}

/** GET the passkeys associated with the authenticated account. */
export async function listPasskeys(): Promise<PasskeyCredentialSummary[]> {
  const { data } = await apiClient.get(`${config.passkeyApiPrefix}/credentials`);
  return Array.isArray(data) ? (data as PasskeyCredentialSummary[]) : [];
}

/** PATCH a credential's label after enforcing the backend's 1–128 character limit. */
export async function renamePasskey(id: string, label: string): Promise<void> {
  const normalizedLabel = label.trim();
  if (!normalizedLabel || normalizedLabel.length > 128) {
    throw new Error("Passkey label must be between 1 and 128 characters");
  }
  await apiClient.patch(`${config.passkeyApiPrefix}/credentials/${encodeURIComponent(id)}`, {
    label: normalizedLabel,
  });
}

/** DELETE a credential. The successful 204 response deliberately has no body to parse. */
export async function deletePasskey(id: string): Promise<void> {
  await apiClient.delete(`${config.passkeyApiPrefix}/credentials/${encodeURIComponent(id)}`);
}

/** Human message for a passkey error, preferring navigator-auth's `{reason}` response field. */
export function passkeyErrorMessage(err: unknown): string {
  const response = responseOf(err);
  const reason =
    response?.data && typeof response.data === "object"
      ? (response.data as Record<string, unknown>).reason
      : undefined;
  if (typeof reason === "string" && reason) return reason;

  const status = typeof response?.status === "number" ? response.status : undefined;
  if (response?.data !== undefined && status !== undefined) {
    const message = extractServerMessage(response.data, status);
    if (message !== `HTTP ${status}`) return message;
  }

  const message = err instanceof Error ? err.message : undefined;
  return message || "Passkey request failed";
}
