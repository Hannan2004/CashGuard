import sqlite3
from pathlib import Path

DB_PATH = Path("app/data/cashguard.db")


def get_connection():
    return sqlite3.connect(DB_PATH)


def initialize_case_store():
    conn = get_connection()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cases (
            case_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    conn.commit()
    conn.close()


def upsert_case(case_id: str, status: str):
    conn = get_connection()

    conn.execute(
        """
        INSERT INTO cases(case_id, status)
        VALUES (?, ?)

        ON CONFLICT(case_id)
        DO UPDATE SET
            status = excluded.status,
            updated_at = CURRENT_TIMESTAMP
        """,
        (case_id, status),
    )

    conn.commit()
    conn.close()


def list_cases():
    conn = get_connection()

    rows = conn.execute(
        """
        SELECT case_id, status, updated_at
        FROM cases
        ORDER BY updated_at DESC
        """
    ).fetchall()

    conn.close()

    return [
        {
            "case_id": row[0],
            "status": row[1],
            "updated_at": row[2],
        }
        for row in rows
    ]