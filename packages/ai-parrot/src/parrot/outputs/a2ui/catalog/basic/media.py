"""A2UI v1.0 Basic Catalog — media/text primitives (TASK-2536).

``Text``, ``Image``, ``Icon``, ``Video``, ``AudioPlayer``. Every field, enum,
and default is transcribed from the vendored
``catalog/basic/spec/catalog.json`` (pinned SHA
``90157ec10f36cf8e192daa71c95d2684af20c756``) — see
``test_basic_primitives.py`` for the anti-drift comparison.

One-way import rule (G8): this module MUST NEVER import from
``parrot.bots``, ``parrot.clients``, agents, or DatasetManager.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from parrot.outputs.a2ui.models import Component, DataBinding, DynamicString

__all__ = ["AudioPlayer", "Icon", "IconSvgPath", "Image", "Text", "Video"]

#: The 60 official named icon values (``catalog.json#/components/Icon/name``).
IconName = Literal[
    "accountCircle",
    "add",
    "arrowBack",
    "arrowForward",
    "attachFile",
    "calendarToday",
    "call",
    "camera",
    "check",
    "close",
    "delete",
    "download",
    "edit",
    "event",
    "error",
    "fastForward",
    "favorite",
    "favoriteOff",
    "folder",
    "help",
    "home",
    "info",
    "locationOn",
    "lock",
    "lockOpen",
    "mail",
    "menu",
    "moreVert",
    "moreHoriz",
    "notificationsOff",
    "notifications",
    "pause",
    "payment",
    "person",
    "phone",
    "photo",
    "play",
    "print",
    "refresh",
    "rewind",
    "search",
    "send",
    "settings",
    "share",
    "shoppingCart",
    "skipNext",
    "skipPrevious",
    "star",
    "starHalf",
    "starOff",
    "stop",
    "upload",
    "visibility",
    "visibilityOff",
    "volumeDown",
    "volumeMute",
    "volumeOff",
    "volumeUp",
    "warning",
]


class Text(Component):
    """Markdown-lite text content."""

    INSTRUCTIONS: ClassVar[str] = (
        "Text: requires `text`. `variant` hints the base style "
        "(caption|body, default body). Simple Markdown (no HTML/images/links) "
        "is supported, but prefer dedicated components for richer content."
    )

    component: Literal["Text"] = "Text"
    text: DynamicString
    variant: Literal["caption", "body"] = "body"


class Image(Component):
    """A displayed image."""

    INSTRUCTIONS: ClassVar[str] = (
        "Image: requires `url`. `fit` controls resizing (contain|cover|fill|"
        "none|scaleDown, default fill); `variant` hints size/style "
        "(icon|avatar|smallFeature|mediumFeature|largeFeature|header, "
        "default mediumFeature)."
    )

    component: Literal["Image"] = "Image"
    url: DynamicString
    description: DynamicString | None = None
    fit: Literal["contain", "cover", "fill", "none", "scaleDown"] = "fill"
    variant: Literal["icon", "avatar", "smallFeature", "mediumFeature", "largeFeature", "header"] = "mediumFeature"


class IconSvgPath(BaseModel):
    """A custom icon given as an inline SVG path."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    svg_path: DynamicString = Field(alias="svgPath")


class Icon(Component):
    """A named icon, a custom SVG path, or a data-model-bound icon name."""

    INSTRUCTIONS: ClassVar[str] = (
        "Icon: requires `name` — one of the 60 official icon names, "
        "{svgPath: <string>} for a custom icon, or a data binding."
    )

    component: Literal["Icon"] = "Icon"
    name: IconName | IconSvgPath | DataBinding


class Video(Component):
    """A video player."""

    INSTRUCTIONS: ClassVar[str] = "Video: requires `url`. `posterUrl` is the poster image shown before playback."

    component: Literal["Video"] = "Video"
    url: DynamicString
    poster_url: DynamicString | None = Field(default=None, alias="posterUrl")


class AudioPlayer(Component):
    """An audio player."""

    INSTRUCTIONS: ClassVar[str] = "AudioPlayer: requires `url`. `description` is an optional title/summary."

    component: Literal["AudioPlayer"] = "AudioPlayer"
    url: DynamicString
    description: DynamicString | None = None
