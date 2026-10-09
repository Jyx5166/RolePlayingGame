from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


PROTOCOL_VERSION = "1.0"


class ProtocolError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.request_id = request_id


class CommandEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol_version: Literal["1.0"]
    kind: Literal["command"]
    type: str = Field(min_length=1, max_length=64)
    request_id: str = Field(min_length=8, max_length=128)
    game_id: int = Field(gt=0)
    payload: dict[str, Any]


class EmptyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=4_000)


class TargetRolePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_role_id: str = Field(min_length=1, max_length=128)


class SearchPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_id: str = Field(min_length=1, max_length=128)


class ShareCluePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clue_id: str = Field(min_length=1, max_length=128)
    mode: Literal["truthful", "distorted"]
    content: str = Field(default="", max_length=4_000)
    scope: Literal["public", "private"]
    target_role_id: str | None = Field(default=None, max_length=128)


PAYLOAD_MODELS: dict[str, type[BaseModel]] = {
    "advance_phase": EmptyPayload,
    "ask_hint": EmptyPayload,
    "player_speech": ContentPayload,
    "request_advance": EmptyPayload,
    "request_phase_end": EmptyPayload,
    "search": SearchPayload,
    "share_clue": ShareCluePayload,
    "stage_vote": TargetRolePayload,
    "whisper_close": EmptyPayload,
    "whisper_invite": TargetRolePayload,
    "whisper_speech": ContentPayload,
}


def parse_command(message: Any, expected_game_id: int) -> tuple[CommandEnvelope, dict[str, Any]]:
    request_id = message.get("request_id") if isinstance(message, dict) else None
    try:
        envelope = CommandEnvelope.model_validate(message)
    except ValidationError as exc:
        raise ProtocolError(
            "WS_COMMAND_INVALID",
            _validation_message(exc),
            str(request_id) if request_id else None,
        ) from exc
    if envelope.game_id != expected_game_id:
        raise ProtocolError(
            "WS_GAME_MISMATCH",
            "命令中的 game_id 与当前连接不一致",
            envelope.request_id,
        )
    payload_model = PAYLOAD_MODELS.get(envelope.type)
    if payload_model is None:
        raise ProtocolError(
            "WS_COMMAND_FORBIDDEN",
            "不支持的客户端命令",
            envelope.request_id,
        )
    try:
        payload = payload_model.model_validate(envelope.payload).model_dump()
    except ValidationError as exc:
        raise ProtocolError(
            "WS_COMMAND_INVALID",
            _validation_message(exc),
            envelope.request_id,
        ) from exc
    return envelope, {"type": envelope.type, **payload}


def event_envelope(
    game_id: int,
    event: dict[str, Any],
) -> dict[str, Any]:
    payload = dict(event["payload"])
    return {
        "protocol_version": PROTOCOL_VERSION,
        "kind": "error" if event["type"] == "error" else "event",
        "type": event["type"],
        "event_id": event["event_id"],
        "request_id": event["request_id"],
        "game_id": game_id,
        "server_time": event["created_at"],
        "payload": payload,
    }


def error_envelope(
    game_id: int,
    code: str,
    message: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "kind": "error",
        "type": "error",
        "event_id": None,
        "request_id": request_id,
        "game_id": game_id,
        "server_time": datetime.now(timezone.utc).isoformat(),
        "payload": {
            "type": "error",
            "code": code,
            "message": message,
        },
    }


def snapshot_envelope(
    game_id: int,
    event_id: int,
    game: dict[str, Any],
    phase_messages: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "kind": "snapshot",
        "type": "game.snapshot",
        "event_id": event_id,
        "request_id": None,
        "game_id": game_id,
        "server_time": datetime.now(timezone.utc).isoformat(),
        "payload": {
            "game": game,
            "phase_messages": phase_messages,
        },
    }


def resume_envelope(
    game_id: int,
    event_id: int,
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "kind": "resume",
        "type": "game.resume",
        "event_id": event_id,
        "request_id": None,
        "game_id": game_id,
        "server_time": datetime.now(timezone.utc).isoformat(),
        "payload": {
            "events": [event_envelope(game_id, event) for event in events],
        },
    }


def _validation_message(exc: ValidationError) -> str:
    first_error = exc.errors()[0]
    location = ".".join(str(part) for part in first_error.get("loc", ()))
    message = first_error.get("msg", "消息格式无效")
    return f"{location}: {message}" if location else str(message)
