"""SQLite metadata storage (spec §45).

Stores event metadata, rules, actions, verifications, and sessions.
No video table. No media blobs.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    type TEXT NOT NULL,
    source TEXT,
    payload_json TEXT,
    confidence REAL
);
CREATE TABLE IF NOT EXISTS rules (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    definition_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT,
    timestamp TEXT NOT NULL,
    action_type TEXT NOT NULL,
    detail TEXT,
    approved INTEGER,
    decision_reason TEXT
);
CREATE TABLE IF NOT EXISTS verifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_id INTEGER,
    timestamp TEXT NOT NULL,
    verified INTEGER NOT NULL,
    detail TEXT,
    method TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    mode TEXT,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


class Database:
    def __init__(self, path: str = "data/events.db") -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.Lock()
        with self._lock, self._conn:
            self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- events ----------------------------------------------------------
    def insert_event(self, event) -> None:
        payload = {
            "text": event.text,
            "url": event.url,
            "region": event.region,
        }
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO events (id, timestamp, type, source, payload_json, confidence) VALUES (?,?,?,?,?,?)",
                (event.id, event.timestamp, event.type.value, event.source, json.dumps(payload), event.confidence),
            )

    def list_events(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, timestamp, type, source, payload_json, confidence FROM events ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        out = []
        for r in rows:
            out.append(
                {
                    "id": r[0],
                    "timestamp": r[1],
                    "type": r[2],
                    "source": r[3],
                    "payload": json.loads(r[4]) if r[4] else {},
                    "confidence": r[5],
                }
            )
        return out

    # -- actions ----------------------------------------------------------
    def insert_action(self, event_id: Optional[str], timestamp: str, action_type: str, detail: str, approved: Optional[bool], reason: str) -> int:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO actions (event_id, timestamp, action_type, detail, approved, decision_reason) VALUES (?,?,?,?,?,?)",
                (event_id, timestamp, action_type, detail, approved, reason),
            )
            return int(cur.lastrowid or 0)

    def list_actions(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, event_id, timestamp, action_type, detail, approved, decision_reason FROM actions ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "id": r[0], "event_id": r[1], "timestamp": r[2], "action_type": r[3],
                "detail": r[4], "approved": bool(r[5]) if r[5] is not None else None,
                "reason": r[6],
            }
            for r in rows
        ]

    # -- verifications ------------------------------------------------------
    def insert_verification(self, action_id: int, timestamp: str, verified: bool, detail: str, method: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO verifications (action_id, timestamp, verified, detail, method) VALUES (?,?,?,?,?)",
                (action_id, timestamp, verified, detail, method),
            )

    # -- rules ---------------------------------------------------------------
    def upsert_rule(self, rule_id: str, name: str, enabled: bool, definition_json: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO rules (id, name, enabled, definition_json) VALUES (?,?,?,?)",
                (rule_id, name, enabled, definition_json),
            )

    def list_rules(self) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT id, name, enabled, definition_json FROM rules").fetchall()
        return [
            {"id": r[0], "name": r[1], "enabled": bool(r[2]), "definition": json.loads(r[3]) if r[3] else {}}
            for r in rows
        ]

    # -- sessions ------------------------------------------------------------
    def start_session(self, started_at: str, mode: str) -> int:
        with self._lock, self._conn:
            cur = self._conn.execute("INSERT INTO sessions (started_at, mode) VALUES (?,?)", (started_at, mode))
            return int(cur.lastrowid or 0)

    def end_session(self, session_id: int, ended_at: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("UPDATE sessions SET ended_at=? WHERE id=?", (ended_at, session_id))
