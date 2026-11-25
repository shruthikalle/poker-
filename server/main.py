"""HTTP admission endpoints for the first multiplayer milestone."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from .sessions import SessionError, SessionStore


class JoinRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    room_code: str = Field(min_length=1, max_length=64)


def create_app(
    code_factory: Callable[[], str] | None = None,
    token_factory: Callable[[], str] | None = None,
) -> FastAPI:
    """Create an isolated app and session store, with injectable test generators."""

    app = FastAPI(title="Heads-Up Live Poker")
    sessions = SessionStore(code_factory, token_factory)

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
    def join_table(request: JoinRequest) -> dict[str, str]:
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

    return app


app = create_app()
