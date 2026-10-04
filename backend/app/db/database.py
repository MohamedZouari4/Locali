"""SQLite persistence (assistant.db): conversations, their messages, an audit_log table that
mirrors file-tool actions, and the background job queue run by app/jobs/worker.py.
"""

import contextlib
import json
import sqlite3
import uuid

from app.core.config import DB_PATH

_initialized = False


def get_connection():
    global _initialized
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    if not _initialized:
        init_schema(conn)
        _initialized = True
    return conn


def init_schema(conn):
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            title TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user','assistant','tool')),
            content TEXT NOT NULL,
            sources TEXT,
            status TEXT NOT NULL DEFAULT 'complete' CHECK(status IN ('streaming','complete','incomplete')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        )
    """)

    # Databases created before the status column existed get it added; their messages count as complete.
    columns = {row[1] for row in cur.execute("PRAGMA table_info(messages)")}
    if "status" not in columns:
        cur.execute(
            "ALTER TABLE messages ADD COLUMN status TEXT NOT NULL DEFAULT 'complete' CHECK(status IN ('streaming','complete','incomplete'))"
        )

    cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            target_path TEXT,
            result TEXT,
            success BOOLEAN NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id)")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            project TEXT NOT NULL DEFAULT 'default',
            state TEXT NOT NULL DEFAULT 'queued' CHECK(state IN ('queued','running','done','failed','cancelled')),
            params TEXT,
            result TEXT,
            error TEXT,
            progress_current INTEGER,
            progress_total INTEGER,
            progress_message TEXT,
            cancel_requested INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            started_at TIMESTAMP,
            finished_at TIMESTAMP
        )
    """)
    # SQLite itself refuse a second running job in the same project, whatever the code does.
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_running_job_per_project ON jobs(project) WHERE state = 'running'")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state, created_at)")

    cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at)")

    # A reply still marked streaming when the server starts was cut off by a crash or shutdown.
    cur.execute("UPDATE messages SET status = 'incomplete' WHERE status = 'streaming'")

    conn.commit()
    print(f"Database initialized at {DB_PATH}")


def init_db():
    """Initialize the database schema if it doesn't exist."""
    conn = get_connection()
    conn.close()
    print(f"Database initialized at {DB_PATH}")


@contextlib.contextmanager
def _transaction():
    # Commits every write inside the block together, or none of them if the block raises.
    conn = get_connection()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def begin_turn(conversation_id, user_text):
    """Stores the user message and an empty assistant reply marked streaming, in one transaction.

    Starts a new conversation, titled after the message, when `conversation_id` is missing or
    unknown. Returns (conversation_id, assistant_message_id).
    """
    with _transaction() as conn:
        known = conversation_id and conn.execute("SELECT 1 FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
        if not known:
            conversation_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO conversations (id, title) VALUES (?, ?)",
                (conversation_id, user_text.strip()[:60] or None),
            )
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES (?, 'user', ?)",
            (conversation_id, user_text),
        )
        reply = conn.execute(
            "INSERT INTO messages (conversation_id, role, content, status) VALUES (?, 'assistant', '', 'streaming')",
            (conversation_id,),
        )
        return conversation_id, reply.lastrowid


def finish_turn(message_id, content, sources=None, complete=True):
    """Stores the assistant reply from begin_turn as complete or incomplete.

    A reply already stored as complete is never changed, so calling this again from a cleanup path
    with complete=False is safe.
    """
    with _transaction() as conn:
        conn.execute(
            "UPDATE messages SET content = ?, sources = ?, status = ? WHERE id = ? AND status != 'complete'",
            (content, json.dumps(sources) if sources else None, "complete" if complete else "incomplete", message_id),
        )


def get_messages(conversation_id):
    conn = get_connection()
    cur = conn.execute(
        "SELECT id, role, content, sources, status, created_at FROM messages WHERE conversation_id = ? ORDER BY id",
        (conversation_id,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in cur]


# Most recently active first: by the newest message, or the start time for an empty conversation.
_CONVERSATION_SUMMARY = """
    SELECT c.id, c.title, c.started_at,
           COALESCE(MAX(m.created_at), c.started_at) AS updated_at,
           COUNT(m.id) AS message_count
    FROM conversations c LEFT JOIN messages m ON m.conversation_id = c.id
"""


def list_conversations():
    conn = get_connection()
    cur = conn.execute(_CONVERSATION_SUMMARY + " GROUP BY c.id ORDER BY updated_at DESC, MAX(m.id) DESC").fetchall()
    conn.close()
    return [dict(row) for row in cur]


def get_conversation(conversation_id):
    """Returns the conversation's summary, or None if it doesn't exist."""
    conn = get_connection()
    row = conn.execute(_CONVERSATION_SUMMARY + " WHERE c.id = ? GROUP BY c.id", (conversation_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def rename_conversation(conversation_id, title):
    """Returns False if the conversation doesn't exist."""
    with _transaction() as conn:
        return conn.execute("UPDATE conversations SET title = ? WHERE id = ?", (title, conversation_id)).rowcount > 0


def delete_conversation(conversation_id):
    """Deletes the conversation and everything stored for it. Returns False if it doesn't exist.

    Any new table that stores per-conversation state must be cleared here too.
    """
    with _transaction() as conn:
        conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
        return conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,)).rowcount > 0


def _job_from_row(row):
    job = dict(row)
    job["params"] = json.loads(job["params"]) if job["params"] else {}
    job["result"] = json.loads(job["result"]) if job["result"] else None
    job["cancel_requested"] = bool(job["cancel_requested"])
    return job


def enqueue_job(kind, params=None, project="default"):
    """Adds a queued job to the database and returns its ID."""
    job_id = str(uuid.uuid4())
    with _transaction() as conn:
        conn.execute(
            "INSERT INTO jobs (id, kind, project, params) VALUES (?, ?, ?, ?)",
            (job_id, kind, project, json.dumps(params or {})),
        )
    return job_id


def claim_next_job():
    """Marks the oldest queued job whose project has nothing running as running, and returns it.

    Returns None when no job can start. Claiming is a single statement, so two workers can never
    take the same job, and the one_running_job_per_project index refuses a second running job anyway.
    """
    with _transaction() as conn:
        rows = conn.execute("""
            UPDATE jobs SET state = 'running', started_at = CURRENT_TIMESTAMP
            WHERE id = (
                SELECT id FROM jobs
                WHERE state = 'queued' AND project NOT IN (SELECT project FROM jobs WHERE state = 'running')
                ORDER BY created_at, rowid
                LIMIT 1
            )
            RETURNING *
        """).fetchall()
    return _job_from_row(rows[0]) if rows else None


def update_job_progress(job_id, current, total=None, message=None):
    with _transaction() as conn:
        conn.execute(
            "UPDATE jobs SET progress_current = ?, progress_total = ?, progress_message = ? WHERE id = ? AND state = 'running'",
            (current, total, message, job_id),
        )


def finish_job(job_id, state, result=None, error=None):
    """Moves a running job to done, failed or cancelled. Returns False if it wasn't running."""
    if state not in ("done", "failed", "cancelled"):
        raise ValueError(f"A job can't finish as {state!r}")
    with _transaction() as conn:
        return (
            conn.execute(
                "UPDATE jobs SET state = ?, result = ?, error = ?, finished_at = CURRENT_TIMESTAMP WHERE id = ? AND state = 'running'",
                (state, json.dumps(result) if result is not None else None, error, job_id),
            ).rowcount
            > 0
        )


def cancel_job(job_id):
    """Cancels a queued job at once, or asks a running job to stop at its next check.

    Returns the job's state afterwards, or None if there is no such job.
    """
    with _transaction() as conn:
        conn.execute("UPDATE jobs SET state = 'cancelled', finished_at = CURRENT_TIMESTAMP WHERE id = ? AND state = 'queued'", (job_id,))
        conn.execute("UPDATE jobs SET cancel_requested = 1 WHERE id = ? AND state = 'running'", (job_id,))
        row = conn.execute("SELECT state FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return row["state"] if row else None


def is_cancel_requested(job_id):
    conn = get_connection()
    row = conn.execute("SELECT cancel_requested FROM jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    return bool(row and row["cancel_requested"])


def get_job(job_id):
    """Returns the job, or None if it doesn't exist."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    return _job_from_row(row) if row else None


def recover_interrupted_jobs():
    """Marks jobs left running by a crash or shutdown as failed, and returns how many there were.

    Call it only from the process that runs the worker, before the worker starts. Another process
    (such as the CLI) calling it would fail jobs that are really still running.
    """
    with _transaction() as conn:
        return conn.execute(
            "UPDATE jobs SET state = 'failed', error = 'Interrupted by a restart', finished_at = CURRENT_TIMESTAMP WHERE state = 'running'"
        ).rowcount


if __name__ == "__main__":
    init_db()
