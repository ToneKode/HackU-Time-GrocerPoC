"""Durable basket snapshots retained until captured orders are persisted."""
from __future__ import annotations

import json
import sqlite3
from collections.abc import MutableMapping
from pathlib import Path


class DraftStore(MutableMapping):
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS drafts (id TEXT PRIMARY KEY, body TEXT NOT NULL)")

    def _connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def __getitem__(self, key):
        with self._connect() as db:
            row = db.execute("SELECT body FROM drafts WHERE id = ?", (key,)).fetchone()
        if row is None:
            raise KeyError(key)
        return json.loads(row[0])

    def __setitem__(self, key, value):
        with self._connect() as db:
            db.execute("INSERT INTO drafts(id, body) VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET body=excluded.body",
                       (key, json.dumps(value, ensure_ascii=False)))

    def __delitem__(self, key):
        with self._connect() as db:
            if not db.execute("DELETE FROM drafts WHERE id = ?", (key,)).rowcount:
                raise KeyError(key)

    def __iter__(self):
        with self._connect() as db:
            keys = [row[0] for row in db.execute("SELECT id FROM drafts ORDER BY rowid")]
        return iter(keys)

    def __len__(self):
        with self._connect() as db:
            return db.execute("SELECT COUNT(*) FROM drafts").fetchone()[0]
