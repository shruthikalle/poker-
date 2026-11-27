"""HTTP and WebSocket transport for the poker application."""

import json
import re
from asyncio import wait_for
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from anyio import create_task_group
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
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from server.clock import Clock
from server.commands import COMMAND_SCHEMA
from server.connections import Connection
from server.coordinator import GameCoordinator
from server.timers import DISCONNECT_GRACE, TURN_DURATION
from server.sessions import SessionError, SessionStore

from .engine import Player
from .rooms import (
    Admission,
    AdmissionConflict,
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


def _admission_key(request: Request) -> str | None:
    keys = request.headers.getlist("admission-key")
    if not keys:
        return None
    if len(keys) != 1 or re.fullmatch(r"[0-9a-f]{64}", keys[0]) is None:
        raise HTTPException(422, "invalid admission key")
    return keys[0]


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
    socket: WebSocket, token: str, coordinator: GameCoordinator, gameplay: bool
) -> None:
    connection = Connection(socket, gameplay)
    seat = coordinator.attach(token, connection)
    if seat is None:
        await _send_error(socket, "UNAUTHORIZED", "Invalid session token")
        await socket.close(code=1008)
        return

    async def read_commands() -> None:
        while True:
            message = await _receive_message(socket)
            if message == {"type": "ping"}:
                coordinator.reply(seat, connection, {"type": "pong"})
            elif gameplay and message == {"type": "snapshot_request"}:
                coordinator.snapshot(seat, connection)
            elif gameplay:
                try:
                    command = COMMAND_SCHEMA.validate_python(message)
                except ValidationError:
                    coordinator.reply(
                        seat, connection, {"type": "error", "code": "INVALID_MESSAGE"}
                    )
                else:
                    coordinator.submit(seat, connection, command)
            elif message is None:
                coordinator.reply(
                    seat,
                    connection,
                    {
                        "type": "error",
                        "code": "INVALID_MESSAGE",
                        "message": "Invalid message",
                    },
                )
            else:
                coordinator.reply(
                    seat,
                    connection,
                    {
                        "type": "error",
                        "code": "NOT_READY",
                        "message": "Gameplay is not available yet",
                    },
                )

    try:
        await connection.run(read_commands)
    finally:
        coordinator.detach(seat, connection)
        await connection.finish_close()


def create_app(
    rooms: RoomManager | None = None,
    *,
    lobby_errors: bool = False,
    clock: Clock | None = None,
    turn_duration: int = TURN_DURATION,
    grace_duration: int = DISCONNECT_GRACE,
) -> FastAPI:
    manager = RoomManager() if rooms is None else rooms
    sessions = SessionStore(manager=manager)
    coordinator = GameCoordinator(
        manager,
        clock=clock,
        turn_duration=turn_duration,
        grace_duration=grace_duration,
    )

    @asynccontextmanager
    async def lifespan(_app):
        async with create_task_group() as tasks:
            tasks.start_soon(coordinator.run_scheduler)
            try:
                yield
            finally:
                tasks.cancel_scope.cancel()

    app = FastAPI(title="Heads-Up Live Poker", lifespan=lifespan)

    static = Path(__file__).resolve().parent.parent / "server" / "static"
    app.mount("/assets", StaticFiles(directory=static), name="browser-assets")

    @app.get("/", include_in_schema=False)
    def browser_app() -> FileResponse:
        return FileResponse(
            static / "index.html",
            headers={
                "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; "
                "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
            },
        )

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
    def create_room(
        body: CreateRoomRequest, request: Request, response: Response
    ) -> Admission:
        try:
            admission = manager.admit_once(
                _admission_key(request),
                ("create", body.bet_unit),
                lambda: manager.create(body.bet_unit),
            )
        except InvalidBetUnit as exc:
            raise HTTPException(422, "invalid request body") from exc
        except RoomAlreadyExists as exc:
            raise HTTPException(409, str(exc)) from exc
        except AdmissionConflict as exc:
            raise HTTPException(409, "admission key conflict") from exc
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
    async def join_room(
        body: JoinRoomRequest, request: Request, response: Response
    ) -> Admission:
        try:
            admission = manager.admit_once(
                _admission_key(request),
                ("join", body.room_code),
                lambda: coordinator.admit(manager.join, body.room_code),
            )
        except RoomNotFound as exc:
            raise HTTPException(404, str(exc)) from exc
        except RoomFull as exc:
            raise HTTPException(409, str(exc)) from exc
        except AdmissionConflict as exc:
            raise HTTPException(409, "admission key conflict") from exc
        response.headers["Cache-Control"] = "no-store"
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
            token = coordinator.admit(sessions.join, body.room_code)
        except SessionError as exc:
            status = 409 if exc.code == "TABLE_FULL" else 404
            raise HTTPException(
                status, {"code": exc.code, "message": exc.message}
            ) from exc
        response.headers["Cache-Control"] = "no-store"
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
                and (
                    set(message) == {"type", "token"}
                    or (
                        set(message) == {"type", "token", "protocol"}
                        and message["protocol"] == "gameplay.v1"
                    )
                )
                and isinstance(message["token"], str)
            ):
                await _lobby_socket(
                    socket, message["token"], coordinator, "protocol" in message
                )
            else:
                if kind == "auth" or lobby_errors:
                    await _send_error(socket, "INVALID_MESSAGE", "Authenticate first")
                await socket.close(code=1008)
        except TimeoutError:
            await socket.close(code=1008)
        except WebSocketDisconnect:
            pass

    return app
