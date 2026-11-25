"""HTTP admission endpoints for the first multiplayer milestone."""

from __future__ import annotations

import json
from collections.abc import Callable
from urllib.parse import urlsplit

from fastapi import (
    FastAPI,
    Header,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from pydantic import BaseModel, ConfigDict, Field

from .connections import ConnectionRegistry
from .sessions import SessionError, SessionStore

MAX_MESSAGE_LENGTH = 4096


class JoinRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    room_code: str = Field(min_length=1, max_length=64)


def _allowed_origin(origin: str | None) -> bool:
    if origin is None:
        return True  # Non-browser clients do not send Origin.
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    return (
        parsed.scheme in ("http", "https")
        and parsed.hostname
        in (
            "localhost",
            "127.0.0.1",
        )
        and parsed.username is None
    )


def _parse_message(raw: str | None) -> dict[str, object] | None:
    if raw is None:
        return None
    if len(raw.encode("utf-8")) > MAX_MESSAGE_LENGTH:
        return None
    try:
        message = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return message if isinstance(message, dict) else None


async def _receive_text(websocket: WebSocket) -> str | None:
    frame = await websocket.receive()
    if frame["type"] == "websocket.disconnect":
        raise WebSocketDisconnect(code=frame.get("code", 1000))
    return frame.get("text")


def create_app(
    code_factory: Callable[[], str] | None = None,
    token_factory: Callable[[], str] | None = None,
) -> FastAPI:
    """Create an isolated app and session store, with injectable test generators."""

    app = FastAPI(title="Heads-Up Live Poker")
    sessions = SessionStore(code_factory, token_factory)
    connections = ConnectionRegistry()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/table", status_code=status.HTTP_201_CREATED)
    def create_table() -> dict[str, str]:
        try:
            code, token = sessions.create()
        except SessionError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        return {"room_code": code, "seat": "A", "session_token": token}

    @app.post("/api/join", status_code=status.HTTP_201_CREATED)
    async def join_table(request: JoinRequest) -> dict[str, str]:
        try:
            token = sessions.join(request.room_code)
        except SessionError as exc:
            http_status = (
                status.HTTP_409_CONFLICT
                if exc.code == "TABLE_FULL"
                else status.HTTP_404_NOT_FOUND
            )
            raise HTTPException(
                status_code=http_status,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        await connections.broadcast_lobby(table_ready=True)
        return {"seat": "B", "session_token": token}

    @app.get("/api/session")
    def current_session(
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        prefix = "Bearer "
        token = (
            authorization[len(prefix) :]
            if authorization and authorization.startswith(prefix)
            else ""
        )
        try:
            seat, ready = sessions.seat_for_token(token)
        except SessionError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        return {"seat": seat, "table_ready": ready}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        if not _allowed_origin(websocket.headers.get("origin")):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        seat = None
        try:
            first = _parse_message(await _receive_text(websocket))
            if (
                first is None
                or set(first) != {"type", "token"}
                or first["type"] != "auth"
                or not isinstance(first["token"], str)
            ):
                await websocket.send_json(
                    {
                        "type": "error",
                        "code": "INVALID_MESSAGE",
                        "message": "Authenticate first",
                    }
                )
                await websocket.close(code=1008)
                return
            try:
                seat, ready = sessions.seat_for_token(first["token"])
            except SessionError:
                await websocket.send_json(
                    {
                        "type": "error",
                        "code": "UNAUTHORIZED",
                        "message": "Invalid session token",
                    }
                )
                await websocket.close(code=1008)
                return
            previous = await connections.attach(seat, websocket)
            if previous is not None:
                try:
                    await previous.websocket.close(code=4000)
                except (RuntimeError, WebSocketDisconnect):
                    pass
            await connections.broadcast_lobby(ready)

            while True:
                message = _parse_message(await _receive_text(websocket))
                if message == {"type": "ping"}:
                    await websocket.send_json({"type": "pong"})
                elif message is None:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "code": "INVALID_MESSAGE",
                            "message": "Invalid message",
                        }
                    )
                else:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "code": "NOT_READY",
                            "message": "Gameplay is not available yet",
                        }
                    )
        except WebSocketDisconnect:
            pass
        finally:
            if seat is not None and await connections.detach_if_current(
                seat, websocket
            ):
                await connections.broadcast_lobby(sessions.table_ready())

    return app


app = create_app()
