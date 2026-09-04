import uuid
import orjson
from typing import TYPE_CHECKING, List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
from abc import ABC, abstractmethod
from datamodel.parsers.json import JSONContent  # pylint: disable=E0611 # noqa
from navconfig.logging import logging
from .compaction.models import (
    CompactionCommit,
    CompactionState,
    ToolInvocation,
    ToolStatus,
    TokenCount,
    TurnState,
)
from .compaction.omission import InMemoryOmissionStore, OmissionStore
from .compaction.budget import apply_commit, apply_usage

if TYPE_CHECKING:  # pragma: no cover - typing only
    # Imported lazily: ``parrot.models`` must not become a runtime dependency
    # of ``parrot.memory`` (FEAT-524 keeps this package import-cycle free).
    from parrot.models import AIMessage
    # ``.compaction.tokens`` and ``.compaction.normalize`` import
    # ``ConversationTurn`` from THIS module, so importing them at module
    # level here would be a circular import. Type-only here; imported
    # lazily inside the methods that need them at runtime.
    from .compaction.tokens import TokenCounter


def _stringify(result: Any) -> Optional[str]:
    """Coerce a tool call's raw ``result`` into text for ``ToolInvocation.output``.

    Args:
        result: The raw value on ``ToolCall.result``.

    Returns:
        ``None`` if ``result`` is ``None``; the string unchanged if it
        already is one; the canonical (key-sorted) JSON text for dict/list
        payloads; ``str(result)`` for anything else.
    """
    if result is None:
        return None
    if isinstance(result, str):
        return result
    if isinstance(result, (dict, list)):
        return orjson.dumps(result, option=orjson.OPT_SORT_KEYS).decode()
    return str(result)


def _tee_key(result: Any) -> Optional[str]:
    """Extract the FEAT-380 working-memory tee key from a tool result, if any."""
    if isinstance(result, dict):
        tee = result.get("_tee")
        if isinstance(tee, dict):
            return tee.get("key")
    return None


def _preview(text: str, max_chars: int = 200) -> str:
    """Truncate ``text`` to a short preview, noting how much was cut.

    Args:
        text: The full text (typically a tool output about to be offloaded
            to the omission store).
        max_chars: Maximum number of characters to keep.

    Returns:
        ``text`` unchanged when it already fits; otherwise the first
        ``max_chars`` characters followed by ``" …(+N chars)"``.
    """
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f" …(+{len(text) - max_chars:,} chars)"


def _provider_prompt_tokens(turn: "ConversationTurn") -> Optional[int]:
    """Read the provider-reported prompt token count from a turn's usage metadata.

    FEAT-524's ``from_ai_message`` stores ``CompletionUsage.model_dump()``
    under ``turn.metadata["usage"]``, which emits both the OpenAI
    (``prompt_tokens``) and OTel-GenAI (``input_tokens``) vocabularies.

    Args:
        turn: The turn to read.

    Returns:
        The provider prompt token count, or ``None`` when the turn carries
        no (or a non-dict) usage metadata.
    """
    usage = turn.metadata.get("usage") if isinstance(turn.metadata, dict) else None
    if not isinstance(usage, dict):
        return None
    value = usage.get("input_tokens")
    if value is None:
        value = usage.get("prompt_tokens")
    return value


@dataclass
class ConversationTurn:
    """Represents a single turn in a conversation."""

    turn_id: str
    user_id: str
    user_message: str
    assistant_response: str
    context_used: Optional[str] = None
    tools_used: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    #: The agent that produced this turn (FEAT-524). Always set by
    #: ``AbstractBot.save_conversation_turn``; ``None`` on records written
    #: before attribution existed.
    chatbot_id: Optional[str] = None
    #: Tool activity captured from ``AIMessage.tool_calls`` (FEAT-525).
    #: Empty for legacy records and for turns with no tool use.
    tool_invocations: List[ToolInvocation] = field(default_factory=list)
    #: Round-level failure text, condensed by Stage 0 rule 5. Never omitted.
    error: Optional[str] = None
    #: Stamped by ``ConversationMemory.add_turn`` (Stage 0.5). ``None`` for
    #: legacy turns until they are counted lazily.
    token_count: Optional[TokenCount] = None
    #: Storage always writes ``RAW`` in v1; ``PRUNED``/``SUMMARIZED`` are
    #: view-only / Stage-2-reserved states.
    state: TurnState = TurnState.RAW
    #: ``1`` for legacy turns; ``2`` once written by ``add_turn``.
    schema_version: int = 1
    #: Stage 0 normalization version stamp (``NORM_VERSION``); ``None`` when
    #: normalization has not run (legacy turns, or ``normalize=False``).
    norm_version: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize turn to dictionary."""
        return {
            "turn_id": self.turn_id,
            "user_id": self.user_id,
            "user_message": self.user_message,
            "assistant_response": self.assistant_response,
            "context_used": self.context_used,
            "tools_used": self.tools_used,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
            "chatbot_id": self.chatbot_id,
            "tool_invocations": [inv.to_dict() for inv in self.tool_invocations],
            "error": self.error,
            "token_count": self.token_count.to_dict() if self.token_count else None,
            "state": self.state.value,
            "schema_version": self.schema_version,
            "norm_version": self.norm_version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConversationTurn":
        """Deserialize turn from dictionary."""
        token_count_data = data.get("token_count")
        return cls(
            turn_id=data["turn_id"],
            user_id=data["user_id"],
            user_message=data["user_message"],
            assistant_response=data["assistant_response"],
            context_used=data.get("context_used"),
            tools_used=data.get("tools_used", []),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            metadata=data.get("metadata", {}),
            # Legacy records predate attribution — absent key means "unknown".
            chatbot_id=data.get("chatbot_id"),
            tool_invocations=[
                ToolInvocation.from_dict(d) for d in data.get("tool_invocations", []) or []
            ],
            error=data.get("error"),
            token_count=TokenCount.from_dict(token_count_data) if token_count_data else None,
            state=TurnState(data.get("state", TurnState.RAW.value)),
            schema_version=data.get("schema_version", 1),
            norm_version=data.get("norm_version"),
        )

    @classmethod
    def from_ai_message(
        cls,
        *,
        user_message: str,
        response: "AIMessage",
        user_id: str,
        chatbot_id: str,
        context_used: Optional[str] = None,
        turn_id: Optional[str] = None,
        assistant_text: Optional[str] = None,
        error: Optional[str] = None,
    ) -> "ConversationTurn":
        """Build a turn from the ``AIMessage`` a bot round produced.

        This is the canonical constructor used by
        ``AbstractBot.save_conversation_turn`` call sites (FEAT-524). Before
        this existed every bot entry point hand-rolled its own turn with
        slightly different metadata keys; routing through here gives every
        persisted turn one shape.

        Args:
            user_message: The user's text for this round.
            response: The final :class:`~parrot.models.responses.AIMessage`
                returned by the bot — i.e. *after* guardrails, redaction and
                formatting, not the raw client output.
            user_id: Owner of the conversation.
            chatbot_id: The agent producing the turn. Must be the bot's
                ``memory_key_id`` — attribution and storage key must agree.
            context_used: Optional retrieval context string used this round.
            turn_id: Explicit turn id. Defaults to ``response.turn_id``, then
                to a fresh uuid4.
            assistant_text: Overrides the assistant text taken from
                ``response``. Used by the streaming partial-save path, where
                the accumulated text is authoritative and the ``AIMessage`` is
                synthesized after the fact.
            error: Round-level failure text (FEAT-525). Condensed by Stage 0
                rule 5 when the turn is normalized; never omitted.

        Returns:
            A fully populated :class:`ConversationTurn`.
        """
        if assistant_text is not None:
            answer = assistant_text
        else:
            answer = getattr(response, "to_text", None)
            if answer is None:
                answer = str(getattr(response, "content", "") or "")

        tool_calls = getattr(response, "tool_calls", None) or []
        usage = getattr(response, "usage", None)

        tool_invocations = [
            ToolInvocation(
                tool_name=tc.name,
                input=tc.arguments,
                output=_stringify(tc.result),
                status=ToolStatus.ERROR if tc.error else ToolStatus.COMPLETED,
                error=tc.error,
                elapsed_ms=(
                    int(tc.execution_time * 1000) if tc.execution_time is not None else None
                ),
                wm_key=_tee_key(tc.result),
            )
            for tc in tool_calls
        ]

        return cls(
            turn_id=turn_id or getattr(response, "turn_id", None) or str(uuid.uuid4()),
            user_id=user_id,
            user_message=user_message,
            assistant_response=answer,
            context_used=context_used,
            tools_used=[tc.name for tc in tool_calls],
            metadata={
                "model": getattr(response, "model", None),
                "provider": getattr(response, "provider", None),
                "usage": usage.model_dump() if hasattr(usage, "model_dump") else usage,
                "finish_reason": getattr(response, "finish_reason", None),
                "response_time": getattr(response, "response_time", None),
            },
            chatbot_id=chatbot_id,
            tool_invocations=tool_invocations,
            error=error,
        )


@dataclass
class ConversationHistory:
    """Manages conversation history for a session - replaces ConversationSession."""

    session_id: str
    user_id: str
    chatbot_id: Optional[str] = None
    turns: List[ConversationTurn] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_turn(self, turn: ConversationTurn) -> None:
        """Add a new turn to the conversation history."""
        self.turns.append(turn)
        self.updated_at = datetime.now()

    def get_recent_turns(self, count: int = 5) -> List[ConversationTurn]:
        """Get the most recent turns for context."""
        return self.turns[-count:] if count > 0 else self.turns

    # NOTE (FEAT-524): ``get_messages_for_api()`` was removed here. Rendering a
    # history into messages is provider-agnostic work that belongs in
    # ``parrot.memory.render.render_history()``, and mapping the result onto a
    # provider's shape belongs in ``AbstractClient._format_history()``.

    def clear_turns(self) -> None:
        """Clear all turns from the conversation history."""
        self.turns.clear()
        self.updated_at = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize conversation history to dictionary."""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "chatbot_id": self.chatbot_id,
            "turns": [turn.to_dict() for turn in self.turns],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConversationHistory":
        """Deserialize conversation history from dictionary."""
        history = cls(
            session_id=data["session_id"],
            user_id=data["user_id"],
            chatbot_id=data.get("chatbot_id"),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            metadata=data.get("metadata", {}),
        )

        for turn_data in data.get("turns", []):
            turn = ConversationTurn.from_dict(turn_data)
            history.turns.append(turn)

        return history


class ConversationMemory(ABC):
    """Abstract base class for conversation memory storage.

    FEAT-525 turns ``add_turn`` into a concrete template method (the
    FEAT-391 "concrete public, abstract private" pattern): every writer —
    bot, ``ChatStorage`` cold tier, voice transcripts — gets Stage 0
    (normalization), Stage 0.5 (token counting) and write-time oversize
    offload for free. Backends implement the abstract :meth:`_store_turn`
    only, persisting the turn **and** (when given) the updated
    ``metadata["compaction"]`` in one write.
    """

    def __init__(
        self,
        debug: bool = False,
        *,
        token_counter: Optional["TokenCounter"] = None,
        omission_store: Optional[OmissionStore] = None,
        normalize: bool = True,
        oversize_tool_tokens: int = 2_000,
    ) -> None:
        """Initialize the memory.

        Args:
            debug: Enables verbose per-history debug logging.
            token_counter: The counter used for Stage 0.5. Defaults to
                :func:`parrot.memory.compaction.tokens.get_default_counter`
                on first use (lazy — never resolved unless needed).
            omission_store: The store oversized tool outputs are offloaded
                to. Backends normally pass their own default; falling back
                to an :class:`InMemoryOmissionStore` here is a safety net,
                not the intended configuration.
            normalize: When ``False``, disables Stage 0 for this instance
                only; Stage 0.5 (token counting) stays always-on.
            oversize_tool_tokens: Write-time offload threshold, in tokens
                (same default as :class:`~parrot.memory.compaction.models.ContextBudget`).
        """
        self.logger = logging.getLogger(f"parrot.Memory.{self.__class__.__name__}")
        self._json = JSONContent()
        self.debug = debug
        self._token_counter = token_counter
        self._omission_store = omission_store
        self._normalize = normalize
        self._oversize_tool_tokens = oversize_tool_tokens

    @property
    def token_counter(self) -> "TokenCounter":
        """The Stage 0.5 token counter, resolved lazily on first use."""
        if self._token_counter is None:
            from .compaction.tokens import get_default_counter

            self._token_counter = get_default_counter()
        return self._token_counter

    @property
    def omission_store(self) -> OmissionStore:
        """The store oversized tool outputs are offloaded to.

        Backends should set ``self._omission_store`` in their own
        ``__init__`` to a store sharing their connection/root. This
        fallback exists so the property never raises, but an
        :class:`InMemoryOmissionStore` built here is unset-and-forget: it
        is process-local and lost on restart.
        """
        if self._omission_store is None:
            self.logger.warning(
                "%s has no OmissionStore configured; falling back to an "
                "in-memory store (not persisted across restarts).",
                self.__class__.__name__,
            )
            self._omission_store = InMemoryOmissionStore()
        return self._omission_store

    def omission_key(self, user_id: str, session_id: str, chatbot_id: Optional[str]) -> str:
        """Compose the omission-store scoping key for one session.

        Args:
            user_id: Owner of the conversation.
            session_id: Conversation session.
            chatbot_id: Agent attribution; ``None`` becomes ``"_default"``.

        Returns:
            ``"{chatbot_id}:{user_id}:{session_id}"``.
        """
        return f"{chatbot_id or '_default'}:{user_id}:{session_id}"

    @abstractmethod
    async def create_history(
        self, user_id: str, session_id: str, metadata: Optional[Dict[str, Any]] = None, chatbot_id: Optional[str] = None
    ) -> ConversationHistory:
        """Create a new conversation history."""
        pass

    @abstractmethod
    async def get_history(
        self, user_id: str, session_id: str, chatbot_id: Optional[str] = None
    ) -> Optional[ConversationHistory]:
        """Get a conversation history."""
        pass

    @abstractmethod
    async def update_history(self, history: ConversationHistory) -> None:
        """Update a conversation history."""
        pass

    async def add_turn(
        self,
        user_id: str,
        session_id: str,
        turn: ConversationTurn,
        chatbot_id: Optional[str] = None,
        *,
        compaction: Optional[CompactionCommit] = None,
    ) -> None:
        """Persist one turn: normalize, count, offload oversized outputs, write once.

        Concrete template method (FEAT-525): normalizes (Stage 0, unless
        ``normalize=False``), counts tokens (Stage 0.5, always-on),
        offloads any tool output above ``oversize_tool_tokens`` to the
        omission store with a short preview left in the turn, then
        delegates the single backend write to :meth:`_store_turn`. When
        ``compaction`` is given, folds it into the persisted
        ``metadata["compaction"]`` state (calibration EWMA, boundary,
        ``stage2_needed``) in the same write.

        Args:
            user_id: Owner of the conversation.
            session_id: Conversation session.
            turn: The turn to persist. Not mutated — Stage 0 (when
                enabled) rebinds it to a new, normalized turn first; the
                offload step mutates that new turn's invocations, which
                belong to the copy being stored, not the caller's object.
            chatbot_id: Agent attribution.
            compaction: The bot's commit for this round, or ``None`` for
                writers that do not participate in the budget round-trip
                (e.g. a partial-save on error, or the ``ChatStorage`` tier).
        """
        from .compaction.tokens import count_turn, needs_recount

        counter = self.token_counter
        if self._normalize:
            from .compaction.normalize import normalize_turn

            turn = normalize_turn(turn)
        if needs_recount(turn, counter):
            turn.token_count = count_turn(turn, counter)

        key = self.omission_key(user_id, session_id, chatbot_id)
        offloaded = False
        for inv in turn.tool_invocations:
            if (
                inv.output
                and "output" not in inv.omitted
                and counter.count(inv.output) > self._oversize_tool_tokens
            ):
                cid = await self.omission_store.put(key, inv.output, turn_id=turn.turn_id)
                inv.output_chars = len(inv.output)
                inv.output = _preview(inv.output)
                inv.omitted["output"] = cid
                offloaded = True
        if offloaded:
            turn.token_count = count_turn(turn, counter)

        turn.schema_version = 2

        state: Optional[Dict[str, Any]] = None
        if compaction is not None:
            prev = await self._get_compaction_state(user_id, session_id, chatbot_id)
            state = apply_commit(
                CompactionState.from_dict(prev) if prev else None,
                compaction,
                counter.name,
                _provider_prompt_tokens(turn),
            ).to_dict()

        await self._store_turn(user_id, session_id, turn, chatbot_id, compaction_state=state)

    @abstractmethod
    async def _store_turn(
        self,
        user_id: str,
        session_id: str,
        turn: ConversationTurn,
        chatbot_id: Optional[str] = None,
        *,
        compaction_state: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Persist ``turn`` and, when given, ``metadata["compaction"]`` in ONE write.

        Args:
            user_id: Owner of the conversation.
            session_id: Conversation session.
            turn: The already normalized/counted/offloaded turn to store.
            chatbot_id: Agent attribution.
            compaction_state: The new ``history.metadata["compaction"]``
                dict to persist alongside the turn, or ``None`` to leave
                the history's compaction state untouched.
        """

    async def _get_compaction_state(
        self, user_id: str, session_id: str, chatbot_id: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """Read the persisted ``metadata["compaction"]`` dict for one session.

        Concrete, overridable default that goes through :meth:`get_history`.
        Backends may override with a cheaper targeted read (e.g. Redis
        ``hget(key, "metadata")``) to avoid the FEAT-524 lazy legacy re-key
        that a full :meth:`get_history` call may perform.

        Args:
            user_id: Owner of the conversation.
            session_id: Conversation session.
            chatbot_id: Agent attribution.

        Returns:
            The persisted compaction-state dict, or ``None`` when the
            history does not exist yet or has none.
        """
        history = await self.get_history(user_id, session_id, chatbot_id)
        if history is None:
            return None
        return history.metadata.get("compaction")

    async def report_usage(
        self,
        user_id: str,
        session_id: str,
        *,
        estimated_prompt_tokens: int,
        provider_prompt_tokens: Optional[int],
        chatbot_id: Optional[str] = None,
    ) -> None:
        """Fold one (estimate, provider) observation into the calibration state, without writing a turn.

        Standalone counterpart to the calibration folded into
        :meth:`add_turn` via ``compaction=`` — used by partial-save paths
        (e.g. ``ask_stream`` on error) and tests that need to update
        calibration independently of a turn write.

        Args:
            user_id: Owner of the conversation.
            session_id: Conversation session.
            estimated_prompt_tokens: The bot's own token estimate for the
                round.
            provider_prompt_tokens: The provider-reported prompt token
                count for the same round, when available.
            chatbot_id: Agent attribution.
        """
        history = await self.get_history(user_id, session_id, chatbot_id)
        if history is None:
            return
        prev = history.metadata.get("compaction")
        state = (
            CompactionState.from_dict(prev)
            if prev
            else CompactionState(tokenizer=self.token_counter.name)
        )
        state = apply_usage(state, estimated_prompt_tokens, provider_prompt_tokens)
        history.metadata["compaction"] = state.to_dict()
        await self.update_history(history)

    @abstractmethod
    async def clear_history(self, user_id: str, session_id: str, chatbot_id: Optional[str] = None) -> None:
        """Clear a conversation history."""
        pass

    @abstractmethod
    async def list_sessions(self, user_id: str, chatbot_id: Optional[str] = None) -> List[str]:
        """List all session IDs for a user."""
        pass

    @abstractmethod
    async def delete_history(self, user_id: str, session_id: str, chatbot_id: Optional[str] = None) -> bool:
        """Delete a conversation history entirely."""
        pass
