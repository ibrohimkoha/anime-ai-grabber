import sqlite3
from datetime import datetime
from config import DB_PATH

def get_db():
    return sqlite3.connect(DB_PATH, timeout=30.0)

def init_db():
    """Ma'lumotlar bazasi jadvallarini yaratadi."""
    conn = get_db()
    cursor = conn.cursor()
    
    # 1. Sozlamalar jadvali (Telegram orqali dinamik boshqarish uchun)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    
    # 2. Yuklangan relizlar jadvali
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS grabbed_releases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_channel TEXT,
            source_msg_id INTEGER,
            anime_name TEXT,
            season INTEGER,
            episode INTEGER,
            studio TEXT,
            bot_username TEXT,
            start_param TEXT,
            video_msg_id INTEGER,
            status TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_anime_ep_studio 
        ON grabbed_releases(anime_name, season, episode, studio)
    """)
    conn.commit()
    conn.close()

def get_setting(key: str, default: str = "") -> str:
    """Sozlamani bazadan oladi."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else default

def set_setting(key: str, value: str):
    """Sozlamani bazaga saqlaydi yoki yangilaydi."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO settings (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
    """, (key, str(value)))
    conn.commit()
    conn.close()

def is_already_grabbed(anime_name: str, season: int, episode: int, studio: str) -> bool:
    """Ushbu qism allaqachon yuklanganligini tekshiradi."""
    if not anime_name or not episode:
        return False
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id FROM grabbed_releases 
        WHERE LOWER(anime_name) = LOWER(?) AND season = ? AND episode = ? AND LOWER(studio) = LOWER(?) AND status = 'COMPLETED'
    """, (anime_name, season, episode, studio))
    row = cursor.fetchone()
    conn.close()
    return row is not None

def log_release(source_channel: str, source_msg_id: int, anime_name: str, 
                season: int, episode: int, studio: str, bot_username: str, 
                start_param: str, status: str = "PENDING", video_msg_id: int = None):
    """Yangi ushlangan relizni bazaga yozadi."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO grabbed_releases 
        (source_channel, source_msg_id, anime_name, season, episode, studio, bot_username, start_param, video_msg_id, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (str(source_channel), source_msg_id, anime_name, season, episode, studio, bot_username, start_param, video_msg_id, status))
    conn.commit()
    conn.close()

def update_status(anime_name: str, season: int, episode: int, studio: str, status: str, video_msg_id: int = None):
    """Reliz holatini yangilaydi (COMPLETED / FAILED)."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE grabbed_releases 
        SET status = ?, video_msg_id = ?
        WHERE LOWER(anime_name) = LOWER(?) AND season = ? AND episode = ? AND LOWER(studio) = LOWER(?)
    """, (status, video_msg_id, anime_name, season, episode, studio))
    conn.commit()
    conn.close()

def get_stats():
    """Statistikani qaytaradi."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM grabbed_releases WHERE status = 'COMPLETED'")
    completed = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM grabbed_releases WHERE status = 'FAILED'")
    failed = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM grabbed_releases WHERE status = 'PENDING'")
    pending = cursor.fetchone()[0]
    conn.close()
    return {"completed": completed, "failed": failed, "pending": pending}
