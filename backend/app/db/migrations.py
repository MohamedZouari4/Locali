"""Versioned schema migrations for assistant.db.

The schema version is SQLite's `PRAGMA user_version`: the number of migrations applied. Each migration
runs in one transaction together with its version bump, so a failing migration leaves the database
unchanged. To change the schema, append a function to MIGRATIONS; never edit or reorder a shipped one.

A migration runs one statement per `conn.execute()`. Never use `executescript()`: it commits the open
transaction first. SQLite's ALTER TABLE can only add or rename columns; any other change rebuilds the
table (create the new one, copy the rows, drop the old one, rename), and `PRAGMA foreign_keys` cannot be
switched inside a transaction.

A small runner instead of Alembic: Alembic is built on SQLAlchemy, which Locali doesn't use, and
user_version needs no extra dependency or tracking table.
"""

import sqlite3
import uuid


class DatabaseTooNewError(RuntimeError):
    """The database was migrated by a newer Locali than this one."""


def _001_initial(conn):
    # The schema as it was before migrations existed. IF NOT EXISTS makes this a no-op on those databases.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            title TEXT
        )
    """)

    conn.execute("""
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
    columns = {row[1] for row in conn.execute("PRAGMA table_info(messages)")}
    if "status" not in columns:
        conn.execute(
            "ALTER TABLE messages ADD COLUMN status TEXT NOT NULL DEFAULT 'complete' CHECK(status IN ('streaming','complete','incomplete'))"
        )

    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            target_path TEXT,
            result TEXT,
            success BOOLEAN NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id)")
    conn.execute("""
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
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_running_job_per_project ON jobs(project) WHERE state = 'running'")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state, created_at)")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS indexed_folders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL UNIQUE,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at)")


def _002_projects(conn):
    conn.execute("""
        CREATE TABLE projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE COLLATE NOCASE,
            instructions TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Read lets the assistant search a folder; Act also lets its tools change files there.
    conn.execute("""
        CREATE TABLE project_folders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            path TEXT NOT NULL,
            permission TEXT NOT NULL DEFAULT 'read' CHECK(permission IN ('read','act')),
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (project_id, path)
        )
    """)
    # NULL is a conversation outside any project; deleting a project keeps its conversations.
    conn.execute("ALTER TABLE conversations ADD COLUMN project_id TEXT REFERENCES projects(id) ON DELETE SET NULL")
    conn.execute("CREATE INDEX idx_conversations_project ON conversations(project_id)")


def _003_general_project(conn):
    # Every chat now belongs to a project, so chats from before projects move into one named General.
    # It is only created when such chats exist, and a project already named General (any case) is reused.
    if conn.execute("SELECT 1 FROM conversations WHERE project_id IS NULL").fetchone() is None:
        return
    conn.execute(
        "INSERT INTO projects (id, name) SELECT ?, 'General' WHERE NOT EXISTS (SELECT 1 FROM projects WHERE name = 'General')",
        (str(uuid.uuid4()),),
    )
    conn.execute("UPDATE conversations SET project_id = (SELECT id FROM projects WHERE name = 'General') WHERE project_id IS NULL")


def _004_catalog(conn):
    # One row per file in a project's folders. The id is the file's stable identity: a rescan finds the
    # row again by file_key (the OS file identifier, or "path:..." where there is none), so a renamed or
    # moved file keeps its id. content_hash is only kept for files without an OS identifier.
    conn.execute("""
        CREATE TABLE catalog_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            file_key TEXT NOT NULL,
            path TEXT NOT NULL,
            name TEXT NOT NULL,
            extension TEXT NOT NULL,
            size INTEGER NOT NULL,
            file_created_at TEXT,
            file_modified_at TEXT NOT NULL,
            content_hash TEXT,
            catalogued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (project_id, file_key)
        )
    """)
    conn.execute("CREATE INDEX idx_catalog_files_path ON catalog_files(project_id, path)")


def _005_project_ignore_rules(conn):
    # ignore_patterns: the project's own patterns on top of the default ignore lists, as a JSON list.
    # catalog_skipped: what the last catalog scan skipped, by reason, as a JSON object; NULL until one runs.
    conn.execute("ALTER TABLE projects ADD COLUMN ignore_patterns TEXT NOT NULL DEFAULT '[]'")
    conn.execute("ALTER TABLE projects ADD COLUMN catalog_skipped TEXT")

def _006_text_cache(conn):
    # Extracted text, stored once per file content: the key is the SHA-256 of the file's bytes, its
    # extension (which picks the reader) and the extractor version, so the same file in several projects
    # shares one entry and a changed file or reader gets a new one. The text is redacted before it is stored.
    conn.execute("""
        CREATE TABLE text_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content_hash TEXT NOT NULL,
            extension TEXT NOT NULL,
            extractor_version INTEGER NOT NULL,
            unit TEXT NOT NULL CHECK(unit IN ('page','section')),
            extracted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (content_hash, extension, extractor_version)
        )
    """)
    # One row per page of a PDF, or one section for other files, numbered from 1.
    conn.execute("""
        CREATE TABLE text_cache_parts (
            cache_id INTEGER NOT NULL REFERENCES text_cache(id) ON DELETE CASCADE,
            part INTEGER NOT NULL,
            text TEXT NOT NULL,
            PRIMARY KEY (cache_id, part)
        )
    """)
    # The content a catalog file's text was last read from, so cached text no file uses can be pruned.
    conn.execute("ALTER TABLE catalog_files ADD COLUMN text_hash TEXT")




MIGRATIONS = [_001_initial, _002_projects, _003_general_project, _004_catalog, _005_project_ignore_rules, _006_text_cache]


def schema_version(conn):
    return conn.execute("PRAGMA user_version").fetchone()[0]


def _backup(conn, path):
    dest = sqlite3.connect(path)
    try:
        conn.backup(dest)
    finally:
        dest.close()


def migrate(conn, migrations=MIGRATIONS, backup_path=None):
    """Applies pending migrations in order and returns the versions applied.

    With backup_path, an existing database is copied to `<backup_path>.v<N>.bak` before it is changed.
    Raises DatabaseTooNewError if the database is at a version this code doesn't know.
    """
    version = schema_version(conn)
    if version > len(migrations):
        raise DatabaseTooNewError(f"Database is at schema version {version}, this Locali knows {len(migrations)}")
    has_tables = conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0] > 0
    if backup_path and has_tables and version < len(migrations):
        _backup(conn, f"{backup_path}.v{version}.bak")

    previous = conn.isolation_level
    conn.isolation_level = None  # transactions are explicit below
    applied = []
    try:
        while True:
            # IMMEDIATE takes the write lock first, so two processes starting together don't both migrate.
            conn.execute("BEGIN IMMEDIATE")
            try:
                version = schema_version(conn)
                if version > len(migrations):
                    raise DatabaseTooNewError(f"Database is at schema version {version}, this Locali knows {len(migrations)}")
                if version == len(migrations):
                    conn.execute("COMMIT")
                    return applied
                migrations[version](conn)
                conn.execute(f"PRAGMA user_version = {version + 1}")
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            applied.append(version + 1)
    finally:
        conn.isolation_level = previous
