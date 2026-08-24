#!/usr/bin/env bash
# Dismiss verified false-positive CodeQL alerts (2026-08-21 audit).
#
# Usage:  bash scripts/dismiss_codeql_false_positives.sh
#
# Requires: gh CLI authenticated with security-events:write scope.
# This script is idempotent — re-running it on already-dismissed alerts is a no-op.

set -euo pipefail

REPO="phenobarbital/ai-parrot"
COMMENT="Verified false positive: input is sanitized before use (regex allowlist, containment check, or non-sensitive data). See security audit 2026-08-21."

# --- Path injection: all have resolve()+startswith() containment or regex allowlists ---
# abstract.py (L376,393,394), agent_context.py (L64,85,87,129,137),
# data.py (L557,562), pythonrepl.py (L299,304,305)
PATH_INJECTION=(201 202 203 204 205 206 207 208 209 210 5 6 7)

# --- SQL injection: all use validate_identifier() regex sanitizer ---
# formdesigner/storage.py (L428,485,521,524,581,585,728)
SQL_INJECTION=(14 129 130 131 132 136 137)

# --- Clear-text logging: already redacted or non-sensitive ---
# abstract.py (L658), simple_server.py (L51)
CLEARTEXT_LOG=(142 159)

# --- Clear-text storage: intentional or non-sensitive data ---
# generate_keys.py (L133), google/tools.py (L1302), databasequery/tool.py (L831)
CLEARTEXT_STORE=(67 68 138)

# --- URL redirection: redirect_uri checked against client.redirect_uris allowlist ---
# mcp/oauth_server.py (L502, L671) — exact-membership check returns 400 before use
URL_REDIRECTION=(122 123)

# --- Overly-large-range: deliberate Unicode emoji block U+2600-U+27BF ---
# voice/tts/supertonic_inference.py (L132)
LARGE_RANGE=(162 163)

# --- Stack-trace exposure: callers pass controlled message strings, never exceptions ---
# handlers/openai_compat.py (L175)
STACK_TRACE=(107)

ALL_ALERTS=("${PATH_INJECTION[@]}" "${SQL_INJECTION[@]}" "${CLEARTEXT_LOG[@]}" "${CLEARTEXT_STORE[@]}" "${URL_REDIRECTION[@]}" "${LARGE_RANGE[@]}" "${STACK_TRACE[@]}")

SUCCESS=0
FAIL=0
for alert_num in "${ALL_ALERTS[@]}"; do
  if gh api -X PATCH \
    "repos/${REPO}/code-scanning/alerts/${alert_num}" \
    -f state=dismissed \
    -f dismissed_reason="false positive" \
    -f dismissed_comment="${COMMENT}" \
    --silent 2>/dev/null; then
    echo "✅ Dismissed alert #${alert_num}"
    SUCCESS=$((SUCCESS + 1))
  else
    echo "❌ Failed alert #${alert_num}"
    FAIL=$((FAIL + 1))
  fi
done

echo ""
echo "Done: ${SUCCESS} dismissed, ${FAIL} failed (out of ${#ALL_ALERTS[@]} total)"
