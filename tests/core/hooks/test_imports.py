"""Import and lazy-loading tests for parrot.core.hooks (TASK-274)."""
import sys


class TestCoreHooksImport:
    def test_core_hooks_import(self):
        from parrot.core.hooks import BaseHook, HookManager, HookEvent, HookType  # noqa: F401

        assert BaseHook is not None
        assert HookManager is not None
        assert HookEvent is not None
        assert HookType is not None

    def test_hookable_agent_import(self):
        from parrot.core.hooks import HookableAgent  # noqa: F401

        assert HookableAgent is not None

    def test_config_imports(self):
        from parrot.core.hooks import (  # noqa: F401
            BrokerHookConfig,
            FileUploadHookConfig,
            FileWatchdogHookConfig,
            IMAPHookConfig,
            JiraWebhookConfig,
            MatrixHookConfig,
            MessagingHookConfig,
            PostgresHookConfig,
            SchedulerHookConfig,
            SharePointHookConfig,
            WhatsAppRedisHookConfig,
        )

    def test_factory_helpers_import(self):
        from parrot.core.hooks import (  # noqa: F401
            create_crew_whatsapp_hook,
            create_multi_agent_whatsapp_hook,
            create_simple_whatsapp_hook,
        )

    def test_lazy_hook_import_scheduler(self):
        from parrot.core.hooks import SchedulerHook  # noqa: F401

        assert SchedulerHook is not None

    def test_lazy_hook_import_file_watchdog(self):
        from parrot.core.hooks import FileWatchdogHook  # noqa: F401

        assert FileWatchdogHook is not None

    def test_lazy_loading_no_asyncpg(self):
        """Package-level import of parrot.core.hooks must NOT pull in asyncpg."""
        before = set(sys.modules.keys())
        import parrot.core.hooks  # noqa: F401
        new = set(sys.modules.keys()) - before
        assert not any(m.startswith("asyncpg") for m in new), (
            f"asyncpg was newly imported by parrot.core.hooks: {new}"
        )

    def test_lazy_loading_no_watchdog(self):
        """Package-level import of parrot.core.hooks must NOT pull in watchdog."""
        before = set(sys.modules.keys())
        import parrot.core.hooks  # noqa: F401
        new = set(sys.modules.keys()) - before
        assert not any(m.startswith("watchdog") for m in new), (
            f"watchdog was newly imported by parrot.core.hooks: {new}"
        )

    def test_lazy_loading_no_apscheduler(self):
        """Package-level import of parrot.core.hooks must NOT pull in apscheduler."""
        before = set(sys.modules.keys())
        import parrot.core.hooks  # noqa: F401
        new = set(sys.modules.keys()) - before
        assert not any(m.startswith("apscheduler") for m in new), (
            f"apscheduler was newly imported by parrot.core.hooks: {new}"
        )

    def test_lazy_loading_no_aioimaplib(self):
        """Package-level import of parrot.core.hooks must NOT pull in aioimaplib."""
        before = set(sys.modules.keys())
        import parrot.core.hooks  # noqa: F401
        new = set(sys.modules.keys()) - before
        assert not any(m.startswith("aioimaplib") for m in new), (
            f"aioimaplib was newly imported by parrot.core.hooks: {new}"
        )

    def test_all_exports_contains_core_symbols(self):
        import parrot.core.hooks as hooks_pkg

        expected = {
            "BaseHook",
            "HookManager",
            "HookableAgent",
            "HookEvent",
            "HookType",
            "SchedulerHook",
            "FileWatchdogHook",
            "PostgresListenHook",
        }
        assert expected.issubset(set(hooks_pkg.__all__))

    def test_backward_compat_shim(self):
        """parrot.autonomous.hooks re-exports everything from parrot.core.hooks."""
        from parrot.autonomous.hooks import BaseHook, HookManager, HookEvent  # noqa: F401

        assert BaseHook is not None
