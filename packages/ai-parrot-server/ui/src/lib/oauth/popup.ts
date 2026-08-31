/**
 * OAuth2 popup helper for the web AgentChat integration flow.
 *
 * Opens a popup window, registers a `message` listener, and resolves when:
 *   - the popup sends an `"ai-parrot-oauth-callback"` postMessage, OR
 *   - the popup is closed by the user (cancelled), OR
 *   - the timeout expires.
 *
 * All resources (listener, polling interval) are cleaned up on every exit path.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface OAuthCallbackPayload {
  provider: string;
  account_id?: string;
  display_name?: string;
}

export interface OAuthCallbackResult {
  success: true;
  payload: OAuthCallbackPayload;
}

export interface OAuthCallbackFailure {
  success: false;
  reason: "popup-blocked" | "cancelled" | "timeout" | "error";
  error?: string;
}

export type OAuthCallbackOutcome = OAuthCallbackResult | OAuthCallbackFailure;

export interface AwaitOAuthCallbackOptions {
  /** The full authorization URL to open in the popup. */
  authUrl: string;
  /**
   * The origin that the popup will postMessage back to.
   * Typically `window.location.origin`.
   */
  allowedOrigin: string;
  /** Timeout in milliseconds. Defaults to 60 000 (60 seconds). */
  timeoutMs?: number;
}

// ---------------------------------------------------------------------------
// Implementation
// ---------------------------------------------------------------------------

const POPUP_MESSAGE_TYPE = "ai-parrot-oauth-callback";
const DEFAULT_TIMEOUT_MS = 60_000;
const POLL_INTERVAL_MS = 500;

/**
 * Open an OAuth popup and await its callback via postMessage.
 *
 * The popup window must post a message of the form:
 * ```json
 * { "type": "ai-parrot-oauth-callback", "provider": "jira", "success": true, ... }
 * ```
 * to the opener using `window.opener.postMessage(payload, allowedOrigin)`.
 *
 * @returns A resolved `OAuthCallbackOutcome` describing the outcome.
 */
export function awaitOAuthCallback(
  options: AwaitOAuthCallbackOptions,
): Promise<OAuthCallbackOutcome> {
  const { authUrl, allowedOrigin, timeoutMs = DEFAULT_TIMEOUT_MS } = options;

  return new Promise<OAuthCallbackOutcome>((resolve) => {
    // Open the popup.
    const popup = window.open(
      authUrl,
      "oauth-popup",
      `width=500,height=700,scrollbars=yes,resizable=yes,left=${Math.round(
        (window.screen.width - 500) / 2,
      )},top=${Math.round((window.screen.height - 700) / 2)}`,
    );

    // Popup blocked by browser.
    if (popup === null) {
      resolve({ success: false, reason: "popup-blocked" });
      return;
    }

    let settled = false;

    function cleanup(): void {
      window.removeEventListener("message", onMessage);
      clearInterval(pollInterval);
      clearTimeout(timeoutHandle);
    }

    function settle(outcome: OAuthCallbackOutcome): void {
      if (settled) return;
      settled = true;
      cleanup();
      resolve(outcome);
    }

    // Listen for postMessage from the popup.
    function onMessage(event: MessageEvent): void {
      // Drop messages from unexpected origins or wrong type.
      if (event.origin !== allowedOrigin) return;
      if (!event.data || event.data.type !== POPUP_MESSAGE_TYPE) return;

      const data = event.data as {
        type: string;
        provider: string;
        success: boolean;
        account_id?: string;
        display_name?: string;
        error?: string;
      };

      if (data.success) {
        settle({
          success: true,
          payload: {
            provider: data.provider,
            account_id: data.account_id,
            display_name: data.display_name,
          },
        });
      } else {
        settle({
          success: false,
          reason: "error",
          error: data.error ?? "unknown_error",
        });
      }
    }

    // Poll for popup closure (user closed popup without completing OAuth).
    const pollInterval = setInterval(() => {
      if (popup.closed) {
        settle({ success: false, reason: "cancelled" });
      }
    }, POLL_INTERVAL_MS);

    // Timeout guard.
    const timeoutHandle = setTimeout(() => {
      settle({ success: false, reason: "timeout" });
    }, timeoutMs);

    window.addEventListener("message", onMessage);
  });
}
