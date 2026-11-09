"""Slack queued slash commands with a bounded acknowledgement path."""

from typing import Any, List, Optional

from parrot.integrations.core.queued import (
    JobNotice,
    QueuedCommand,
    QueuedCommandService,
    Requester,
    discover_queued_commands,
)
from parrot.integrations.core.queued.messages import (
    JOB_COMMANDS,
    format_ack,
    format_cancel,
    format_job_list,
    format_job_view,
    format_notice_header,
)
from parrot.integrations.parser import parse_response
from parrot.integrations.slack.commands import SlackCommandRouter


class SlackQueuedCommands:
    """Own a Slack wrapper's background commands and registered names."""

    def __init__(self, wrapper: Any, commands: List[QueuedCommand]) -> None:
        """Configure bounded Slack admission for one wrapper."""

        self.wrapper = wrapper
        self.commands = commands
        self.service = QueuedCommandService(
            owner=f"slack:{wrapper.config.name}",
            prepare_timeout=2.0,
            admission_timeout=2.0,
        )
        self.registered_names: List[str] = []
        self.help_entries: List[tuple[str, str]] = []

    @staticmethod
    def _requester(payload: dict[str, Any]) -> Requester:
        """Build the requester identity and delivery location from Slack payload data."""

        return Requester(
            platform="slack",
            user_id=payload["user_id"],
            chat_id=payload["channel_id"],
        )

    def _queued_handler(self, command: QueuedCommand) -> Any:
        """Build an async router handler for one discovered command."""

        async def handler(payload: dict[str, Any]) -> dict[str, str]:
            requester = self._requester(payload)

            async def deliver(notice: JobNotice) -> None:
                parsed = parse_response(notice.result if notice.result is not None else "")
                header = format_notice_header(notice)
                text = f"<@{requester.user_id}> {header}"
                if parsed.text:
                    text = f"{text}\n{parsed.text}"
                await self.wrapper.post_message(
                    requester.chat_id,
                    text=text,
                    blocks=self.wrapper._build_blocks(parsed),
                )

            outcome = await self.service.submit(
                command,
                payload.get("text", ""),
                requester,
                deliver,
            )
            return {"response_type": "ephemeral", "text": format_ack(outcome)}

        return handler

    def _jobs_handler(self) -> Any:
        """Build the requester-scoped recent-jobs handler."""

        async def handler(payload: dict[str, Any]) -> dict[str, str]:
            views = await self.service.list_for(self._requester(payload))
            return {"response_type": "ephemeral", "text": format_job_list(views)}

        return handler

    def _job_status_handler(self) -> Any:
        """Build the requester-scoped job-status handler."""

        async def handler(payload: dict[str, Any]) -> dict[str, str]:
            job_id = payload.get("text", "").strip()
            if not job_id:
                text = "Usage: /job_status <job_id>"
            else:
                view = await self.service.get(job_id, self._requester(payload))
                text = format_job_view(view) if view is not None else f"No job `{job_id}` found for you."
            return {"response_type": "ephemeral", "text": text}

        return handler

    def _job_cancel_handler(self) -> Any:
        """Build the requester-scoped job-cancellation handler."""

        async def handler(payload: dict[str, Any]) -> dict[str, str]:
            job_id = payload.get("text", "").strip()
            if not job_id:
                text = "Usage: /job_cancel <job_id>"
            else:
                result = await self.service.cancel(job_id, self._requester(payload))
                text = format_cancel(result, job_id)
            return {"response_type": "ephemeral", "text": text}

        return handler

    def register(self, router: SlackCommandRouter) -> List[str]:
        """Register queued commands, aliases and requester-scoped job controls."""

        names: List[str] = []
        help_entries: List[tuple[str, str]] = []
        for command in self.commands:
            handler = self._queued_handler(command)
            command_names = (command.spec.command, *command.spec.aliases)
            for name in command_names:
                router.register(name, handler)
                names.append(name)
                help_entries.append((name, command.spec.description))

        job_handlers = {
            "jobs": self._jobs_handler(),
            "job_status": self._job_status_handler(),
            "job_cancel": self._job_cancel_handler(),
        }
        for name, description in JOB_COMMANDS:
            router.register(name, job_handlers[name])
            names.append(name)
            help_entries.append((name, description))

        self.registered_names = names
        self.help_entries = help_entries
        return list(names)

    async def start(self) -> None:
        """Initialize local execution without awaiting Redis health."""

        await self.service.start()

    async def shutdown(self) -> None:
        """Deliver interruptions and stop the service."""

        await self.service.stop()


def register_queued_commands(router: SlackCommandRouter, wrapper: Any) -> Optional[SlackQueuedCommands]:
    """Discover and register queued commands, or return ``None`` when absent."""

    commands = discover_queued_commands(wrapper.agent)
    if not commands:
        return None
    holder = SlackQueuedCommands(wrapper, commands)
    holder.register(router)
    return holder
