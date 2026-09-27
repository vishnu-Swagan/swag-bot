"""``swag memory`` commands."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated

import typer

from swag_bot.config import load_settings
from swag_bot.errors import ConfigError, SwagError
from swag_bot.interfaces import MemoryItem
from swag_bot.memory.factory import get_memory_store
from swag_bot.memory.util import redact_secrets, tags_from_metadata

app = typer.Typer(help="Pluggable memory store.", no_args_is_help=True)


@app.command("add")
def add(
    content: Annotated[str, typer.Argument(help="Text to remember.")],
    tag: Annotated[
        list[str] | None,
        typer.Option("--tag", "-t", help="Tag stored with the memory. Repeat for more than one."),
    ] = None,
) -> None:
    """Store one memory and print its id."""
    metadata = {"tags": list(tag)} if tag else None
    try:
        item = get_memory_store(load_settings()).add(content, metadata=metadata)
    except (ConfigError, SwagError) as exc:
        _fail(str(exc))
        return
    typer.echo(item.id)


@app.command("search")
def search(
    query: Annotated[str, typer.Argument(help="Text to search for.")],
    limit: Annotated[int, typer.Option("--limit", "-n", help="Maximum matches.")] = 5,
) -> None:
    """Search the memory store. Best matches are printed first."""
    try:
        items = get_memory_store(load_settings()).search(query, limit=limit)
    except (ConfigError, SwagError) as exc:
        _fail(str(exc))
        return
    if not items:
        typer.echo("no matches")
        return
    _print_items(items)


@app.command("list")
def list_memories(
    limit: Annotated[int, typer.Option("--limit", "-n", help="Maximum items.")] = 20,
) -> None:
    """List recent memories, newest first."""
    try:
        store = get_memory_store(load_settings())
        listed = getattr(store, "list_recent", None)
        if listed is None:
            _fail("this memory backend cannot list items")
            return
        items = listed(limit=limit)
    except (ConfigError, SwagError) as exc:
        _fail(str(exc))
        return
    if not items:
        typer.echo("no memories")
        return
    _print_items(items)


@app.command("forget")
def forget(
    item_id: Annotated[str, typer.Argument(help="Id of the memory to delete.")],
) -> None:
    """Delete one memory."""
    try:
        removed = get_memory_store(load_settings()).delete(item_id)
    except (ConfigError, SwagError) as exc:
        _fail(str(exc))
        return
    if not removed:
        typer.echo(f"no memory {item_id}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"forgot {item_id}")


def _print_items(items: Sequence[MemoryItem]) -> None:
    for item in items:
        tags = tags_from_metadata(item.metadata)
        tag_text = ",".join(tags) if tags else "-"
        typer.echo(f"{item.id}  {item.created_at.isoformat()}  tags={tag_text}")
        typer.echo(item.content)


def _fail(message: str) -> None:
    typer.echo(redact_secrets(message), err=True)
    raise typer.Exit(code=1)
