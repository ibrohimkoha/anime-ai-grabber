import json
import logging
from typing import Optional, Dict, Any, List
from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

logger = logging.getLogger("DeepSeekParser")

client = AsyncOpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url=DEEPSEEK_BASE_URL
)

class AnimeRelease(BaseModel):
    is_anime_release: bool = Field(description="Post yangi anime qismi relizi haqidami?")
    anime_name: str = Field(default="Anime", description="Animening to'liq va rasmiy nomi")
    season: int = Field(default=1, description="Anime mavsumi (1, 2, 3...)")
    episode: int = Field(default=1, description="Qism raqami (1, 11, 24...)")
    studio: str = Field(default="Uzbekcha", description="Dublyaj studiyasi (UzDub, Amedia, FanDub va h.k.)")
    quality: str = Field(default="720p", description="Sifat (720p, 1080p, 480p)")
    bot_username: Optional[str] = Field(default="", description="Postdagi bot username (@bot_nomi)")
    start_param: Optional[str] = Field(default="", description="Bot start parametri")
    summary: Optional[str] = Field(default="", description="Qisqa izoh")

async def parse_anime_post(text: str) -> Optional[AnimeRelease]:
    """Kanal postidagi bot havolasi va anime ma'lumotlarini aniqlaydi."""
    if not text or len(text.strip()) < 3:
        return None

    prompt = f"""
Siz Telegram O'zbek anime kanallari postlarini tahlil qiluvchi professional AI (DeepSeek V4-Flash)siz.
Quyidagi post matnini o'rganib, toza JSON qaytaring:

Post matni:
\"\"\"
{text}
\"\"\"

Talablar:
- `anime_name`: Animening to'g'ri nomini aniqlang (masalan "Solo Leveling", "Jujutsu Kaisen").
- `season`: Fasl raqami (default 1).
- `episode`: Qism raqami (default 1).
- `studio`: Dublyaj jamoasi.
- `bot_username`: @username (masalan @AniMacUzbot).
- `start_param`: Havoladagi start kodi (masalan "down_11").

JSON Format:
{{
  "is_anime_release": true,
  "anime_name": "Solo Leveling",
  "season": 3,
  "episode": 11,
  "studio": "Uzbekcha",
  "quality": "720p",
  "bot_username": "@AniMacUzbot",
  "start_param": "down_11",
  "summary": "Solo Leveling 3-mavsum 11-qism"
}}
"""
    try:
        response = await client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": "Sen o'ta aqlli va tezkor anime tahlilchisisan. Faqat toza JSON qaytar."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.1
        )
        data = json.loads(response.choices[0].message.content.strip())
        if data.get("bot_username"):
            bot = data["bot_username"].strip()
            if not bot.startswith("@") and not bot.startswith("http"):
                bot = "@" + bot
            data["bot_username"] = bot
        return AnimeRelease(**data)
    except Exception as e:
        logger.error(f"DeepSeek tahlil xatosi: {e}")
        return None

async def decide_inline_action(
    target_anime: str,
    target_episode: int,
    bot_message_text: str,
    buttons: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """
    Begona botning inline tugmalari orasidan eng to'g'ri tugmani aniqlaydi.
    """
    if not buttons:
        return None

    buttons_json = json.dumps(buttons, ensure_ascii=False, indent=2)
    prompt = f"""
Telegram Anime Bot foydalanuvchiga quyidagi xabarni va inline tugmalarni ko'rsatmoqda:

Bizning Maqsadimiz:
- Anime: "{target_anime}"
- Qism: {target_episode}-qism (yoki barcha qismlar)
- Biz O'ZBEKCHA dublyajdagi videoni yuklab olmoqchimiz (sifat: 720p/1080p).

Bot xabari:
\"\"\"
{bot_message_text}
\"\"\"

Inline Tugmalar:
{buttons_json}

Vazifa:
Qaysi tugmani bosish kerak?
- Agar "📥 Barchasini yuklash" yoki "Barcha qismlar" bo'lsa -> o'shani tanlang!
- Obunani tekshirish bo'lsa -> "✅ Obunani tekshirish", "Tekshirish", "Start"
- Fasl/Anime tanlash bo'lsa -> Fasl yoki anime nomi yozilgan tugma (masalan "{target_anime} 3-fasl")
- Til tanlash bo'lsa -> "🇺🇿 O'zbekcha", "Uzbek"
- Sifat tanlash bo'lsa -> "720p", "1080p", "HD"
- Qismlar ro'yxati bo'lsa -> eng birinchi qism yoki so'ralgan qism tugmasini tanlang.

Format (Faqat toza JSON):
{{
  "selected_text": "Tugmadagi matn",
  "button_index": 0,
  "is_batch_download": false,
  "reason": "Tanlov sababi"
}}
"""
    try:
        response = await client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": "Siz Telegram botlari bilan muloqot qiluvchi mutaxassis AIsiz. Faqat JSON qaytaring."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.1
        )
        return json.loads(response.choices[0].message.content.strip())
    except Exception as e:
        logger.error(f"DeepSeek inline tanlov xatosi: {e}")
        return {"selected_text": buttons[0].get("text"), "button_index": 0, "is_batch_download": False, "reason": "Fallback"}

async def match_anime_with_existing(
    video_caption: str,
    dialog_logs: List[str],
    existing_animes: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Videoni mavjud animelar bilan QAT'IY semantik taqqoslaydi.
    Boshqa animeni boshqa animega qo'shib yuborishning oldini oladi.
    """
    animes_json = json.dumps(existing_animes, ensure_ascii=False, indent=2)
    dialog_str = "\n".join(dialog_logs) if dialog_logs else "Muloqot yo'q"
    
    prompt = f"""
Siz Telegram Anime Boshqaruv Tizimisiz (DeepSeek V4-Flash).
Biz yangi video yuklab oldik:
- Video Caption (sarlavhasi):
\"\"\"
{video_caption}
\"\"\"
- Muloqot tarixi:
\"\"\"
{dialog_str}
\"\"\"

Bazada mavjud animelar ro'yxati:
{animes_json}

QAT'IY QOIDALAR:
1. Hech qachon boshqa animeni boshqa animega qo'shib yubormang!
   - Masalan: "Solo Leveling" ni "Egzartis" yoki "Jujutsu Kaisen"ga qo'shish qat'iyan taqiqlanadi!
2. Agar yuklangan video mavjud ro'yxatdagi anime bilan 100% BIR XIL anime va aynan shu fasli bo'lsa:
   `is_new`: false, `matched_unique_id`: <o'sha animening unique_id si>
3. Agar bu anime bazada BO'LMASA yoki boshqa fasli bo'lsa:
   `is_new`: true, `matched_unique_id`: null, `clean_title`: "Animening to'liq va rasmiy nomi"
4. Fasl (season), Qism raqami (episode) va Dublyaj studiyasini (studio) aniqlang.

Format (Faqat toza JSON):
{{
  "is_new": false,
  "matched_unique_id": 29,
  "clean_title": "Solo Leveling 3-mavsum",
  "season": 3,
  "episode": 11,
  "studio": "UzDub",
  "quality": "720p"
}}
"""
    try:
        response = await client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": "Siz anime tahlilchisi va aniq klassifikatorisiz. Faqat JSON qaytaring."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.1
        )
        return json.loads(response.choices[0].message.content.strip())
    except Exception as e:
        logger.error(f"Anime taqqoslash xatosi: {e}")
        return {
            "is_new": True,
            "matched_unique_id": None,
            "clean_title": "Anime",
            "season": 1,
            "episode": 1,
            "studio": "Uzbekcha",
            "quality": "720p"
        }

async def extract_all_episode_buttons_from_menu(buttons: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Agar botda ko'plab qismlar tugmalari (1-qism, 2-qism, 3-qism...) bo'lsa,
    ularning barchasini ajratib tartib bilan qaytaradi.
    """
    if not buttons:
        return []

    btns_str = json.dumps(buttons, ensure_ascii=False, indent=2)
    prompt = f"""
Quyidagi inline tugmalar orasidan qism yuklash tugmalarini (masalan: 1-qism, 2-qism, 3-qism, Ep 1, Ep 2...) ajrating.

Tugmalar:
{btns_str}

Format (Faqat toza JSON):
{{
  "has_multiple_episodes": true,
  "episode_button_indexes": [0, 1, 2, 3]
}}
"""
    try:
        response = await client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1
        )
        data = json.loads(response.choices[0].message.content.strip())
        indexes = data.get("episode_button_indexes", [])
        return [buttons[i] for i in indexes if i < len(buttons)]
    except Exception as e:
        logger.warning(f"Qismlar tugmalarini ajratishda xatolik: {e}")
        return []
