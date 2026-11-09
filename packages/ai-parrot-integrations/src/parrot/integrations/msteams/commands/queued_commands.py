"""MS Teams queued-command routing and proactive result delivery."""

from typing import Any, List, Optional

from botbuilder.core import TurnContext

from parrot.integrations.core.queued import (
    JobNotice,
    QueuedCommand,
    QueuedCommandService,
    Requester,
    discover_queued_commands,
)
from parrot.integrations.core.queued.messages import (
    format_ack,
    format_cancel,
    format_job_list,
    format_job_view,
    format_notice_header,
)
from parrot.integrations.msteams.commands import MSTeamsCommandRouter, command_args
from parrot.integrations.parser import parse_response


class TeamsQueuedCommands:
    """Own one Teams wrapper's service and captured conversation callbacks."""

    def __init__(self, wrapper: Any, commands: List[QueuedCommand]) -> None:
        """Capture local dependencies without contacting Redis."""

        self.wrapper = wrapper
        self.commands = commands
        self.service = QueuedCommandService(owner=f"msteams:{wrapper.config.name}")

    def register(self, router: MSTeamsCommandRouter) -> None:
        """Register async turn-context handlers and owner-scoped controls."""

        for command in self.commands:

            async def command_handler(turn_context: TurnContext, _command: QueuedCommand = command) -> None:
                client_id = getattr(self.wrapper.config, "client_id", None)
                if not client_id:
                    await self.wrapper.send_text("Queued commands require a configured client_id.", turn_context)
                    return

                activity = turn_context.activity
                requester = Requester(
                    platform="msteams",
                    user_id=str(activity.from_property.id),
                    chat_id=str(activity.conversation.id),
                    display_name=getattr(activity.from_property, "name", None),
                )
                conversation_reference = TurnContext.get_conversation_reference(activity)

                async def deliver(notice: JobNotice) -> None:
                    adapter = getattr(self.wrapper, "adapter", None)
                    if adapter is None:
                        return

                    async def callback(context: TurnContext) -> None:
                        parsed = parse_response(notice.result if notice.status == "completed" else "")
                        header = format_notice_header(notice)
                        if notice.status == "completed" and parsed.text:
                            parsed.text = f"{header}\n\n{parsed.text}"
                        else:
                            parsed.text = header
                        await self.wrapper._send_parsed_response(parsed, context)

                    await adapter.continue_conversation(conversation_reference, callback, client_id)

                outcome = await self.service.submit(_command, command_args(turn_context), requester, deliver)
                await self.wrapper.send_text(format_ack(outcome), turn_context)

            for name in (command.spec.command, *command.spec.aliases):
                router.register(name, command_handler)

        router.register("jobs", self._jobs)
        router.register("job_status", self._job_status)
        router.register("job_cancel", self._job_cancel)

    async def shutdown(self) -> None:
        """Stop the service before platform resources close."""

        await self.service.stop()

    @staticmethod
    def _requester(turn_context: TurnContext) -> Requester:
        """Build the requester identity used to scope job controls."""

        activity = turn_context.activity
        return Requester(
            platform="msteams",
            user_id=str(activity.from_property.id),
            chat_id=str(activity.conversation.id),
            display_name=getattr(activity.from_property, "name", None),
        )

    async def _jobs(self, turn_context: TurnContext) -> None:
        """Show the calling user's recent queued jobs."""

        await self.wrapper.send_text(
            format_job_list(await self.service.list_for(self._requester(turn_context))), turn_context
        )

    async def _job_status(self, turn_context: TurnContext) -> None:
        """Show one requester-owned queued job."""

        job_id = command_args(turn_context).strip()
        if not job_id:
            await self.wrapper.send_text("Usage: /job_status <job_id>", turn_context)
            return
        view = await self.service.get(job_id, self._requester(turn_context))
        text = format_job_view(view) if view is not None else f"No job `{job_id}` found for you."
        await self.wrapper.send_text(text, turn_context)

    async def _job_cancel(self, turn_context: TurnContext) -> None:
        """Cancel one requester-owned queued job."""

        job_id = command_args(turn_context).strip()
        if not job_id:
            await self.wrapper.send_text("Usage: /job_cancel <job_id>", turn_context)
            return
        result = await self.service.cancel(job_id, self._requester(turn_context))
        await self.wrapper.send_text(format_cancel(result, job_id), turn_context)


def register_queued_commands(router: MSTeamsCommandRouter, wrapper: Any) -> Optional[TeamsQueuedCommands]:
    """Discover and register, returning None when no queued command exists."""

    commands = discover_queued_commands(wrapper.agent)
    if not commands:
        return None
    holder = TeamsQueuedCommands(wrapper, commands)
    holder.register(router)
    return holder
