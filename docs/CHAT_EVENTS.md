# Chat event contract (v1.0.0)

The `/chat/stream` WebSocket streams one answer per connection. This file and the schemas in
`/openapi.json` (`components.schemas`, plus `x-websockets` for the endpoint) are the whole contract.
The models live in [backend/app/chat_events.py](../backend/app/chat_events.py).

## Connecting

- URL: `ws://127.0.0.1:8000/chat/stream`
- Header: `Authorization: Bearer <token>` (from `.auth_token`)
- Subprotocol: `locali.chat.v1`. The server closes with code `1008` if the client asks only for
  versions it doesn't support. A client that sends no subprotocol gets v1.

## Request

After connecting, send one JSON message:

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `message` | string | yes | The user's question. |
| `conversation_id` | string \| null | no | From the previous `done` event. Omit it to start a new conversation. |
| `use_docs` | boolean \| null | no | Search indexed documents. Defaults to true, except for greetings. |
| `project` | string \| null | no | Limit document search to one project. |

## Events

Every message from the server is a JSON object with a `type` field.

| `type` | Fields | When |
| --- | --- | --- |
| `token` | `text` | A piece of the answer. Append it to the text so far. |
| `sources` | `sources`: string[] | Once, just before `done`. May be empty. |
| `done` | `conversation_id`: string \| null | The answer is complete. Send this ID with the next message. |
| `error` | `text` | The request failed. No `done` follows. |
| `activity` | `text`, `tool`: string \| null | *Not sent yet.* What the assistant is doing. |
| `approval_needed` | `id`, `tool`, `arguments`: object, `summary` | *Not sent yet.* A file action waits for approval. |
| `action_result` | `id`: string \| null, `tool`, `success`: boolean, `text` | *Not sent yet.* Outcome of a file action. |

**Order:** zero or more `token` events, then `sources`, then `done`. An `error` can arrive at any
point and ends the stream. The server closes the socket after `done` or `error`.

Example:

```json
{"type": "token", "text": "The project "}
{"type": "token", "text": "codename is Falcon."}
{"type": "sources", "sources": ["D:/notes/plan.md"]}
{"type": "done", "conversation_id": "726ac2b7-9fee-48b4-8fdc-3700a042ccbe"}
```

## Versioning rules

The contract has a semantic version (`CHAT_EVENTS_VERSION`, also in `x-websockets.version`).
Only the major number is part of the subprotocol.

- **Minor** (`1.1.0`): adding a new event type, or an optional field to an event. Same subprotocol.
  Clients must ignore event types and fields they don't know.
- **Major** (`2.0.0`, subprotocol `locali.chat.v2`): renaming or removing an event or field,
  changing a field's type or meaning, or changing the event order.
- **Patch** (`1.0.1`): wording fixes in this document or the schema descriptions.
- Events marked *Not sent yet* may still change before the server first sends them.
