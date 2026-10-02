"""Chat event contract for the /chat/stream WebSocket. docs/CHAT_EVENTS.md documents it.

The server only sends events built from these models, and the OpenAPI document publishes their
JSON schemas, so clients can be generated from either.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

# Semantic version of the contract. Only the major number is in the subprotocol, because minor
# versions only add things that older clients can ignore.
CHAT_EVENTS_VERSION = "1.0.0"
CHAT_SUBPROTOCOL = f"locali.chat.v{CHAT_EVENTS_VERSION.split('.')[0]}"


class ChatStreamRequest(BaseModel):
    """The one message the client sends after connecting."""

    message: str
    conversation_id: str | None = None
    use_docs: bool | None = Field(None, description="Defaults to true, except for greetings.")
    project: str | None = None


class _Event(BaseModel):
    # Marks `type` as required in the published schema even though the models fill it in.
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class TokenEvent(_Event):
    """The next piece of the answer text. Append it to the text received so far."""

    type: Literal["token"] = "token"
    text: str


class ActivityEvent(_Event):
    """Not sent yet. What the assistant is doing, for example running a tool."""

    type: Literal["activity"] = "activity"
    text: str
    tool: str | None = None


class SourcesEvent(_Event):
    """The documents the answer was based on. Sent once, just before done; may be empty."""

    type: Literal["sources"] = "sources"
    sources: list[str]


class ApprovalNeededEvent(_Event):
    """Not sent yet. A file action is waiting for the user's approval."""

    type: Literal["approval_needed"] = "approval_needed"
    id: str
    tool: str
    arguments: dict[str, Any]
    summary: str


class ActionResultEvent(_Event):
    """Not sent yet. The outcome of a file action."""

    type: Literal["action_result"] = "action_result"
    id: str | None = None
    tool: str
    success: bool
    text: str


class ErrorEvent(_Event):
    """The request failed. No done event follows, and the server closes the socket."""

    type: Literal["error"] = "error"
    text: str


class DoneEvent(_Event):
    """The answer is complete. Send conversation_id with the next message to continue the chat."""

    type: Literal["done"] = "done"
    conversation_id: str | None


ChatEvent = Annotated[
    TokenEvent | ActivityEvent | SourcesEvent | ApprovalNeededEvent | ActionResultEvent | ErrorEvent | DoneEvent,
    Field(discriminator="type"),
]
chat_event_adapter = TypeAdapter(ChatEvent)


def openapi_schemas():
    """JSON schemas for the request and every event, keyed by name, for components.schemas."""
    ref_template = "#/components/schemas/{model}"
    event_schema = chat_event_adapter.json_schema(ref_template=ref_template, mode="serialization")
    schemas = event_schema.pop("$defs")
    schemas["ChatEvent"] = event_schema
    schemas["ChatStreamRequest"] = ChatStreamRequest.model_json_schema(ref_template=ref_template)
    return schemas
