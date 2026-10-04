from backend.db import database_connection, init_db


def test_database_initialization_creates_query_indexes():
    init_db()

    with database_connection() as connection:
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }

    assert {
        "idx_sessions_created_at",
        "idx_telemetry_session_timestamp",
        "idx_collisions_session_timestamp",
        "idx_safety_zones_active_name",
    } <= indexes
