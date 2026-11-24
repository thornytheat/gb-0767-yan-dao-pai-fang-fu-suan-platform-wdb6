import json
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from app.archive.manifest import canonical
from app.errors import InputError


class Archive:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS monitoring (id TEXT PRIMARY KEY, packet TEXT NOT NULL)')
            # 每个监测留档至多接受一套校时确认：UNIQUE 约束保证两班并发冲突只入库一套。
            db.execute('CREATE TABLE IF NOT EXISTS clock_confirmations ('
                       'run_id TEXT PRIMARY KEY, ticket TEXT NOT NULL, packet TEXT NOT NULL)')

    @contextmanager
    def connection(self):
        # check_same_thread=False：配合短连接与 timeout，允许两班并发提交，
        # 最终由 clock_confirmations 的 PRIMARY KEY 唯一约束裁决只入库一套。
        with closing(sqlite3.connect(self.path, timeout=15, check_same_thread=False)) as db:
            db.execute('PRAGMA busy_timeout=15000')
            with db:
                yield db

    def lookup(self, run_id):
        with self.connection() as db:
            row = db.execute('SELECT packet FROM monitoring WHERE id = ?', (run_id,)).fetchone()
        return None if row is None else json.loads(row[0])

    def require(self, run_id):
        packet = self.lookup(run_id)
        if packet is None:
            raise InputError('RUN_UNKNOWN', '找不到监测留档', 404)
        return packet

    def commit(self, run_id, packet):
        with self.connection() as db:
            cursor = db.execute('INSERT INTO monitoring VALUES (?, ?) ON CONFLICT(id) DO NOTHING',
                                (run_id, canonical(packet)))
            reused = cursor.rowcount == 0
            record = db.execute('SELECT packet FROM monitoring WHERE id = ?', (run_id,)).fetchone()[0]
        return json.loads(record), reused

    def history(self):
        with self.connection() as db:
            return [json.loads(row[0]) for row in db.execute(
                "SELECT json_extract(packet, '$.manifest') FROM monitoring ORDER BY rowid DESC LIMIT 100")]

    def clock_confirmation(self, run_id):
        with self.connection() as db:
            row = db.execute('SELECT packet FROM clock_confirmations WHERE run_id = ?', (run_id,)).fetchone()
        return None if row is None else json.loads(row[0])

    def require_effective(self, run_id):
        """取监测留档；若已确认校时，返回确认后重算的整包。"""
        packet = self.require(run_id)
        confirmation = self.clock_confirmation(run_id)
        return confirmation['packet'] if confirmation is not None else packet

    def save_clock_confirmation(self, run_id, ticket, meta, packet):
        """幂等写入第一套确认；并发下只有一个 INSERT 成功，其余看到已接受凭据。"""
        with self.connection() as db:
            db.execute('INSERT INTO clock_confirmations (run_id, ticket, packet) VALUES (?, ?, ?) '
                       'ON CONFLICT(run_id) DO NOTHING',
                       (run_id, ticket, canonical({'meta': meta, 'packet': packet})))
            row = db.execute('SELECT ticket, packet FROM clock_confirmations WHERE run_id = ?',
                             (run_id,)).fetchone()
        saved = json.loads(row[1])
        return row[0], saved['packet']
