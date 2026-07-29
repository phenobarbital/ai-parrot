# F001 — AHP protocol model (overview + common types)

**Queries**: Q001, Q002 (web_fetch, curl fallback)
**Sources**:
- https://microsoft.github.io/agent-host-protocol/specification/overview.html
- https://microsoft.github.io/agent-host-protocol/reference/common.html
**Fetched**: 2026-07-21

## Status
- Spec is **DRAFT**: "Breaking changes to wire types, actions, and state
  shapes are expected. Do not rely on backward compatibility."
- JSON-RPC 2.0 framing, transport-agnostic; SemVer protocol version
  negotiated at `initialize` (client offers `protocolVersions[]`, server picks).
- JSON Schema 2020-12 published for state/actions/commands/notifications/errors
  (generated from TypeScript types) — usable for codegen/drift gates.

## Channel model (the routing invariant)
- Every push interaction is scoped to a **channel** — URI-identified
  subscribable resource. Channels: `ahp-root://` (agents/terminals catalogue,
  host config, session catalogue events), `ahp-session:/<uuid>` (per-session
  state: chats catalog, active clients, changesets, aggregated status),
  `ahp-chat:/<cid>` (turns, streaming, tool calls, input requests),
  terminal channel (pty state, claims), changeset channel, `ahp-otlp:`
  telemetry.
- **Every command's params extends `BaseParams { channel: URI }`**;
  connection-level commands narrow channel to literal `'ahp-root://'`.
  Every notification's params also carries `channel`. Implementations route
  any message by `(method, params.channel)` without per-method deserialization.

## Commands / notifications
- Client→server requests: `initialize`, `reconnect`, `subscribe`,
  `createSession`, `disposeSession`, `listSessions`, `fetchTurns`,
  `resource*` (symmetrical — may be sent by either peer), `createResourceWatch`.
- Client→server notifications (fire-and-forget): `dispatchAction`
  (**write-ahead**: client applies optimistically; server echoes the accepted
  action back as an `ActionEnvelope` on the `action` notification), `unsubscribe`.
- Server→client notifications: `action` (params = ActionEnvelope),
  `root/sessionAdded|Removed|SummaryChanged`, `auth/required`.

## Common wire types (reference/common)
- `Snapshot { resource: URI, state: RootState|SessionState|ChatState|TerminalState|ChangesetState|..., fromSeq: number }`
  — returned by `initialize`, `reconnect`, `subscribe`. "Subsequent actions
  will have serverSeq > fromSeq."
- `ActionEnvelope { channel: URI, action: StateAction, serverSeq: number, origin?: ActionOrigin, rejectionReason?: string }`
- `ActionOrigin { clientId: string, clientSeq: number }` — identifies the
  dispatching client (multi-client write attribution).
- `StateAction` — one closed discriminated union across ALL channels
  (~77 variants), discriminant is a `'<channel>/<event>'` string
  (e.g. `session/ready`, `chat/toolCallConfirmed`, `terminal/exited`).
- Reconnect: client sends `lastSeenServerSeq`; result is
  `Replay { actions: ActionEnvelope[] }` **or** `Snapshot` (host's choice).
- `initialize` result carries `serverSeq` + `snapshots[]` for
  `initialSubscriptions`.

## HITL-relevant AHP shapes (direct analogues for gates)
- `SessionInputNeededSet` / `SessionInputNeededRemoved` — session-level
  "blocked on human input" flag ≅ our `awaiting_gate` phase.
- `ChatToolCallReady` → `ChatToolCallConfirmed` — the tool-call confirmation
  flow: host proposes, a client confirms, confirmation is sequenced as a
  state action ≅ our `GateOpened` → `GateResolved` arbitration.
- `ChatInputRequested` / `ChatInputAnswerChanged` / `ChatInputCompleted` —
  structured input-request lifecycle ≅ gate with typed payload.
- `ErrorInfo { errorType, message, stack?, _meta? }`, `UsageInfo`
  (token usage per turn — worth projecting from dispatchers later).

## Implications for the parrot simil
- AHP's **host = process that owns many sessions** ⇒ `DevLoopRunner` is the
  host; a dev-loop run ≅ an AHP *session*; a dispatch pty ≅ *terminal*;
  the PR diff ≅ *changeset*; the root catalogue ≅ run registry
  (`root/sessionAdded` ≅ run created/registered).
- AHP has **no notion of reducers on the wire** — reducers are an
  implementation idiom (Redux-style) implied by snapshot+actions; the
  brainstorm's pure-reducer core is compatible and stricter.
- `origin`/`rejectionReason` on the envelope are worth adopting in
  `ActionEnvelope` (parrot sketch lacks them): they carry exactly the
  multi-client audit data constraint 2 asks for.
