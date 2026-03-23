from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Union
import datetime
from navconfig.logging import logging

from jinja2 import (
    BaseLoader,
    ChoiceLoader,
    DictLoader,
    Environment,
    FileSystemBytecodeCache,
    FileSystemLoader,
    TemplateError,
    TemplateNotFound,
    StrictUndefined,
    select_autoescape,
)

PathLike = Union[str, Path]


@dataclass
class JinjaConfig:
    """Configuration for the async Jinja2 Environment."""
    template_dirs: list[Path] = field(default_factory=list)
    extensions: list[str] = field(default_factory=lambda: [
        "jinja2.ext.i18n",
        "jinja2.ext.loopcontrols",
        "jinja2_time.TimeExtension",
        "jinja2_iso8601.ISO8601Extension",
        "jinja2.ext.do",
        "jinja2_humanize_extension.HumanizeExtension",
        # "jinja2.ext.debug",  # enable in dev if desired
    ])
    bytecode_cache_dir: Optional[Path] = None
    bytecode_cache_pattern: str = "%s.cache"
    autoescape: Any = select_autoescape(["html", "xml", "j2", "jinja", "jinja2"])
    undefined: Any = StrictUndefined  # raise on missing variables
    keep_trailing_newline: bool = True
    trim_blocks: bool = True
    lstrip_blocks: bool = True


class TemplateEngine:
    """
    Async-only Jinja2 template engine with:
        - multiple directories
        - in-memory templates
        - pluggable extensions/filters/globals
        - optional bytecode cache
    """

    def __init__(
        self,
        template_dirs: Optional[Union[PathLike, Sequence[PathLike]]] = None,
        *,
        extensions: Optional[Sequence[str]] = None,
        bytecode_cache_dir: Optional[PathLike] = None,
        filters: Optional[Mapping[str, Any]] = None,
        globals_: Optional[Mapping[str, Any]] = None,
        config: Optional[JinjaConfig] = None,
        debug: bool = False,
    ) -> None:
        cfg = config or JinjaConfig()
        self.logger = logging.getLogger(__name__)

        # Normalize directories
        if template_dirs is not None:
            if isinstance(template_dirs, (str, Path)):
                cfg.template_dirs.append(Path(template_dirs).resolve())
            else:
                cfg.template_dirs.extend(Path(p).resolve() for p in template_dirs)

        # Validate & store directories
        self._fs_dirs: list[Path] = []
        for d in cfg.template_dirs:
            if not d.exists():
                raise ValueError(f"Template directory not found: {d}")
            if not d.is_dir():
                raise ValueError(f"Template path is not a directory: {d}")
            self._fs_dirs.append(d)

        # Extensions
        self._configure_extensions(cfg, extensions, debug)

        # Optional bytecode cache
        self._bytecode_cache = None
        if bytecode_cache_dir is not None:
            bdir = Path(bytecode_cache_dir).resolve()
            bdir.mkdir(parents=True, exist_ok=True)
            self._bytecode_cache = FileSystemBytecodeCache(str(bdir), cfg.bytecode_cache_pattern)
        elif cfg.bytecode_cache_dir:
            bdir = Path(cfg.bytecode_cache_dir).resolve()
            bdir.mkdir(parents=True, exist_ok=True)
            self._bytecode_cache = FileSystemBytecodeCache(str(bdir), cfg.bytecode_cache_pattern)

        # Loaders: FileSystem + (optional) in-memory DictLoader
        self._dict_loader = DictLoader({})
        fs_loader = FileSystemLoader([str(p) for p in self._fs_dirs]) if self._fs_dirs else None

        if fs_loader:
            loader: BaseLoader = ChoiceLoader([self._dict_loader, fs_loader])
        else:
            loader = self._dict_loader  # still works with only in-memory templates

        # Build the environment (async-only)
        self.env = Environment(
            loader=loader,
            enable_async=True,
            extensions=self._extensions,
            bytecode_cache=self._bytecode_cache,
            autoescape=cfg.autoescape,
            undefined=cfg.undefined,
            keep_trailing_newline=cfg.keep_trailing_newline,
            trim_blocks=cfg.trim_blocks,
            lstrip_blocks=cfg.lstrip_blocks,
        )

        # Useful default filters/globals
        self.env.filters.setdefault("datetime", datetime.datetime.fromtimestamp)
        # Add user-supplied
        if filters:
            for name, fn in filters.items():
                self.env.filters[name] = fn
        if globals_:
            for name, val in globals_.items():
                self.env.globals[name] = val

        self.logger.debug(
            "AsyncTemplateEngine initialized: dirs=%s, extensions=%s, bytecode_cache=%s",
            [str(d) for d in self._fs_dirs],
            self._extensions,
            bool(self._bytecode_cache),
        )

    def _configure_extensions(self, cfg: JinjaConfig, extensions: Optional[Sequence[str]], debug: bool) -> None:
        """Configure Jinja2 extensions."""
        # Merge extensions
        self._extensions: list[str] = list(cfg.extensions)
        if extensions:
            for ext in extensions:
                if ext not in self._extensions:
                    self._extensions.append(ext)
        if debug and "jinja2.ext.debug" not in self._extensions:
            self._extensions.append("jinja2.ext.debug")

    # -------- Public API
    def add_template_dir(self, path: PathLike) -> None:
        """Add a new filesystem directory to the search path at runtime."""
        p = Path(path).resolve()
        if not p.exists() or not p.is_dir():
            raise ValueError(f"Template directory invalid: {p}")
        self._fs_dirs.append(p)

        # Rebuild loader chain (ChoiceLoader is immutable in practice)
        current_dicts = self._dict_loader.mapping
        self._dict_loader = DictLoader(current_dicts)
        fs_loader = FileSystemLoader([str(d) for d in self._fs_dirs])
        self.env.loader = ChoiceLoader([self._dict_loader, fs_loader])

    def add_templates(self, templates: Mapping[str, str]) -> None:
        """
        Add/override in-memory templates.
        Example: add_templates({'layout.html': '<html>{{ self.block() }}</html>'})
        """
        for name, content in templates.items():
            self._dict_loader.mapping[name] = content

    def get_template(self, name: str):
        """Get a compiled template by name (raises FileNotFoundError on miss)."""
        try:
            return self.env.get_template(name)
        except TemplateNotFound as ex:
            raise FileNotFoundError(f"Template not found: {name}") from ex
        except Exception as ex:
            raise RuntimeError(f"Error loading template '{name}': {ex}") from ex

    async def render(self, name: str, params: Optional[Mapping[str, Any]] = None) -> str:
        """
        Async render of a template by name.
        Only async path is supported (no sync render).
        """
        params = dict(params or {})
        try:
            tmpl = self.get_template(name)
            # MUST use render_async because enable_async=True
            return await tmpl.render_async(**params)
        except TemplateError as ex:
            raise ValueError(f"Template error while rendering '{name}': {ex}") from ex
        except Exception as ex:
            raise RuntimeError(f"Unexpected error rendering '{name}': {ex}") from ex

    async def render_string(self, source: str, params: Optional[Mapping[str, Any]] = None) -> str:
        """
        Async render from a string (compiled via the current environment).
        Useful for ad-hoc/injected content.
        """
        params = dict(params or {})
        try:
            tmpl = self.env.from_string(source)
            return await tmpl.render_async(**params)
        except TemplateError as ex:
            raise ValueError(f"Template error while rendering string: {ex}") from ex
        except Exception as ex:
            raise RuntimeError(f"Unexpected error rendering string: {ex}") from ex

    def add_filters(self, filters: Mapping[str, Any]) -> None:
        """Register additional filters (supports async filters too)."""
        for name, fn in filters.items():
            self.env.filters[name] = fn

    def add_globals(self, globals_: Mapping[str, Any]) -> None:
        """Register additional global variables/functions."""
        for name, val in globals_.items():
            self.env.globals[name] = val

    def compile_directory(self, target: PathLike, *, zip: Optional[str] = "deflated") -> None:
        """
        Optionally precompile all templates from filesystem loaders into `target`.
        Skips silently if there are no filesystem directories.
        """
        if not self._fs_dirs:
            return
        target_path = Path(target).resolve()
        target_path.mkdir(parents=True, exist_ok=True)
        try:
            self.env.compile_templates(
                target=str(target_path),
                zip=zip
            )
        except Exception as ex:
            # If a transient decode error happens, try once again without failing the app
            self.logger.warning(
                f"Compile templates failed once: {ex}; retrying…"
            )
            self.env.compile_templates(
                target=str(target_path),
                zip=zip
            )


# ------------------------------
# Minimal usage example (async)
# ------------------------------
# engine = TemplateEngine(
#     template_dirs=["/path/to/templates", "/path/to/partials"],
#     extensions=["jinja2.ext.debug"],  # optional
#     bytecode_cache_dir="/tmp/jinja-cache",  # optional
#     filters={"jsonify": json_encoder},      # e.g. your custom filter
#     globals_={"app_name": "QuerySource"},   # optional
# )
#
# engine.add_templates({"inline.html": "Hello {{ name }}!"})
#
# html = await engine.render("index.html", {"user": "Pilar"})
# text = await engine.render_string("Hi {{ who }}", {"who": "there"})
