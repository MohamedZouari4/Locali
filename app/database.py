import json
import sqlite3
import os
import uuid

DB_PATH = os.path.abspath('assistant.db')
_initialized = False

def get_connection():
    global _initialized
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA foreign_keys = ON;")
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        )
    """)

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
    cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at)")

    conn.commit()
    print(f"Database initialized at {DB_PATH}")

def init_db():
    """Initialize the database schema if it doesn't exist."""
    conn=get_connection()
    conn.close()
    print(f"Database initialized at {DB_PATH}")

def create_conversation(title=None):
    conn = get_connection()
    conv_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO conversations (id, title) VALUES (?, ?)",
        (conv_id, title)
    )
    conn.commit()
    conn.close()
    return conv_id

def save_conversation(conversation_id, role, messages, sources=None):
    conn = get_connection()
    sources_json = json.dumps(sources) if sources else None
    conn.execute(
        "INSERT INTO messages (conversation_id, role, content, sources) VALUES (?, ?, ?, ?)",
        (conversation_id, role, messages, sources_json)
    )
    conn.commit()
    conn.close()

def get_messages (conversation_id):
    conn = get_connection()
    cur = conn.execute(
        "SELECT role, content, sources, created_at FROM messages WHERE conversation_id = ? ORDER BY id",
        (conversation_id,)
    ).fetchall()
    conn.close()
    return [dict(row) for row in cur]

def list_conversations():
    conn = get_connection()
    cur = conn.execute(
        "SELECT id, title, started_at FROM conversations ORDER BY started_at DESC"
    ).fetchall()
    conn.close()
    return [dict(row) for row in cur]

if __name__ == "__main__":
    init_db()
