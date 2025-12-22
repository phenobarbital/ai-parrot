from typing import Dict, Optional, Callable, Awaitable, List, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
import asyncio
import hashlib
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent
from .models import FormDefinition


@dataclass
class CacheEntry:
    """Cache entry with metadata."""
    form: FormDefinition
    loaded_at: datetime
    file_hash: str
    access_count: int = 0
    last_accessed: datetime = field(default_factory=datetime.utcnow)


class FormDefinitionCache:
    """
    Cache for FormDefinitions with file watching for auto-invalidation.

    Supports:
    - In-memory cache with TTL
    - Optional Redis backend for distributed systems
    - File system watching for YAML changes
    """

    def __init__(
        self,
        redis_client: Optional[Any] = None,
        ttl_seconds: int = 3600,
        watch_files: bool = True,
        forms_directory: Optional[str] = None,
    ):
        self._memory_cache: Dict[str, CacheEntry] = {}
        self._redis = redis_client
        self._ttl = timedelta(seconds=ttl_seconds)
        self._watch_files = watch_files
        self._forms_directory = Path(forms_directory) if forms_directory else None
        self._observer: Optional[Observer] = None
        self._lock = asyncio.Lock()

        # Callbacks for cache events
        self._on_invalidate: List[Callable[[str], Awaitable[None]]] = []

        if watch_files and forms_directory:
            self._setup_file_watcher()

    def _setup_file_watcher(self):
        """Setup file system watcher for YAML changes."""
        if not self._forms_directory or not self._forms_directory.exists():
            return

        class YAMLChangeHandler(FileSystemEventHandler):
            def __init__(self, cache: 'FormDefinitionCache'):
                self.cache = cache

            def on_modified(self, event):
                if event.is_directory:
                    return
                if event.src_path.endswith(('.yaml', '.yml')):
                    asyncio.create_task(
                        self.cache._handle_file_change(event.src_path)
                    )

        self._observer = Observer()
        self._observer.schedule(
            YAMLChangeHandler(self),
            str(self._forms_directory),
            recursive=True
        )
        self._observer.start()

    async def _handle_file_change(self, file_path: str):
        """Handle YAML file modification."""
        # Find and invalidate cached form from this file
        async with self._lock:
            to_invalidate = []
            for form_id, entry in self._memory_cache.items():
                if entry.form._file_path == file_path:
                    to_invalidate.append(form_id)

            for form_id in to_invalidate:
                await self.invalidate(form_id)

                # Reload the form
                try:
                    new_form = FormDefinition.from_yaml_file(file_path)
                    await self.set(new_form.form_id, new_form)
                except Exception as e:
                    # Log error but don't crash
                    print(f"Error reloading form from {file_path}: {e}")

    async def get(self, form_id: str) -> Optional[FormDefinition]:
        """Get form from cache."""
        # Try memory first
        if form_id in self._memory_cache:
            entry = self._memory_cache[form_id]

            # Check TTL
            if datetime.utcnow() - entry.loaded_at > self._ttl:
                await self.invalidate(form_id)
                return None

            # Update access stats
            entry.access_count += 1
            entry.last_accessed = datetime.utcnow()
            return entry.form

        # Try Redis if available
        if self._redis:
            cached = await self._get_from_redis(form_id)
            if cached:
                # Populate memory cache
                await self.set(form_id, cached, skip_redis=True)
                return cached

        return None

    async def set(
        self,
        form_id: str,
        form: FormDefinition,
        skip_redis: bool = False
    ):
        """Store form in cache."""
        async with self._lock:
            self._memory_cache[form_id] = CacheEntry(
                form=form,
                loaded_at=datetime.utcnow(),
                file_hash=form.compute_hash(),
            )

        if self._redis and not skip_redis:
            await self._set_in_redis(form_id, form)

    async def invalidate(self, form_id: str):
        """Invalidate a cached form."""
        async with self._lock:
            if form_id in self._memory_cache:
                del self._memory_cache[form_id]

        if self._redis:
            await self._delete_from_redis(form_id)

        # Notify callbacks
        for callback in self._on_invalidate:
            await callback(form_id)

    async def invalidate_all(self):
        """Clear entire cache."""
        async with self._lock:
            self._memory_cache.clear()

        if self._redis:
            # Clear Redis keys with prefix
            await self._clear_redis_cache()

    def on_invalidate(self, callback: Callable[[str], Awaitable[None]]):
        """Register callback for cache invalidation events."""
        self._on_invalidate.append(callback)

    async def load_directory(self, directory: str = None):
        """Load all YAML forms from directory."""
        dir_path = Path(directory) if directory else self._forms_directory
        if not dir_path or not dir_path.exists():
            return

        for yaml_file in dir_path.glob("**/*.yaml"):
            try:
                form = FormDefinition.from_yaml_file(str(yaml_file))
                await self.set(form.form_id, form)
            except Exception as e:
                print(f"Error loading {yaml_file}: {e}")

    # Redis helpers
    async def _get_from_redis(self, form_id: str) -> Optional[FormDefinition]:
        """Get form from Redis."""
        if not self._redis:
            return None
        try:
            import json
            key = f"form_definition:{form_id}"
            data = await self._redis.get(key)
            if data:
                return FormDefinition._from_dict(json.loads(data))
        except Exception:
            pass
        return None

    async def _set_in_redis(self, form_id: str, form: FormDefinition):
        """Store form in Redis."""
        if not self._redis:
            return
        try:
            import json
            key = f"form_definition:{form_id}"
            # Serialize form to dict (simplified)
            data = {
                'form_id': form.form_id,
                'title': form.title,
                'sections': [],  # Would need full serialization
                'version': form.version,
            }
            await self._redis.setex(
                key,
                int(self._ttl.total_seconds()),
                json.dumps(data)
            )
        except Exception:
            pass

    async def _delete_from_redis(self, form_id: str):
        """Delete form from Redis."""
        if not self._redis:
            return
        try:
            key = f"form_definition:{form_id}"
            await self._redis.delete(key)
        except Exception:
            pass

    async def _clear_redis_cache(self):
        """Clear all form definitions from Redis."""
        if not self._redis:
            return
        try:
            keys = await self._redis.keys("form_definition:*")
            if keys:
                await self._redis.delete(*keys)
        except Exception:
            pass

    def shutdown(self):
        """Stop file watcher."""
        if self._observer:
            self._observer.stop()
            self._observer.join()
