from parrot.scheduler.functions import build_scheduler_callback, list_supported_callbacks
from parrot.handlers.scheduler import SchedulerCatalogHelper


def test_scheduler_callback_registry_contains_expected_callbacks():
    names = {item["name"] for item in list_supported_callbacks()}
    assert {
        "send_email_report",
        "create_file",
        "saving_data",
        "send_notify_report",
    }.issubset(names)


def test_build_scheduler_callback_returns_expected_class():
    callback = build_scheduler_callback({"type": "create_file", "config": {"output_dir": "/tmp"}})
    assert callback.callback_name == "create_file"


def test_scheduler_catalog_helper_lists_schedule_types():
    values = SchedulerCatalogHelper.list_schedule_types()
    assert "cron" in values
    assert "interval" in values
