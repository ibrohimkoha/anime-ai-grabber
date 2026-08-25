import logging
from typing import Optional, Dict, Any, Tuple
import psycopg2
from psycopg2.extras import RealDictCursor
import os

logger = logging.getLogger("BotDbSync")

PG_URL_ANIRIOUZ = os.getenv("BOT_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/aniriouz")
PG_URL_NOKORI = os.getenv("NOKORI_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/nokori_go")

def sync_to_aniriouz(clean_title: str, episode_number: int, studio: str, video_file_id: str) -> Optional[int]:
    """aniriouz (TarjimaAnimelar) bazasiga qo'shadi."""
    conn = None
    try:
        conn = psycopg2.connect(PG_URL_ANIRIOUZ, connect_timeout=5)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        search_pattern = f"%{clean_title}%"
        cur.execute("""
            SELECT id, unique_id FROM animes 
            WHERE LOWER(title) = LOWER(%s) 
               OR LOWER(original_title) = LOWER(%s) 
               OR LOWER(title) LIKE LOWER(%s)
            ORDER BY id ASC LIMIT 1
        """, (clean_title, clean_title, search_pattern))
        anime_row = cur.fetchone()

        if anime_row:
            anime_id = anime_row["id"]
            unique_id = anime_row["unique_id"]
        else:
            cur.execute("SELECT COALESCE(MAX(unique_id), 0) + 1 AS next_code FROM animes")
            unique_id = cur.fetchone()["next_code"]

            cur.execute("""
                INSERT INTO animes (title, original_title, description, genre, type, status, unique_id, image, created_at, updated_at)
                VALUES (%s, %s, %s, %s, 'TV', 'ONGOING', %s, %s, NOW(), NOW())
                RETURNING id, unique_id
            """, (clean_title, clean_title, f"{clean_title} o'zbek tilida", "Anime, Sarguzasht", unique_id, "https://telegra.ph/file/default.jpg"))
            anime_id = cur.fetchone()["id"]
            logger.info(f"🎉 [AniRioUz] Yangi anime qo'shildi: {clean_title} (Kod: #{unique_id})")

        # Til
        cur.execute("SELECT id FROM anime_languages WHERE anime_id = %s AND (LOWER(language) = 'uzbekcha' OR LOWER(language) = 'uz') LIMIT 1", (anime_id,))
        lang_row = cur.fetchone()
        if lang_row:
            language_id = lang_row["id"]
        else:
            cur.execute("INSERT INTO anime_languages (language, description, anime_id) VALUES ('Uzbekcha', %s, %s) RETURNING id", (f"{studio or 'Uzbekcha'} dublyaj", anime_id))
            language_id = cur.fetchone()["id"]

        # Epizod
        cur.execute("""
            INSERT INTO episodes (episode_number, video_id, anime_id, language_id)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (anime_id, language_id, episode_number)
            DO UPDATE SET video_id = EXCLUDED.video_id
            RETURNING id
        """, (episode_number, video_file_id, anime_id, language_id))
        
        conn.commit()
        cur.close()
        conn.close()
        return unique_id
    except Exception as e:
        logger.error(f"[AniRioUz] Sinxronizatsiyada xatolik: {e}")
        if conn:
            conn.rollback()
            conn.close()
        return None

def sync_to_nokori(clean_title: str, episode_number: int, studio: str, video_file_id: str) -> Optional[int]:
    """nokori_go (Nokori Anime & Web) bazasiga qo'shadi."""
    conn = None
    try:
        conn = psycopg2.connect(PG_URL_NOKORI, connect_timeout=5)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        search_pattern = f"%{clean_title}%"
        cur.execute("""
            SELECT id, unique_id FROM animes 
            WHERE LOWER(title) = LOWER(%s) 
               OR LOWER(title) LIKE LOWER(%s)
            ORDER BY id ASC LIMIT 1
        """, (clean_title, search_pattern))
        anime_row = cur.fetchone()

        if anime_row:
            anime_id = anime_row["id"]
            unique_id = anime_row["unique_id"]
        else:
            cur.execute("SELECT COALESCE(MAX(unique_id), 0) + 1 AS next_code FROM animes")
            unique_id = cur.fetchone()["next_code"]

            cur.execute("""
                INSERT INTO animes (unique_id, title, description, genre, status, studio, dub_studio, video_file_id, created_at, updated_at)
                VALUES (%s, %s, %s, %s, 'ONGOING', %s, %s, %s, NOW(), NOW())
                RETURNING id
            """, (unique_id, clean_title, f"{clean_title} o'zbek tilida", "Anime", studio or "Anime", studio or "UzDub", video_file_id))
            anime_id = cur.fetchone()["id"]
            logger.info(f"🎉 [Nokori-Go] Yangi anime qo'shildi: {clean_title} (Kod: #{unique_id})")

        # Epizod
        cur.execute("""
            INSERT INTO episodes (anime_id, episode_number, video_file_id, title, created_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT DO NOTHING
            RETURNING id
        """, (anime_id, episode_number, video_file_id, f"{episode_number}-qism"))
        
        conn.commit()
        cur.close()
        conn.close()
        return unique_id
    except Exception as e:
        logger.error(f"[Nokori-Go] Sinxronizatsiyada xatolik: {e}")
        if conn:
            conn.rollback()
            conn.close()
        return None

def sync_episode_to_bot_database(
    anime_name: str, 
    season: int, 
    episode_number: int, 
    studio: str, 
    video_file_id: str
) -> Tuple[bool, str, Optional[int]]:
    """Ikkala bot bazasiga (aniriouz va nokori_go) birdaniga yozadi."""
    clean_title = anime_name.strip()
    if season > 1 and f"{season}-" not in clean_title.lower() and f"season {season}" not in clean_title.lower():
        clean_title = f"{clean_title} {season}-mavsum"

    code_aniriouz = sync_to_aniriouz(clean_title, episode_number, studio, video_file_id)
    code_nokori = sync_to_nokori(clean_title, episode_number, studio, video_file_id)
    
    unique_code = code_aniriouz or code_nokori
    if unique_code:
        return True, f"Bazada faollashdi! Kod: #{unique_code}", unique_code
    return False, "Bazaga yozilmadi", None
