"""SQLite storage for Kota Kow: dictation history, analytics, API usage, and dictionary.

Features:
- Automatic 90-day rolling auto-purge on startup.
- Lazy-loading month -> date -> entries queries for snappy History browsing.
- Rich Manage History deletions (single item, day, month, 24h, 7d, 30d,
  keep last X days, custom date range, clear all).
- Dashboard metrics: total words, average WPM, daily streak, 90-day activity
  heatmap, desktop app usage breakdown, and today's Gemini/Groq API usage.
- Custom Dictionary CRUD.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from kotakow.config import get_db_path


@dataclass
class DictationEntry:
    id: int
    text: str
    word_count: int
    duration_sec: float
    app_name: str
    engine: str  # "gemini" | "groq"
    language_mode: str
    created_at: str  # ISO local timestamp "YYYY-MM-DD HH:MM:SS"
    day_key: str     # "YYYY-MM-DD"
    month_key: str   # "YYYY-MM"


@dataclass
class DictionaryTerm:
    id: int
    term: str
    note: str
    created_at: str


class Database:
    """Thread-safe SQLite wrapper stored in %APPDATA%\\KotaKow\\kotakow.db."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or get_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()
        self.purge_older_than_days(90)

    def _init_schema(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;

                CREATE TABLE IF NOT EXISTS dictations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    word_count INTEGER NOT NULL DEFAULT 0,
                    duration_sec REAL NOT NULL DEFAULT 0.0,
                    app_name TEXT NOT NULL DEFAULT 'Unknown',
                    engine TEXT NOT NULL DEFAULT 'gemini',
                    language_mode TEXT NOT NULL DEFAULT 'auto',
                    created_at TEXT NOT NULL,
                    day_key TEXT NOT NULL,
                    month_key TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_dictations_created_at ON dictations(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_dictations_month_day ON dictations(month_key DESC, day_key DESC);

                CREATE TABLE IF NOT EXISTS api_usage_daily (
                    day_key TEXT NOT NULL,
                    engine TEXT NOT NULL,
                    request_count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (day_key, engine)
                );

                CREATE TABLE IF NOT EXISTS dictionary (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    term TEXT NOT NULL UNIQUE,
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                """
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------
    # Dictation recording & API usage logging
    # ------------------------------------------------------------------

    @staticmethod
    def count_words(text: str) -> int:
        return len([w for w in text.strip().split() if w])

    def add_dictation(
        self,
        text: str,
        duration_sec: float,
        app_name: str,
        engine: str,
        language_mode: str,
        timestamp: datetime | None = None,
    ) -> int:
        now = timestamp or datetime.now()
        created_at = now.strftime("%Y-%m-%d %H:%M:%S")
        day_key = now.strftime("%Y-%m-%d")
        month_key = now.strftime("%Y-%m")
        word_count = self.count_words(text)
        clean_app = (app_name or "Unknown").strip() or "Unknown"
        clean_engine = (engine or "gemini").lower()

        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO dictations
                    (text, word_count, duration_sec, app_name, engine, language_mode, created_at, day_key, month_key)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    text,
                    word_count,
                    max(0.1, float(duration_sec)),
                    clean_app,
                    clean_engine,
                    language_mode,
                    created_at,
                    day_key,
                    month_key,
                ),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def increment_api_usage(self, engine: str, day_key: str | None = None) -> None:
        key = day_key or date.today().strftime("%Y-%m-%d")
        eng = engine.lower().strip()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO api_usage_daily (day_key, engine, request_count)
                VALUES (?, ?, 1)
                ON CONFLICT(day_key, engine)
                DO UPDATE SET request_count = request_count + 1
                """,
                (key, eng),
            )
            self._conn.commit()

    def get_today_api_usage(self) -> dict[str, int]:
        today = date.today().strftime("%Y-%m-%d")
        result = {"gemini": 0, "groq": 0}
        with self._lock:
            rows = self._conn.execute(
                "SELECT engine, request_count FROM api_usage_daily WHERE day_key = ?",
                (today,),
            ).fetchall()
            for r in rows:
                eng = str(r["engine"]).lower()
                if eng in result:
                    result[eng] = int(r["request_count"])
        return result

    # ------------------------------------------------------------------
    # Dashboard Analytics
    # ------------------------------------------------------------------

    def get_dashboard_stats(self) -> dict[str, Any]:
        with self._lock:
            summary = self._conn.execute(
                """
                SELECT
                    COUNT(*) AS total_sessions,
                    COALESCE(SUM(word_count), 0) AS total_words,
                    COALESCE(SUM(duration_sec), 0.0) AS total_duration
                FROM dictations
                """
            ).fetchone()

            total_sessions = int(summary["total_sessions"])
            total_words = int(summary["total_words"])
            total_duration = float(summary["total_duration"])
            avg_wpm = round((total_words / (total_duration / 60.0)), 1) if total_duration > 0.5 else 0.0

            # Daily activity over last 91 days (13 full weeks) for heatmap
            today = date.today()
            start_day = (today - timedelta(days=90)).strftime("%Y-%m-%d")
            day_rows = self._conn.execute(
                """
                SELECT day_key, SUM(word_count) AS words, COUNT(*) AS sessions
                FROM dictations
                WHERE day_key >= ?
                GROUP BY day_key
                """,
                (start_day,),
            ).fetchall()
            heatmap: dict[str, dict[str, int]] = {
                str(r["day_key"]): {"words": int(r["words"]), "sessions": int(r["sessions"])}
                for r in day_rows
            }

            # Compute current daily streak (ending today or yesterday if user hasn't dictated yet today)
            all_active_days = {
                str(r["day_key"])
                for r in self._conn.execute("SELECT DISTINCT day_key FROM dictations").fetchall()
            }
            streak = 0
            cursor_day = today
            if cursor_day.strftime("%Y-%m-%d") not in all_active_days:
                cursor_day = today - timedelta(days=1)
            while cursor_day.strftime("%Y-%m-%d") in all_active_days:
                streak += 1
                cursor_day -= timedelta(days=1)

            # Desktop app usage breakdown (top 6 + Others)
            app_rows = self._conn.execute(
                """
                SELECT app_name, COUNT(*) AS count, SUM(word_count) AS words
                FROM dictations
                GROUP BY app_name
                ORDER BY count DESC, words DESC
                """
            ).fetchall()
            app_usage: list[dict[str, Any]] = []
            if total_sessions > 0:
                top_rows = app_rows[:6]
                other_count = sum(int(r["count"]) for r in app_rows[6:])
                for r in top_rows:
                    cnt = int(r["count"])
                    app_usage.append(
                        {
                            "app_name": str(r["app_name"]),
                            "count": cnt,
                            "words": int(r["words"]),
                            "percent": round((cnt / total_sessions) * 100.0, 1),
                        }
                    )
                if other_count > 0:
                    app_usage.append(
                        {
                            "app_name": "Other Apps",
                            "count": other_count,
                            "words": sum(int(r["words"]) for r in app_rows[6:]),
                            "percent": round((other_count / total_sessions) * 100.0, 1),
                        }
                    )

            api_usage = self.get_today_api_usage()

            return {
                "total_sessions": total_sessions,
                "total_words": total_words,
                "avg_wpm": avg_wpm,
                "streak_days": streak,
                "active_days_90d": len(heatmap),
                "heatmap": heatmap,
                "app_usage": app_usage,
                "api_usage_today": api_usage,
            }

    # ------------------------------------------------------------------
    # Lazy-Loading History Queries
    # ------------------------------------------------------------------

    def get_months(self, search: str = "") -> list[dict[str, Any]]:
        """Return months with entry counts (newest first)."""
        with self._lock:
            q = search.strip()
            if q:
                like = f"%{q}%"
                rows = self._conn.execute(
                    """
                    SELECT month_key, COUNT(*) AS count, SUM(word_count) AS words
                    FROM dictations
                    WHERE text LIKE ? OR app_name LIKE ?
                    GROUP BY month_key
                    ORDER BY month_key DESC
                    """,
                    (like, like),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """
                    SELECT month_key, COUNT(*) AS count, SUM(word_count) AS words
                    FROM dictations
                    GROUP BY month_key
                    ORDER BY month_key DESC
                    """
                ).fetchall()
            return [
                {"month_key": str(r["month_key"]), "count": int(r["count"]), "words": int(r["words"])}
                for r in rows
            ]

    def get_days_in_month(self, month_key: str, search: str = "") -> list[dict[str, Any]]:
        """Return dates inside a given month (newest first)."""
        with self._lock:
            q = search.strip()
            if q:
                like = f"%{q}%"
                rows = self._conn.execute(
                    """
                    SELECT day_key, COUNT(*) AS count, SUM(word_count) AS words
                    FROM dictations
                    WHERE month_key = ? AND (text LIKE ? OR app_name LIKE ?)
                    GROUP BY day_key
                    ORDER BY day_key DESC
                    """,
                    (month_key, like, like),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """
                    SELECT day_key, COUNT(*) AS count, SUM(word_count) AS words
                    FROM dictations
                    WHERE month_key = ?
                    GROUP BY day_key
                    ORDER BY day_key DESC
                    """,
                    (month_key,),
                ).fetchall()
            return [
                {"day_key": str(r["day_key"]), "count": int(r["count"]), "words": int(r["words"])}
                for r in rows
            ]

    def get_entries_for_day(self, day_key: str, search: str = "") -> list[DictationEntry]:
        """Return all dictation entries for a specific date (newest first)."""
        with self._lock:
            q = search.strip()
            if q:
                like = f"%{q}%"
                rows = self._conn.execute(
                    """
                    SELECT * FROM dictations
                    WHERE day_key = ? AND (text LIKE ? OR app_name LIKE ?)
                    ORDER BY created_at DESC, id DESC
                    """,
                    (day_key, like, like),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """
                    SELECT * FROM dictations
                    WHERE day_key = ?
                    ORDER BY created_at DESC, id DESC
                    """,
                    (day_key,),
                ).fetchall()
            return [
                DictationEntry(
                    id=int(r["id"]),
                    text=str(r["text"]),
                    word_count=int(r["word_count"]),
                    duration_sec=float(r["duration_sec"]),
                    app_name=str(r["app_name"]),
                    engine=str(r["engine"]),
                    language_mode=str(r["language_mode"]),
                    created_at=str(r["created_at"]),
                    day_key=str(r["day_key"]),
                    month_key=str(r["month_key"]),
                )
                for r in rows
            ]

    # ------------------------------------------------------------------
    # History Deletion & 90-Day Auto-Purge
    # ------------------------------------------------------------------

    def purge_older_than_days(self, keep_days: int) -> int:
        cutoff = (datetime.now() - timedelta(days=max(0, int(keep_days)))).strftime("%Y-%m-%d %H:%M:%S")
        day_cutoff = (date.today() - timedelta(days=max(0, int(keep_days)))).strftime("%Y-%m-%d")
        with self._lock:
            cur = self._conn.execute("DELETE FROM dictations WHERE created_at < ?", (cutoff,))
            self._conn.execute("DELETE FROM api_usage_daily WHERE day_key < ?", (day_cutoff,))
            self._conn.commit()
            return cur.rowcount

    def delete_entry(self, entry_id: int) -> int:
        with self._lock:
            cur = self._conn.execute("DELETE FROM dictations WHERE id = ?", (entry_id,))
            self._conn.commit()
            return cur.rowcount

    def delete_day(self, day_key: str) -> int:
        with self._lock:
            cur = self._conn.execute("DELETE FROM dictations WHERE day_key = ?", (day_key,))
            self._conn.commit()
            return cur.rowcount

    def delete_month(self, month_key: str) -> int:
        with self._lock:
            cur = self._conn.execute("DELETE FROM dictations WHERE month_key = ?", (month_key,))
            self._conn.commit()
            return cur.rowcount

    def delete_last_hours(self, hours: int) -> int:
        cutoff = (datetime.now() - timedelta(hours=max(1, int(hours)))).strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            cur = self._conn.execute("DELETE FROM dictations WHERE created_at >= ?", (cutoff,))
            self._conn.commit()
            return cur.rowcount

    def delete_last_days(self, days: int) -> int:
        cutoff = (datetime.now() - timedelta(days=max(1, int(days)))).strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            cur = self._conn.execute("DELETE FROM dictations WHERE created_at >= ?", (cutoff,))
            self._conn.commit()
            return cur.rowcount

    def delete_date_range(self, start_day: str, end_day: str) -> int:
        """Delete all dictations where start_day <= day_key <= end_day (inclusive)."""
        lo, hi = (start_day, end_day) if start_day <= end_day else (end_day, start_day)
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM dictations WHERE day_key >= ? AND day_key <= ?",
                (lo, hi),
            )
            self._conn.commit()
            return cur.rowcount

    def clear_all_history(self) -> int:
        with self._lock:
            cur = self._conn.execute("DELETE FROM dictations")
            self._conn.commit()
            return cur.rowcount

    # ------------------------------------------------------------------
    # Custom Dictionary CRUD
    # ------------------------------------------------------------------

    def list_dictionary_terms(self) -> list[DictionaryTerm]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, term, note, created_at FROM dictionary ORDER BY term COLLATE NOCASE ASC"
            ).fetchall()
            return [
                DictionaryTerm(
                    id=int(r["id"]),
                    term=str(r["term"]),
                    note=str(r["note"]),
                    created_at=str(r["created_at"]),
                )
                for r in rows
            ]

    def get_dictionary_term_strings(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT term, note FROM dictionary ORDER BY term COLLATE NOCASE ASC"
            ).fetchall()
            out: list[str] = []
            for r in rows:
                t = str(r["term"]).strip()
                n = str(r["note"]).strip()
                if t:
                    out.append(f"{t} ({n})" if n else t)
            return out

    def add_dictionary_term(self, term: str, note: str = "") -> int:
        clean_term = term.strip()
        if not clean_term:
            raise ValueError("Term cannot be empty.")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO dictionary (term, note, created_at) VALUES (?, ?, ?)",
                (clean_term, note.strip(), now),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def update_dictionary_term(self, term_id: int, term: str, note: str = "") -> None:
        clean_term = term.strip()
        if not clean_term:
            raise ValueError("Term cannot be empty.")
        with self._lock:
            self._conn.execute(
                "UPDATE dictionary SET term = ?, note = ? WHERE id = ?",
                (clean_term, note.strip(), term_id),
            )
            self._conn.commit()

    def delete_dictionary_term(self, term_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM dictionary WHERE id = ?", (term_id,))
            self._conn.commit()
