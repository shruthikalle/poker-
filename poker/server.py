"""HTTP and WebSocket transport for the poker application."""

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

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

    return app
