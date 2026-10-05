# Job event contract (v1)

The `/jobs/events` WebSocket pushes background job changes for as long as the client stays connected.
This file and the schemas in `/openapi.json` (`components.schemas.JobEvent`, plus `x-websockets`)
are the whole contract. The models live in [backend/app/job_events.py](../backend/app/job_events.py).

## Connecting

- URL: `ws://127.0.0.1:8000/jobs/events`
- Header: `Authorization: Bearer <token>` (from `.auth_token`)
- Subprotocol: `locali.jobs.v1`. The server closes with code `1008` if the client asks only for
  versions it doesn't support. A client that sends no subprotocol gets v1.
- The client sends nothing. Start and cancel jobs with the `/jobs` routes.

## Events

| `type` | Fields | When |
| --- | --- | --- |
| `job` | `job`: the same object `GET /jobs/{id}` returns | A job was queued, made progress, or finished. On connect, one event per active job. |

`job.state` is `queued`, `running`, `done`, `failed` or `cancelled`. While running, `progress_current`,
`progress_total` and `progress_message` show progress (`progress_total` is null when unknown).
`cancel_requested` is true between a cancel request and the job stopping. After a job's final event
(`done`, `failed` or `cancelled`) no more events are sent for it.

Progress is saved at most once a second and the socket checks for changes every half second, so a
progress bar updates about once a second. Events may be missed while disconnected: after reconnecting,
reload `GET /jobs?state=queued&state=running`.

## Versioning rules

The same as [CHAT_EVENTS.md](CHAT_EVENTS.md): major for breaking changes, minor for additions that
clients can ignore, patch for wording. Clients must ignore event types and fields they don't know.
