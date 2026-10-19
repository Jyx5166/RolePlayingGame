"""Canonical per-actor originals, extractive indexes, and authorized paged retrieval."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any

from agent.memory import terms
from runtime.contracts import RuntimeAccessError, RuntimeScope
from storage import AppStore, utc_now


def extract_summary(content: str, limit: int = 160) -> str:
    # No synthetic claims: this is an explicitly partial quotation, backed by an original.
    sentences = re.split(r'(?<=[。！？\n])', content)
    text = ''.join(sentences[:2]).strip()
    return text[:limit] + ('…' if len(content) > min(len(text), limit) else '')


class MemoryArchive:
    def __init__(self, store: AppStore):
        self.store = store
        with store._connect() as connection:
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS memory_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, memory_id TEXT NOT NULL UNIQUE,
                    game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
                    context_id TEXT NOT NULL REFERENCES game_context_scopes(context_id) ON DELETE CASCADE,
                    actor_kind TEXT NOT NULL, actor_role_id TEXT NOT NULL, source_key TEXT NOT NULL,
                    kind TEXT NOT NULL, stage INTEGER NOT NULL, raw_content TEXT NOT NULL,
                    summary TEXT NOT NULL, content_hash TEXT NOT NULL, metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL, UNIQUE(context_id,source_key,content_hash));
                CREATE INDEX IF NOT EXISTS idx_memory_scope ON memory_records(game_id,context_id,stage,id);
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_search USING fts5(terms);
                CREATE TRIGGER IF NOT EXISTS memory_delete AFTER DELETE ON memory_records BEGIN
                    DELETE FROM memory_search WHERE rowid=old.id;
                END;
            ''')

    def _validate(self, scope: RuntimeScope):
        key = 'dm' if scope.actor_kind == 'dm' else 'role:' + scope.actor_role_id
        with self.store._connect() as connection:
            row = connection.execute('SELECT scope_key FROM game_context_scopes WHERE game_id=? AND context_id=?',
                                     (scope.game_id, scope.context_id)).fetchone()
        if row is None or row['scope_key'] != key:
            raise RuntimeAccessError('记忆作用域与本场游戏、角色不匹配')

    def sync(self, scope: RuntimeScope, records: list[dict[str, Any]]):
        self._validate(scope)
        with self.store.transaction() as connection:
            for record in records:
                if record['owner_role_id'] != scope.actor_role_id:
                    raise RuntimeAccessError('不能将其他角色信息写入当前记忆空间')
                content = record['content']
                digest = hashlib.sha256(content.encode()).hexdigest()
                memory_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f'{scope.context_id}:{record["source_key"]}:{digest}'))
                cursor = connection.execute('''INSERT OR IGNORE INTO memory_records(
                    memory_id,game_id,context_id,actor_kind,actor_role_id,source_key,kind,stage,
                    raw_content,summary,content_hash,metadata_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (memory_id,scope.game_id,scope.context_id,scope.actor_kind,scope.actor_role_id,record['source_key'],
                     record['kind'],record['stage'],content,extract_summary(content),digest,
                     json.dumps({key:value for key,value in record.items() if key!='content'},ensure_ascii=False),utc_now()))
                if cursor.rowcount:
                    connection.execute('INSERT INTO memory_search(rowid,terms) VALUES (?,?)',
                                       (cursor.lastrowid, ' '.join(sorted(terms(content)))))
                else:
                    # Old originals keep their IDs; provenance corrections must
                    # also reach indexes and subsequent paged reads.
                    connection.execute('UPDATE memory_records SET kind=?,metadata_json=? WHERE memory_id=?',
                        (record['kind'],json.dumps({key:value for key,value in record.items() if key!='content'},ensure_ascii=False),memory_id))

    def _rows(self, scope: RuntimeScope, stage: int, query: str = ''):
        self._validate(scope)
        parameters: list[Any] = [scope.game_id,scope.context_id,scope.actor_kind,scope.actor_role_id]
        clause = 'm.game_id=? AND m.context_id=? AND m.actor_kind=? AND m.actor_role_id=?'
        if scope.actor_kind != 'dm':
            clause += ' AND m.stage<=?'
            parameters.append(stage)
        tokens = sorted(terms(query))[:40]
        with self.store._connect() as connection:
            if tokens:
                expression = ' OR '.join('"'+token.replace('"','""')+'"' for token in tokens)
                rows = connection.execute('SELECT m.* FROM memory_records m JOIN memory_search f ON f.rowid=m.id '
                    'WHERE '+clause+' AND memory_search MATCH ? ORDER BY m.id DESC LIMIT 200', (*parameters,expression)).fetchall()
            else:
                rows = connection.execute('SELECT m.* FROM memory_records m WHERE '+clause+' ORDER BY m.id DESC LIMIT 200', parameters).fetchall()
        return [dict(row) for row in rows]

    def index(self, scope: RuntimeScope, stage: int, query: str, limit: int = 12):
        rows = self._rows(scope, stage, query)
        rows.sort(key=lambda row: (len(terms(query)&terms(row['raw_content'])), row['kind'] in {'search_fact','role_knowledge','dm_knowledge'},row['id']),reverse=True)
        return [{'memory_id':row['memory_id'],'source_key':row['source_key'],'kind':row['kind'],'stage':row['stage'],
                 'summary':row['summary'],'summary_type':'extractive_partial','original_chars':len(row['raw_content']),
                 **self._provenance(row)}
                for row in rows[:limit]]

    @staticmethod
    def _provenance(row: dict[str, Any]) -> dict[str, Any]:
        metadata = json.loads(row['metadata_json'])
        fields = ('speaker_role_id','speaker_role_name','first_person_role_id','epistemic_status',
                  'event_verified','statement_verified','content_is_verbatim')
        result = {key:metadata[key] for key in fields if key in metadata}
        if row['kind'] in {'testimony','belief'}:
            result.setdefault('epistemic_status','unverified_'+row['kind'])
            result.setdefault('statement_verified',False)
            result.setdefault('first_person_role_id','unknown')
        return result

    def retrieve(self, scope: RuntimeScope, stage: int, *, query: str = '', memory_id: str | None = None,
                 offset: int = 0, limit: int = 3, chunk_chars: int = 1500):
        self._validate(scope)
        if memory_id:
            with self.store._connect() as connection:
                row = connection.execute('''SELECT * FROM memory_records WHERE memory_id=? AND game_id=? AND context_id=?
                    AND actor_kind=? AND actor_role_id=?''', (memory_id,scope.game_id,scope.context_id,scope.actor_kind,scope.actor_role_id)).fetchone()
            if row is None or scope.actor_kind!='dm' and row['stage']>stage:
                raise RuntimeAccessError('记忆编号不存在或无权读取')
            rows = [dict(row)]
        else:
            rows = self._rows(scope,stage,query)[:limit]
        results = []
        for row in rows:
            raw = row['raw_content']
            end = min(len(raw),offset+chunk_chars)
            results.append({'memory_id':row['memory_id'],'source_key':row['source_key'],'kind':row['kind'],
                'stage':row['stage'],'content':raw[offset:end],'offset':offset,'next_offset':end if end<len(raw) else None,
                'complete':offset==0 and end==len(raw),
                'certainty':'unverified' if row['kind'] in {'testimony','belief'} else 'runtime_action' if row['kind']=='observed_action' else 'authorized_source',
                **self._provenance(row)})
        return {'records':results,'query':query,'originals_retained':True}

    def dm_records(self, dm: Any):
        script = dm._require_script()
        records=[]
        def add(key, content, kind='dm_knowledge', stage=1):
            records.append({'source_key':key,'owner_role_id':'dm','kind':kind,'stage':stage,'scope':'dm_only',
                            'recipients':['dm'],'content':content,'required':False})
        for key,value in script.items():
            if key=='roles':
                for role in value: add('script:role:'+role['role_id'],json.dumps(role,ensure_ascii=False))
            elif key=='stage_flow':
                for stage,flow in value.items(): add('script:'+stage,json.dumps(flow,ensure_ascii=False))
            else: add('script:'+key, value if isinstance(value,str) else json.dumps(value,ensure_ascii=False))
        for index,message in enumerate(dm.state.public_history):
            add('public:'+str(index),message['content'],'testimony',dm.state.current_stage_num)
        if dm.workflow_settings.dm_reads_private_dialogue:
            for role in dm.state.ai_role_ids:
                for note in dm.agent_pool.get(role)._private_memory:
                    add('authorized-private:'+role+':'+note['source_key'],note['content'],'testimony',note['stage'])
        return records

    def sync_game(self, dm: Any):
        if not dm.runtime_scopes: return
        self.sync(dm.runtime_scopes['dm'],self.dm_records(dm))
        for role in dm.state.ai_role_ids:
            self.sync(dm.runtime_scopes['role:'+role],dm.agent_pool.get(role)._memory_records())
