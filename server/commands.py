"""Strict schemas for browser-issued gameplay commands."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

MAX_WIRE_INTEGER = 2**53 - 1


class CommandFields(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    action_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    hand_id: int = Field(ge=1, le=MAX_WIRE_INTEGER)
    expected_revision: int = Field(ge=0, le=MAX_WIRE_INTEGER)


class ActionCommand(CommandFields):
    type: Literal["action"]
    action: Literal["fold", "check", "call", "bet", "raise"]


class ReadyCommand(CommandFields):
    type: Literal["ready"]


Command = ActionCommand | ReadyCommand
COMMAND_SCHEMA = TypeAdapter(Annotated[Command, Field(discriminator="type")])
