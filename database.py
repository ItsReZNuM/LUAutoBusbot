import os
import json
import sqlite3
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database.sqlite")

def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    # Table for users and their sessions
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        telegram_id INTEGER PRIMARY KEY,
        phone TEXT,
        rana_session TEXT,
        csrf_token TEXT,
        user_name TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Table for user auto-reserve settings (no hardcoded stations)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_settings (
        telegram_id INTEGER PRIMARY KEY,
        enabled INTEGER DEFAULT 0,
        target_time TEXT DEFAULT '00:01',
        days TEXT DEFAULT '["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه"]',
        go_station_id TEXT DEFAULT '',
        go_station_name TEXT DEFAULT '',
        go_time TEXT DEFAULT '',
        return_station_id TEXT DEFAULT '',
        return_station_name TEXT DEFAULT '',
        return_time TEXT DEFAULT '',
        last_reserve_key TEXT DEFAULT '',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(telegram_id) REFERENCES users(telegram_id) ON DELETE CASCADE
    );
    """)

    # Table for user favorite stations/routes
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_favorites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER,
        station_type TEXT, -- 'go' or 'return'
        station_id TEXT,
        station_name TEXT,
        route_name TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(telegram_id, station_type, station_id)
    );
    """)

    conn.commit()
    conn.close()
    logger.info("Database initialized successfully.")

# ---------------- User Session Operations ----------------

def get_user(telegram_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def save_user_session(telegram_id, phone, rana_session, csrf_token=None, user_name=None):
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()

    cursor.execute("""
    INSERT INTO users (telegram_id, phone, rana_session, csrf_token, user_name, updated_at)
    VALUES (?, ?, ?, ?, ?, ?)
    ON CONFLICT(telegram_id) DO UPDATE SET
        phone = COALESCE(excluded.phone, users.phone),
        rana_session = excluded.rana_session,
        csrf_token = COALESCE(excluded.csrf_token, users.csrf_token),
        user_name = COALESCE(excluded.user_name, users.user_name),
        updated_at = excluded.updated_at;
    """, (telegram_id, phone, rana_session, csrf_token, user_name, now))

    conn.commit()
    conn.close()

def delete_user_session(telegram_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET rana_session = NULL, csrf_token = NULL WHERE telegram_id = ?", (telegram_id,))
    conn.commit()
    conn.close()

# ---------------- User Settings Operations ----------------

def get_user_settings(telegram_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM user_settings WHERE telegram_id = ?", (telegram_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
        data = dict(row)
        try:
            data["days"] = json.loads(data["days"])
        except Exception:
            data["days"] = ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه"]
        data["enabled"] = bool(data["enabled"])
        return data

    default = {
        "telegram_id": telegram_id,
        "enabled": False,
        "target_time": "00:01",
        "days": ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه"],
        "go_station_id": "",
        "go_station_name": "",
        "go_time": "",
        "return_station_id": "",
        "return_station_name": "",
        "return_time": "",
        "last_reserve_key": ""
    }
    save_user_settings(telegram_id, default)
    return default

def save_user_settings(telegram_id, settings_dict):
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()

    days_json = json.dumps(settings_dict.get("days", []), ensure_ascii=False)
    enabled_int = 1 if settings_dict.get("enabled") else 0
    target_time = settings_dict.get("target_time", "00:01")
    go_station_id = settings_dict.get("go_station_id", "")
    go_station_name = settings_dict.get("go_station_name", "")
    go_time = settings_dict.get("go_time", "")
    return_station_id = settings_dict.get("return_station_id", "")
    return_station_name = settings_dict.get("return_station_name", "")
    return_time = settings_dict.get("return_time", "")
    last_reserve_key = settings_dict.get("last_reserve_key", "")

    cursor.execute("""
    INSERT INTO user_settings (telegram_id, enabled, target_time, days, go_station_id, go_station_name, go_time, return_station_id, return_station_name, return_time, last_reserve_key, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(telegram_id) DO UPDATE SET
        enabled = excluded.enabled,
        target_time = excluded.target_time,
        days = excluded.days,
        go_station_id = excluded.go_station_id,
        go_station_name = excluded.go_station_name,
        go_time = excluded.go_time,
        return_station_id = excluded.return_station_id,
        return_station_name = excluded.return_station_name,
        return_time = excluded.return_time,
        last_reserve_key = excluded.last_reserve_key,
        updated_at = excluded.updated_at;
    """, (telegram_id, enabled_int, target_time, days_json, go_station_id, go_station_name, go_time, return_station_id, return_station_name, return_time, last_reserve_key, now))

    conn.commit()
    conn.close()

# ---------------- User Favorites Operations ----------------

def add_favorite(telegram_id, station_type, station_id, station_name, route_name):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO user_favorites (telegram_id, station_type, station_id, station_name, route_name)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(telegram_id, station_type, station_id) DO UPDATE SET
        station_name = excluded.station_name,
        route_name = excluded.route_name;
    """, (telegram_id, station_type, station_id, station_name, route_name))
    conn.commit()
    conn.close()

def remove_favorite(telegram_id, station_type, station_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM user_favorites WHERE telegram_id = ? AND station_type = ? AND station_id = ?",
                   (telegram_id, station_type, station_id))
    conn.commit()
    conn.close()

def is_favorite(telegram_id, station_type, station_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM user_favorites WHERE telegram_id = ? AND station_type = ? AND station_id = ?",
                   (telegram_id, station_type, station_id))
    row = cursor.fetchone()
    conn.close()
    return bool(row)

def get_favorites(telegram_id, station_type=None):
    conn = get_connection()
    cursor = conn.cursor()
    if station_type:
        cursor.execute("SELECT * FROM user_favorites WHERE telegram_id = ? AND station_type = ? ORDER BY id DESC",
                       (telegram_id, station_type))
    else:
        cursor.execute("SELECT * FROM user_favorites WHERE telegram_id = ? ORDER BY id DESC",
                       (telegram_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ---------------- Auto Reserve Active Users ----------------

def get_all_active_auto_users():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT u.telegram_id, u.phone, u.rana_session, u.csrf_token, u.user_name,
           s.enabled, s.target_time, s.days, s.go_station_id, s.go_station_name, s.go_time,
           s.return_station_id, s.return_station_name, s.return_time, s.last_reserve_key
    FROM user_settings s
    JOIN users u ON s.telegram_id = u.telegram_id
    WHERE s.enabled = 1 AND u.rana_session IS NOT NULL AND length(u.rana_session) > 5;
    """)
    rows = cursor.fetchall()
    conn.close()

    result = []
    for r in rows:
        d = dict(r)
        try:
            d["days"] = json.loads(d["days"])
        except Exception:
            d["days"] = []
        d["enabled"] = bool(d["enabled"])
        result.append(d)
    return result
