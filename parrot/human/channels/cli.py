"""
CLI Human Channel for AI-Parrot HITL.

Interactive terminal channel that renders questions using Rich
and captures responses via stdin. Supports two modes:

1. INTERACTIVE (default): Prompt appears directly in the terminal
   where the agent runs. Ideal for development and active monitoring.

2. DAEMON: Questions are published to a Redis queue. A separate
   CLI companion process (cli_companion.py) reads and responds.
   Used when the agent runs as a background service.

The CLI channel is "local" by definition — the human who responds
is whoever has access to the terminal. The recipient ID is typically
"local" or a user identifier for the daemon queue.
"""
import asyncio
import json
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional

from navconfig.logging import logging

from .base import HumanChannel
from ..models import (
    HumanInteraction,
    HumanResponse,
    InteractionType,
)

try:
    from rich.console import Console, Group
    from rich.panel import Panel
    from rich.table import Table
    from rich.prompt import Prompt, Confirm
    from rich.text import Text

    HAS_RICH = True
except ImportError:
    HAS_RICH = False


class CLIHumanChannel(HumanChannel):
    """Interactive CLI channel for Human-in-the-Loop.

    Renders interaction prompts in the terminal using Rich and captures
    human responses via stdin. Uses asyncio.run_in_executor to avoid
    blocking the event loop during input().

    This is a production-grade channel — not just for testing. If you're
    running agents from your terminal and want to answer questions
    directly, this is the channel to use.

    Args:
        console: Rich Console instance (created if not provided).
        prompt_prefix: Prefix shown before user input prompts.
        show_context: Whether to display interaction context.
        input_timeout: Optional local timeout for input in seconds.
            None means no local timeout (global interaction timeout
            still applies via the manager).
    """

    channel_type = "cli"

    def __init__(
        self,
        console: Optional[Any] = None,
        prompt_prefix: str = "🧑 Human",
        show_context: bool = True,
        input_timeout: Optional[int] = None,
    ) -> None:
        if not HAS_RICH:
            raise ImportError(
                "Rich is required for CLIHumanChannel. "
                "Install it with: pip install rich"
            )

        self.console = console or Console()
        self.prompt_prefix = prompt_prefix
        self.show_context = show_context
        self.input_timeout = input_timeout
        self.logger = logging.getLogger("HITL.CLI")

        # Callback registered by the manager
        self._response_callback: Optional[Callable] = None
        # Track pending interactions for cancel support
        self._pending: Dict[str, HumanInteraction] = {}

    # ─── HumanChannel interface ──────────────────────────────────────────

    async def register_response_handler(
        self,
        callback: Callable[[HumanResponse], Awaitable[None]],
    ) -> None:
        """Register the manager's response callback."""
        self._response_callback = callback

    async def send_interaction(
        self,
        interaction: HumanInteraction,
        recipient: str,
    ) -> bool:
        """Display the interaction in the terminal and capture the response.

        Uses run_in_executor for all input() calls to keep the asyncio
        event loop free.
        """
        self._pending[interaction.interaction_id] = interaction

        # Render the question
        self._render_interaction(interaction)

        # Capture response based on type
        try:
            response_value = await self._capture_response(interaction)
        except asyncio.TimeoutError:
            self.console.print(
                "\n⏰ [yellow]Timeout waiting for CLI response[/yellow]\n"
            )
            return True  # Delivered (shown) even if not answered
        except (EOFError, KeyboardInterrupt):
            self.console.print(
                "\n⚠️ [yellow]Input cancelled[/yellow]\n"
            )
            return True

        if response_value is None:
            return True

        # Build and dispatch the response
        response = HumanResponse(
            interaction_id=interaction.interaction_id,
            respondent=recipient,
            response_type=interaction.interaction_type,
            value=response_value,
            timestamp=datetime.utcnow().isoformat(),
            metadata={"channel": "cli", "terminal": True},
        )

        if self._response_callback:
            await self._response_callback(response)

        self._pending.pop(interaction.interaction_id, None)
        return True

    async def send_notification(self, recipient: str, message: str) -> None:
        """Display a notification in the terminal."""
        self.console.print(
            Panel(
                message,
                title="📬 Notification",
                border_style="green",
                padding=(0, 2),
            )
        )

    async def cancel_interaction(
        self, interaction_id: str, recipient: str
    ) -> None:
        """Cancel a pending interaction."""
        if interaction_id in self._pending:
            del self._pending[interaction_id]
            short_id = interaction_id[:8]
            self.console.print(
                f"\n  [yellow]⚠️ Interaction {short_id}... cancelled[/yellow]"
            )

    # ─── Rendering ────────────────────────────────────────────────────────

    def _render_interaction(self, interaction: HumanInteraction) -> None:
        """Render the interaction prompt with Rich."""
        source = (
            interaction.source_agent
            or interaction.source_flow
            or "Agent"
        )
        title = f"🤖 {source} needs your input"

        body_parts: list = []

        # Context block
        if interaction.context and self.show_context:
            body_parts.append(Text(interaction.context, style="dim"))
            body_parts.append(Text(""))

        # Main question
        body_parts.append(Text(interaction.question, style="bold white"))

        # Type-specific rendering
        if (
            interaction.interaction_type
            in (InteractionType.SINGLE_CHOICE, InteractionType.MULTI_CHOICE)
            and interaction.options
        ):
            body_parts.append(Text(""))
            table = Table(show_header=False, box=None, padding=(0, 2))
            table.add_column("Key", style="cyan bold", width=12)
            table.add_column("Option", style="white")
            table.add_column("Desc", style="dim")

            for opt in interaction.options:
                table.add_row(
                    f"[{opt.key}]",
                    opt.label,
                    opt.description or "",
                )
            body_parts.append(table)

            if interaction.interaction_type == InteractionType.MULTI_CHOICE:
                body_parts.append(Text(""))
                body_parts.append(
                    Text(
                        "  Comma-separated keys, 'all', 'none', "
                        "or 'done' to finish",
                        style="dim italic",
                    )
                )

        elif interaction.interaction_type == InteractionType.APPROVAL:
            body_parts.append(Text(""))
            body_parts.append(
                Text("  [y] ✅ Approve    [n] ❌ Reject", style="cyan")
            )

        elif interaction.interaction_type == InteractionType.FORM:
            body_parts.append(Text(""))
            body_parts.append(
                Text(
                    "  Fill in the form fields below:",
                    style="dim italic",
                )
            )

        # Footer
        timeout_str = str(interaction.timeout)
        footer = (
            f"Timeout: {timeout_str} | "
            f"Type: {interaction.interaction_type.value}"
        )

        panel_content = Group(*body_parts)

        self.console.print()
        self.console.print(
            Panel(
                panel_content,
                title=title,
                subtitle=footer,
                border_style="blue",
                padding=(1, 2),
            )
        )

    # ─── Input Capture ────────────────────────────────────────────────────

    async def _capture_response(
        self,
        interaction: HumanInteraction,
    ) -> Optional[Any]:
        """Capture the human's response based on interaction type.

        All input is done via run_in_executor to avoid blocking asyncio.
        """
        handler = {
            InteractionType.FREE_TEXT: self._prompt_free_text,
            InteractionType.APPROVAL: self._prompt_approval,
            InteractionType.SINGLE_CHOICE: self._prompt_single_choice,
            InteractionType.MULTI_CHOICE: self._prompt_multi_choice,
            InteractionType.FORM: self._prompt_form,
            InteractionType.POLL: self._prompt_single_choice,
        }.get(interaction.interaction_type, self._prompt_free_text)

        if self.input_timeout:
            return await asyncio.wait_for(
                handler(interaction), timeout=self.input_timeout
            )
        return await handler(interaction)

    async def _prompt_free_text(
        self, interaction: HumanInteraction
    ) -> str:
        """Free text input."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: Prompt.ask(f"\n{self.prompt_prefix}")
        )

    async def _prompt_approval(
        self, interaction: HumanInteraction
    ) -> bool:
        """Yes/No approval input."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: Confirm.ask(f"\n{self.prompt_prefix}")
        )

    async def _prompt_single_choice(
        self, interaction: HumanInteraction
    ) -> str:
        """Single selection from options."""
        options = interaction.options or []
        valid_keys = [o.key for o in options]

        def _ask() -> str:
            return Prompt.ask(
                f"\n{self.prompt_prefix} [cyan](choose one)[/cyan]",
                choices=valid_keys,
                show_choices=True,
            )

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _ask)

    async def _prompt_multi_choice(
        self, interaction: HumanInteraction
    ) -> List[str]:
        """Multi-selection from options.

        The human types keys separated by commas, or one by one.
        Special commands:
        - 'done' → finish selection
        - 'all'  → select all options
        - 'none' → select none
        - Typing a key again toggles it off
        """
        options = interaction.options or []
        valid_keys = {o.key for o in options}
        labels = {o.key: o.label for o in options}

        def _ask() -> List[str]:
            selected: List[str] = []

            while True:
                raw = Prompt.ask(
                    f"{self.prompt_prefix} [cyan](select)[/cyan]"
                )
                raw = raw.strip().lower()

                if raw == "done":
                    break
                elif raw == "all":
                    selected = list(valid_keys)
                    self.console.print("    ✅ All selected")
                    break
                elif raw == "none":
                    selected = []
                    self.console.print("    ❌ None selected")
                    break
                else:
                    keys = [
                        k.strip() for k in raw.split(",") if k.strip()
                    ]
                    for key in keys:
                        if key in valid_keys:
                            if key not in selected:
                                selected.append(key)
                                self.console.print(
                                    f"    ✅ {labels.get(key, key)}"
                                )
                            else:
                                selected.remove(key)
                                self.console.print(
                                    f"    ❌ {labels.get(key, key)} "
                                    f"[dim](deselected)[/dim]"
                                )
                        else:
                            self.console.print(
                                f"    ⚠️ [yellow]'{key}' is not a "
                                f"valid option[/yellow]"
                            )

                    if selected:
                        sel_str = ", ".join(selected)
                        self.console.print(
                            f"    [dim]Selected: {sel_str} "
                            f"(type 'done' to confirm)[/dim]"
                        )
                    else:
                        self.console.print(
                            "    [dim]Nothing selected yet[/dim]"
                        )

            return selected

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _ask)

    async def _prompt_form(
        self, interaction: HumanInteraction
    ) -> dict:
        """Structured form input.

        Iterates through the fields defined in form_schema (JSON Schema)
        and prompts for each one, with type coercion and validation.
        """
        schema = interaction.form_schema
        if not schema or "properties" not in schema:
            text = await self._prompt_free_text(interaction)
            return {"raw": text}

        def _ask_form() -> dict:
            result: Dict[str, Any] = {}
            properties = schema["properties"]
            required = schema.get("required", [])

            self.console.print(
                "\n  [dim]Form — fill in the fields:[/dim]"
            )

            for field_name, field_def in properties.items():
                field_type = field_def.get("type", "string")
                description = field_def.get("description", field_name)
                default = field_def.get("default")
                is_required = field_name in required

                req_mark = " [red]*[/red]" if is_required else ""
                default_hint = (
                    f" [dim](default: {default})[/dim]"
                    if default is not None
                    else ""
                )

                if field_type == "boolean":
                    value: Any = Confirm.ask(
                        f"  {description}{req_mark}{default_hint}",
                        default=default,
                    )
                elif field_type == "string" and "enum" in field_def:
                    value = Prompt.ask(
                        f"  {description}{req_mark}",
                        choices=field_def["enum"],
                        show_choices=True,
                        default=default,
                    )
                else:
                    raw = Prompt.ask(
                        f"  {description}{req_mark}{default_hint}",
                        default=(
                            str(default) if default is not None else ""
                        ),
                    )
                    if field_type == "integer":
                        try:
                            value = int(raw) if raw else default
                        except ValueError:
                            value = default
                    elif field_type == "number":
                        try:
                            value = float(raw) if raw else default
                        except ValueError:
                            value = default
                    else:
                        value = raw if raw else default

                result[field_name] = value

            return result

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _ask_form)


class CLIDaemonHumanChannel(HumanChannel):
    """CLI channel for when the agent runs as a daemon/background service.

    Interactions are published to a Redis queue. A separate CLI companion
    process reads them and lets the human respond interactively.

    The companion (cli_companion.py) subscribes to the queue, renders
    questions using the interactive CLIHumanChannel, and pushes responses
    back through Redis.

    Args:
        redis: Redis client instance (asyncio-compatible).
        queue_prefix: Redis key prefix for the interaction queues.
    """

    channel_type = "cli"

    def __init__(
        self,
        redis: Any,
        queue_prefix: str = "hitl:cli_queue",
    ) -> None:
        self.redis = redis
        self.queue_prefix = queue_prefix
        self.logger = logging.getLogger("HITL.CLI.Daemon")
        self._response_callback: Optional[Callable] = None

    async def register_response_handler(
        self,
        callback: Callable[[HumanResponse], Awaitable[None]],
    ) -> None:
        """Register the manager's response callback."""
        self._response_callback = callback

    async def send_interaction(
        self,
        interaction: HumanInteraction,
        recipient: str,
    ) -> bool:
        """Publish interaction to Redis queue for the CLI companion."""
        try:
            await self.redis.lpush(
                f"{self.queue_prefix}:{recipient}:pending",
                interaction.model_dump_json(),
            )
            # Notify listening companions
            await self.redis.publish(
                f"{self.queue_prefix}:{recipient}:notify",
                json.dumps(
                    {
                        "interaction_id": interaction.interaction_id,
                        "question": interaction.question,
                        "type": interaction.interaction_type.value,
                        "source": (
                            interaction.source_agent
                            or interaction.source_flow
                            or "agent"
                        ),
                    }
                ),
            )
            self.logger.info(
                "Interaction %s... queued for CLI companion "
                "(recipient=%s)",
                interaction.interaction_id[:8],
                recipient,
            )
            return True
        except Exception:
            self.logger.exception("Failed to queue interaction")
            return False

    async def send_notification(self, recipient: str, message: str) -> None:
        """Send notification via Redis queue."""
        try:
            await self.redis.publish(
                f"{self.queue_prefix}:{recipient}:notify",
                json.dumps({"notification": message}),
            )
        except Exception:
            self.logger.exception("Failed to send notification")

    async def cancel_interaction(
        self, interaction_id: str, recipient: str
    ) -> None:
        """Publish cancellation event."""
        try:
            await self.redis.publish(
                f"{self.queue_prefix}:{recipient}:notify",
                json.dumps(
                    {
                        "cancelled": interaction_id,
                        "message": (
                            f"Interaction {interaction_id[:8]}... cancelled"
                        ),
                    }
                ),
            )
        except Exception:
            self.logger.exception("Failed to cancel interaction")

    async def start_response_listener(self, recipient: str) -> None:
        """Listen for responses from the CLI companion.

        Runs as a background asyncio task in the agent worker process.
        Picks up responses pushed to the Redis queue by the companion.
        """
        self.logger.info(
            "Listening for CLI responses (recipient=%s)", recipient
        )
        while True:
            try:
                data = await self.redis.brpop(
                    f"{self.queue_prefix}:{recipient}:responses",
                    timeout=5,
                )
                if data:
                    _, payload = data
                    response = HumanResponse.model_validate_json(payload)
                    if self._response_callback:
                        await self._response_callback(response)
            except asyncio.CancelledError:
                break
            except Exception:
                self.logger.exception("Error in response listener")
                await asyncio.sleep(1)
