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
    is_anime_release: bool = Field(description="Post haqiqatan ham yangi anime qismi relizi haqidami?")
    anime_name: Optional[str] = Field(default="", description="Animening to'liq va rasmiy nomi")
    season: int = Field(default=1, description="Anime mavsumi (1, 2, 3...)")
    episode: Optional[int] = Field(default=1, description="Qism raqami (masalan 1, 18, 24)")
    studio: Optional[str] = Field(default="Uzbekcha", description="Dublyaj studiyasi (Amedia, UzDub, FanDub, AniDub va h.k.)")
    quality: Optional[str] = Field(default="720p", description="Sifat (720p, 1080p, 480p)")
    bot_username: Optional[str] = Field(default="", description="Postdagi bot username (@belgisi bilan, masalan @amediatarjima_bot)")
    start_param: Optional[str] = Field(default="", description="Botga yuboriladigan start parametri")
    summary: Optional[str] = Field(default="", description="Qisqa izoh")

async def parse_anime_post(text: str) -> Optional[AnimeRelease]:
    """
    DeepSeek AI orqali Telegram kanalidagi har qanday chalkash postni tahlil qilib,
    toza va tuzilgan ma'lumotlarni chiqarib oladi.
    """
    if not text or len(text.strip()) < 3:
        return None

    prompt = f"""
Siz Telegramdagi O'zbek anime kanallari postlarini tahlil qiluvchi professional AIsiz.
Quyidagi post matnini o'rganib chiqing va JSON formatida javob qaytaring.

Post matni:
\"\"\"
{text}
\"\"\"

Talablar:
1. Agar post shunchaki reklama, suhbat yoki yangilik bo'lsa va unda yangi qism videosi/boti bo'lmasa, `is_anime_release: false` qiling.
2. Agar bu yangi anime qismi yoki bot havolasi bo'lsa:
   - `anime_name`: Animening to'g'ri, to'liq nomini yozing (masalan "JJK 2" bo'lsa -> "Jujutsu Kaisen Season 2", "Solo Leveling 7" -> "Solo Leveling").
   - `season`: Fasl raqami (default 1).
   - `episode`: Aniq qism raqami (agar aniqlanmasa 1).
   - `studio`: Dublyaj qilgan jamoa (Amedia, UzDub, FanDub, AnimeUz, TarjimaKinolar va h.k.).
   - `bot_username`: Post ichidagi havola qaysi botga olib borsa, o'sha botning @username ni aniqlang (masalan @amediatarjima_bot).
   - `start_param`: Agar havola `t.me/bot?start=xyz` yoki `tg://resolve?domain=bot&start=xyz` ko'rinishida bo'lsa, `start` dan keyingi parametrni oling.

Faqat va faqat quyidagi toza JSON formatida javob bering, boshqa hech narsa yozmang:
{{
  "is_anime_release": true,
  "anime_name": "Jujutsu Kaisen",
  "season": 2,
  "episode": 18,
  "studio": "Amedia",
  "quality": "720p",
  "bot_username": "@bot_nomi",
  "start_param": "param_kodi",
  "summary": "Jujutsu Kaisen 2-mavsum 18-qism Amedia dublyajida"
}}
"""
    try:
        response = await client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": "Sen faqat toza JSON qaytaruvchi aqlli tahlilchisiz."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.1
        )
        content = response.choices[0].message.content.strip()
        data = json.loads(content)
        
        if data.get("bot_username"):
            bot = data["bot_username"].strip()
            if not bot.startswith("@") and not bot.startswith("http"):
                bot = "@" + bot
            data["bot_username"] = bot

        if not data.get("episode"):
            data["episode"] = 1

        return AnimeRelease(**data)
    except Exception as e:
        logger.error(f"DeepSeek tahlilida xatolik: {e}")
        return None

async def decide_inline_action(
    target_anime: str,
    target_episode: int,
    bot_message_text: str,
    buttons: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """
    Begona botning har qanday ko'p bosqichli inline tugmalari orasidan
    eng to'g'ri tugmani (Obunani tekshirish, Til tanlash, Sifat tanlash, Qism tanlash)
    aniqlaydi.
    """
    if not buttons:
        return None

    buttons_json = json.dumps(buttons, ensure_ascii=False, indent=2)
    prompt = f"""
Telegram Anime Bot foydalanuvchiga quyidagi xabarni va inline tugmalarni ko'rsatmoqda:

Maqsadimiz:
- Anime: "{target_anime}"
- Qism: {target_episode}-qism
- Biz O'ZBEKCHA dublyajdagi videoni yuklab olmoqchimiz (agar sifat so'ralsa 720p yoki 1080p).

Bot xabari:
\"\"\"
{bot_message_text}
\"\"\"

Mavjud Inline Tugmalar:
{buttons_json}

Vazifa:
1. Ushbu tugmalar ichidan qaysi birini bosish kerakligini aniqlang.
   - Agar bu Obunani tekshirish bo'lsa -> "✅ Obunani tekshirish", "Tekshirish", "Tasdiqlash", "Start" tugmasini tanlang.
   - Agar bu Til tanlash bo'lsa -> "🇺🇿 O'zbekcha", "Uzbek", "Tarjima" tugmasini tanlang.
   - Agar bu Sifat tanlash bo'lsa -> "720p", "1080p", "HD" tugmasini tanlang.
   - Agar bu Qismlar ro'yxati bo'lsa -> "{target_episode}-qism" yoki unga eng yaqin qism tugmasini tanlang.
   - Agar bu "Yuklab olish" / "Tomosha qilish" bo'lsa -> o'sha tugmani tanlang.

Format (Faqat toza JSON):
{{
  "selected_text": "Tugma ustidagi aniq matn",
  "button_index": 0,
  "reason": "O'zbek tili tanlandi"
}}
"""
    try:
        response = await client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": "Siz Telegram botlarining inline interfeysini mukammal tushunuvchi aqlli AIsiz. Faqat JSON qaytaring."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.1
        )
        content = response.choices[0].message.content.strip()
        res = json.loads(content)
        return res
    except Exception as e:
        logger.error(f"DeepSeek inline tugma tanlashida xatolik: {e}")
        return {"selected_text": buttons[0].get("text"), "button_index": 0, "reason": "Default fallback"}
