"""Checks that /chat/stream only sends events from the documented contract (docs/CHAT_EVENTS.md)."""

import json
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.ai.chat import orchestrator
from app.api.main import app
from app.chat_events import CHAT_SUBPROTOCOL, chat_event_adapter
from app.core.security import API_TOKEN
from app.db import database


def _headers():
    # A fresh dict per connection: websocket_connect writes the subprotocol into the dict it gets.
    return {"authorization": f"Bearer {API_TOKEN}"}


def _ollama_reply(*texts):
    lines = [json.dumps({"message": {"content": text}, "done": False}).encode() for text in texts]
    lines.append(json.dumps({"message": {"content": ""}, "done": True}).encode())
    reply = MagicMock()
    reply.__enter__.return_value = reply
    reply.iter_lines.return_value = lines
    return reply


class ChatEventContractTests(unittest.TestCase):
    def test_ask_stream_sends_tokens_then_sources(self):
        with patch.object(orchestrator.requests, "post", return_value=_ollama_reply("hi ", "there")):
            events = [event.model_dump() for event in orchestrator.ask_stream("hello")]

        self.assertEqual([event["type"] for event in events], ["token", "token", "sources"])

    def test_websocket_only_sends_documented_events(self):
        with (
            patch.object(orchestrator.requests, "post", return_value=_ollama_reply("ok")),
            patch.object(database, "begin_turn", return_value=("conv-1", 1)),
            patch.object(database, "finish_turn"),
        ):
            client = TestClient(app)
            with client.websocket_connect("/chat/stream", headers=_headers(), subprotocols=[CHAT_SUBPROTOCOL]) as ws:
                self.assertEqual(ws.accepted_subprotocol, CHAT_SUBPROTOCOL)
                ws.send_json({"message": "hello", "use_docs": False})
                events = [ws.receive_json()]
                while events[-1]["type"] not in ("done", "error"):
                    events.append(ws.receive_json())

        for event in events:
            chat_event_adapter.validate_python(event)
        self.assertEqual(events[-1], {"type": "done", "conversation_id": "conv-1"})

    def test_unsupported_version_is_rejected(self):
        client = TestClient(app)
        with self.assertRaises(WebSocketDisconnect) as ctx:
            with client.websocket_connect("/chat/stream", headers=_headers(), subprotocols=["locali.chat.v99"]):
                pass
        self.assertEqual(ctx.exception.code, 1008)

    def test_openapi_publishes_every_event(self):
        spec = TestClient(app).get("/openapi.json").json()
        schemas = spec["components"]["schemas"]
        mapping = schemas["ChatEvent"]["discriminator"]["mapping"]

        self.assertEqual(
            set(mapping),
            {"token", "activity", "sources", "approval_needed", "action_result", "error", "done"},
        )
        self.assertIn("type", schemas["TokenEvent"]["required"])
        self.assertEqual(spec["x-websockets"]["/chat/stream"]["subprotocol"], CHAT_SUBPROTOCOL)


if __name__ == "__main__":
    unittest.main()
