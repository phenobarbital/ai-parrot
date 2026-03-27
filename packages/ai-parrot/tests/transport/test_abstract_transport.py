"""Tests for AbstractTransport interface contract."""

import pytest

from parrot.transport.base import AbstractTransport


class TestAbstractTransport:
    """Verify the AbstractTransport ABC contract."""

    def test_cannot_instantiate(self):
        """AbstractTransport cannot be instantiated directly."""
        with pytest.raises(TypeError):
            AbstractTransport()

    def test_requires_all_abstract_methods(self):
        """Subclass missing methods raises TypeError."""
        class Incomplete(AbstractTransport):
            pass

        with pytest.raises(TypeError):
            Incomplete()

    def test_partial_implementation_raises(self):
        """Subclass with only some methods still raises TypeError."""
        class Partial(AbstractTransport):
            async def start(self):
                pass

            async def stop(self):
                pass

        with pytest.raises(TypeError):
            Partial()

    @pytest.mark.asyncio
    async def test_context_manager_calls_lifecycle(self):
        """__aenter__/__aexit__ call start/stop."""
        class MockTransport(AbstractTransport):
            started = False
            stopped = False

            async def start(self):
                self.started = True

            async def stop(self):
                self.stopped = True

            async def send(self, to, content, msg_type="message",
                           payload=None, reply_to=None):
                return ""

            async def broadcast(self, content, channel="general",
                                payload=None):
                pass

            async def messages(self):
                yield {}

            async def list_agents(self):
                return []

            async def reserve(self, paths, reason=""):
                return True

            async def release(self, paths=None):
                pass

            async def set_status(self, status, message=""):
                pass

        t = MockTransport()
        async with t:
            assert t.started
        assert t.stopped

    @pytest.mark.asyncio
    async def test_context_manager_stops_on_exception(self):
        """__aexit__ calls stop() even if body raises."""
        class MockTransport(AbstractTransport):
            stopped = False

            async def start(self):
                pass

            async def stop(self):
                self.stopped = True

            async def send(self, to, content, msg_type="message",
                           payload=None, reply_to=None):
                return ""

            async def broadcast(self, content, channel="general",
                                payload=None):
                pass

            async def messages(self):
                yield {}

            async def list_agents(self):
                return []

            async def reserve(self, paths, reason=""):
                return True

            async def release(self, paths=None):
                pass

            async def set_status(self, status, message=""):
                pass

        t = MockTransport()
        with pytest.raises(ValueError):
            async with t:
                raise ValueError("boom")
        assert t.stopped

    def test_import_from_package(self):
        """Import works from the expected path."""
        from parrot.transport.base import AbstractTransport as AT
        assert AT is AbstractTransport
