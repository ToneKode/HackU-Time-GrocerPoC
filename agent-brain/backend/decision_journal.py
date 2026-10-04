"""Append-only decision evidence committed before continuing a model tool turn."""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class DecisionJournal:
    def __init__(self, path):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path, timeout=10) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS agent_decisions (
                run_id TEXT NOT NULL, seq INTEGER NOT NULL, account_id TEXT NOT NULL,
                ts TEXT NOT NULL, evidence TEXT NOT NULL, prev_hash TEXT NOT NULL,
                hash TEXT NOT NULL, PRIMARY KEY(run_id,seq))''')

    def append(self, run_id, account_id, event):
        evidence = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
        ts = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.path, timeout=10) as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT seq,hash FROM agent_decisions WHERE run_id=? ORDER BY seq DESC LIMIT 1', (run_id,)).fetchone()
            seq, prev = (previous[0]+1, previous[1]) if previous else (0, '0'*64)
            material = json.dumps([run_id,seq,account_id,ts,evidence,prev], ensure_ascii=False, separators=(',', ':'))
            digest = hashlib.sha256(material.encode()).hexdigest()
            db.execute('INSERT INTO agent_decisions VALUES (?,?,?,?,?,?,?)', (run_id,seq,account_id,ts,evidence,prev,digest))
        return digest
