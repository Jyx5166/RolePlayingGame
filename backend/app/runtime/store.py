from __future__ import annotations

import hashlib
import json
import uuid
import time
from typing import Any

from runtime.contracts import RuntimeAccessError, RuntimeScope
from storage import AppStore, utc_now


def fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class RuntimeStore:
    """Local execution records. Gameplay snapshots and receipts remain the authority."""
    def __init__(self, store: AppStore) -> None:
        self.store = store
        with store._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS game_runs (
                    run_id TEXT PRIMARY KEY, game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
                    status TEXT NOT NULL, instances_json TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT);
                CREATE TABLE IF NOT EXISTS model_requests (
                    model_request_id TEXT PRIMARY KEY, game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
                    run_id TEXT NOT NULL REFERENCES game_runs(run_id) ON DELETE CASCADE, turn_id TEXT NOT NULL,
                    context_id TEXT NOT NULL REFERENCES game_context_scopes(context_id) ON DELETE CASCADE,
                    actor_kind TEXT NOT NULL, actor_role_id TEXT NOT NULL, agent_instance_id TEXT NOT NULL,
                    transport TEXT NOT NULL, status TEXT NOT NULL, input_json TEXT NOT NULL, output_json TEXT,
                    usage_json TEXT, metadata_json TEXT NOT NULL, error TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS tool_calls (
                    tool_call_id TEXT PRIMARY KEY, game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
                    run_id TEXT NOT NULL REFERENCES game_runs(run_id) ON DELETE CASCADE, turn_id TEXT NOT NULL,
                    context_id TEXT NOT NULL REFERENCES game_context_scopes(context_id) ON DELETE CASCADE,
                    actor_kind TEXT NOT NULL, actor_role_id TEXT NOT NULL, agent_instance_id TEXT NOT NULL,
                    request_id TEXT NOT NULL, model_request_id TEXT REFERENCES model_requests(model_request_id) ON DELETE SET NULL,
                    provider_tool_call_id TEXT, tool_name TEXT NOT NULL, arguments_json TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, phase_epoch INTEGER NOT NULL, state_version INTEGER NOT NULL,
                    status TEXT NOT NULL, result_json TEXT, started_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS workflow_commands (
                    game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE, request_id TEXT NOT NULL,
                    run_id TEXT NOT NULL REFERENCES game_runs(run_id) ON DELETE CASCADE, turn_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, payload_json TEXT NOT NULL, status TEXT NOT NULL,
                    started_at TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(game_id, request_id));
                CREATE INDEX IF NOT EXISTS idx_model_requests_game ON model_requests(game_id, started_at);
                CREATE INDEX IF NOT EXISTS idx_tool_calls_game ON tool_calls(game_id, started_at);
                CREATE TABLE IF NOT EXISTS hosting_scenes (
                    game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
                    stage INTEGER NOT NULL, phase TEXT NOT NULL, request_id TEXT NOT NULL,
                    created_at TEXT NOT NULL, PRIMARY KEY(game_id,stage,phase));
            """)
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(games)")}
            for name, definition in (("state_version", "INTEGER NOT NULL DEFAULT 0"),
                                     ("phase_epoch", "INTEGER NOT NULL DEFAULT 0"), ("workflow_config_json", "TEXT")):
                if name not in columns:
                    connection.execute(f"ALTER TABLE games ADD COLUMN {name} {definition}")

    def context_ids(self, game_id: int, role_ids: list[str]) -> dict[str, str]:
        with self.store.transaction() as connection:
            for key in ["dm", *(f"role:{role}" for role in role_ids)]:
                connection.execute("INSERT OR IGNORE INTO game_context_scopes VALUES (?, ?, ?)", (str(uuid.uuid4()), game_id, key))
            return {row["scope_key"]: row["context_id"] for row in connection.execute("SELECT * FROM game_context_scopes WHERE game_id = ?", (game_id,))}

    def reserve_hosting(self,scope,stage,phase,request_id):
        with self.store.transaction() as connection:
            self.assert_scope(scope)
            section={'briefing':'public_briefing','dm_hosting':'dm_hosting'}[phase]
            # Already committed sections also cover games created before this table.
            prior=connection.execute("SELECT 1 FROM tool_calls WHERE game_id=? AND tool_name='present_script_section' AND status='succeeded' AND json_extract(result_json,'$.data.source_key')=?",
                (scope.game_id,f'script:stage_{stage}:{section}')).fetchone()
            inserted=connection.execute('INSERT OR IGNORE INTO hosting_scenes VALUES (?,?,?,?,?)',
                (scope.game_id,stage,phase,request_id,utc_now())).rowcount
            return bool(inserted and not prior)

    def register_run(self, game_id: int, run_id: str, instances: dict[str, str]) -> None:
        with self.store.transaction() as connection:
            connection.execute("UPDATE game_runs SET status='interrupted', ended_at=? WHERE game_id=? AND run_id<>? AND status='active'", (utc_now(), game_id, run_id))
            connection.execute("INSERT OR IGNORE INTO game_runs VALUES (?, ?, 'active', ?, ?, NULL)", (run_id, game_id, json.dumps(instances), utc_now()))
            # A request interrupted during an external call cannot be silently counted as a success or retried.
            connection.execute("UPDATE model_requests SET status='unknown', error='运行已中断，供应商完成与计费情况未知', updated_at=? WHERE game_id=? AND run_id<>? AND status='running'", (utc_now(), game_id, run_id))
            for row in connection.execute("SELECT tool_call_id FROM tool_calls WHERE game_id=? AND run_id<>? AND status='pending'", (game_id, run_id)).fetchall():
                self.finish_tool(row["tool_call_id"], {"schema_version": "1.0", "tool_call_id": row["tool_call_id"],
                    "status": "unknown", "code": "RUN_INTERRUPTED", "message": "运行已中断，未自动重放工具",
                    "data": {}, "gameplay_committed": False})
            connection.execute("UPDATE workflow_commands SET status='interrupted',updated_at=? WHERE game_id=? AND run_id<>? AND status='running'", (utc_now(), game_id, run_id))

    def close_run(self, run_id: str, status: str) -> None:
        with self.store._connect() as connection:
            connection.execute("UPDATE game_runs SET status=?, ended_at=? WHERE run_id=?", (status, utc_now(), run_id))

    def assert_scope(self, scope: RuntimeScope, *, expected_epoch: int | None = None) -> dict[str, Any]:
        with self.store._connect() as connection:
            game = connection.execute("SELECT * FROM games WHERE id=?", (scope.game_id,)).fetchone()
            run = connection.execute("SELECT * FROM game_runs WHERE run_id=? AND game_id=?", (scope.run_id, scope.game_id)).fetchone()
            context = connection.execute("SELECT * FROM game_context_scopes WHERE context_id=? AND game_id=?", (scope.context_id, scope.game_id)).fetchone()
            lease = connection.execute('SELECT * FROM game_leases WHERE game_id=?', (scope.game_id,)).fetchone() if connection.execute("SELECT name FROM sqlite_master WHERE name='game_leases'").fetchone() else None
        key = "dm" if scope.actor_kind == "dm" else f"role:{scope.actor_role_id}"
        if game is None or run is None or context is None or context["scope_key"] != key:
            raise RuntimeAccessError("游戏、角色或上下文编号关联无效")
        if game["run_id"] != scope.run_id or game["status"] not in {"playing", "completed"} or run["status"] != "active":
            raise RuntimeAccessError("运行批次已失效或游戏已暂停")
        if json.loads(run["instances_json"]).get(key) != scope.agent_instance_id:
            raise RuntimeAccessError("Agent 实例与运行批次不匹配")
        if expected_epoch is not None and game["phase_epoch"] != expected_epoch:
            raise RuntimeAccessError("工具提出后场景阶段已变化")
        if lease is not None and (lease['status']!='active' or lease['expires_at']<=time.time() or lease['run_id']!=scope.run_id):
            raise RuntimeAccessError('游戏控制租约过期或已被接管')
        return dict(game)

    def start_model(self, scope: RuntimeScope, model_id: str, turn_id: str, transport: str,
                    messages: list[dict[str, Any]], metadata: dict[str, Any]) -> None:
        self.assert_scope(scope)
        if self.store._transaction_connection.get() is not None:
            raise RuntimeError("模型请求不能在游戏写事务内开始")
        with self.store._connect() as connection:
            connection.execute("INSERT INTO model_requests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'running', ?, NULL, NULL, ?, '', ?, ?)",
                (model_id, scope.game_id, scope.run_id, turn_id, scope.context_id, scope.actor_kind, scope.actor_role_id,
                 scope.agent_instance_id, transport, json.dumps(messages, ensure_ascii=False), json.dumps(metadata), utc_now(), utc_now()))

    def finish_model(self, model_id: str, status: str, output: dict[str, Any] | None, metadata: dict[str, Any], error: str) -> None:
        with self.store._connect() as connection:
            connection.execute("UPDATE model_requests SET status=?, output_json=?, usage_json=?, metadata_json=?, error=?, updated_at=? WHERE model_request_id=?",
                (status, json.dumps(output, ensure_ascii=False) if output is not None else None,
                 json.dumps(metadata["usage"]) if metadata.get("usage") is not None else None,
                 json.dumps(metadata, ensure_ascii=False), error, utc_now(), model_id))

    def model_record(self, scope: RuntimeScope, model_id: str) -> dict[str, Any]:
        with self.store._connect() as connection:
            row = connection.execute("SELECT * FROM model_requests WHERE model_request_id=? AND game_id=? AND context_id=?", (model_id, scope.game_id, scope.context_id)).fetchone()
        if row is None:
            raise RuntimeAccessError("模型记录不属于当前上下文")
        if row["run_id"] != scope.run_id or row["agent_instance_id"] != scope.agent_instance_id:
            raise RuntimeAccessError("模型记录属于旧的运行实例，不能当作当前工具提案")
        result = dict(row)
        result["output"] = json.loads(result["output_json"]) if result["output_json"] else None
        return result

    def enqueue_tool(self, scope: RuntimeScope, call_id: str, turn_id: str, request_id: str,
                     name: str, arguments: dict[str, Any], model_id: str | None = None, provider_id: str | None = None) -> None:
        game = self.assert_scope(scope)
        with self.store._connect() as connection:
            connection.execute("""INSERT INTO tool_calls VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', NULL, ?, ?)
                ON CONFLICT(tool_call_id) DO NOTHING""", (call_id, scope.game_id, scope.run_id, turn_id, scope.context_id,
                scope.actor_kind, scope.actor_role_id, scope.agent_instance_id, request_id, model_id, provider_id, name,
                json.dumps(arguments, ensure_ascii=False), fingerprint({"name": name, "arguments": arguments}),
                game["phase_epoch"], game["state_version"], utc_now(), utc_now()))
            existing = connection.execute("SELECT * FROM tool_calls WHERE tool_call_id=?", (call_id,)).fetchone()
            if (existing["game_id"], existing["context_id"], existing["actor_kind"], existing["actor_role_id"], existing["fingerprint"]) != (
                scope.game_id, scope.context_id, scope.actor_kind, scope.actor_role_id, fingerprint({"name": name, "arguments": arguments})):
                raise RuntimeAccessError("工具编号已绑定到不同的调用，不能覆盖或复用")

    def tool_record(self, scope: RuntimeScope, call_id: str) -> dict[str, Any]:
        with self.store._connect() as connection:
            row = connection.execute("SELECT * FROM tool_calls WHERE tool_call_id=? AND game_id=? AND context_id=? AND actor_kind=? AND actor_role_id=?",
                                     (call_id, scope.game_id, scope.context_id, scope.actor_kind, scope.actor_role_id)).fetchone()
        if row is None:
            raise RuntimeAccessError("工具记录不属于当前游戏或角色")
        result = dict(row)
        result["arguments"] = json.loads(result["arguments_json"])
        result["result"] = json.loads(result["result_json"]) if result["result_json"] else None
        return result

    def finish_tool(self, call_id: str, result: dict[str, Any]) -> None:
        with self.store._connect() as connection:
            connection.execute("UPDATE tool_calls SET status=?, result_json=?, updated_at=? WHERE tool_call_id=?", (result["status"], json.dumps(result, ensure_ascii=False), utc_now(), call_id))

    def bump_state(self, game_id: int, *, phase_changed: bool) -> None:
        with self.store._connect() as connection:
            connection.execute("UPDATE games SET state_version=state_version+1, phase_epoch=phase_epoch+? WHERE id=?", (int(phase_changed), game_id))

    def command(self, game_id: int, request_id: str) -> dict[str, Any] | None:
        with self.store._connect() as connection:
            row = connection.execute("SELECT * FROM workflow_commands WHERE game_id=? AND request_id=?", (game_id, request_id)).fetchone()
        if row is None:
            return None
        return {**dict(row), "payload": json.loads(row["payload_json"])}

    def start_command(self, game_id: int, run_id: str, request_id: str, turn_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self.store.transaction() as connection:
            existing = self.command(game_id, request_id)
            if existing is not None:
                if existing["fingerprint"] != fingerprint(payload):
                    raise ValueError("同一请求编号不能用于不同的游戏操作")
                return existing
            connection.execute("INSERT INTO workflow_commands VALUES (?, ?, ?, ?, ?, ?, 'running', ?, ?)",
                (game_id, request_id, run_id, turn_id, fingerprint(payload), json.dumps(payload, ensure_ascii=False), utc_now(), utc_now()))
        return self.command(game_id, request_id)  # type: ignore[return-value]

    def finish_command(self, game_id: int, request_id: str, status: str) -> None:
        with self.store._connect() as connection:
            connection.execute("UPDATE workflow_commands SET status=?, updated_at=? WHERE game_id=? AND request_id=?", (status, utc_now(), game_id, request_id))

    def append_events(self, game_id: int, request_id: str, events: list[dict[str, Any]]) -> None:
        with self.store._connect() as connection:
            start = connection.execute("SELECT COALESCE(MAX(event_index),-1)+1 FROM realtime_events WHERE game_id=? AND request_id=?", (game_id, request_id)).fetchone()[0]
            for offset, event in enumerate(events):
                connection.execute("INSERT INTO realtime_events(game_id,request_id,event_index,event_type,payload_json,created_at) VALUES (?,?,?,?,?,?)",
                                   (game_id, request_id, start+offset, event["type"], json.dumps(event, ensure_ascii=False), utc_now()))

    def logs(self, user_id: int, game_id: int) -> dict[str, Any]:
        game = self.store.get_game(user_id, game_id)
        with self.store._connect() as connection:
            rows = {table: [dict(row) for row in connection.execute(f"SELECT * FROM {table} WHERE game_id=? ORDER BY started_at", (game_id,))]
                    for table in ("game_runs", "model_requests", "tool_calls")}
        if game["status"] != "completed":
            rows["model_requests"] = []
            rows["tool_calls"] = [row for row in rows["tool_calls"] if row["actor_kind"] == "human" and row["actor_role_id"] == game["player_role_id"]]
        for row in rows["model_requests"]:
            for key in ("input_json", "output_json"):
                if row[key]:
                    payload = json.loads(row[key])
                    if isinstance(payload, list):
                        payload = [{key: value for key, value in message.items() if key != "reasoning_content"} for message in payload]
                    elif isinstance(payload, dict):
                        payload.pop("reasoning_content", None)
                    row[key.removesuffix("_json")] = payload
                row.pop(key)
        return {"game_id": game_id, "schema_version": "1.0", **rows}

    def log_page(self,user_id,game_id,kind,actor_role_id='',offset=0,limit=30):
        game = self.store.get_game(user_id,game_id)
        table = {'models':'model_requests','tools':'tool_calls','runs':'game_runs'}[kind]
        clause,values = 'game_id=?',[game_id]
        if table!='game_runs':
            if game['status']!='completed':
                if kind=='models': return {'items':[],'next_offset':offset,'has_more':False}
                clause += " AND actor_kind='human' AND actor_role_id=?"
                values.append(game['player_role_id'])
            if actor_role_id:
                clause += ' AND actor_role_id=?'; values.append(actor_role_id)
        with self.store._connect() as connection:
            rows = [dict(row) for row in connection.execute(f'SELECT * FROM {table} WHERE {clause} ORDER BY started_at,rowid LIMIT ? OFFSET ?',(*values,limit+1,offset))]
        def scrub(value):
            if isinstance(value,dict): return {key:scrub(item) for key,item in value.items() if key!='reasoning_content'}
            if isinstance(value,list): return [scrub(item) for item in value]
            return value
        for row in rows:
            for key in list(row):
                if key.endswith('_json') and row[key]: row[key] = json.dumps(scrub(json.loads(row[key])),ensure_ascii=False)
        return {'items':rows[:limit],'next_offset':offset+min(limit,len(rows)),'has_more':len(rows)>limit}
