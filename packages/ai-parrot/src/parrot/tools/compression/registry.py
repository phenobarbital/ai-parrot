"""Multi-source, immutable compressor configuration registry.

Mirrors the source-precedence shape of ``parrot/tools/discovery.py``
(project override > third-party package manifests > core defaults) but for
declarative TOML compressor manifests rather than tool classes. Loaded once
per process; :meth:`CompressorRegistry.load` never mutates a previously
returned instance.
"""
import importlib
import logging
import tomllib
from fnmatch import fnmatch
from pathlib import Path
from types import MappingProxyType

from pydantic import ValidationError

from .config import CompressorConfig, CompressorEntry
from .protocol import known_codecs

logger = logging.getLogger(__name__)

# Mirrors parrot/tools/discovery.py:DEFAULT_SOURCES — module names probed
# for a `compressors.toml` shipped alongside their package. Overridable per
# call (e.g. by tests) via the `thirdparty_sources` parameter.
DEFAULT_THIRDPARTY_SOURCES: tuple[str, ...] = ("parrot_tools", "plugins.tools")

# Core defaults manifest shipped inside this package.
_CORE_MANIFEST = Path(__file__).parent / "compressors.toml"


class CompressorRegistry:
    """Immutable, process-wide compressor configuration.

    Built by :meth:`load`, which merges TOML manifests from three sources in
    precedence order (first source to declare a key wins):

    1. project ``.parrot/compressors.toml``
    2. third-party package manifests (a ``compressors.toml`` shipped next to
       an importable package's ``__init__.py``)
    3. core defaults (``parrot/tools/compression/compressors.toml``)

    The registry never exposes a public mutator — after :meth:`load`
    returns, the instance is read-only.
    """

    def __init__(self, entries: dict[str, CompressorEntry]) -> None:
        self._entries: MappingProxyType[str, CompressorEntry] = MappingProxyType(
            dict(entries)
        )

    @property
    def entries(self) -> MappingProxyType[str, CompressorEntry]:
        """Read-only view of the merged tool-name-pattern -> entry mapping."""
        return self._entries

    @classmethod
    def load(
        cls,
        project_root: Path | None = None,
        *,
        thirdparty_sources: tuple[str, ...] | None = None,
    ) -> "CompressorRegistry":
        """Load and merge all compressor manifests into one registry.

        Args:
            project_root: Root directory to look for ``.parrot/compressors.toml``
                in. Defaults to the current working directory when omitted.
            thirdparty_sources: Module names to probe for a package-shipped
                ``compressors.toml``. Defaults to
                :data:`DEFAULT_THIRDPARTY_SOURCES`; overridable (e.g. by
                tests / a fixture package proving G6).

        Returns:
            A new, immutable :class:`CompressorRegistry`.

        Raises:
            ValueError: A manifest references a codec that is not registered
                (via ``register_codec``), naming the manifest path and the
                offending entry key.
            tomllib.TOMLDecodeError: A manifest is not valid TOML.
            pydantic.ValidationError: A manifest does not match the
                ``CompressorConfig`` schema.
        """
        project_root = project_root or Path.cwd()
        sources = cls._sources(project_root, thirdparty_sources)

        merged: dict[str, CompressorEntry] = {}
        # (source path) -> set of keys it declared, used for shadow warnings.
        declared_by: dict[str, set[str]] = {}

        for path in sources:
            if not path.is_file():
                continue
            cfg = cls._parse(path)
            cls._validate_codecs(cfg, path)
            keys_here: set[str] = set()
            for key, entry in cfg.compressor.items():
                keys_here.add(key)
                if key not in merged:
                    merged[key] = entry
            declared_by[str(path)] = keys_here

        cls._warn_shadows(declared_by, str(_CORE_MANIFEST))
        return cls(merged)

    @staticmethod
    def _sources(
        project_root: Path,
        thirdparty_sources: tuple[str, ...] | None,
    ) -> list[Path]:
        """Return manifest paths in precedence order (highest first)."""
        paths: list[Path] = [project_root / ".parrot" / "compressors.toml"]

        for source in thirdparty_sources or DEFAULT_THIRDPARTY_SOURCES:
            try:
                package = importlib.import_module(source)
            except ImportError:
                logger.debug(
                    "Compressor manifest source '%s' not installed, skipping",
                    source,
                )
                continue
            package_file = getattr(package, "__file__", None)
            if not package_file:
                continue
            candidate = Path(package_file).parent / "compressors.toml"
            paths.append(candidate)

        paths.append(_CORE_MANIFEST)
        return paths

    @staticmethod
    def _parse(path: Path) -> CompressorConfig:
        try:
            with open(path, "rb") as fh:
                raw = tomllib.load(fh)
        except tomllib.TOMLDecodeError as exc:
            raise ValueError(f"Malformed TOML in {path}: {exc}") from exc

        try:
            return CompressorConfig.model_validate(raw)
        except ValidationError as exc:
            raise ValueError(
                f"Invalid compressor manifest schema in {path}: {exc}"
            ) from exc

    @staticmethod
    def _validate_codecs(cfg: CompressorConfig, path: Path) -> None:
        known = known_codecs()
        for key, entry in cfg.compressor.items():
            if entry.codec not in known:
                raise ValueError(
                    f"Unknown codec '{entry.codec}' for entry '{key}' in "
                    f"{path} (known: {', '.join(sorted(known)) or '<none registered>'})"
                )

    @staticmethod
    def _warn_shadows(declared_by: dict[str, set[str]], core_path: str) -> None:
        core_keys = declared_by.get(core_path, set())
        if not core_keys:
            return
        for path, keys in declared_by.items():
            if path == core_path:
                continue
            shadowed = keys & core_keys
            for key in shadowed:
                logger.warning(
                    "Compressor entry '%s' in %s shadows the built-in entry "
                    "declared in %s",
                    key, path, core_path,
                )

    def resolve(self, tool_name: str) -> CompressorEntry | None:
        """Resolve the effective :class:`CompressorEntry` for a tool.

        Match precedence: exact ``tool_name`` key > glob pattern (longest
        pattern first, for determinism) > the ``"*"`` wildcard.

        Args:
            tool_name: The tool name to resolve an entry for.

        Returns:
            The matching :class:`CompressorEntry`, or ``None`` if no entry
            (not even a wildcard) is configured.
        """
        if tool_name in self._entries:
            return self._entries[tool_name]

        glob_keys = [k for k in self._entries if k != "*" and _is_glob(k)]
        for key in sorted(glob_keys, key=len, reverse=True):
            if fnmatch(tool_name, key):
                return self._entries[key]

        return self._entries.get("*")


def _is_glob(pattern: str) -> bool:
    """Return True if `pattern` contains glob metacharacters."""
    return any(ch in pattern for ch in "*?[")
