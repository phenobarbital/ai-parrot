"""CommCenterService — transport-agnostic bulk notification sending core.

Ships the request/response ``datamodel`` models and the recipient
ingestion, rendering/validation, and fan-out logic consumed by
``parrot.handlers.comm_center.CommCenterHandler`` (spec §2 G12: the
sending core must be reusable without aiohttp, e.g. by a future toolkit).
"""
