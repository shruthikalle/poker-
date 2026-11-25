"""HTTP and WebSocket transport for the poker application."""

import json
from asyncio import wait_for
from typing import Literal
from urllib.parse import urlsplit

from fastapi import (
    FastAPI,
    Header,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from server.connections import ConnectionRegistry
from server.sessions import SessionError, SessionStore

from .engine import Player
from .rooms import (
    Admission,
    InvalidBetUnit,
    RoomAlreadyExists,
    RoomFull,
    RoomManager,
    RoomNotFound,
    RoomStatus,
)


class CreateRoomRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bet_unit: int = Field(strict=True, ge=2, le=20, multiple_of=2)


class JoinRoomRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    room_code: str = Field(strict=True, min_length=1, max_length=128)


class LobbyJoinRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    room_code: str = Field(strict=True, min_length=1, max_length=64)


class AdmissionResponse(BaseModel):
    room_code: str
    seat: Player
    session_token: str = Field(repr=False)
    bet_unit: int
    status: RoomStatus


class ErrorResponse(BaseModel):
    detail: str


class AuthenticateMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["authenticate"]
    session_token: str = Field(
        strict=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
        repr=False,
    )


def _allowed_origin(origin: str | None) -> bool:
    if origin is None:
        return True
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    return (
        parsed.scheme in ("http", "https")
        and parsed.hostname in ("localhost", "127.0.0.1")
        and parsed.username is None
    )


def _parse_message(raw: str | None) -> dict[str, object] | None:
    if raw is None:
        return None
    try:
        if len(raw.encode("utf-8")) > 4096:
            return None
        message = json.loads(raw)
    except (ValueError, RecursionError):
        return None
    return message if isinstance(message, dict) else None


async def _receive_message(socket: WebSocket) -> dict[str, object] | None:
    frame = await socket.receive()
    if frame["type"] == "websocket.disconnect":
        raise WebSocketDisconnect(code=frame.get("code", 1000))
    return _parse_message(frame.get("text"))


async def _send_error(socket: WebSocket, code: str, message: str) -> None:
    await socket.send_json({"type": "error", "code": code, "message": message})


async def _lobby_socket(
    socket: WebSocket,
    token: str,
    sessions: SessionStore,
    connections: ConnectionRegistry,
) -> None:
    try:
        seat, _ = await run_in_threadpool(sessions.seat_for_token, token)
    except SessionError:
        await _send_error(socket, "UNAUTHORIZED", "Invalid session token")
        await socket.close(code=1008)
        return

    previous = await connections.attach(seat, socket)
    try:
        if previous is not None:
            try:
                await previous.websocket.close(code=4000)
            except (RuntimeError, OSError, WebSocketDisconnect):
                pass
        await connections.broadcast_lobby(sessions.table_ready())

        while True:
            message = await _receive_message(socket)
            if message == {"type": "ping"}:
                await socket.send_json({"type": "pong"})
            elif message is None:
                await _send_error(socket, "INVALID_MESSAGE", "Invalid message")
            else:
                await _send_error(socket, "NOT_READY", "Gameplay is not available yet")
    finally:
        if await connections.detach_if_current(seat, socket):
            await connections.broadcast_lobby(sessions.table_ready())


def create_app(
    rooms: RoomManager | None = None, *, lobby_errors: bool = False
) -> FastAPI:
    app = FastAPI(title="Heads-Up Live Poker")
    manager = RoomManager() if rooms is None else rooms
    sessions = SessionStore(manager=manager)
    connections = ConnectionRegistry()

    @app.exception_handler(RequestValidationError)
    async def invalid_request(
        _request: Request, _error: RequestValidationError
    ) -> JSONResponse:
        # FastAPI's default validation response can echo submitted data.
        return JSONResponse({"detail": "invalid request body"}, status_code=422)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post(
        "/api/rooms",
        status_code=201,
        response_model=AdmissionResponse,
        responses={409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
    )
    def create_room(body: CreateRoomRequest, response: Response) -> Admission:
        try:
            admission = manager.create(body.bet_unit)
        except InvalidBetUnit as exc:
            raise HTTPException(422, "invalid request body") from exc
        except RoomAlreadyExists as exc:
            raise HTTPException(409, str(exc)) from exc
        response.headers["Cache-Control"] = "no-store"
        return admission

    @app.post(
        "/api/rooms/join",
        response_model=AdmissionResponse,
        responses={
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
        },
    )
    async def join_room(body: JoinRoomRequest, response: Response) -> Admission:
        try:
            admission = await run_in_threadpool(manager.join, body.room_code)
        except RoomNotFound as exc:
            raise HTTPException(404, str(exc)) from exc
        except RoomFull as exc:
            raise HTTPException(409, str(exc)) from exc
        response.headers["Cache-Control"] = "no-store"
        await connections.broadcast_lobby(table_ready=True)
        return admission

    @app.post("/api/table", status_code=201)
    def create_table(response: Response) -> dict[str, str]:
        try:
            room_code, token = sessions.create()
        except SessionError as exc:
            raise HTTPException(
                409, {"code": exc.code, "message": exc.message}
            ) from exc
        response.headers["Cache-Control"] = "no-store"
        return {"room_code": room_code, "seat": "A", "session_token": token}

    @app.post("/api/join", status_code=201)
    async def join_table(body: LobbyJoinRequest, response: Response) -> dict[str, str]:
        try:
            token = await run_in_threadpool(sessions.join, body.room_code)
        except SessionError as exc:
            status = 409 if exc.code == "TABLE_FULL" else 404
            raise HTTPException(
                status, {"code": exc.code, "message": exc.message}
            ) from exc
        response.headers["Cache-Control"] = "no-store"
        await connections.broadcast_lobby(table_ready=True)
        return {"seat": "B", "session_token": token}

    @app.get("/api/session")
    def current_session(
        response: Response, authorization: str | None = Header(default=None)
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
                401, {"code": exc.code, "message": exc.message}
            ) from exc
        response.headers["Cache-Control"] = "no-store"
        return {"seat": seat, "table_ready": ready}

    @app.websocket("/ws")
    async def room_socket(socket: WebSocket) -> None:
        if not _allowed_origin(socket.headers.get("origin")):
            await socket.close(code=1008)
            return
        await socket.accept()
        try:
            message = await wait_for(_receive_message(socket), timeout=5)
            kind = message.get("type") if message is not None else None
            if kind == "authenticate":
                try:
                    authenticate = AuthenticateMessage.model_validate(message)
                except ValidationError:
                    await socket.close(code=1008)
                    return
                room = await run_in_threadpool(
                    manager.authenticate, authenticate.session_token
                )
                if room is None:
                    await socket.close(code=1008)
                    return
                await socket.send_json(
                    {
                        "type": "room_status",
                        "seat": room.seat,
                        "bet_unit": room.bet_unit,
                        "status": room.status,
                    }
                )
                await _receive_message(socket)
                await socket.close(code=1008)
            elif (
                kind == "auth"
                and set(message) == {"type", "token"}
                and isinstance(message["token"], str)
            ):
                await _lobby_socket(socket, message["token"], sessions, connections)
            else:
                if kind == "auth" or lobby_errors:
                    await _send_error(socket, "INVALID_MESSAGE", "Authenticate first")
                await socket.close(code=1008)
        except TimeoutError:
            await socket.close(code=1008)
        except WebSocketDisconnect:
            pass

    return app
