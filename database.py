import sqlite3
import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

DB_DIR = Path.home() / ".openflow"
DB_PATH = DB_DIR / "openflow.db"


class Database:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # History table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    raw_text TEXT NOT NULL,
                    formatted_text TEXT NOT NULL,
                    target_app TEXT,
                    target_window TEXT,
                    duration_seconds REAL,
                    word_count INTEGER,
                    tone_preset TEXT,
                    model_used TEXT,
                    device_used TEXT,
                    latency_ms INTEGER
                )
            """)
            # Custom vocabulary/dictionary replacement table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS dictionary (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    phrase_match TEXT UNIQUE NOT NULL,
                    replace_with TEXT NOT NULL,
                    case_sensitive INTEGER DEFAULT 0,
                    category TEXT DEFAULT 'general'
                )
            """)
            # Preload default dictionary examples if empty
            cursor.execute("SELECT COUNT(*) FROM dictionary")
            if cursor.fetchone()[0] == 0:
                default_terms = [
                    ("open flow", "OpenFlow", 0, "branding"),
                    ("whisper flow", "Wispr Flow", 0, "branding"),
                    ("git hub", "GitHub", 0, "tech"),
                    ("vs code", "VS Code", 0, "tech"),
                    ("pi torch", "PyTorch", 0, "tech"),
                    ("react js", "React.js", 0, "tech"),
                    ("node js", "Node.js", 0, "tech"),
                    ("cuda", "CUDA", 0, "tech"),
                    ("sqlite", "SQLite", 0, "tech"),
                ]
                cursor.executemany("""
                    INSERT OR IGNORE INTO dictionary (phrase_match, replace_with, case_sensitive, category)
                    VALUES (?, ?, ?, ?)
                """, default_terms)

            conn.commit()

    def add_history_entry(
        self,
        raw_text: str,
        formatted_text: str,
        target_app: str = "",
        target_window: str = "",
        duration_seconds: float = 0.0,
        word_count: int = 0,
        tone_preset: str = "smart_clean",
        model_used: str = "base.en",
        device_used: str = "cuda",
        latency_ms: int = 0
    ) -> int:
        now = datetime.datetime.now().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO history (
                    timestamp, raw_text, formatted_text, target_app, target_window,
                    duration_seconds, word_count, tone_preset, model_used, device_used, latency_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                now, raw_text, formatted_text, target_app, target_window,
                duration_seconds, word_count, tone_preset, model_used, device_used, latency_ms
            ))
            conn.commit()
            return cursor.lastrowid if cursor.lastrowid is not None else 0

    def get_history(self, limit: int = 100, query: str = "") -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if query:
                q = f"%{query}%"
                cursor.execute("""
                    SELECT * FROM history 
                    WHERE formatted_text LIKE ? OR raw_text LIKE ? OR target_app LIKE ?
                    ORDER BY id DESC LIMIT ?
                """, (q, q, q, limit))
            else:
                cursor.execute("SELECT * FROM history ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def delete_history_entry(self, entry_id: int):
        with self._get_connection() as conn:
            conn.execute("DELETE FROM history WHERE id = ?", (entry_id,))
            conn.commit()

    def clear_history(self):
        with self._get_connection() as conn:
            conn.execute("DELETE FROM history")
            conn.commit()

    def get_stats(self) -> Dict[str, Any]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*), COALESCE(SUM(word_count), 0), COALESCE(SUM(duration_seconds), 0) FROM history")
            total_dictations, total_words, total_duration = cursor.fetchone()
            
            # Estimate time saved (assuming average typing speed of 40 WPM vs speaking 150 WPM)
            typing_minutes = total_words / 40.0 if total_words > 0 else 0
            speaking_minutes = total_duration / 60.0
            time_saved_minutes = max(0.0, typing_minutes - speaking_minutes)

            return {
                "total_dictations": total_dictations,
                "total_words": total_words,
                "total_duration_seconds": round(total_duration, 1),
                "time_saved_minutes": round(time_saved_minutes, 1),
                "time_saved_hours": round(time_saved_minutes / 60.0, 2),
            }

    def get_dictionary(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM dictionary ORDER BY id ASC")
            return [dict(row) for row in cursor.fetchall()]

    def add_dictionary_entry(self, phrase_match: str, replace_with: str, case_sensitive: bool = False, category: str = "general") -> bool:
        try:
            with self._get_connection() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO dictionary (phrase_match, replace_with, case_sensitive, category)
                    VALUES (?, ?, ?, ?)
                """, (phrase_match.strip(), replace_with.strip(), 1 if case_sensitive else 0, category))
                conn.commit()
                return True
        except Exception:
            return False

    def delete_dictionary_entry(self, entry_id: int):
        with self._get_connection() as conn:
            conn.execute("DELETE FROM dictionary WHERE id = ?", (entry_id,))
            conn.commit()
