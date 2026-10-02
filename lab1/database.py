import sqlite3
from datetime import datetime, timezone
from pathlib import Path


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


def save_test_result(
    telegram_id: int,
    username: str | None,
    first_name: str | None,
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
