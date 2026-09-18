"""Video-reel reliability package (FEAT-564).

Deliberately has no eager exports: sub-modules (``errors``, ``profiles``,
``clip``, ``veo``, ``omni``, ``timeline``, ``music``) are populated by
dependent tasks and should be imported explicitly by their consumers,
e.g. ``from parrot.clients.google.reel.errors import ReelErrorCode``.
"""
