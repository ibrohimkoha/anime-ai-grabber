import re
import asyncio
import logging
from typing import Optional, List, Dict, Any, Tuple
from telethon import TelegramClient, events, functions, types
from telethon.sessions import StringSession
from telethon.utils import pack_bot_file_id
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
    SESSION_STRING, 
    DEFAULT_TARGET_CHANNELS, 
    DEFAULT_DESTINATION_BOT,
    AUTO_JOIN_CHANNELS
)
from deepseek_parser import parse_anime_post, decide_inline_action, extract_final_metadata, AnimeRelease
from database import (
    is_already_grabbed, 
    log_release, 
    update_status, 
    get_setting, 
    set_setting,
    get_stats
)
from bot_db_sync import sync_episode_to_bot_database

logger = logging.getLogger("UserbotEngine")

if SESSION_STRING:
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
else:
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
        if "+" in clean_target or "joinchat" in clean_target:
            invite_hash = clean_target.split("+")[-1].split("/")[-1]
            logger.info(f"Yopiq kanalga zayavka/a'zolik yuborilmoqda: hash={invite_hash}")
            try:
                await client(functions.messages.ImportChatInviteRequest(invite_hash))
            except Exception as e:
                logger.warning(f"Zayavka yuborildi yoki kanalga kirilmadi: {e}")
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

async def interact_with_bot_and_grab_video(release: AnimeRelease) -> Tuple[bool, Optional[str]]:
    """
    Begona fan-dub boti bilan KO'P BOSQICHLI (MULTI-TURN) muloqot qiladi:
    1. Obunalar va zayavkalarni yuboradi.
    2. Inline tugmalarni (Fasl, Til, Sifat, Qism) DeepSeek AI orqali bosib boradi.
    3. Videoni sug'urib oladi.
    4. Xabarlar va video sarlavhasidan animening haqiqiy nomini aniqlaydi.
    5. Ikkala bot bazasiga (aniriouz va nokori_go) avtomatik qo'shadi!
    6. Shaxsiy botingizga hisobot bilan uzatadi.
    """
    bot = release.bot_username
    start_param = release.start_param
    dest_bot = get_current_destination_bot()
    
    logger.info(f"🤖 Begona botga so'rov yuborilmoqda: {bot} -> /start {start_param}")
    
    try:
        # 1. Botga /start yuborish
        start_cmd = f"/start {start_param}" if start_param else "/start"
        await client.send_message(bot, start_cmd)
        
        video_message = None
        clicked_history = set()
        dialog_logs = [f"Yuborildi: {start_cmd}"]

        # 2. Ko'p bosqichli AI Avtonom Navigatsiya (7 qadamgacha)
        for turn in range(1, 8):
            await asyncio.sleep(2.5)
            
            recent_msgs = await client.get_messages(bot, limit=5)
            
            # A) Agar video kelgan bo'lsa -> To'xtatish
            for m in recent_msgs:
                if not m.out and (m.video or (m.document and "video" in (m.document.mime_type or ""))):
                    video_message = m
                    break
            
            if video_message:
                logger.info(f"🎉 Video topildi! (Turn {turn})")
                break

            # B) Eng so'nggi bot xabarini tahlil qilish
            latest_bot_msg = None
            for m in recent_msgs:
                if not m.out:
                    latest_bot_msg = m
                    break

            if not latest_bot_msg:
                continue

            bot_text = latest_bot_msg.text or latest_bot_msg.raw_text or ""
            dialog_logs.append(f"Bot xabari: {bot_text}")

            # Majburiy kanallarni topish va a'zo bo'lish
            await extract_and_join_required_channels(latest_bot_msg)

            # Inline tugmalarni tahlil qilish
            if latest_bot_msg.reply_markup and isinstance(latest_bot_msg.reply_markup, ReplyInlineMarkup):
                buttons_list = []
                idx = 0
                for r_idx, row in enumerate(latest_bot_msg.reply_markup.rows):
                    for b_idx, btn in enumerate(row.buttons):
                        if isinstance(btn, KeyboardButtonCallback):
                            buttons_list.append({
                                "index": idx,
                                "text": btn.text,
                                "data": btn.data.decode(errors="ignore") if btn.data else "",
                                "row": r_idx,
                                "col": b_idx
                            })
                            idx += 1

                if buttons_list:
                    btn_texts = [b["text"] for b in buttons_list]
                    dialog_logs.append(f"Mavjud tugmalar: {btn_texts}")

                    decision = await decide_inline_action(
                        target_anime=release.anime_name,
                        target_episode=release.episode,
                        bot_message_text=bot_text,
                        buttons=buttons_list
                    )
                    
                    if decision:
                        chosen_text = decision.get("selected_text")
                        b_idx = decision.get("button_index", 0)
                        reason = decision.get("reason", "")
                        
                        btn_key = f"{latest_bot_msg.id}_{chosen_text}"
                        if btn_key in clicked_history and len(buttons_list) > 1:
                            logger.info(f"Qayta bosilish oldi olindi, navbatdagi tugma bosiladi.")
                            b_idx = (b_idx + 1) % len(buttons_list)
                            chosen_text = buttons_list[b_idx]["text"]

                        clicked_history.add(btn_key)
                        dialog_logs.append(f"Bosildi: {chosen_text}")
                        logger.info(f"🎯 AI Qadami ({turn}): '{chosen_text}' bosilmoqda (Sabab: {reason})")
                        
                        try:
                            await latest_bot_msg.click(text=chosen_text)
                        except Exception as e:
                            logger.warning(f"Matn bo'yicha bosishda xatolik: {e}, index={b_idx} bosilmoqda")
                            try:
                                await latest_bot_msg.click(b_idx)
                            except Exception as ex:
                                logger.error(f"Tugma bosish amalga oshmadi: {ex}")

        if not video_message:
            logger.warning(f"Video fayl kelmadi ({release.anime_name} - {release.episode}-qism)")
            return False, "Video topilmadi yoki bot javob bermadi"

        logger.info(f"✅ Video muvaffaqiyatli qabul qilindi! ID={video_message.id}")

        # 3. Video va butun dialogdan HAQIQIY Anime Nomini aniqlash (DeepSeek Final Metadata)
        video_caption = video_message.text or video_message.raw_text or ""
        final_meta = await extract_final_metadata(
            bot_username=bot,
            start_param=start_param,
            dialog_logs=dialog_logs,
            video_caption=video_caption,
            default_anime=release.anime_name,
            default_ep=release.episode
        )
        logger.info(f"💎 Aniqlandi: {final_meta.anime_name} | {final_meta.season}-mavsum {final_meta.episode}-qism ({final_meta.studio})")

        # 4. Telegram Bot API standartidagi `file_id` ni olish
        bot_file_id = ""
        try:
            bot_file_id = pack_bot_file_id(video_message.media)
            logger.info(f"📦 Telegram Bot File ID: {bot_file_id[:30]}...")
        except Exception as e:
            logger.warning(f"File ID generatsiyasida xatolik: {e}")

        # 5. PostgreSQL bazasiga avtomatik qo'shish (AniRioUz va Nokori-Go)
        db_synced, db_msg, unique_code = sync_episode_to_bot_database(
            anime_name=final_meta.anime_name,
            season=final_meta.season,
            episode_number=final_meta.episode,
            studio=final_meta.studio,
            video_file_id=bot_file_id or str(video_message.id)
        )

        # 6. Videoni shaxsiy botingizga jo'natish
        code_badge = f"\n\n⚡️ **Bazada faollashdi!**\n🆔 Anime Kodi: `#{unique_code}`\n🔢 Qism: `{final_meta.episode}-qism`\n👉 Foydalanuvchilar botda `#{unique_code}` kodini yozib darhol tomosha qila olishadi!" if db_synced else ""
        
        caption = (
            f"🎬 **{final_meta.anime_name}** | {final_meta.season}-Mavsum {final_meta.episode}-Qism\n"
            f"🎙 **Dublyaj:** {final_meta.studio}\n"
            f"🎞 **Sifat:** {final_meta.quality}\n"
            f"{code_badge}\n\n"
            f"📥 Avtomatik yuklandi: {bot}"
        )

        if dest_bot:
            logger.info(f"🚀 Video shaxsiy botingizga yuborilmoqda: {dest_bot}")
            sent = await client.send_file(
                dest_bot,
                video_message.media,
                caption=caption
            )
            update_status(
                final_meta.anime_name, 
                final_meta.season, 
                final_meta.episode, 
                final_meta.studio, 
                "COMPLETED", 
                sent.id
            )
        else:
            update_status(
                final_meta.anime_name, 
                final_meta.season, 
                final_meta.episode, 
                final_meta.studio, 
                "COMPLETED", 
                video_message.id
            )

        return True, f"Muvaffaqiyatli yuklandi va bazaga qo'shildi! (Kod: #{unique_code}, Anime: {final_meta.anime_name})"

    except Exception as e:
        logger.error(f"Bot bilan muloqotda xatolik: {e}", exc_info=True)
        update_status(release.anime_name, release.season, release.episode, release.studio, "FAILED")
        return False, str(e)

async def handle_channel_message(event):
    """Kuzatilayotgan kanallarga yangi post kelganda ishga tushadi."""
    msg = event.message
    text = msg.text or msg.raw_text or ""
    if not text:
        return

    chat = await event.get_chat()
    chat_username = getattr(chat, 'username', str(chat.id))
    
    release = await parse_anime_post(text)
    if not release or not release.is_anime_release:
        return

    logger.info(f"🔥 Yangi reliz aniqlandi: {release.anime_name} - {release.episode}-qism ({release.studio})")

    if is_already_grabbed(release.anime_name, release.season, release.episode, release.studio):
        logger.info(f"⏩ Ushbu qism allaqachon yuklangan: {release.anime_name} Ep {release.episode}")
        return

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

    if release.bot_username:
        await interact_with_bot_and_grab_video(release)

# ==========================================================
# 📱 TELEGRAM ICHIDAN BOSHQARISH BUYRUQLARI (ADMIN COMMANDS)
# ==========================================================
async def handle_admin_commands(event):
    """Foydalanuvchi o'ziga o'zi (Saved Messages) yoki istalgan chatda buyruq berganda."""
    msg = event.message
    text = (msg.text or msg.raw_text or "").strip()
    if not text.startswith("."):
        return

    logger.info(f"⚡️ Admin buyruq qabul qilindi: {text}")
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    async def reply_or_edit(content: str):
        try:
            await msg.edit(content)
        except Exception:
            await msg.reply(content)

    if cmd == ".setbot":
        if not arg:
            await reply_or_edit("❌ Bot nomini kiriting: `.setbot @Tarjima_Animelarrbot`")
            return
        bot_name = arg if arg.startswith("@") else f"@{arg}"
        set_setting("destination_bot", bot_name)
        await reply_or_edit(f"✅ **Qabul qiluvchi bot o'zgartirildi!**\n🤖 Joriy bot: `{bot_name}`\nBarcha yangi videolar endi shu botga boradi.")

    elif cmd == ".bot":
        current_bot = get_current_destination_bot()
        await reply_or_edit(f"🤖 **Joriy qabul qiluvchi bot:** `{current_bot or 'Belgilanmagan'}`\nO'zgartirish: `.setbot @YangiBot`")

    elif cmd == ".addchannel":
        if not arg:
            await reply_or_edit("❌ Kanal nomini kiriting: `.addchannel @amediatarjima`")
            return
        ch_name = arg if arg.startswith("@") else f"@{arg}"
        current = get_monitored_channels()
        if ch_name not in current:
            current.append(ch_name)
            set_setting("target_channels", ",".join(current))
            await reply_or_edit(f"✅ Kanal qo'shildi: `{ch_name}`")
        else:
            await reply_or_edit(f"ℹ️ Ushbu kanal allaqachon bor: `{ch_name}`")

    elif cmd == ".delchannel":
        if not arg:
            await reply_or_edit("❌ O'chiriladigan kanalni kiriting: `.delchannel @amediatarjima`")
            return
        ch_name = arg if arg.startswith("@") else f"@{arg}"
        current = get_monitored_channels()
        if ch_name in current:
            current.remove(ch_name)
            set_setting("target_channels", ",".join(current))
            await reply_or_edit(f"🗑 Kanal o'chirildi: `{ch_name}`")
        else:
            await reply_or_edit(f"❌ Kanal topilmadi: `{ch_name}`")

    elif cmd == ".channels":
        channels = get_monitored_channels()
        ch_list = "\n".join([f"  • `{c}`" for c in channels]) if channels else "Kanal kiritilmagan."
        await reply_or_edit(f"📢 **Kuzatilayotgan Kanallar:**\n{ch_list}\n\nQo'shish: `.addchannel @kanal`\nO'chirish: `.delchannel @kanal`")

    elif cmd == ".status":
        stats = get_stats()
        current_bot = get_current_destination_bot()
        channels = get_monitored_channels()
        status_text = (
            "📊 **Anime AI Auto-Grabber Holati:**\n\n"
            f"🤖 **Qabul qiluvchi Bot:** `{current_bot or 'Belgilanmagan'}`\n"
            f"📢 **Kuzatuvdagi Kanallar:** `{len(channels)} ta`\n"
            f"✅ **Bazasiga Yuklangan:** `{stats['completed']} ta qism`\n"
            f"⏳ **Jarayonda:** `{stats['pending']} ta`\n"
            f"❌ **Xatolik:** `{stats['failed']} ta`\n\n"
            "🟢 Tizim 24/7 faol ishlamoqda."
        )
        await reply_or_edit(status_text)

    elif cmd == ".grab":
        if not arg:
            await reply_or_edit("❌ Havolani kiriting: `.grab https://t.me/amediatarjima_bot?start=jjk18`")
            return
        
        await reply_or_edit(f"⏳ **AI Avtonom Yuklash Boshlandi...**\n🔗 Havola: `{arg}`\n\n🧠 DeepSeek AI havolani tahlil qilmoqda...")
        
        release = await parse_anime_post(f"Anime yuklash: {arg}")
        if release and release.bot_username:
            await reply_or_edit(
                f"⏳ **AI Avtonom Yuklash:**\n"
                f"🤖 Bot: `{release.bot_username}`\n"
                f"🕹 Inline tugmalar va obunalar tekshirilmoqda..."
            )
            
            success, message = await interact_with_bot_and_grab_video(release)
            if success:
                await reply_or_edit(
                    f"🎉 **Muvaffaqiyatli Yakunlandi!**\n\n"
                    f"📦 **Holat:** {message}\n"
                    f"🤖 **Yetkazildi:** `{get_current_destination_bot()}`"
                )
            else:
                await reply_or_edit(f"❌ **Yuklashda xatolik:** {message}")
        else:
            await reply_or_edit("❌ Havoladan bot ma'lumotlari aniqlanmadi. Iltimos to'g'ri `t.me/bot?start=xxx` havolasini yuboring.")

    elif cmd == ".help":
        help_text = (
            "🛠 **Anime AI Grabber Telegram Buyruqlari:**\n\n"
            "• `.grab <havola>` — Istalgan bot havolasini avtonom yuklash va bazaga qo'shish\n"
            "• `.setbot @BotNomi` — Videolar borishi kerak bo'lgan botni o'zgartirish\n"
            "• `.bot` — Joriy qabul qiluvchi botni ko'rish\n"
            "• `.channels` — Kuzatilayotgan kanallar ro'yxati\n"
            "• `.addchannel @Kanal` — Yangi fan-dub kanal qo'shish\n"
            "• `.delchannel @Kanal` — Kanalni ro'yxatdan o'chirish\n"
            "• `.status` — Tizim statistikasi va holati\n"
            "• `.help` — Ushbu yordam oynasi"
        )
        await reply_or_edit(help_text)
