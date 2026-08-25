import re
import asyncio
import logging
from typing import Optional, List
from telethon import TelegramClient, events, functions, types
from telethon.tl.types import (
    KeyboardButtonUrl, 
    KeyboardButtonCallback, 
    ReplyInlineMarkup,
    MessageMediaDocument
)

from config import (
    API_ID, 
    API_HASH, 
    PHONE_NUMBER, 
    SESSION_NAME, 
    DEFAULT_TARGET_CHANNELS, 
    DEFAULT_DESTINATION_BOT,
    AUTO_JOIN_CHANNELS
)
from deepseek_parser import parse_anime_post, select_best_button, AnimeRelease
from database import (
    is_already_grabbed, 
    log_release, 
    update_status, 
    get_setting, 
    set_setting,
    get_stats
)

logger = logging.getLogger("UserbotEngine")

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

def get_current_destination_bot() -> str:
    """Joriy qabul qiluvchi bot nomini bazadan oladi."""
    return get_setting("destination_bot", DEFAULT_DESTINATION_BOT)

def get_monitored_channels() -> List[str]:
    """Kuzatilayotgan kanallar ro'yxatini bazadan oladi."""
    raw = get_setting("target_channels", DEFAULT_TARGET_CHANNELS)
    return [c.strip() for c in raw.split(",") if c.strip()]

async def join_or_request_chat(url_or_username: str):
    """Kanalga avtomatik a'zo bo'ladi yoki Zayavka (Join Request) yuboradi."""
    if not AUTO_JOIN_CHANNELS or not url_or_username:
        return

    clean_target = url_or_username.strip()
    try:
        # 1. Agar xususiy havola (t.me/+hash yoki t.me/joinchat/hash) bo'lsa
        if "+" in clean_target or "joinchat" in clean_target:
            invite_hash = clean_target.split("+")[-1].split("/")[-1]
            logger.info(f"Yopiq kanalga zayavka/a'zolik yuborilmoqda: hash={invite_hash}")
            try:
                await client(functions.messages.ImportChatInviteRequest(invite_hash))
            except Exception as e:
                logger.warning(f"Zayavka yuborildi yoki kanalga kirilmadi: {e}")
        
        # 2. Agar ochiq kanal (@channel yoki t.me/channel) bo'lsa
        else:
            username = clean_target.replace("https://t.me/", "").replace("http://t.me/", "").replace("@", "").split("/")[0]
            if username:
                logger.info(f"Ochiq kanalga a'zo bo'linmoqda: @{username}")
                await client(functions.channels.JoinChannelRequest(username))
    except Exception as e:
        logger.error(f"Kanalga a'zo bo'lishda xatolik ({url_or_username}): {e}")

async def extract_and_join_required_channels(msg: types.Message):
    """Bot yuborgan tugmalar orasidan barcha homiy kanallarni topib a'zo bo'ladi."""
    if not msg.reply_markup:
        return

    if isinstance(msg.reply_markup, ReplyInlineMarkup):
        for row in msg.reply_markup.rows:
            for button in row.buttons:
                if isinstance(button, KeyboardButtonUrl):
                    url = button.url
                    if "t.me/" in url:
                        await join_or_request_chat(url)
                        await asyncio.sleep(1.0)

async def interact_with_bot_and_grab_video(release: AnimeRelease) -> bool:
    """Begona fan-dub boti bilan muloqot qilib, videoni tortib oladi va shaxsiy botingizga jo'natadi."""
    bot = release.bot_username
    start_param = release.start_param
    dest_bot = get_current_destination_bot()
    
    logger.info(f"🤖 Begona botga so'rov yuborilmoqda: {bot} -> /start {start_param}")
    
    try:
        # Botga /start yuborish
        start_cmd = f"/start {start_param}" if start_param else "/start"
        await client.send_message(bot, start_cmd)
        
        # Bot javobini kutish
        bot_response = None
        for _ in range(15):
            await asyncio.sleep(1)
            messages = await client.get_messages(bot, limit=3)
            for m in messages:
                if not m.out:
                    bot_response = m
                    break
            if bot_response:
                break

        if not bot_response:
            logger.warning(f"{bot} botidan javob kelmadi.")
            return False

        # 1. Agar bot majburiy kanallarni yuborgan bo'lsa -> A'zo bo'lish / Zayavka tashlash
        await extract_and_join_required_channels(bot_response)

        # 2. Agar botda inline tugmalar bo'lsa -> Tekshirish yoki eng mos tugmani bosish
        if bot_response.reply_markup and isinstance(bot_response.reply_markup, ReplyInlineMarkup):
            buttons_list = []
            for r_idx, row in enumerate(bot_response.reply_markup.rows):
                for b_idx, btn in enumerate(row.buttons):
                    if isinstance(btn, KeyboardButtonCallback):
                        buttons_list.append({
                            "text": btn.text,
                            "data": btn.data.decode(errors="ignore") if btn.data else "",
                            "row": r_idx,
                            "col": b_idx
                        })

            if buttons_list:
                chosen_text = await select_best_button(bot_response.text or "", buttons_list)
                logger.info(f"Tanlangan tugma: '{chosen_text}'")
                try:
                    await bot_response.click(text=chosen_text)
                except Exception as e:
                    logger.warning(f"Tugma bosishda xatolik: {e}, birinchi tugma bosilmoqda")
                    try:
                        await bot_response.click(0)
                    except Exception:
                        pass

        # 3. Videoni kutish (25 soniya)
        video_message = None
        for _ in range(25):
            await asyncio.sleep(1)
            recent_msgs = await client.get_messages(bot, limit=5)
            for m in recent_msgs:
                if not m.out and (m.video or (m.document and "video" in (m.document.mime_type or ""))):
                    video_message = m
                    break
            if video_message:
                break

        if not video_message:
            logger.warning(f"Video fayl kelmadi ({release.anime_name} - {release.episode}-qism)")
            return False

        logger.info(f"✅ Video qabul qilindi! ID={video_message.id}")

        # 4. Videoni shaxsiy botingizga jo'natish (@Tarjima_Animelarrbot yoki dinamik sozlangan bot)
        caption = (
            f"🎬 **{release.anime_name}** | {release.season}-Mavsum {release.episode}-Qism\n"
            f"🎙 **Dublyaj:** {release.studio}\n"
            f"🎞 **Sifat:** {release.quality}\n\n"
            f"📥 Ushbu video avtomatik yuklandi: {bot}"
        )

        if dest_bot:
            logger.info(f"🚀 Video shaxsiy botingizga yuborilmoqda: {dest_bot}")
            sent = await client.send_file(
                dest_bot,
                video_message.media,
                caption=caption
            )
            update_status(
                release.anime_name, 
                release.season, 
                release.episode, 
                release.studio, 
                "COMPLETED", 
                sent.id
            )
            logger.info(f"🎉 Video {dest_bot} botingizga muvaffaqiyatli yetkazildi!")
        else:
            logger.warning("Qabul qiluvchi bot belgilanmagan (.setbot @botingiz orqali sozlang)")
            update_status(release.anime_name, release.season, release.episode, release.studio, "COMPLETED", video_message.id)

        return True

    except Exception as e:
        logger.error(f"Bot bilan muloqotda xatolik: {e}", exc_info=True)
        update_status(release.anime_name, release.season, release.episode, release.studio, "FAILED")
        return False

async def handle_channel_message(event):
    """Kuzatilayotgan kanallarga yangi post kelganda ishga tushadi."""
    msg = event.message
    text = msg.text or msg.raw_text or ""
    if not text:
        return

    chat = await event.get_chat()
    chat_title = getattr(chat, 'title', 'Kanal')
    chat_username = getattr(chat, 'username', str(chat.id))
    
    # 1. DeepSeek AI orqali postni tahlil qilish
    release = await parse_anime_post(text)
    if not release or not release.is_anime_release:
        return

    logger.info(f"🔥 Yangi reliz aniqlandi: {release.anime_name} - {release.episode}-qism ({release.studio})")

    # 2. Takroriylikni tekshirish
    if is_already_grabbed(release.anime_name, release.season, release.episode, release.studio):
        logger.info(f"⏩ Ushbu qism allaqachon yuklangan: {release.anime_name} Ep {release.episode}")
        return

    # 3. Bazaga yozish
    log_release(
        source_channel=f"@{chat_username}" if chat_username else str(chat.id),
        source_msg_id=msg.id,
        anime_name=release.anime_name,
        season=release.season,
        episode=release.episode,
        studio=release.studio,
        bot_username=release.bot_username,
        start_param=release.start_param,
        status="PENDING"
    )

    # 4. Videoni sug'urib shaxsiy botga jo'natish
    if release.bot_username:
        await interact_with_bot_and_grab_video(release)

# ==========================================================
# 📱 TELEGRAM ICHIDAN BOSHQARISH BUYRUQLARI (ADMIN COMMANDS)
# ==========================================================
async def handle_admin_commands(event):
    """Foydalanuvchi o'ziga o'zi (Saved Messages) yoki istalgan chatda buyruq berganda."""
    msg = event.message
    text = (msg.text or "").strip()
    if not text.startswith("."):
        return

    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd == ".setbot":
        if not arg:
            await msg.reply("❌ Bot nomini kiriting: `.setbot @Tarjima_Animelarrbot`")
            return
        bot_name = arg if arg.startswith("@") else f"@{arg}"
        set_setting("destination_bot", bot_name)
        await msg.reply(f"✅ **Qabul qiluvchi bot muvaffaqiyatli o'zgartirildi!**\n🤖 Joriy bot: `{bot_name}`\nBarcha yuklangan videolar endi shu botga boradi.")

    elif cmd == ".bot":
        current_bot = get_current_destination_bot()
        await msg.reply(f"🤖 **Joriy qabul qiluvchi bot:** `{current_bot or 'Belgilanmagan'}`\nO'zgartirish uchun: `.setbot @YangiBot`")

    elif cmd == ".addchannel":
        if not arg:
            await msg.reply("❌ Kanal nomini kiriting: `.addchannel @amediatarjima`")
            return
        ch_name = arg if arg.startswith("@") else f"@{arg}"
        current = get_monitored_channels()
        if ch_name not in current:
            current.append(ch_name)
            set_setting("target_channels", ",".join(current))
            await msg.reply(f"✅ Kanal ro'yxatga qo'shildi: `{ch_name}`")
        else:
            await msg.reply(f"ℹ️ Ushbu kanal allaqachon ro'yxatda bor: `{ch_name}`")

    elif cmd == ".delchannel":
        if not arg:
            await msg.reply("❌ O'chiriladigan kanalni kiriting: `.delchannel @amediatarjima`")
            return
        ch_name = arg if arg.startswith("@") else f"@{arg}"
        current = get_monitored_channels()
        if ch_name in current:
            current.remove(ch_name)
            set_setting("target_channels", ",".join(current))
            await msg.reply(f"🗑 Kanal ro'yxatdan o'chirildi: `{ch_name}`")
        else:
            await msg.reply(f"❌ Kanal topilmadi: `{ch_name}`")

    elif cmd == ".channels":
        channels = get_monitored_channels()
        ch_list = "\n".join([f"  • `{c}`" for c in channels]) if channels else "Hech qanday kanal kiritilmagan."
        await msg.reply(f"📢 **Kuzatilayotgan Fan-Dub Kanallari:**\n{ch_list}\n\nQo'shish: `.addchannel @kanal`\nO'chirish: `.delchannel @kanal`")

    elif cmd == ".status":
        stats = get_stats()
        current_bot = get_current_destination_bot()
        channels = get_monitored_channels()
        status_text = (
            "📊 **Anime AI Auto-Grabber Holati:**\n\n"
            f"🤖 **Qabul qiluvchi Bot:** `{current_bot or 'Belgilanmagan'}`\n"
            f"📢 **Kuzatuvdagi Kanallar:** `{len(channels)} ta`\n"
            f"✅ **Muvaffaqiyatli Yuklangan:** `{stats['completed']} ta qism`\n"
            f"⏳ **Jarayonda:** `{stats['pending']} ta`\n"
            f"❌ **Xatolik bo'lgan:** `{stats['failed']} ta`\n\n"
            "🟢 Tizim 24/7 faol ishlamoqda."
        )
        await msg.reply(status_text)

    elif cmd == ".grab":
        if not arg:
            await msg.reply("❌ Havolani kiriting: `.grab https://t.me/amediatarjima_bot?start=jjk18`")
            return
        await msg.reply(f"⏳ Qo'lda yuklash boshlandi: `{arg}`...")
        # DeepSeek orqali linkni tahlil qilish
        release = await parse_anime_post(f"Ko'rish havolasi: {arg}")
        if release and release.bot_username:
            success = await interact_with_bot_and_grab_video(release)
            if success:
                await msg.reply(f"✅ Video muvaffaqiyatli yuklandi va `{get_current_destination_bot()}` ga yuborildi!")
            else:
                await msg.reply("❌ Videoni yuklashda xatolik yuz berdi.")
        else:
            await msg.reply("❌ Havoladan bot ma'lumotlari aniqlanmadi.")

    elif cmd == ".help":
        help_text = (
            "🛠 **Anime AI Grabber Telegram Buyruqlari:**\n\n"
            "• `.setbot @BotNomi` — Videolar borishi kerak bo'lgan botni o'zgartirish\n"
            "• `.bot` — Joriy qabul qiluvchi botni ko'rish\n"
            "• `.channels` — Kuzatilayotgan kanallar ro'yxati\n"
            "• `.addchannel @Kanal` — Yangi fan-dub kanal qo'shish\n"
            "• `.delchannel @Kanal` — Kanalni ro'yxatdan o'chirish\n"
            "• `.status` — Tizim statistikasi va holati\n"
            "• `.grab <havola>` — Istalgan bot havolasini darhol yuklash\n"
            "• `.help` — Ushbu yordam oynasi"
        )
        await msg.reply(help_text)
