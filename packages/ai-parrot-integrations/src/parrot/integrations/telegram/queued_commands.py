"""Telegram routing for queued commands and requester job controls."""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Tuple

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from parrot.integrations.core.queued import JobNotice, QueuedCommand, QueuedCommandService, Requester
from parrot.integrations.core.queued.messages import (
    JOB_COMMANDS,
    format_ack,
    format_cancel,
    format_job_list,
    format_job_view,
    format_notice_header,
)
from parrot.integrations.parser import parse_response
from parrot.integrations.telegram.context import telegram_chat_scope

if TYPE_CHECKING:
    from .wrapper import TelegramAgentWrapper


class TelegramQueuedCommands:
    """Own one Telegram wrapper's queued-command service and handlers."""

    def __init__(self, wrapper: TelegramAgentWrapper, commands: List[QueuedCommand]) -> None:
        """Capture the wrapper and create a service owned by its Telegram bot."""

        self.wrapper = wrapper
        self.commands = commands
        self.service = QueuedCommandService(owner=f"telegram:{wrapper.config.name}")

    def register(self, router: Router) -> List[Tuple[str, str]]:
        """Register canonical/alias routes and requester-scoped job controls."""

        for command in self.commands:
            names = (command.spec.command, *command.spec.aliases)

            async def command_handler(message: Message, _command: QueuedCommand = command) -> None:
                requester = await self._requester(message)
                if requester is None:
                    return
                raw_args = (message.text or "").split(maxsplit=1)
                args_text = raw_args[1] if len(raw_args) > 1 else ""
                topic_id = message.message_thread_id if getattr(message, "is_topic_message", False) else None
                reply_id = message.message_id

                async def deliver(notice: JobNotice) -> None:
                    header = format_notice_header(notice)
                    parsed = parse_response(notice.result) if notice.status == "completed" else parse_response("")
                    prefix = f"{header}\n\n" if notice.status == "completed" else header
                    await self.wrapper.send_parsed_to_chat(
                        message.chat.id,
                        parsed,
                        message_thread_id=topic_id,
                        reply_to_message_id=reply_id,
                        prefix=prefix,
                    )

                with telegram_chat_scope(message.chat.id):
                    outcome = await self.service.submit(_command, args_text, requester, deliver)
                await message.answer(format_ack(outcome))

            router.message.register(command_handler, Command(*names))

        router.message.register(self._jobs, Command("jobs"))
        router.message.register(self._job_status, Command("job_status"))
        router.message.register(self._job_cancel, Command("job_cancel"))
        return [(command.spec.command, command.spec.description) for command in self.commands] + list(JOB_COMMANDS)

    async def shutdown(self) -> None:
        """Stop jobs while the Telegram session remains available for notices."""

        await self.service.stop()

    async def _requester(self, message: Message) -> Requester | None:
        """Apply wrapper access gates and capture the immutable request destination."""

        if not self.wrapper._is_authorized(message.chat.id):
            await message.answer("⛔ You are not authorized to use this bot.")
            return None
        if not await self.wrapper._check_authentication(message):
            return None
        session = self.wrapper._get_user_session(message)
        user = message.from_user
        return Requester(
            platform="telegram",
            user_id=str(user.id) if user is not None else "unknown",
            chat_id=str(message.chat.id),
            thread_id=str(message.message_thread_id) if getattr(message, "is_topic_message", False) else None,
            message_id=str(message.message_id),
            display_name=session.display_name,
        )

    async def _jobs(self, message: Message) -> None:
        """Show the calling user's recent queued jobs."""

        requester = await self._requester(message)
        if requester is not None:
            await message.answer(format_job_list(await self.service.list_for(requester)))

    async def _job_status(self, message: Message) -> None:
        """Show one requester-owned queued job."""

        requester = await self._requester(message)
        if requester is None:
            return
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2:
            await message.answer("Usage: /job_status <job_id>")
            return
        view = await self.service.get(parts[1].strip(), requester)
        await message.answer(format_job_view(view) if view is not None else "Job not found.")

    async def _job_cancel(self, message: Message) -> None:
        """Cancel one requester-owned queued job."""

        requester = await self._requester(message)
        if requester is None:
            return
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2:
            await message.answer("Usage: /job_cancel <job_id>")
            return
        job_id = parts[1].strip()
        await message.answer(format_cancel(await self.service.cancel(job_id, requester), job_id))
