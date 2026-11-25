"""ASGI entry point for the original lobby launch command."""

from collections.abc import Callable

from fastapi import FastAPI

from poker.rooms import RoomManager
from poker.server import create_app as create_combined_app


def create_app(
    code_factory: Callable[[], str] | None = None,
    token_factory: Callable[[], str] | None = None,
) -> FastAPI:
    rooms = RoomManager(code_factory=code_factory, token_factory=token_factory)
    return create_combined_app(rooms, lobby_errors=True)


app = create_app()
