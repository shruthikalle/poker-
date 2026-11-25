"""HTTP and WebSocket transport for the poker application."""

from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="Heads-Up Live Poker")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
