import sqlite3
import time

DB_NAME = "database.db"


def _connect():
    return sqlite3.connect(DB_NAME)


def init_db():
    conn = _connect()
    cur = conn.cursor()

    # --- Users ---
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT
    )
    """)

    # --- Queue ---
    cur.execute("""
    CREATE TABLE IF NOT EXISTS queue (
        user_id INTEGER PRIMARY KEY
    )
    """)

    # --- Chats ---
    cur.execute("""
    CREATE TABLE IF NOT EXISTS chats (
        user1_id INTEGER,
        user2_id INTEGER,
        PRIMARY KEY (user1_id, user2_id)
    )
    """)

    # --- Reports ---
    cur.execute("""
    CREATE TABLE IF NOT EXISTS reports (
        reporter_id INTEGER,
        reported_id INTEGER,
        reason TEXT,
        timestamp INTEGER
    )
    """)

    # --- Blocks ---
    cur.execute("""
    CREATE TABLE IF NOT EXISTS blocks (
        user_id INTEGER PRIMARY KEY
    )
    """)

    # --- Limits ---
    cur.execute("""
    CREATE TABLE IF NOT EXISTS limits (
        user_id INTEGER PRIMARY KEY,
        used_count INTEGER DEFAULT 0,
        reset_time INTEGER,
        premium INTEGER DEFAULT 0
    )
    """)

    conn.commit()
    conn.close()


# ---------------- USERS ----------------
def add_user(user_id, username, first_name, last_name):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("""
    INSERT OR REPLACE INTO users (user_id, username, first_name, last_name)
    VALUES (?, ?, ?, ?)
    """, (user_id, username, first_name, last_name))
    conn.commit()
    conn.close()


# ---------------- QUEUE ----------------
def add_to_queue(user_id):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO queue (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()


def remove_from_queue(user_id):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM queue WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def get_first_in_queue(exclude_user_id=None):
    conn = _connect()
    cur = conn.cursor()
    if exclude_user_id:
        cur.execute("SELECT user_id FROM queue WHERE user_id != ? ORDER BY ROWID ASC LIMIT 1", (exclude_user_id,))
    else:
        cur.execute("SELECT user_id FROM queue ORDER BY ROWID ASC LIMIT 1")
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


# ---------------- CHATS ----------------
def add_chat(user1_id, user2_id):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("INSERT INTO chats (user1_id, user2_id) VALUES (?, ?)", (user1_id, user2_id))
    conn.commit()
    conn.close()


def get_partner(user_id):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT user2_id FROM chats WHERE user1_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        cur.execute("SELECT user1_id FROM chats WHERE user2_id = ?", (user_id,))
        row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def remove_chat_by_users(user1_id, user2_id):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM chats WHERE (user1_id = ? AND user2_id = ?) OR (user1_id = ? AND user2_id = ?)",
                (user1_id, user2_id, user2_id, user1_id))
    conn.commit()
    conn.close()


# ---------------- REPORTS ----------------
def add_report(reporter_id: int, reported_id: int, reason: str = "No reason provided"):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("INSERT INTO reports (reporter_id, reported_id, reason, timestamp) VALUES (?, ?, ?, ?)",
                (reporter_id, reported_id, reason, int(time.time())))
    conn.commit()
    conn.close()


# ---------------- BLOCKS ----------------
def block_user(user_id):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO blocks (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()


def unblock_user(user_id):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM blocks WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def is_blocked(user_id):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM blocks WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return bool(row)


# ---------------- LIMITS ----------------
def get_limit_info(user_id: int):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT used_count, reset_time, premium FROM limits WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return {"used_count": row[0], "reset_time": row[1], "premium": row[2]} if row else {"used_count": 0, "reset_time": 0, "premium": 0}


def update_limit(user_id: int, used_count: int, reset_time: int, premium: int):
    conn = _connect()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO limits (user_id, used_count, reset_time, premium)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET 
            used_count=excluded.used_count,
            reset_time=excluded.reset_time,
            premium=excluded.premium
    """, (user_id, used_count, reset_time, premium))
    conn.commit()
    conn.close()


def get_stats():
    conn = _connect()
    cur = conn.cursor()

    # Users
    cur.execute("SELECT COUNT(*) FROM users")
    users_count = cur.fetchone()[0]

    # Reports
    cur.execute("SELECT COUNT(*) FROM reports")
    reports_count = cur.fetchone()[0]

    # Chats
    cur.execute("SELECT COUNT(*) FROM chats")
    chats_count = cur.fetchone()[0]

    # Queue
    cur.execute("SELECT COUNT(*) FROM queue")
    queue_count = cur.fetchone()[0]

    conn.close()

    return {
        "users": users_count,
        "reports": reports_count,
        "active_chats": chats_count,
        "queue": queue_count
    }
