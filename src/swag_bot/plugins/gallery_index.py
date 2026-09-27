"""Static gallery index (``swag_gallery`` version 1).

An index is a JSON document. It can live on disk or at any HTTP URL, including
GitHub Pages. This module only parses it. It does not rank plugins or talk to
a gallery server.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from swag_bot.plugins.errors import PluginError

_SOURCE_TYPES = frozenset({"path", "github", "git", "archive"})


class GalleryError(PluginError):
    """A gallery index or gallery install check failed."""


class DigestSpec(BaseModel):
    """SHA-256 of the canonical plugin bundle."""

    model_config = ConfigDict(extra="ignore")

    algorithm: str
    value: str

    @field_validator("algorithm")
    @classmethod
    def _algorithm(cls, value: str) -> str:
        if value != "sha256":
            raise ValueError("digest algorithm must be sha256")
        return value

    @field_validator("value")
    @classmethod
    def _value(cls, value: str) -> str:
        text = value.strip().lower()
        if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
            raise ValueError("sha256 digest must be 64 hex characters")
        return text


class SignatureSpec(BaseModel):
    """Minisign signature carried in the index."""

    model_config = ConfigDict(extra="ignore")

    scheme: str
    public_key: str
    file: str

    @field_validator("scheme")
    @classmethod
    def _scheme(cls, value: str) -> str:
        if value != "minisign":
            raise ValueError("signature scheme must be minisign")
        return value

    @field_validator("public_key", "file")
    @classmethod
    def _nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("signature public_key and file must not be empty")
        return value


class SourceSpec(BaseModel):
    """Where to fetch the plugin tree. ``path`` is relative to a local index."""

    model_config = ConfigDict(extra="ignore")

    type: str
    path: str | None = None
    repo: str | None = None
    url: str | None = None
    ref: str | None = None

    @field_validator("type")
    @classmethod
    def _type(cls, value: str) -> str:
        if value not in _SOURCE_TYPES:
            allowed = ", ".join(sorted(_SOURCE_TYPES))
            raise ValueError(f"source type must be one of: {allowed}")
        return value

    @model_validator(mode="after")
    def _fields(self) -> SourceSpec:
        if self.type == "path" and not self.path:
            raise ValueError("path source needs path")
        if self.type == "github" and not self.repo:
            raise ValueError("github source needs repo")
        if self.type in {"git", "archive"} and not self.url:
            raise ValueError(f"{self.type} source needs url")
        return self


class GalleryPluginEntry(BaseModel):
    """One plugin in the index. Unknown keys are ignored."""

    model_config = ConfigDict(extra="ignore")

    name: str
    version: str | None = None
    description: str | None = None
    author: str | None = None
    license: str | None = None
    homepage: str | None = None
    keywords: list[str] = Field(default_factory=list)
    permissions: list[str] | None = None
    source: SourceSpec
    digest: DigestSpec | None = None
    signature: SignatureSpec | None = None

    @field_validator("author", mode="before")
    @classmethod
    def _author(cls, value: Any) -> Any:
        if isinstance(value, dict):
            name = value.get("name")
            if isinstance(name, str):
                return name
        return value

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        if not value or any(char.isspace() for char in value) or "/" in value or "\\" in value:
            raise ValueError("plugin name must be non-empty and contain no spaces or slashes")
        return value


class GalleryIndex(BaseModel):
    """Top-level ``swag_gallery`` document."""

    model_config = ConfigDict(extra="ignore")

    swag_gallery: int
    name: str = ""
    plugins: list[GalleryPluginEntry]

    @field_validator("swag_gallery")
    @classmethod
    def _version(cls, value: int) -> int:
        if value != 1:
            raise ValueError(
                f"unsupported swag_gallery version {value}; this client reads version 1"
            )
        return value

    @model_validator(mode="after")
    def _unique(self) -> GalleryIndex:
        names = [plugin.name for plugin in self.plugins]
        if len(names) != len(set(names)):
            raise ValueError("gallery plugin names must be unique")
        return self


class LoadedIndex:
    """An index plus the location it was read from."""

    def __init__(self, index: GalleryIndex, source: str, base_dir: Path | None) -> None:
        self.index = index
        self.source = source
        self.base_dir = base_dir

    def find(self, name: str) -> GalleryPluginEntry:
        """Return the entry named ``name``."""
        for plugin in self.index.plugins:
            if plugin.name == name:
                return plugin
        listed = ", ".join(plugin.name for plugin in self.index.plugins) or "(none)"
        raise GalleryError(f"gallery has no plugin {name!r} ({listed})")


def parse_index(data: bytes, *, source: str, base_dir: Path | None) -> LoadedIndex:
    """Parse index bytes. ``base_dir`` resolves ``path`` sources for a local file."""
    try:
        payload = json.loads(data.decode("utf-8-sig"))
    except UnicodeError as exc:
        raise GalleryError(f"{source}: index is not UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise GalleryError(f"{source}: invalid JSON ({exc})") from exc
    if not isinstance(payload, dict):
        raise GalleryError(f"{source}: gallery index must be a JSON object")
    try:
        index = GalleryIndex.model_validate(payload)
    except ValidationError as exc:
        raise GalleryError(f"{source}: invalid gallery index: {exc}") from exc
    return LoadedIndex(index, source, base_dir)


def index_base_dir(source: str) -> Path | None:
    """Directory of a local index. Remote indexes have no relative base."""
    if _is_remote(source):
        return None
    if source.startswith("file:"):
        path = Path(urlparse(source).path)
    else:
        path = Path(source).expanduser()
    return path.resolve().parent


def _is_remote(source: str) -> bool:
    return source.startswith(("http://", "https://"))
