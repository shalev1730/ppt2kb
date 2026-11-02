"""
SQLite persistence for jobs and slides.

A single-file SQLite database (WAL mode) is sufficient for an internal tool
that processes one presentation at a time; it keeps the deployment free of
external services and survives restarts, which is what makes "resume after
interruption" and "retry one slide" possible.

Slide content is stored here, so the data directory must be protected like
the presentations themselves (see docs/SECURITY_REVIEW.md).
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ..schemas.deck import DeckData, JobStatus, SlideData, SlideDescription, SlideStatus

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    slide_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_sha256 TEXT NOT NULL DEFAULT '',
    source_kind TEXT NOT NULL DEFAULT 'pptx',
    source_size INTEGER NOT NULL DEFAULT 0,
    macro_enabled INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    model TEXT NOT NULL DEFAULT '',
    kb_sys_id TEXT NOT NULL DEFAULT '',
    servicenow_json TEXT NOT NULL DEFAULT '{}',
    options_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS slides (
    job_id TEXT NOT NULL,
    number INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    original_text TEXT NOT NULL DEFAULT '',
    notes_text TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    edited_content TEXT,
    description_json TEXT,
    image_ref TEXT NOT NULL DEFAULT '',
    image_sha256 TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    model TEXT NOT NULL DEFAULT '',
    processed_at TEXT,
    render_error TEXT,
    attachment_sys_id TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (job_id, number),
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
"""


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        with self._lock:
            self._conn.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---------------------------------------------------------------- helpers
    def _exec(self, sql: str, params: Iterable[Any] = ()) -> None:
        with self._lock:
            self._conn.execute(sql, tuple(params))

    def _one(self, sql: str, params: Iterable[Any] = ()) -> Optional[sqlite3.Row]:
        # fetch inside the lock: the connection is shared between threads
        with self._lock:
            return self._conn.execute(sql, tuple(params)).fetchone()

    def _all(self, sql: str, params: Iterable[Any] = ()) -> List[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, tuple(params))

    # ------------------------------------------------------------------ jobs
    def create_job(self, *, job_id: str, display_name: str, title: str, source_path: str, source_sha256: str,
                   source_kind: str, source_size: int, macro_enabled: bool, options: Optional[dict] = None) -> None:
        ts = now_iso()
        self._exec(
            "INSERT INTO jobs (id, display_name, title, status, created_at, updated_at, source_path, source_sha256, "
            "source_kind, source_size, macro_enabled, options_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (job_id, display_name, title, JobStatus.uploaded.value, ts, ts, source_path, source_sha256, source_kind,
             source_size, int(macro_enabled), json.dumps(options or {})),
        )

    def update_job(self, job_id: str, **fields: Any) -> None:
        if not fields:
            return
        fields["updated_at"] = now_iso()
        if "status" in fields and isinstance(fields["status"], JobStatus):
            fields["status"] = fields["status"].value
        if "servicenow" in fields:
            fields["servicenow_json"] = json.dumps(fields.pop("servicenow"))
        if "options" in fields:
            fields["options_json"] = json.dumps(fields.pop("options"))
        cols = ", ".join(f"{k} = ?" for k in fields)
        self._exec(f"UPDATE jobs SET {cols} WHERE id = ?", (*fields.values(), job_id))

    def get_job(self, job_id: str) -> Optional[dict]:
        row = self._one("SELECT * FROM jobs WHERE id = ?", (job_id,))
        return self._job_row(row) if row else None

    def list_jobs(self, limit: int = 100) -> List[dict]:
        rows = self._all("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,))
        return [self._job_row(r) for r in rows]

    def jobs_with_status(self, statuses: Iterable[str]) -> List[dict]:
        st = list(statuses)
        q = ",".join("?" for _ in st)
        rows = self._all(f"SELECT * FROM jobs WHERE status IN ({q})", st)
        return [self._job_row(r) for r in rows]

    def delete_job(self, job_id: str) -> None:
        self._exec("DELETE FROM slides WHERE job_id = ?", (job_id,))
        self._exec("DELETE FROM jobs WHERE id = ?", (job_id,))

    def old_jobs(self, older_than_iso: str) -> List[dict]:
        rows = self._all("SELECT * FROM jobs WHERE created_at < ?", (older_than_iso,))
        return [self._job_row(r) for r in rows]

    @staticmethod
    def _job_row(row: sqlite3.Row) -> dict:
        d = dict(row)
        d["servicenow"] = json.loads(d.pop("servicenow_json") or "{}")
        d["options"] = json.loads(d.pop("options_json") or "{}")
        d["macro_enabled"] = bool(d["macro_enabled"])
        return d

    # ---------------------------------------------------------------- slides
    def upsert_slides(self, job_id: str, slides: Iterable[SlideData]) -> None:
        with self._lock:
            for s in slides:
                self._conn.execute(
                    "INSERT INTO slides (job_id, number, title, original_text, notes_text, content, edited_content, "
                    "description_json, image_ref, image_sha256, status, error, attempts, model, processed_at, render_error) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(job_id, number) DO UPDATE SET title=excluded.title, original_text=excluded.original_text, "
                    "notes_text=excluded.notes_text, image_ref=excluded.image_ref, image_sha256=excluded.image_sha256, "
                    "render_error=excluded.render_error",
                    (job_id, s.number, s.title, s.original_text, s.notes_text, s.content, s.edited_content,
                     s.description.model_dump_json() if s.description else None, s.image_ref, s.image_sha256,
                     s.status.value, s.error, s.attempts, s.model, s.processed_at, s.render_error),
                )

    def update_slide(self, job_id: str, number: int, **fields: Any) -> None:
        if not fields:
            return
        if "status" in fields and isinstance(fields["status"], SlideStatus):
            fields["status"] = fields["status"].value
        if "description" in fields:
            d = fields.pop("description")
            fields["description_json"] = d.model_dump_json() if d is not None else None
        cols = ", ".join(f"{k} = ?" for k in fields)
        self._exec(f"UPDATE slides SET {cols} WHERE job_id = ? AND number = ?", (*fields.values(), job_id, number))

    def increment_attempts(self, job_id: str, number: int) -> None:
        self._exec("UPDATE slides SET attempts = attempts + 1 WHERE job_id = ? AND number = ?", (job_id, number))

    def get_slides(self, job_id: str) -> List[SlideData]:
        rows = self._all("SELECT * FROM slides WHERE job_id = ? ORDER BY number", (job_id,))
        return [self._slide_row(r) for r in rows]

    def get_slide(self, job_id: str, number: int) -> Optional[SlideData]:
        row = self._one("SELECT * FROM slides WHERE job_id = ? AND number = ?", (job_id, number))
        return self._slide_row(row) if row else None

    def slide_status_counts(self, job_id: str) -> Dict[str, int]:
        rows = self._all("SELECT status, COUNT(*) AS n FROM slides WHERE job_id = ? GROUP BY status", (job_id,))
        counts = {s.value: 0 for s in SlideStatus}
        for r in rows:
            counts[r["status"]] = r["n"]
        return counts

    def attachment_map(self, job_id: str) -> Dict[int, str]:
        rows = self._all("SELECT number, attachment_sys_id FROM slides WHERE job_id = ? AND attachment_sys_id != ''", (job_id,))
        return {r["number"]: r["attachment_sys_id"] for r in rows}

    @staticmethod
    def _slide_row(row: sqlite3.Row) -> SlideData:
        d = dict(row)
        desc = d.pop("description_json")
        d.pop("attachment_sys_id", None)
        d["presentation_id"] = d.pop("job_id")
        d["status"] = SlideStatus(d["status"])
        d["description"] = SlideDescription.model_validate_json(desc) if desc else None
        return SlideData(**d)

    # ------------------------------------------------------------------ deck
    def deck(self, job_id: str) -> Optional[DeckData]:
        job = self.get_job(job_id)
        if not job:
            return None
        slides = self.get_slides(job_id)
        for s in slides:
            s.presentation_id = job_id
        return DeckData(
            deck=job["display_name"],
            model=job["model"],
            slides=slides,
            presentation_id=job_id,
            title=job["title"],
            status=JobStatus(job["status"]),
            slide_count=job["slide_count"],
            created_at=job["created_at"],
            updated_at=job["updated_at"],
            source_sha256=job["source_sha256"],
            servicenow=job["servicenow"],
        )

    # -------------------------------------------------------------- settings
    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self._one("SELECT value FROM settings WHERE key = ?", (key,))
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self._exec("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))

    def delete_setting(self, key: str) -> None:
        self._exec("DELETE FROM settings WHERE key = ?", (key,))

    def all_settings(self) -> Dict[str, str]:
        rows = self._all("SELECT key, value FROM settings")
        return {r["key"]: r["value"] for r in rows}
