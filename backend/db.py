"""
SQLite Database Manager for RoboArm AI
Handles session recording, telemetry logs, collision events, and training runs.
"""

import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "roboarm.db"


def _row_to_dict(row, json_fields=()):
    result = dict(row)
    for field in json_fields:
        if result.get(field):
            result[field] = json.loads(result[field])
    return result


def get_connection():
    """Get a database connection, creating the DB file if needed."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Initialize database tables."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ended_at TIMESTAMP,
            duration_seconds REAL,
            mode TEXT DEFAULT 'manual',
            metadata TEXT DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS telemetry_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            timestamp REAL NOT NULL,
            joint_angles TEXT NOT NULL,
            joint_velocities TEXT,
            joint_torques TEXT,
            end_effector_pos TEXT,
            end_effector_orn TEXT,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS collision_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            timestamp REAL NOT NULL,
            body_a INTEGER,
            body_b INTEGER,
            link_a INTEGER,
            link_b INTEGER,
            contact_point TEXT,
            contact_normal TEXT,
            contact_force REAL,
            joint_angles_at_impact TEXT,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS training_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            algorithm TEXT DEFAULT 'PPO',
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ended_at TIMESTAMP,
            total_episodes INTEGER DEFAULT 0,
            total_timesteps INTEGER DEFAULT 0,
            best_reward REAL,
            checkpoint_path TEXT,
            config TEXT DEFAULT '{}',
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS training_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            episode INTEGER NOT NULL,
            timestep INTEGER NOT NULL,
            reward REAL,
            episode_length INTEGER,
            success INTEGER DEFAULT 0,
            loss REAL,
            entropy REAL,
            FOREIGN KEY (run_id) REFERENCES training_runs(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS safety_zones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            zone_type TEXT CHECK(zone_type IN ('keep_in', 'keep_out')) NOT NULL,
            min_x REAL NOT NULL, min_y REAL NOT NULL, min_z REAL NOT NULL,
            max_x REAL NOT NULL, max_y REAL NOT NULL, max_z REAL NOT NULL,
            color TEXT DEFAULT '#ff000080',
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS task_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            description TEXT,
            parameters TEXT DEFAULT '{}',
            trajectory TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    conn.commit()
    conn.close()


class SessionManager:
    """Manages simulation sessions."""

    @staticmethod
    def create_session(name: str, mode: str = "manual") -> int:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO sessions (name, mode) VALUES (?, ?)",
            (name, mode)
        )
        session_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return session_id

    @staticmethod
    def end_session(session_id: int):
        conn = get_connection()
        conn.execute(
            """UPDATE sessions SET ended_at = CURRENT_TIMESTAMP,
               duration_seconds = (julianday(CURRENT_TIMESTAMP) - julianday(created_at)) * 86400
               WHERE id = ?""",
            (session_id,)
        )
        conn.commit()
        conn.close()

    @staticmethod
    def get_sessions(limit: int = 50):
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM sessions ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        conn.close()
        return [_row_to_dict(row, ("metadata",)) for row in rows]

    @staticmethod
    def log_telemetry(session_id: int, timestamp: float,
                      joint_angles: list, joint_velocities: list = None,
                      joint_torques: list = None, ee_pos: list = None,
                      ee_orn: list = None):
        conn = get_connection()
        conn.execute(
            """INSERT INTO telemetry_logs
               (session_id, timestamp, joint_angles, joint_velocities,
                joint_torques, end_effector_pos, end_effector_orn)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (session_id, timestamp,
             json.dumps(joint_angles),
             json.dumps(joint_velocities) if joint_velocities else None,
             json.dumps(joint_torques) if joint_torques else None,
             json.dumps(ee_pos) if ee_pos else None,
             json.dumps(ee_orn) if ee_orn else None)
        )
        conn.commit()
        conn.close()

    @staticmethod
    def log_collision(session_id: int, timestamp: float, body_a: int,
                      body_b: int, link_a: int, link_b: int,
                      contact_point: list, contact_normal: list,
                      contact_force: float, joint_angles: list):
        conn = get_connection()
        conn.execute(
            """INSERT INTO collision_events
               (session_id, timestamp, body_a, body_b, link_a, link_b,
                contact_point, contact_normal, contact_force, joint_angles_at_impact)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, timestamp, body_a, body_b, link_a, link_b,
             json.dumps(contact_point), json.dumps(contact_normal),
             contact_force, json.dumps(joint_angles))
        )
        conn.commit()
        conn.close()

    @staticmethod
    def get_telemetry(session_id: int, limit: int = 1000):
        conn = get_connection()
        rows = conn.execute(
            """SELECT * FROM telemetry_logs WHERE session_id = ?
               ORDER BY timestamp DESC LIMIT ?""",
            (session_id, limit)
        ).fetchall()
        conn.close()
        json_fields = (
            "joint_angles", "joint_velocities", "joint_torques",
            "end_effector_pos", "end_effector_orn",
        )
        return [_row_to_dict(row, json_fields) for row in rows]

    @staticmethod
    def get_collisions(session_id: int):
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM collision_events WHERE session_id = ? ORDER BY timestamp",
            (session_id,)
        ).fetchall()
        conn.close()
        json_fields = (
            "contact_point", "contact_normal", "joint_angles_at_impact",
        )
        return [_row_to_dict(row, json_fields) for row in rows]


class SafetyZoneManager:
    """Manages workspace safety zones."""

    @staticmethod
    def create_zone(name: str, zone_type: str, min_bounds: list,
                    max_bounds: list, color: str = "#ff000080") -> int:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO safety_zones
               (name, zone_type, min_x, min_y, min_z, max_x, max_y, max_z, color)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, zone_type, *min_bounds, *max_bounds, color)
        )
        zone_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return zone_id

    @staticmethod
    def get_zones():
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM safety_zones WHERE active = 1 ORDER BY name"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @staticmethod
    def delete_zone(zone_id: int):
        conn = get_connection()
        conn.execute("UPDATE safety_zones SET active = 0 WHERE id = ?", (zone_id,))
        conn.commit()
        conn.close()

    @staticmethod
    def check_position(position: list) -> list:
        """Check if a position violates any safety zones. Returns list of violations."""
        zones = SafetyZoneManager.get_zones()
        violations = []
        x, y, z = position
        for zone in zones:
            inside = (zone['min_x'] <= x <= zone['max_x'] and
                      zone['min_y'] <= y <= zone['max_y'] and
                      zone['min_z'] <= z <= zone['max_z'])
            if zone['zone_type'] == 'keep_out' and inside:
                violations.append({
                    'zone': zone['name'], 'type': 'keep_out',
                    'message': f"Position inside keep-out zone '{zone['name']}'"
                })
            elif zone['zone_type'] == 'keep_in' and not inside:
                violations.append({
                    'zone': zone['name'], 'type': 'keep_in',
                    'message': f"Position outside keep-in zone '{zone['name']}'"
                })
        return violations
