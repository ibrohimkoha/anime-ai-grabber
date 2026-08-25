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
- Qism: {target_episode}-qism
- Biz O'ZBEKCHA dublyajdagi videoni yuklab olmoqchimiz (sifat: 720p/1080p).

Bot xabari:
\"\"\"
{bot_message_text}
\"\"\"

Inline Tugmalar:
{buttons_json}

Vazifa:
Qaysi tugmani bosish kerak?
- Obunani tekshirish bo'lsa -> "✅ Obunani tekshirish", "Tekshirish", "Start"
- Fasl/Anime tanlash bo'lsa -> Fasl yoki anime nomi yozilgan tugma (masalan "{target_anime} 3-fasl")
- Til tanlash bo'lsa -> "🇺🇿 O'zbekcha", "Uzbek"
- Sifat tanlash bo'lsa -> "720p", "1080p", "HD"
- Qismlar bo'lsa -> "{target_episode}-qism"

Format (Faqat toza JSON):
{{
  "selected_text": "Tugmadagi matn",
  "button_index": 0,
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
        return {"selected_text": buttons[0].get("text"), "button_index": 0, "reason": "Fallback"}

async def extract_final_metadata(
    bot_username: str,
    start_param: str,
    dialog_logs: List[str],
    video_caption: str,
    default_anime: str = "Anime",
    default_ep: int = 1
) -> AnimeRelease:
    """
    Video qabul qilingandan so'ng botdan olingan barcha xabarlar,
    bosilgan tugmalar va video sarlavhasidan animening 100% HAQIQIY NOMINI ajratadi.
    """
    context = "\n".join(dialog_logs)
    prompt = f"""
Biz Telegram anime botidan video yuklab oldik:
- Bot: {bot_username} (param: {start_param})
- Muloqot va bosilgan tugmalar tarixi:
\"\"\"
{context}
\"\"\"
- Video sarlavhasi (caption):
\"\"\"
{video_caption}
\"\"\"

Vazifa:
Ushbu ma'lumotlar asosida animening to'liq va aniq nomini, mavsumini (faslini), qismini va dublyaj studiyasini aniqlang.
Hech qachon shunchaki "Anime" deb qoldirmang, haqiqiy nomini yozing (masalan "Solo Leveling", "Jujutsu Kaisen", "Naruto").

JSON Format:
{{
  "is_anime_release": true,
  "anime_name": "Solo Leveling",
  "season": 3,
  "episode": 11,
  "studio": "UzDub",
  "quality": "720p",
  "summary": "Solo Leveling 3-mavsum 11-qism"
}}
"""
    try:
        response = await client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": "Siz anime nomlarini aniqlovchi mutaxassissiz. Faqat toza JSON qaytaring."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.1
        )
        data = json.loads(response.choices[0].message.content.strip())
        data["bot_username"] = bot_username
        data["start_param"] = start_param
        return AnimeRelease(**data)
    except Exception as e:
        logger.error(f"Final metadata tahlilida xatolik: {e}")
        return AnimeRelease(
            is_anime_release=True,
            anime_name=default_anime,
            season=1,
            episode=default_ep,
            studio="Uzbekcha",
            quality="720p",
            bot_username=bot_username,
            start_param=start_param
        )
