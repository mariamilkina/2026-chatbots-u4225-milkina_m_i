import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple


DB_PATH = Path(__file__).with_name("englishmate.db")


def get_connection() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def init_db() -> None:
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                level TEXT,
                goal TEXT,
                score INTEGER NOT NULL DEFAULT 0,
                total_questions INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            )
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS lesson_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                level TEXT NOT NULL,
                goal TEXT NOT NULL,
                score INTEGER NOT NULL,
                total_questions INTEGER NOT NULL,
                percentage REAL NOT NULL,
                completed_at TEXT NOT NULL,
                FOREIGN KEY (telegram_id) REFERENCES users (telegram_id)
            )
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_lesson_results_user
            ON lesson_results (telegram_id)
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS saved_words (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                word TEXT NOT NULL COLLATE NOCASE,
                phonetic TEXT,
                part_of_speech TEXT,
                definition TEXT NOT NULL,
                example TEXT,
                added_at TEXT NOT NULL,
                UNIQUE (telegram_id, word)
            )
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_saved_words_user
            ON saved_words (telegram_id, added_at DESC)
            """
        )


def save_test_result(
    telegram_id: int,
    username: Optional[str],
    first_name: Optional[str],
    level: str,
    score: int,
    total_questions: int,
) -> None:
    updated_at = datetime.now(timezone.utc).isoformat()

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO users (
                telegram_id, username, first_name, level, goal,
                score, total_questions, updated_at
            )
            VALUES (?, ?, ?, ?, NULL, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                level = excluded.level,
                goal = NULL,
                score = excluded.score,
                total_questions = excluded.total_questions,
                updated_at = excluded.updated_at
            """,
            (
                telegram_id,
                username,
                first_name,
                level,
                score,
                total_questions,
                updated_at,
            ),
        )


def update_goal(telegram_id: int, goal: str) -> None:
    updated_at = datetime.now(timezone.utc).isoformat()

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE users
            SET goal = ?, updated_at = ?
            WHERE telegram_id = ?
            """,
            (goal, updated_at, telegram_id),
        )


def get_user(telegram_id: int):
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT telegram_id, username, level, goal, score, total_questions
            FROM users
            WHERE telegram_id = ?
            """,
            (telegram_id,),
        ).fetchone()


def save_lesson_result(
    telegram_id: int,
    level: str,
    goal: str,
    score: int,
    total_questions: int,
    percentage: float,
) -> None:
    completed_at = datetime.now(timezone.utc).isoformat()

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO lesson_results (
                telegram_id, level, goal, score,
                total_questions, percentage, completed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                telegram_id,
                level,
                goal,
                score,
                total_questions,
                percentage,
                completed_at,
            ),
        )


def get_lesson_stats(telegram_id: int) -> Tuple[int, float]:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT COUNT(*), COALESCE(AVG(percentage), 0)
            FROM lesson_results
            WHERE telegram_id = ?
            """,
            (telegram_id,),
        ).fetchone()

    return int(row[0]), float(row[1])



def save_word(
    telegram_id: int,
    word: str,
    phonetic: Optional[str],
    part_of_speech: Optional[str],
    definition: str,
    example: Optional[str],
) -> bool:
    added_at = datetime.now(timezone.utc).isoformat()

    try:
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO saved_words (
                    telegram_id, word, phonetic, part_of_speech,
                    definition, example, added_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    telegram_id,
                    word,
                    phonetic,
                    part_of_speech,
                    definition,
                    example,
                    added_at,
                ),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def get_saved_words(telegram_id: int, limit: int = 10):
    limit = max(1, min(int(limit), 50))

    with get_connection() as connection:
        return connection.execute(
            """
            SELECT
                word,
                phonetic,
                part_of_speech,
                definition,
                example,
                added_at
            FROM saved_words
            WHERE telegram_id = ?
            ORDER BY added_at DESC
            LIMIT ?
            """,
            (telegram_id, limit),
        ).fetchall()
