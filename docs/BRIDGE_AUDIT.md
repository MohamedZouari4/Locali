# Desktop bridge audit

Ticket P0-E4-T1, 3 October 2026. Every method the desktop exposes to the React app
(`window.localiAPI` in [desktop/electron/preload.cjs](../desktop/electron/preload.cjs)), traced
through [desktop/electron/main.cjs](../desktop/electron/main.cjs) to the backend route it calls in
[backend/app/api](../backend/app/api).

**Summary:** of 17 bridge methods, 12 are supported and 5 are partial. Five backend features have no
desktop method. Only 5 bridge methods are unused by the React app: `chat`, `search`, `ingest`,
`ingestStatus` and `files.list`.

Status key:

- **Supported**: the method passes everything the backend route accepts and handles its reply.
- **Partial**: the method works but can't use part of the route, or misreports something.
- **Missing**: the backend has the feature, but the desktop has no method for it.

## Bridge methods

| # | Bridge method | Backend route | Status | Used by the UI | Notes |
| --- | --- | --- | --- | --- | --- |
| 1 | `health()` | `GET /health`, plus Ollama's `GET :11434/api/tags` | Supported | Yes | Electron checks Ollama directly, not through the backend. |
| 2 | `chat(message, conversationId)` | `POST /chat` | Partial | No | Can't send `use_docs` or `project`. The backend defaults `use_docs` to false here but to true on `/chat/stream` (except greetings), so the two chat routes behave differently. |
| 3 | `conversations.list()` | `GET /conversations` | Supported | Yes | |
| 4 | `conversations.open(id)` | `GET /conversations/{id}` | Supported | Yes | |
| 5 | `conversations.rename(id, title)` | `PATCH /conversations/{id}` | Supported | Yes | |
| 6 | `conversations.remove(id)` | `DELETE /conversations/{id}` | Supported | Yes | |
| 7 | `search(query)` | `GET /search` | Partial | No | Can't send `k` or `project`. |
| 8 | `ingest(fullReset)` | `POST /ingest` | Supported | No | A `409` (already running) reaches the UI only as "API /ingest failed: 409" (see C1). |
| 9 | `ingestStatus()` | `GET /ingest/status` | Supported | No | The reply shape isn't documented (see C3). |
| 10 | `files.list(path)` | `GET /files` | Supported | No | Returns names only, with no file/folder type or size. |
| 11 | `files.reveal(relativePath)` | None (Electron only) | Partial | Yes (source chips) | Sources are absolute paths from anywhere in `SCAN_DRIVES`, but reveal only allows paths inside `AI-Workspace`, so any source outside it is refused. The parameter is named `relativePath` but receives absolute paths. |
| 12 | `chatStream.start(message, conversationId, useDocs)` | `WS /chat/stream` | Partial | Yes | Can't send `project`. |
| 13 | `chatStream.stop()` | None (closes the socket) | Supported | Yes | The backend treats a disconnect as a stop and saves the reply as incomplete. |
| 14 | `chatStream.onChunk` | `token` event | Supported | Yes | |
| 15 | `chatStream.onFinal` | `sources` and `done` events | Supported | Yes | Named `final` on the desktop and `done` in [CHAT_EVENTS.md](CHAT_EVENTS.md). |
| 16 | `chatStream.onDone` | None (socket `close`) | Supported | Yes | Confusing name: it means "socket closed", while the contract's `done` means "answer finished". |
| 17 | `chatStream.onError` | `error` event and socket errors | Partial | Yes | The `error` event has no `conversation_id`, so after a failed first message the app doesn't know the conversation the backend created. |

## Backend features with no desktop method

| Backend | Status | Notes |
| --- | --- | --- |
| `POST /files/move` | Missing | |
| `POST /files/organize` | Missing | |
| `activity` event | Missing | In the event contract; Electron drops it. The backend doesn't send it yet. |
| `approval_needed` event | Missing | Same. Needed before file-tool approvals. |
| `action_result` event | Missing | Same. |

## Problems across several methods

| # | Problem | Effect |
| --- | --- | --- |
| C1 | `apiFetch` in `main.cjs` throws `API /x failed: <status>` and drops the backend's `detail` message. | The UI can never show why a call failed (409, 404, 403, 422). |
| C2 | The workspace root is hard-coded in both `main.cjs` and `backend/app/core/config.py`. | If one changes, `files.reveal` silently refuses every path. |
| C3 | `/search`, `/ingest`, `/ingest/status` and `/files*` have no response models. | `/openapi.json` doesn't describe their replies, so clients can't be generated from it. |
| C4 | Electron reads the token from `userData/api-token` before the repo's `.auth_token`, which is the file the backend writes. | A stale `api-token` from an old install would make every call fail with 401. |
