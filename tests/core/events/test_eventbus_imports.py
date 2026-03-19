"""EventBus import tests for parrot.core.events (TASK-274)."""


class TestEventBusImport:
    def test_eventbus_import(self):
        from parrot.core.events import EventBus, Event, EventPriority  # noqa: F401

        assert EventBus is not None
        assert Event is not None
        assert EventPriority is not None

    def test_event_subscription_import(self):
        from parrot.core.events import EventSubscription  # noqa: F401

        assert EventSubscription is not None

    def test_all_exports(self):
        import parrot.core.events as evts

        assert set(evts.__all__) == {
            "EventBus",
            "Event",
            "EventPriority",
            "EventSubscription",
        }

    def test_event_model_fields(self):
        from parrot.core.events import Event, EventPriority

        evt = Event(
            event_type="test.event",
            payload={"key": "value"},
            priority=EventPriority.NORMAL,
        )
        assert evt.event_type == "test.event"
        assert evt.payload == {"key": "value"}

    def test_event_priority_values(self):
        from parrot.core.events import EventPriority

        assert EventPriority.LOW is not None
        assert EventPriority.NORMAL is not None
        assert EventPriority.HIGH is not None
