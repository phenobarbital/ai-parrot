"""Generic Pydantic-model to interactive-wizard engine.

Introspects ``model_fields`` on any Pydantic v2 ``BaseModel`` and generates
an interactive terminal form using ``prompt_toolkit`` for async input and
``Rich`` for rendering. Supports scalar types (str, int, float, bool),
``Literal`` choices, ``Optional`` fields, nested ``BaseModel`` sub-forms,
``List[...]`` with "add another?" loops (including discriminated unions),
and ``@path`` file input that inlines file contents or parses YAML/JSON.
"""
from __future__ import annotations

import json
import logging
import os
import types
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    Literal,
    Optional,
    Type,
    Union,
    get_args,
    get_origin,
)

from pydantic import BaseModel, Field, ValidationError
from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

_MAX_FILE_SIZE = 64 * 1024  # 64 KiB cap for @path file input


class WizardFieldOverride(BaseModel):
    """Per-field presentation override."""

    prompt: Optional[str] = None
    hide: bool = False
    file_loadable: bool = False


class WizardConfig(BaseModel):
    """Configuration for wizard behaviour."""

    overrides: Dict[str, WizardFieldOverride] = Field(default_factory=dict)
    allow_file_input: bool = True


class PydanticWizard:
    """Model-agnostic interactive form engine driven by pydantic v2 metadata."""

    def __init__(
        self,
        model: Type[BaseModel],
        *,
        config: Optional[WizardConfig] = None,
        console: Optional[Console] = None,
        session: Optional[PromptSession] = None,
    ) -> None:
        self.model = model
        self.config = config or WizardConfig()
        self.console = console or Console()
        self._session = session or PromptSession()
        self.logger = logging.getLogger(__name__)

    async def collect(self, *, initial: Optional[Dict[str, Any]] = None) -> BaseModel:
        """Prompt field-by-field; loop on ValidationError; return validated model."""
        values: Dict[str, Any] = dict(initial or {})
        fields = self.model.model_fields

        for name, field_info in fields.items():
            override = self.config.overrides.get(name)
            if override and override.hide:
                continue
            if name in values:
                continue

            try:
                value = await self._collect_field(name, field_info, override)
            except EOFError:
                break
            if value is not _SKIP:
                values[name] = value

        return self._validate_loop(values, fields)

    def _validate_loop(
        self, values: Dict[str, Any], fields: Any
    ) -> BaseModel:
        """Attempt model construction; on ValidationError, return partial for re-prompt."""
        try:
            return self.model(**values)
        except ValidationError as exc:
            self.console.print(
                Panel(
                    str(exc),
                    title="[red]Validation Error[/red]",
                    border_style="red",
                )
            )
            raise

    async def _collect_field(
        self,
        name: str,
        field_info: Any,
        override: Optional[WizardFieldOverride],
    ) -> Any:
        """Collect a single field value based on its type annotation."""
        annotation = field_info.annotation
        prompt_text = self._prompt_text(name, field_info, override)
        required = field_info.is_required()
        default = field_info.default if not required else _SKIP

        real_type, is_optional = _unwrap_optional(annotation)

        if not required and not is_optional and default is not None and default is not _SKIP:
            pass

        if _is_list_type(real_type):
            return await self._collect_list(name, real_type, field_info, override)

        if _is_literal(real_type):
            return await self._collect_literal(prompt_text, real_type, required, default)

        if _is_bool(real_type):
            return await self._collect_bool(prompt_text, required, default)

        if _is_pydantic_model(real_type):
            return await self._collect_submodel(name, real_type)

        return await self._collect_scalar(
            prompt_text, real_type, required, default, is_optional, override
        )

    def _prompt_text(
        self,
        name: str,
        field_info: Any,
        override: Optional[WizardFieldOverride],
    ) -> str:
        if override and override.prompt:
            return override.prompt
        desc = field_info.description
        if desc:
            return f"{_humanize(name)} ({desc})"
        return _humanize(name)

    async def _collect_scalar(
        self,
        prompt_text: str,
        real_type: type,
        required: bool,
        default: Any,
        is_optional: bool,
        override: Optional[WizardFieldOverride],
    ) -> Any:
        file_loadable = (
            self.config.allow_file_input
            and override is not None
            and override.file_loadable
        ) or (self.config.allow_file_input and real_type is str)
        default_hint = ""
        if default is not _SKIP and default is not None:
            default_hint = f" [{default}]"
        elif is_optional:
            default_hint = " [optional]"

        while True:
            try:
                raw = await self._prompt(f"{prompt_text}{default_hint}: ")
            except EOFError:
                if default is not _SKIP:
                    return default
                if is_optional:
                    return None
                return _SKIP

            if not raw and default is not _SKIP:
                return default
            if not raw and is_optional:
                return None
            if not raw and required:
                self.console.print("[yellow]This field is required.[/yellow]")
                continue

            if file_loadable and raw.startswith("@"):
                loaded = self._load_file_content(raw[1:])
                if loaded is not None:
                    return loaded
                continue

            try:
                return _coerce(raw, real_type)
            except (ValueError, TypeError) as exc:
                self.console.print(f"[red]Invalid input: {exc}[/red]")

    async def _collect_literal(
        self,
        prompt_text: str,
        annotation: Any,
        required: bool,
        default: Any,
    ) -> Any:
        choices = list(get_args(annotation))
        table = Table(show_header=False, box=None, padding=(0, 1))
        for i, choice in enumerate(choices, 1):
            marker = "*" if choice == default else " "
            table.add_row(f"  {marker}{i}.", str(choice))

        self.console.print(f"\n[bold]{prompt_text}:[/bold]")
        self.console.print(table)

        while True:
            hint = f" [{default}]" if default is not _SKIP else ""
            try:
                raw = await self._prompt(f"  Choice{hint}: ")
            except EOFError:
                if default is not _SKIP:
                    return default
                raise
            if not raw and default is not _SKIP:
                return default
            try:
                idx = int(raw)
                if 1 <= idx <= len(choices):
                    return choices[idx - 1]
            except ValueError:
                if raw in [str(c) for c in choices]:
                    return raw
            self.console.print(f"[red]Choose 1-{len(choices)}[/red]")

    async def _collect_bool(
        self, prompt_text: str, required: bool, default: Any
    ) -> bool:
        hint = ""
        if default is not _SKIP:
            hint = f" [{'Y/n' if default else 'y/N'}]"
        else:
            hint = " [y/n]"
        while True:
            try:
                raw = await self._prompt(f"{prompt_text}{hint}: ")
            except EOFError:
                if default is not _SKIP:
                    return default
                raise
            if not raw and default is not _SKIP:
                return default
            if raw.lower() in ("y", "yes", "true", "1"):
                return True
            if raw.lower() in ("n", "no", "false", "0"):
                return False
            self.console.print("[red]Enter y or n[/red]")

    async def _collect_submodel(self, name: str, model_type: Type[BaseModel]) -> BaseModel:
        self.console.print(f"\n[bold cyan]--- {_humanize(name)} ---[/bold cyan]")
        sub_wizard = PydanticWizard(
            model_type, config=self.config, console=self.console, session=self._session
        )
        result = await sub_wizard.collect()
        self.console.print(f"[bold cyan]--- end {_humanize(name)} ---[/bold cyan]")
        return result

    async def _collect_list(
        self,
        name: str,
        list_type: Any,
        field_info: Any,
        override: Optional[WizardFieldOverride],
    ) -> List[Any]:
        item_type = _list_item_type(list_type)
        items: List[Any] = []

        file_loadable = self.config.allow_file_input and (
            (override and override.file_loadable) or True
        )

        self.console.print(f"\n[bold]{_humanize(name)}[/bold] (list — enter items, or @path for YAML/JSON file)")

        if file_loadable:
            try:
                raw = await self._prompt("  Load from file? (@path or Enter to add interactively): ")
            except EOFError:
                return items
            if raw.startswith("@"):
                loaded = self._load_file_list(raw[1:], item_type)
                if loaded is not None:
                    return loaded

        variants = _get_discriminated_variants(item_type)

        while True:
            try:
                if variants:
                    item = await self._collect_variant(name, variants, len(items) + 1)
                elif _is_pydantic_model(item_type):
                    self.console.print(f"  [dim]Item {len(items) + 1}:[/dim]")
                    item = await self._collect_submodel(f"item {len(items) + 1}", item_type)
                else:
                    raw = await self._prompt(f"  Item {len(items) + 1} (or Enter to finish): ")
                    if not raw:
                        break
                    try:
                        item = _coerce(raw, item_type)
                    except (ValueError, TypeError) as exc:
                        self.console.print(f"[red]{exc}[/red]")
                        continue
            except EOFError:
                break

            items.append(item)
            try:
                more = await self._prompt("  Add another? [y/N]: ")
            except EOFError:
                break
            if more.lower() not in ("y", "yes"):
                break

        min_length = getattr(field_info, "metadata", None)
        if not items and field_info.is_required():
            self.console.print("[yellow]At least one item is required.[/yellow]")
            return await self._collect_list(name, list_type, field_info, override)
        return items

    async def _collect_variant(
        self, field_name: str, variants: Dict[str, Type[BaseModel]], item_num: int
    ) -> BaseModel:
        self.console.print(f"  [dim]Item {item_num} — choose type:[/dim]")
        names = list(variants.keys())
        for i, vname in enumerate(names, 1):
            self.console.print(f"    {i}. {vname}")
        while True:
            raw = await self._prompt("    Type: ")  # EOFError propagates
            try:
                idx = int(raw)
                if 1 <= idx <= len(names):
                    chosen = variants[names[idx - 1]]
                    return await self._collect_submodel(names[idx - 1], chosen)
            except ValueError:
                if raw in names:
                    return await self._collect_submodel(raw, variants[raw])
            self.console.print(f"[red]Choose 1-{len(names)}[/red]")

    def _load_file_content(self, path_str: str) -> Optional[str]:
        path = Path(path_str).expanduser()
        if not path.is_file():
            self.console.print(f"[red]File not found: {path}[/red]")
            return None
        size = path.stat().st_size
        if size > _MAX_FILE_SIZE:
            self.console.print(f"[red]File too large ({size} bytes > {_MAX_FILE_SIZE})[/red]")
            return None
        content = path.read_text(encoding="utf-8")
        source_line = f"[source: {path.name}]\n"
        self.console.print(f"[green]Loaded {len(content)} chars from {path.name}[/green]")
        return source_line + content

    def _load_file_list(self, path_str: str, item_type: type) -> Optional[List[Any]]:
        path = Path(path_str).expanduser()
        if not path.is_file():
            self.console.print(f"[red]File not found: {path}[/red]")
            return None
        size = path.stat().st_size
        if size > _MAX_FILE_SIZE:
            self.console.print(f"[red]File too large[/red]")
            return None
        text = path.read_text(encoding="utf-8")
        try:
            import yaml  # noqa: PLC0415
            data = yaml.safe_load(text)
        except Exception:
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                self.console.print(f"[red]Cannot parse as YAML or JSON: {exc}[/red]")
                return None
        if not isinstance(data, list):
            self.console.print("[red]File must contain a list/array[/red]")
            return None
        if _is_pydantic_model(item_type):
            try:
                return [item_type(**item) if isinstance(item, dict) else item_type(item) for item in data]
            except Exception as exc:
                self.console.print(f"[red]Failed to parse items: {exc}[/red]")
                return None
        return data

    async def _prompt(self, text: str) -> str:
        try:
            return (await self._session.prompt_async(text)).strip()
        except EOFError:
            raise
        except KeyboardInterrupt:
            raise EOFError

    def render_summary(self, instance: BaseModel) -> None:
        """Render a Rich summary of the collected model."""
        table = Table(title=f"{self.model.__name__} Summary", show_lines=True)
        table.add_column("Field", style="cyan")
        table.add_column("Value", style="white")
        for name, value in instance.model_dump().items():
            display = str(value)
            if len(display) > 80:
                display = display[:77] + "..."
            table.add_row(name, display)
        self.console.print(table)


# ── Sentinel ────────────────────────────────────────────────────────────────

class _SkipType:
    def __repr__(self) -> str:
        return "<SKIP>"
    def __bool__(self) -> bool:
        return False

_SKIP = _SkipType()

# ── Helpers ─────────────────────────────────────────────────────────────────


def _humanize(name: str) -> str:
    return name.replace("_", " ").title()


def _coerce(raw: str, target: type) -> Any:
    if target is str or target is Any:
        return raw
    if target is int:
        return int(raw)
    if target is float:
        return float(raw)
    return raw


def _unwrap_optional(annotation: Any) -> tuple[Any, bool]:
    origin = get_origin(annotation)
    if origin is Union or origin is types.UnionType:
        args = get_args(annotation)
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1 and len(args) == 2:
            return non_none[0], True
        return annotation, False
    return annotation, False


def _is_literal(annotation: Any) -> bool:
    return get_origin(annotation) is Literal


def _is_bool(annotation: Any) -> bool:
    return annotation is bool


def _is_list_type(annotation: Any) -> bool:
    origin = get_origin(annotation)
    return origin is list or origin is List


def _list_item_type(annotation: Any) -> Any:
    args = get_args(annotation)
    if args:
        inner = args[0]
        real, _ = _unwrap_optional(inner)
        return real
    return str


def _is_pydantic_model(annotation: Any) -> bool:
    try:
        return isinstance(annotation, type) and issubclass(annotation, BaseModel)
    except TypeError:
        return False


def _get_discriminated_variants(item_type: Any) -> Dict[str, Type[BaseModel]]:
    origin = get_origin(item_type)
    if origin is Union or origin is types.UnionType:
        args = get_args(item_type)
        variants = {}
        for arg in args:
            if _is_pydantic_model(arg):
                kind_field = arg.model_fields.get("kind")
                if kind_field and _is_literal(kind_field.annotation):
                    kind_val = get_args(kind_field.annotation)[0]
                    variants[kind_val] = arg
                else:
                    variants[arg.__name__] = arg
        if len(variants) >= 2:
            return variants
    if origin is not None:
        inner_args = get_args(item_type)
        if inner_args:
            return _get_discriminated_variants(inner_args[0])
    return {}
