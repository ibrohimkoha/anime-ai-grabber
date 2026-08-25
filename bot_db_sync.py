import logging
from typing import Optional, Dict, Any, Tuple
import psycopg2
from psycopg2.extras import RealDictCursor
from config import BASE_DIR
import os

logger = logging.getLogger("BotDbSync")

PG_URL = os.getenv("BOT_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/aniriouz")

def get_pg_connection():
    """PostgreSQL (aniriouz) bazasiga ulanish."""
    if not PG_URL:
        return None
    try:
        conn = psycopg2.connect(PG_URL, connect_timeout=5)
        return conn
    except Exception as e:
        logger.warning(f"PostgreSQL ulanishda ogohlantirish: {e}")
        return None

def sync_episode_to_bot_database(
    anime_name: str, 
    season: int, 
    episode_number: int, 
    studio: str, 
    video_file_id: str,
    image_url: Optional[str] = None,
    genre: Optional[str] = None
) -> Tuple[bool, str, Optional[int]]:
    """
    Videoni to'g'ridan-to'g'ri AniRioUz / TarjimaAnimelar PostgreSQL bazasiga qo'shadi.
    Agar anime bazada bo'lmasa -> Avtomatik yangi anime va unique_id yaratadi!
    Agar til (Uzbekcha) bo'lmasa -> Avtomatik til yaratadi!
    Epizodni video_id bilan ro'yxatdan o'tkazadi!
    """
    conn = get_pg_connection()
    if not conn:
        return False, "PostgreSQL ulanmadi", None

    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # 1. Anime bazada bor-yo'qligini tekshirish
        clean_title = anime_name.strip()
        search_pattern = f"%{clean_title}%"
        
        cur.execute("""
            SELECT id, title, unique_id FROM animes 
            WHERE LOWER(title) = LOWER(%s) 
               OR LOWER(original_title) = LOWER(%s)
               OR LOWER(title) LIKE LOWER(%s)
            ORDER BY id ASC LIMIT 1
        """, (clean_title, clean_title, search_pattern))
        anime_row = cur.fetchone()

        anime_id = None
        unique_id = None

        if anime_row:
            anime_id = anime_row["id"]
            unique_id = anime_row["unique_id"]
            logger.info(f"✅ Mavjud anime topildi: {anime_row['title']} (ID={anime_id}, Kod={unique_id})")
        else:
            # 2. Yangi Anime yaratish
            cur.execute("SELECT COALESCE(MAX(unique_id), 0) + 1 AS next_code FROM animes")
            next_code_row = cur.fetchone()
            unique_id = next_code_row["next_code"] if next_code_row else 1

            cur.execute("""
                INSERT INTO animes (
                    title, original_title, description, genre, type, status, 
                    unique_id, image, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, 'TV', 'ONGOING', %s, %s, NOW(), NOW())
                RETURNING id, unique_id
            """, (
                clean_title, 
                clean_title, 
                f"{clean_title} o'zbek tilida tomosha qilish", 
                genre or "Anime, Sarguzasht", 
                unique_id, 
                image_url or "https://telegra.ph/file/default.jpg"
            ))
            new_anime = cur.fetchone()
            anime_id = new_anime["id"]
            unique_id = new_anime["unique_id"]
            logger.info(f"🎉 Yangi anime bazaga qo'shildi: {clean_title} (Kod: #{unique_id})")

        # 3. Anime tilini tekshirish / yaratish (Standart: Uzbekcha)
        cur.execute("""
            SELECT id FROM anime_languages 
            WHERE anime_id = %s AND (LOWER(language) = 'uzbekcha' OR LOWER(language) = 'uz')
            LIMIT 1
        """, (anime_id,))
        lang_row = cur.fetchone()

        if lang_row:
            language_id = lang_row["id"]
        else:
            cur.execute("""
                INSERT INTO anime_languages (language, description, anime_id)
                VALUES ('Uzbekcha', %s, %s)
                RETURNING id
            """, (f"{studio or 'Uzbekcha'} dublyaj", anime_id))
            new_lang = cur.fetchone()
            language_id = new_lang["id"]
            logger.info(f"✅ Til qo'shildi: Uzbekcha (ID={language_id})")

        # 4. Qismni (Episode) bazaga kiritish / yangilash
        cur.execute("""
            INSERT INTO episodes (episode_number, video_id, anime_id, language_id)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (anime_id, language_id, episode_number)
            DO UPDATE SET video_id = EXCLUDED.video_id
            RETURNING id
        """, (episode_number, video_file_id, anime_id, language_id))
        ep_row = cur.fetchone()
        ep_id = ep_row["id"]
        
        conn.commit()
        cur.close()
        conn.close()

        logger.info(f"🎬 {clean_title} {episode_number}-qism bot bazasiga muvaffaqiyatli saqlandi! (Episode ID={ep_id})")
        return True, f"Muvaffaqiyatli qo'shildi! Kod: #{unique_id}", unique_id

    except Exception as e:
        logger.error(f"PostgreSQL saqlashda xatolik: {e}", exc_info=True)
        if conn:
            conn.rollback()
            conn.close()
        return False, str(e), None
