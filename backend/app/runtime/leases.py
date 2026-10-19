"""SQLite controller ownership and crash-safe clock checkpoints."""
from __future__ import annotations

import time
import uuid

from runtime.contracts import RuntimeAccessError


class GameLeases:
    def __init__(self, store):
        self.store = store
        self.owner_id = str(uuid.uuid4())
        with store._connect() as connection:
            connection.execute('''CREATE TABLE IF NOT EXISTS game_leases (
                game_id INTEGER PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,
                owner_id TEXT NOT NULL, controller_id TEXT NOT NULL, run_id TEXT,
                status TEXT NOT NULL, heartbeat_at REAL NOT NULL, expires_at REAL NOT NULL)''')

    def claim(self, user_id, game_id, controller_id, settings, *, now=None):
        now = time.time() if now is None else now
        with self.store.transaction() as connection:
            game = self.store.get_game(user_id, game_id)
            previous = connection.execute('SELECT * FROM game_leases WHERE game_id=?', (game_id,)).fetchone()
            if previous and previous['expires_at'] > now:
                reserved = previous['status']=='reserved' and previous['controller_id']==controller_id
                if not reserved:
                    raise RuntimeAccessError('本场游戏由另一个窗口控制，可等待租约到期或明确接管')
            if previous and previous['status']=='active' and game['status']=='playing':
                # The last durable heartbeat is the crash boundary. No offline time is consumed.
                snapshot=self.store.get_runtime_snapshot(user_id,game_id)
                anchor=max(previous['heartbeat_at'],(snapshot or {}).get('saved_at_epoch',0))
                self.store.set_game_lifecycle(game_id, paused_at=anchor, status='paused')
                connection.execute("UPDATE game_runs SET status='interrupted' WHERE game_id=? AND status='active'", (game_id,))
            connection.execute('''INSERT INTO game_leases VALUES (?,?,?,?,?,?,?) ON CONFLICT(game_id) DO UPDATE SET
                owner_id=excluded.owner_id,controller_id=excluded.controller_id,run_id=NULL,status='active',
                heartbeat_at=excluded.heartbeat_at,expires_at=excluded.expires_at''',
                (game_id,self.owner_id,controller_id,None,'active',now,now+settings.lease_seconds))

    def bind(self, game_id, run_id):
        with self.store._connect() as connection:
            connection.execute("UPDATE game_leases SET run_id=? WHERE game_id=? AND owner_id=? AND status='active'",
                               (run_id,game_id,self.owner_id))

    def heartbeat(self, game_id, settings, *, now=None):
        now = time.time() if now is None else now
        with self.store.transaction() as connection:
            row = connection.execute('SELECT * FROM game_leases WHERE game_id=?', (game_id,)).fetchone()
            game = connection.execute('SELECT run_id,status FROM games WHERE id=?', (game_id,)).fetchone()
            if not row or row['owner_id']!=self.owner_id or row['status']!='active' or row['expires_at']<=now:
                raise RuntimeAccessError('游戏控制租约已失效')
            if row['run_id'] and (not game or row['run_id']!=game['run_id'] or game['status']=='paused'):
                raise RuntimeAccessError('本场游戏已暂停或被其他窗口接管')
            connection.execute('UPDATE game_leases SET heartbeat_at=?,expires_at=? WHERE game_id=?',
                               (now,now+settings.lease_seconds,game_id))

    def owned(self, game_id):
        with self.store._connect() as connection:
            row = connection.execute('SELECT * FROM game_leases WHERE game_id=?', (game_id,)).fetchone()
        return bool(row and row['owner_id']==self.owner_id and row['status']=='active')

    def release(self, game_id, settings):
        with self.store._connect() as connection:
            connection.execute("UPDATE game_leases SET status='reserved', expires_at=? WHERE game_id=? AND owner_id=? AND status='active'",
                               (time.time()+settings.reconnect_grace_seconds,game_id,self.owner_id))

    def invalidate(self, user_id, game_id):
        with self.store.transaction() as connection:
            game = self.store.get_game(user_id,game_id)
            row = connection.execute('SELECT * FROM game_leases WHERE game_id=?', (game_id,)).fetchone()
            if game['status']=='playing':
                now=time.time()
                anchor=now if row is None or row['expires_at']>now else row['heartbeat_at']
                self.store.set_game_lifecycle(game_id,paused_at=anchor,status='paused')
            connection.execute("UPDATE game_runs SET status='interrupted' WHERE game_id=? AND status='active'", (game_id,))
            connection.execute('DELETE FROM game_leases WHERE game_id=?', (game_id,))
        return self.store.get_game(user_id,game_id)
