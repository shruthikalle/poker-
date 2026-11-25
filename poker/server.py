"""HTTP and WebSocket transport for the poker application."""

from asyncio import wait_for
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

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


def create_app(rooms: RoomManager | None = None) -> FastAPI:
    app = FastAPI(title="Heads-Up Live Poker")
    manager = RoomManager() if rooms is None else rooms

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
    def join_room(body: JoinRoomRequest, response: Response) -> Admission:
        try:
            admission = manager.join(body.room_code)
        except RoomNotFound as exc:
            raise HTTPException(404, str(exc)) from exc
        except RoomFull as exc:
            raise HTTPException(409, str(exc)) from exc
        response.headers["Cache-Control"] = "no-store"
        return admission

    @app.websocket("/ws")
    async def room_socket(socket: WebSocket) -> None:
        await socket.accept()
        try:
            message = await wait_for(socket.receive(), timeout=5)
            if message["type"] == "websocket.disconnect":
                return
            text = message.get("text")
            if text is None:
                await socket.close(code=1008)
                return
            authenticate = AuthenticateMessage.model_validate_json(text)
        except (TimeoutError, ValidationError):
            await socket.close(code=1008)
            return

        room = await run_in_threadpool(manager.authenticate, authenticate.session_token)
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
        message = await socket.receive()
        if message["type"] != "websocket.disconnect":
            await socket.close(code=1008)

    return app
