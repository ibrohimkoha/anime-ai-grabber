import sys
import asyncio
import logging
from telethon import events
from config import (
    API_ID, 
    API_HASH, 
    PHONE_NUMBER, 
    DEFAULT_DESTINATION_BOT
)
from database import init_db, set_setting, get_setting
from userbot_engine import (
    client, 
    handle_channel_message, 
    handle_admin_commands, 
    get_current_destination_bot, 
    get_monitored_channels
)
from deepseek_parser import parse_anime_post

# Logging sozlamalari
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("anime_grabber.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("Main")

async def test_mode(sample_text: str):
    """DeepSeek AI tahlilini sinab ko'rish rejimi."""
    print("\n" + "="*50)
    print("🧪 TEST REJIMI: DeepSeek Post Tahlili")
    print("="*50)
    print(f"Kiruvchi matn:\n{sample_text}\n")
    
    release = await parse_anime_post(sample_text)
    if release:
        print("✅ Natija:")
        print(f"  • Anime: {release.anime_name}")
        print(f"  • Mavsum: {release.season}")
        print(f"  • Qism: {release.episode}")
        print(f"  • Studiya: {release.studio}")
        print(f"  • Sifat: {release.quality}")
        print(f"  • Bot: {release.bot_username}")
        print(f"  • Start Parametr: {release.start_param}")
        print(f"  • Xulosa: {release.summary}")
    else:
        print("❌ Post tahlil qilinmadi.")
    print("="*50 + "\n")

async def main():
    # 1. Bazani ishga tushirish
    init_db()
    logger.info("📦 Ma'lumotlar bazasi tayyor.")

    # Agar bazada bot belgilanmagan bo'lsa, default botni o'rnatish
    if not get_setting("destination_bot"):
        set_setting("destination_bot", DEFAULT_DESTINATION_BOT)

    if not API_ID or not API_HASH:
        logger.error("❌ Xatolik: .env faylida TELEGRAM_API_ID va TELEGRAM_API_HASH ko'rsatilmagan!")
        logger.info("👉 Iltimos, https://my.telegram.org ga kirib API ID va HASH oling va .env ga yozing.")
        return

    # 2. Telegramga ulanish
    logger.info("🚀 Telegram Userbot ishga tushmoqda...")
    await client.start(phone=PHONE_NUMBER if PHONE_NUMBER else None)
    
    me = await client.get_me()
    logger.info(f"✅ Userbot muvaffaqiyatli ulandi: {me.first_name} (@{me.username or me.id})")
    logger.info(f"🤖 Qabul qiluvchi bot: {get_current_destination_bot()}")
    logger.info(f"📢 Kuzatilayotgan kanallar: {get_monitored_channels()}")

    # 3. Foydalanuvchining shaxsiy Admin buyruqlarini tinglash (.setbot, .status, .addchannel va h.k.)
    @client.on(events.NewMessage(outgoing=True))
    async def admin_listener(event):
        await handle_admin_commands(event)

    # 4. Kanallardan keladigan yangi postlarni tinglash
    @client.on(events.NewMessage)
    async def channel_listener(event):
        if event.is_channel and not event.is_group:
            chat = await event.get_chat()
            chat_username = f"@{chat.username}" if getattr(chat, "username", None) else str(chat.id)
            monitored = get_monitored_channels()
            
            # Agar kanal monitoring ro'yxatida bo'lsa
            if not monitored or chat_username in monitored or str(chat.id) in monitored:
                await handle_channel_message(event)

    logger.info("🟢 Anime AI Auto-Grabber 24/7 rejimida faol. Telegramdan .help deb yozib buyruqlarni ko'rishingiz mumkin!")
    await client.run_until_disconnected()

if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--test":
        test_text = " ".join(sys.argv[2:])
        asyncio.run(test_mode(test_text))
    else:
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            logger.info("Dastur to'xtatildi.")
