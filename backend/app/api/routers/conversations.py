"""Conversation history: list past chats, open one with its messages, rename it, delete it.

Chats are created and continued through /chat and /chat/stream; these routes only read and manage them.
"""

import json
from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from app.db import database

router = APIRouter(prefix="/conversations")


class ConversationSummary(BaseModel):
    id: str
    title: str | None
    started_at: str
    updated_at: str = Field(description="Time of the newest message; the list is sorted by this, newest first.")
    message_count: int


class StoredMessage(BaseModel):
    id: int
    role: Literal["user", "assistant", "tool"]
    content: str
    sources: list[str]
    status: Literal["streaming", "complete", "incomplete"] = Field(
        description="streaming: the reply is still being written. incomplete: it was cut off by an error, Stop or a crash."
    )
    created_at: str


class ConversationDetail(ConversationSummary):
    messages: list[StoredMessage]


class RenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


def _summary_or_404(conversation_id):
    conversation = database.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@router.get("", response_model=list[ConversationSummary])
def list_conversations():
    return database.list_conversations()


@router.get("/{conversation_id}", response_model=ConversationDetail)
def open_conversation(conversation_id: str):
    conversation = _summary_or_404(conversation_id)
    messages = database.get_messages(conversation_id)
    for message in messages:
        message["sources"] = json.loads(message["sources"]) if message["sources"] else []
    return {**conversation, "messages": messages}


@router.patch("/{conversation_id}", response_model=ConversationSummary)
def rename_conversation(conversation_id: str, req: RenameRequest):
    if not database.rename_conversation(conversation_id, req.title.strip()):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return _summary_or_404(conversation_id)


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str):
    if not database.delete_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return Response(status_code=204)
