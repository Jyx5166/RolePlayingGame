from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from auth import (
    hash_password,
    new_csrf_token,
    new_session_token,
    new_websocket_ticket,
    session_storage_key,
    verify_password,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> bool | None:
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class AppStore:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._transaction_connection: ContextVar[sqlite3.Connection | None] = ContextVar(
            f"store_transaction_{id(self)}", default=None,
        )
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        active = self._transaction_connection.get()
        if active is not None:
            yield active
            return
        connection = sqlite3.connect(self.database_path, factory=ClosingConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            yield connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        if self._transaction_connection.get() is not None:
            yield self._transaction_connection.get()
            return
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            token = self._transaction_connection.set(connection)
            try:
                yield connection
            finally:
                self._transaction_connection.reset(token)

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    csrf_token TEXT NOT NULL DEFAULT '',
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS websocket_tickets (
                    ticket_hash TEXT PRIMARY KEY,
                    session_key TEXT NOT NULL,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS games (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    category TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    player_role_id TEXT,
                    ai_agent_count INTEGER NOT NULL,
                    current_stage INTEGER NOT NULL DEFAULT 1,
                    current_phase TEXT NOT NULL DEFAULT 'investigation',
                    total_stages INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'playing',
                    script_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS game_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS published_scripts (
                    catalog_id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    version TEXT NOT NULL,
                    authoring_job_id TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    script_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS game_context_scopes (
                    context_id TEXT PRIMARY KEY,
                    game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
                    scope_key TEXT NOT NULL,
                    UNIQUE(game_id, scope_key)
                );

                CREATE TABLE IF NOT EXISTS game_preparation_requests (
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    request_id TEXT NOT NULL,
                    game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
                    catalog_id TEXT NOT NULL,
                    script_version TEXT NOT NULL,
                    PRIMARY KEY(user_id, request_id)
                );

                CREATE TABLE IF NOT EXISTS realtime_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
                    request_id TEXT NOT NULL,
                    event_index INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(game_id, request_id, event_index)
                );

                CREATE INDEX IF NOT EXISTS idx_realtime_events_game_cursor
                ON realtime_events(game_id, id);

                CREATE TABLE IF NOT EXISTS game_runtime_snapshots (
                    game_id INTEGER PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,
                    snapshot_version INTEGER NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS role_notebook_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
                    role_id TEXT NOT NULL,
                    section TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_key TEXT NOT NULL,
                    stage INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(game_id, role_id, section, source_key)
                );

                CREATE TABLE IF NOT EXISTS role_manual_notes (
                    game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
                    role_id TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    stage INTEGER,
                    phase TEXT NOT NULL DEFAULT 'legacy_unknown',
                    PRIMARY KEY(game_id, role_id)
                );

                CREATE TABLE IF NOT EXISTS role_manual_note_revisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
                    role_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    stage INTEGER,
                    phase TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(game_id, role_id, revision)
                );

                CREATE TABLE IF NOT EXISTS role_activity_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
                    actor_role_id TEXT NOT NULL,
                    target_role_id TEXT,
                    event_type TEXT NOT NULL,
                    stage INTEGER NOT NULL,
                    phase TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS agent_context_audits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
                    call_id TEXT NOT NULL,
                    role_id TEXT NOT NULL,
                    stage INTEGER NOT NULL,
                    phase TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT NOT NULL DEFAULT '',
                    context_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(game_id, call_id)
                );

                CREATE TABLE IF NOT EXISTS agent_call_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
                    role_id TEXT NOT NULL,
                    stage INTEGER NOT NULL,
                    phase TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT NOT NULL DEFAULT '',
                    context_json TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_agent_attempts_game ON agent_call_attempts(game_id, started_at);

                CREATE TABLE IF NOT EXISTS role_clues (
                    game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
                    role_id TEXT NOT NULL,
                    clue_id TEXT NOT NULL,
                    stage INTEGER NOT NULL,
                    target_id TEXT NOT NULL,
                    target_name TEXT NOT NULL,
                    truth_content TEXT NOT NULL,
                    disclosure_mode TEXT NOT NULL DEFAULT 'private',
                    shared_content TEXT NOT NULL DEFAULT '',
                    shared_scope TEXT NOT NULL DEFAULT '',
                    target_role_id TEXT,
                    acquired_at TEXT NOT NULL,
                    disclosed_at TEXT,
                    PRIMARY KEY(game_id, role_id, clue_id)
                );
                """
            )
            game_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(games)").fetchall()
            }
            if "current_phase" not in game_columns:
                connection.execute(
                    "ALTER TABLE games ADD COLUMN current_phase TEXT NOT NULL DEFAULT 'investigation'"
                )
            for name, definition in (
                ("lifecycle_version", "INTEGER NOT NULL DEFAULT 1"),
                ("catalog_script_id", "TEXT"), ("script_version", "TEXT"),
                ("paused_at", "REAL"), ("run_id", "TEXT"),
                ("state_version", "INTEGER NOT NULL DEFAULT 0"),
                ("phase_epoch", "INTEGER NOT NULL DEFAULT 0"), ("workflow_config_json", "TEXT"),
            ):
                if name not in game_columns:
                    connection.execute(f"ALTER TABLE games ADD COLUMN {name} {definition}")
            self._migrate_optional_player_role(connection)
            ticket_columns = {row['name'] for row in connection.execute('PRAGMA table_info(websocket_tickets)')}
            if 'controller_id' not in ticket_columns:
                connection.execute("ALTER TABLE websocket_tickets ADD COLUMN controller_id TEXT NOT NULL DEFAULT ''")
            session_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(sessions)").fetchall()
            }
            note_columns = {row["name"] for row in connection.execute("PRAGMA table_info(role_manual_notes)")}
            if "stage" not in note_columns:
                connection.execute("ALTER TABLE role_manual_notes ADD COLUMN stage INTEGER")
            if "phase" not in note_columns:
                connection.execute("ALTER TABLE role_manual_notes ADD COLUMN phase TEXT NOT NULL DEFAULT 'legacy_unknown'")
            connection.execute("""
                INSERT INTO role_manual_note_revisions(game_id, role_id, revision, stage, phase, content, created_at)
                SELECT game_id, role_id, 1, stage, phase, content, updated_at FROM role_manual_notes AS notes
                WHERE NOT EXISTS (SELECT 1 FROM role_manual_note_revisions AS revisions
                                  WHERE revisions.game_id = notes.game_id AND revisions.role_id = notes.role_id)
            """)
            if "csrf_token" not in session_columns:
                connection.execute(
                    "ALTER TABLE sessions ADD COLUMN csrf_token TEXT NOT NULL DEFAULT ''"
                )
            for row in connection.execute("SELECT token FROM sessions WHERE token NOT LIKE 'sha256:%'").fetchall():
                connection.execute(
                    "UPDATE sessions SET token = ? WHERE token = ?",
                    (session_storage_key(row["token"]), row["token"]),
                )

    def register(self, username: str, password: str) -> dict[str, Any]:
        normalized = username.strip()
        if len(normalized) < 3 or len(normalized) > 32:
            raise ValueError("用户名长度需要在 3 到 32 个字符之间")
        now = utc_now()
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    "INSERT INTO users(username, password_hash, created_at) VALUES (?, ?, ?)",
                    (normalized, hash_password(password), now),
                )
                user_id = int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise ValueError("用户名已存在") from exc
        return self._create_session(user_id, normalized)

    def login(self, username: str, password: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, username, password_hash FROM users WHERE username = ? COLLATE NOCASE",
                (username.strip(),),
            ).fetchone()
        if row is None or not verify_password(password, row["password_hash"]):
            raise ValueError("用户名或密码错误")
        return self._create_session(int(row["id"]), row["username"])

    def _create_session(self, user_id: int, username: str) -> dict[str, Any]:
        token = new_session_token()
        csrf_token = new_csrf_token()
        now = datetime.now(timezone.utc)
        expires = now + timedelta(days=30)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sessions(token, user_id, csrf_token, expires_at, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session_storage_key(token),
                    user_id,
                    csrf_token,
                    expires.isoformat(),
                    now.isoformat(),
                ),
            )
        return {
            "token": token,
            "csrf_token": csrf_token,
            "user": {"id": user_id, "username": username},
        }

    def user_for_token(self, token: str | None) -> dict[str, Any] | None:
        if not token:
            return None
        now = utc_now()
        hashed_token = session_storage_key(token)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    users.id,
                    users.username,
                    sessions.token AS session_key,
                    sessions.csrf_token
                FROM sessions
                JOIN users ON users.id = sessions.user_id
                WHERE sessions.token = ? AND sessions.expires_at > ?
                """,
                (hashed_token, now),
            ).fetchone()
        return dict(row) if row else None

    def logout(self, token: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM sessions WHERE token = ?",
                (session_storage_key(token),),
            )

    def session_is_active(self, session_key: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM sessions WHERE token = ? AND expires_at > ?",
                (session_key, utc_now()),
            ).fetchone()
        return row is not None

    def create_websocket_ticket(
        self,
        user_id: int,
        game_id: int,
        session_key: str,
        ttl_seconds: int = 30,
        controller_id: str = '',
    ) -> str:
        self.get_game(user_id, game_id)
        ticket = new_websocket_ticket()
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=ttl_seconds)
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM websocket_tickets WHERE expires_at <= ?",
                (now.isoformat(),),
            )
            connection.execute(
                """
                INSERT INTO websocket_tickets(
                    ticket_hash, session_key, user_id, game_id, expires_at, created_at, controller_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_storage_key(ticket),
                    session_key,
                    user_id,
                    game_id,
                    expires.isoformat(),
                    now.isoformat(),
                    controller_id or str(uuid.uuid4()),
                ),
            )
        return ticket

    def consume_websocket_ticket(
        self,
        ticket: str,
        game_id: int,
    ) -> dict[str, Any] | None:
        ticket_hash = session_storage_key(ticket)
        now = utc_now()
        with self._connect() as connection:
            if not connection.in_transaction:
                connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT
                    websocket_tickets.user_id,
                    websocket_tickets.session_key,
                    websocket_tickets.controller_id,
                    users.username
                FROM websocket_tickets
                JOIN sessions ON sessions.token = websocket_tickets.session_key
                JOIN users ON users.id = websocket_tickets.user_id
                WHERE websocket_tickets.ticket_hash = ?
                  AND websocket_tickets.game_id = ?
                  AND websocket_tickets.expires_at > ?
                  AND sessions.expires_at > ?
                """,
                (ticket_hash, game_id, now, now),
            ).fetchone()
            connection.execute(
                "DELETE FROM websocket_tickets WHERE ticket_hash = ?",
                (ticket_hash,),
            )
        return dict(row) if row else None

    @staticmethod
    def _migrate_optional_player_role(connection: sqlite3.Connection) -> None:
        columns = connection.execute("PRAGMA table_info(games)").fetchall()
        if not next(row["notnull"] for row in columns if row["name"] == "player_role_id"):
            return
        sequence = connection.execute("SELECT seq FROM sqlite_sequence WHERE name = 'games'").fetchone()
        connection.execute("PRAGMA foreign_keys = OFF")
        try:
            connection.execute("BEGIN IMMEDIATE")
            definitions = []
            for row in columns:
                definition = f'{row["name"]} {row["type"]}'
                if row["pk"]:
                    definition += " PRIMARY KEY AUTOINCREMENT"
                elif row["name"] == "user_id":
                    definition += " NOT NULL REFERENCES users(id) ON DELETE CASCADE"
                elif row["notnull"] and row["name"] != "player_role_id":
                    definition += " NOT NULL"
                if row["dflt_value"] is not None:
                    definition += f' DEFAULT {row["dflt_value"]}'
                definitions.append(definition)
            connection.execute(f"CREATE TABLE games_migration ({', '.join(definitions)})")
            names = ", ".join(row["name"] for row in columns)
            connection.execute(f"INSERT INTO games_migration ({names}) SELECT {names} FROM games")
            connection.execute("DROP TABLE games")
            connection.execute("ALTER TABLE games_migration RENAME TO games")
            if sequence is not None:
                connection.execute("UPDATE sqlite_sequence SET seq = MAX(seq, ?) WHERE name = 'games'", (sequence["seq"],))
            if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise ValueError("游戏表迁移后外键校验失败")
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.execute("PRAGMA foreign_keys = ON")

    def publish_script(self, user_id: int, catalog_id: str, version: str, job_id: str,
                       script: dict[str, Any], tags: list[str]) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO published_scripts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (catalog_id, user_id, version, job_id, script["script_meta"]["title"],
                 json.dumps(tags, ensure_ascii=False), json.dumps(script, ensure_ascii=False), utc_now()),
            )

    def list_published_scripts(self, user_id: int) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM published_scripts WHERE user_id = ? ORDER BY created_at DESC", (user_id,),
            ).fetchall()
        return [{**dict(row), "script": json.loads(row["script_json"])} for row in rows]

    def find_preparation_request(self, user_id: int, request_id: str, catalog_id: str, version: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM game_preparation_requests WHERE user_id = ? AND request_id = ?", (user_id, request_id)).fetchone()
        if row is None:
            return None
        if row["catalog_id"] != catalog_id or row["script_version"] != version:
            raise ValueError("同一开局请求编号不能用于不同的剧本版本")
        return self.get_game(user_id, row["game_id"])

    def prepare_game(self, user_id: int, script: dict[str, Any], catalog_id: str, version: str,
                     request_id: str | None = None, workflow_config: dict[str, Any] | None = None) -> dict[str, Any]:
        meta = script["script_meta"]
        now = utc_now()
        request_id = request_id or str(uuid.uuid4())
        with self.transaction() as connection:
            existing = self.find_preparation_request(user_id, request_id, catalog_id, version)
            if existing is not None:
                return existing
            cursor = connection.execute(
                """INSERT INTO games(user_id, title, category, mode, player_role_id, ai_agent_count,
                    current_stage, current_phase, total_stages, status, script_json, created_at, updated_at,
                    lifecycle_version, catalog_script_id, script_version, paused_at, workflow_config_json)
                    VALUES (?, ?, 'mystery', 'deduction', NULL, ?, 1, 'preparing', ?, 'preparing', ?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, meta["title"], len(script["roles"]) - 1, meta["total_stages"],
                 json.dumps(script, ensure_ascii=False), now, now, (4 if workflow_config.get('version') == 2 else 3) if workflow_config else 2, catalog_id, version, time.time(),
                 json.dumps(workflow_config) if workflow_config else None),
            )
            game_id = int(cursor.lastrowid)
            connection.execute("INSERT INTO game_preparation_requests VALUES (?, ?, ?, ?, ?)", (user_id, request_id, game_id, catalog_id, version))
            for scope in ["dm", *(f'role:{role["role_id"]}' for role in script["roles"])]:
                connection.execute("INSERT INTO game_context_scopes VALUES (?, ?, ?)", (str(uuid.uuid4()), game_id, scope))
            self.add_event(game_id, "game_prepared", {"catalog_script_id": catalog_id, "script_version": version})
        return self.get_game(user_id, game_id)

    def activate_preparation(self, user_id: int, game_id: int, role_id: str, run_id: str) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE games SET player_role_id = ?, status = 'playing', run_id = ?, paused_at = ?, updated_at = ?
                    WHERE id = ? AND user_id = ? AND status = 'preparing'""",
                (role_id, run_id, time.time(), utc_now(), game_id, user_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("游戏准备状态已发生变化，请重新读取")

    def set_game_lifecycle(self, game_id: int, *, paused_at: float | None, status: str | None = None,
                           run_id: str | None = None) -> None:
        with self._connect() as connection:
            connection.execute("UPDATE games SET paused_at = ?, status = COALESCE(?, status), run_id = COALESCE(?, run_id), updated_at = ? WHERE id = ?",
                               (paused_at, status, run_id, utc_now(), game_id))

    def create_game(
        self,
        user_id: int,
        script: dict[str, Any],
        category: str,
        mode: str,
        player_role_id: str,
    ) -> dict[str, Any]:
        meta = script["script_meta"]
        ai_agent_count = len(script["roles"]) - 1
        current_phase = "briefing" if script.get("stage_flow") else "investigation"
        now = utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO games(
                    user_id, title, category, mode, player_role_id, ai_agent_count,
                    current_stage, current_phase, total_stages, status, script_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, 'playing', ?, ?, ?)
                """,
                (
                    user_id,
                    meta["title"],
                    category,
                    mode,
                    player_role_id,
                    ai_agent_count,
                    current_phase,
                    int(meta["total_stages"]),
                    json.dumps(script, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            game_id = int(cursor.lastrowid)
        return self.get_game(user_id, game_id, include_script=True)

    def get_game(self, user_id: int, game_id: int, include_script: bool = False) -> dict[str, Any]:
        columns = "*" if include_script else "id, title, category, mode, player_role_id, ai_agent_count, current_stage, current_phase, total_stages, status, created_at, updated_at, lifecycle_version, catalog_script_id, script_version, paused_at, run_id"
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT {columns} FROM games WHERE id = ? AND user_id = ?",
                (game_id, user_id),
            ).fetchone()
        if row is None:
            raise KeyError("游戏记录不存在")
        result = dict(row)
        if include_script:
            result["script"] = json.loads(result.pop("script_json"))
        return result

    def list_games(self, user_id: int) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, title, category, mode, player_role_id, ai_agent_count,
                       current_stage, current_phase, total_stages, status, created_at, updated_at,
                       lifecycle_version, catalog_script_id, script_version, paused_at, run_id
                FROM games WHERE user_id = ? ORDER BY updated_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_game(self, user_id: int, game_id: int) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM games WHERE id = ? AND user_id = ?",
                (game_id, user_id),
            )
            if cursor.rowcount == 0:
                raise KeyError("游戏记录不存在")

    def update_game(
        self,
        game_id: int,
        stage: int,
        status: str,
        current_phase: str | None = None,
    ) -> None:
        with self._connect() as connection:
            if current_phase is None:
                connection.execute(
                    "UPDATE games SET current_stage = ?, status = ?, updated_at = ? WHERE id = ?",
                    (stage, status, utc_now(), game_id),
                )
            else:
                connection.execute(
                    """
                    UPDATE games
                    SET current_stage = ?, current_phase = ?, status = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (stage, current_phase, status, utc_now(), game_id),
                )

    def add_event(self, game_id: int, event_type: str, payload: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO game_events(game_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?)",
                (game_id, event_type, json.dumps(payload, ensure_ascii=False), utc_now()),
            )

    def list_events(self, user_id: int, game_id: int) -> list[dict[str, Any]]:
        self.get_game(user_id, game_id)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT event_type, payload_json, created_at FROM game_events WHERE game_id = ? ORDER BY id",
                (game_id,),
            ).fetchall()
        return [
            {
                "type": row["event_type"],
                "payload": self._public_event_payload(json.loads(row["payload_json"])),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def record_realtime_events(
        self,
        game_id: int,
        request_id: str,
        responses: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        now = utc_now()
        with self._connect() as connection:
            if not connection.in_transaction:
                connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT id, request_id, event_type, payload_json, created_at
                FROM realtime_events
                WHERE game_id = ? AND request_id = ?
                ORDER BY event_index
                """,
                (game_id, request_id),
            ).fetchall()
            if existing:
                return [self._realtime_event(row) for row in existing]
            for index, response in enumerate(responses):
                connection.execute(
                    """
                    INSERT INTO realtime_events(
                        game_id, request_id, event_index, event_type, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        game_id,
                        request_id,
                        index,
                        str(response.get("type", "unknown")),
                        json.dumps(response, ensure_ascii=False),
                        now,
                    ),
                )
            rows = connection.execute(
                """
                SELECT id, request_id, event_type, payload_json, created_at
                FROM realtime_events
                WHERE game_id = ? AND request_id = ?
                ORDER BY event_index
                """,
                (game_id, request_id),
            ).fetchall()
        return [self._realtime_event(row) for row in rows]

    def realtime_events_for_request(
        self,
        game_id: int,
        request_id: str,
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, request_id, event_type, payload_json, created_at
                FROM realtime_events
                WHERE game_id = ? AND request_id = ?
                ORDER BY event_index
                """,
                (game_id, request_id),
            ).fetchall()
        return [self._realtime_event(row) for row in rows]

    def list_realtime_events(
        self,
        user_id: int,
        game_id: int,
        after_event_id: int = 0,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self.get_game(user_id, game_id)
        safe_limit = max(1, min(limit, 200))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, request_id, event_type, payload_json, created_at
                FROM realtime_events
                WHERE game_id = ? AND id > ?
                ORDER BY id
                LIMIT ?
                """,
                (game_id, max(0, after_event_id), safe_limit),
            ).fetchall()
        return [self._realtime_event(row) for row in rows]

    def latest_realtime_event_id(self, game_id: int) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(id), 0) AS event_id FROM realtime_events WHERE game_id = ?",
                (game_id,),
            ).fetchone()
        return int(row["event_id"])

    @staticmethod
    def _public_event_payload(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: AppStore._public_event_payload(item) for key, item in value.items()
                    if key not in {"correct_verdict", "incorrect_verdict"}}
        if isinstance(value, list):
            return [AppStore._public_event_payload(item) for item in value]
        return value

    @staticmethod
    def _realtime_event(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "event_id": int(row["id"]),
            "request_id": row["request_id"],
            "type": row["event_type"],
            "payload": AppStore._public_event_payload(json.loads(row["payload_json"])),
            "created_at": row["created_at"],
        }

    def save_runtime_snapshot(
        self,
        game_id: int,
        snapshot: dict[str, Any],
    ) -> None:
        version = int(snapshot.get("version", 0))
        if version < 1:
            raise ValueError("游戏快照缺少有效版本")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO game_runtime_snapshots(
                    game_id, snapshot_version, snapshot_json, updated_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(game_id)
                DO UPDATE SET
                    snapshot_version = excluded.snapshot_version,
                    snapshot_json = excluded.snapshot_json,
                    updated_at = excluded.updated_at
                """,
                (
                    game_id,
                    version,
                    json.dumps(snapshot, ensure_ascii=False),
                    utc_now(),
                ),
            )

    def get_runtime_snapshot(
        self,
        user_id: int,
        game_id: int,
    ) -> dict[str, Any] | None:
        self.get_game(user_id, game_id)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT snapshot_version, snapshot_json, updated_at
                FROM game_runtime_snapshots
                WHERE game_id = ?
                """,
                (game_id,),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row["snapshot_json"])
        if not isinstance(payload, dict):
            raise ValueError("游戏快照内容无效")
        if int(payload.get("version", 0)) != int(row["snapshot_version"]):
            raise ValueError("游戏快照版本记录不一致")
        return {
            **payload,
            "snapshot_updated_at": row["updated_at"],
        }

    def add_notebook_entry(
        self,
        game_id: int,
        role_id: str,
        section: str,
        source_type: str,
        source_key: str,
        stage: int,
        title: str,
        content: str,
    ) -> None:
        if section not in {"automatic", "reasoning"}:
            raise ValueError("未知的记录本分区")
        normalized = content.strip()
        if not normalized:
            return
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO role_notebook_entries(
                    game_id, role_id, section, source_type, source_key,
                    stage, title, content, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(game_id, role_id, section, source_key)
                DO UPDATE SET
                    source_type = excluded.source_type,
                    stage = excluded.stage,
                    title = excluded.title,
                    content = excluded.content
                """,
                (
                    game_id,
                    role_id,
                    section,
                    source_type,
                    source_key,
                    stage,
                    title.strip(),
                    normalized,
                    utc_now(),
                ),
            )

    def list_notebook_entries(
        self,
        user_id: int,
        game_id: int,
        role_id: str | None = None,
    ) -> list[dict[str, Any]]:
        self.get_game(user_id, game_id)
        query = (
            """
            SELECT role_id, section, source_type, source_key, stage, title, content, created_at
            FROM role_notebook_entries
            WHERE game_id = ?
            """
        )
        parameters: tuple[Any, ...] = (game_id,)
        if role_id is not None:
            query += " AND role_id = ?"
            parameters = (game_id, role_id)
        query += " ORDER BY stage, id"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [dict(row) for row in rows]

    def save_manual_notes(
        self,
        user_id: int,
        game_id: int,
        role_id: str,
        content: str,
    ) -> dict[str, Any]:
        with self.transaction() as connection:
            game = self.get_game(user_id, game_id)
            if role_id != game["player_role_id"]:
                raise ValueError("只能编辑当前玩家角色的手记")
            previous = connection.execute("SELECT * FROM role_manual_notes WHERE game_id = ? AND role_id = ?", (game_id, role_id)).fetchone()
            if previous is not None and previous["content"] == content:
                revision = connection.execute("SELECT MAX(revision) FROM role_manual_note_revisions WHERE game_id = ? AND role_id = ?", (game_id, role_id)).fetchone()[0]
                return {"content": content, "updated_at": previous["updated_at"], "stage": previous["stage"], "phase": previous["phase"], "revision": revision}
            updated_at = utc_now()
            stage, phase = int(game["current_stage"]), str(game["current_phase"])
            connection.execute(
                """
                INSERT INTO role_manual_notes(game_id, role_id, content, updated_at, stage, phase)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(game_id, role_id)
                DO UPDATE SET content = excluded.content, updated_at = excluded.updated_at, stage = excluded.stage, phase = excluded.phase
                """,
                (game_id, role_id, content, updated_at, stage, phase),
            )
            revision = connection.execute("SELECT COALESCE(MAX(revision), 0) + 1 FROM role_manual_note_revisions WHERE game_id = ? AND role_id = ?", (game_id, role_id)).fetchone()[0]
            connection.execute("INSERT INTO role_manual_note_revisions(game_id, role_id, revision, stage, phase, content, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                               (game_id, role_id, revision, stage, phase, content, updated_at))
        return {"content": content, "updated_at": updated_at, "stage": stage, "phase": phase, "revision": revision}

    def list_manual_notes(
        self,
        user_id: int,
        game_id: int,
    ) -> dict[str, dict[str, Any]]:
        self.get_game(user_id, game_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT role_id, content, updated_at, stage, phase
                FROM role_manual_notes
                WHERE game_id = ?
                """,
                (game_id,),
            ).fetchall()
        return {
            row["role_id"]: {
                "content": row["content"],
                "updated_at": row["updated_at"],
                "stage": row["stage"], "phase": row["phase"],
            }
            for row in rows
        }

    def list_manual_note_revisions(self, user_id: int, game_id: int) -> list[dict[str, Any]]:
        self.get_game(user_id, game_id)
        with self._connect() as connection:
            rows = connection.execute("SELECT role_id, revision, stage, phase, content, created_at FROM role_manual_note_revisions WHERE game_id = ? ORDER BY id", (game_id,)).fetchall()
        return [dict(row) for row in rows]

    def record_agent_attempt(self, game_id: int, attempt: dict[str, Any]) -> None:
        # Deliberately ignore the gameplay transaction connection.
        if self._transaction_connection.get() is not None:
            raise RuntimeError("模型调用观测不能在游戏写事务内执行")
        now = utc_now()
        connection = sqlite3.connect(self.database_path, factory=ClosingConnection)
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            connection.execute("""
                INSERT INTO agent_call_attempts(attempt_id, game_id, role_id, stage, phase, channel, purpose,
                                                status, error, context_json, started_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(attempt_id) DO UPDATE SET status=excluded.status, error=excluded.error,
                                                     context_json=excluded.context_json, updated_at=excluded.updated_at
            """, (attempt["call_id"], game_id, attempt["role_id"], attempt["stage"], attempt["phase"],
                  attempt["channel"], attempt["purpose"], attempt["status"], attempt.get("error", ""),
                  json.dumps(attempt["context"], ensure_ascii=False), now, now))

    def list_agent_attempts(self, user_id: int, game_id: int) -> list[dict[str, Any]]:
        self.get_game(user_id, game_id)
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM agent_call_attempts WHERE game_id = ? ORDER BY started_at, rowid", (game_id,)).fetchall()
        return [{"call_id": row["attempt_id"], "role_id": row["role_id"], "stage": row["stage"],
                 "phase": row["phase"], "channel": row["channel"], "purpose": row["purpose"],
                 "status": row["status"], "error": row["error"], "created_at": row["started_at"],
                 "updated_at": row["updated_at"], "context": json.loads(row["context_json"])} for row in rows]

    def add_role_activity(
        self,
        game_id: int,
        actor_role_id: str,
        target_role_id: str | None,
        event_type: str,
        stage: int,
        phase: str,
        channel: str,
        summary: str,
        details: dict[str, Any],
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO role_activity_events(
                    game_id, actor_role_id, target_role_id, event_type,
                    stage, phase, channel, summary, details_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    game_id,
                    actor_role_id,
                    target_role_id,
                    event_type,
                    stage,
                    phase,
                    channel,
                    summary.strip(),
                    json.dumps(details, ensure_ascii=False),
                    utc_now(),
                ),
            )

    def add_agent_context_audit(
        self,
        *,
        game_id: int,
        call_id: str,
        role_id: str,
        stage: int,
        phase: str,
        channel: str,
        purpose: str,
        status: str,
        error: str,
        context: dict[str, Any],
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO agent_context_audits(
                    game_id, call_id, role_id, stage, phase, channel,
                    purpose, status, error, context_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(game_id, call_id) DO NOTHING
                """,
                (
                    game_id,
                    call_id,
                    role_id,
                    stage,
                    phase,
                    channel,
                    purpose,
                    status,
                    error.strip(),
                    json.dumps(context, ensure_ascii=False),
                    utc_now(),
                ),
            )

    def upsert_role_clue(
        self,
        *,
        game_id: int,
        role_id: str,
        clue_id: str,
        stage: int,
        target_id: str,
        target_name: str,
        truth_content: str,
        disclosure_mode: str,
        shared_content: str,
        shared_scope: str,
        target_role_id: str | None,
    ) -> None:
        now = utc_now()
        disclosed_at = now if disclosure_mode != "private" else None
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO role_clues(
                    game_id, role_id, clue_id, stage, target_id, target_name,
                    truth_content, disclosure_mode, shared_content, shared_scope,
                    target_role_id, acquired_at, disclosed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(game_id, role_id, clue_id)
                DO UPDATE SET
                    stage = excluded.stage,
                    target_id = excluded.target_id,
                    target_name = excluded.target_name,
                    truth_content = excluded.truth_content,
                    disclosure_mode = excluded.disclosure_mode,
                    shared_content = excluded.shared_content,
                    shared_scope = excluded.shared_scope,
                    target_role_id = excluded.target_role_id,
                    disclosed_at = excluded.disclosed_at
                """,
                (
                    game_id,
                    role_id,
                    clue_id,
                    stage,
                    target_id,
                    target_name.strip(),
                    truth_content.strip(),
                    disclosure_mode,
                    shared_content.strip(),
                    shared_scope,
                    target_role_id,
                    now,
                    disclosed_at,
                ),
            )

    def list_role_clues(
        self,
        user_id: int,
        game_id: int,
        role_id: str | None = None,
    ) -> list[dict[str, Any]]:
        self.get_game(user_id, game_id)
        query = (
            """
            SELECT role_id, clue_id, stage, target_id, target_name,
                   truth_content, disclosure_mode, shared_content,
                   shared_scope, target_role_id, acquired_at, disclosed_at
            FROM role_clues
            WHERE game_id = ?
            """
        )
        parameters: tuple[Any, ...] = (game_id,)
        if role_id is not None:
            query += " AND role_id = ?"
            parameters = (game_id, role_id)
        query += " ORDER BY stage, acquired_at, clue_id"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [dict(row) for row in rows]

    def list_role_activities(
        self,
        user_id: int,
        game_id: int,
    ) -> list[dict[str, Any]]:
        self.get_game(user_id, game_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, actor_role_id, target_role_id, event_type, stage, phase,
                       channel, summary, details_json, created_at
                FROM role_activity_events
                WHERE game_id = ?
                ORDER BY id
                """,
                (game_id,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "actor_role_id": row["actor_role_id"],
                "target_role_id": row["target_role_id"],
                "event_type": row["event_type"],
                "stage": row["stage"],
                "phase": row["phase"],
                "channel": row["channel"],
                "summary": row["summary"],
                "details": json.loads(row["details_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def list_agent_context_audits(
        self,
        user_id: int,
        game_id: int,
        role_id: str | None = None,
    ) -> list[dict[str, Any]]:
        self.get_game(user_id, game_id)
        query = (
            """
            SELECT call_id, role_id, stage, phase, channel, purpose,
                   status, error, context_json, created_at
            FROM agent_context_audits
            WHERE game_id = ?
            """
        )
        parameters: tuple[Any, ...] = (game_id,)
        if role_id is not None:
            query += " AND role_id = ?"
            parameters = (game_id, role_id)
        query += " ORDER BY id"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [
            {
                "call_id": row["call_id"],
                "role_id": row["role_id"],
                "stage": row["stage"],
                "phase": row["phase"],
                "channel": row["channel"],
                "purpose": row["purpose"],
                "status": row["status"],
                "error": row["error"],
                "context": json.loads(row["context_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]
