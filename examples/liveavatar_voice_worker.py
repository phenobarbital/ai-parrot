"""LiveAvatar Phase C — LiveKit voice worker entry point (FEAT-243).

Run this as a standalone process to serve the voice-native avatar:

    python examples/liveavatar_voice_worker.py dev      # local
    python examples/liveavatar_voice_worker.py start    # prod
    # or deploy: lk agent deploy

``worker.configure(...)`` is called at **import time** (module level) so that
``livekit-agents``' ``forkserver`` job processes re-run it when they re-import
this module. The bot brain is resolved in-process via a standalone
``BotManager`` (``build_standalone_bot_resolver``), and structured outputs are
forwarded to the ai-parrot-server over Redis (the server runs
``configure_liveavatar_output_subscriber`` — enable it with
``ENABLE_LIVEAVATAR_VOICE=true`` — to re-broadcast them to the browser).

Required env: ``LIVEAVATAR_API_KEY``, ``LIVEAVATAR_AVATAR_ID``, ``LIVEKIT_URL``,
``LIVEKIT_API_KEY``, ``LIVEKIT_API_SECRET``, ``REDIS_URL`` plus the STT/TTS
provider keys (Deepgram / Cartesia). Requires
``ai-parrot-integrations[liveavatar-voice]`` and ``ai-parrot-server`` installed
in the worker environment (the resolver uses the server's ``BotManager``).
"""

from parrot.integrations.liveavatar.livekit_agent import worker
from parrot.manager.bot_resolver import build_standalone_bot_resolver

# Configure at import time (module level) — NOT inside ``if __name__ == ...`` —
# so forkserver children pick it up on re-import.
worker.configure(
    bot_resolver=build_standalone_bot_resolver(enable_registry_bots=True),
    agent_name="liveavatar-voice",
    # cfg / output_sink / room_manager default from env (LIVEAVATAR_*, REDIS_URL,
    # LIVEKIT_*). The output_sink is a RedisBroadcastForwarder publishing on the
    # same channel the server's subscriber listens on.
)


if __name__ == "__main__":
    worker.run()
