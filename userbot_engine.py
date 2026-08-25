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
    MessageMediaDocument,
    MessageEntityTextUrl,
    MessageEntityUrl
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
from deepseek_parser import (
    parse_anime_post, 
    decide_inline_action, 
    match_anime_with_existing, 
    extract_all_episode_buttons_from_menu,
    AnimeRelease
)
from database import (
    is_already_grabbed, 
    log_release, 
    update_status, 
    get_setting, 
    set_setting,
    get_stats
)
from bot_db_sync import (
    sync_episode_to_bot_database, 
    get_existing_animes_list
)
from destination_bot_admin import upload_episode_via_admin_flow

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

def extract_all_links_and_entities_from_msg(msg: types.Message) -> str:
    """Kanal postidagi barcha yashirin havolalar, matn va inline tugmalarni birlashtiradi."""
    combined_texts = [msg.text or msg.raw_text or ""]
    
    if msg.entities:
        for ent in msg.entities:
            if isinstance(ent, MessageEntityTextUrl) and ent.url:
                combined_texts.append(f"Havola: {ent.url}")
            elif isinstance(ent, MessageEntityUrl):
                offset = ent.offset
                length = ent.length
                text_content = msg.raw_text or msg.text or ""
                url_snippet = text_content[offset:offset+length]
                if url_snippet:
                    combined_texts.append(f"Havola: {url_snippet}")

    if msg.reply_markup and isinstance(msg.reply_markup, ReplyInlineMarkup):
        for row in msg.reply_markup.rows:
            for btn in row.buttons:
                if isinstance(btn, KeyboardButtonUrl) and btn.url:
                    combined_texts.append(f"Tugma: '{btn.text}' -> {btn.url}")
                elif isinstance(btn, KeyboardButtonCallback):
                    data_str = btn.data.decode(errors="ignore") if btn.data else ""
                    combined_texts.append(f"Tugma: '{btn.text}' (data={data_str})")

    return "\n".join(combined_texts)

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

async def process_single_video_message(
    video_message: types.Message,
    dialog_logs: List[str],
    source_bot: str,
    dest_bot: str
) -> Tuple[bool, str]:
    """
    Qabul qilingan bitta videoni qat'iy AI tahlildan o'tkazib,
    to'g'ri animega biriktiradi va /admin inline orqali botga yuklaydi.
    """
    try:
        video_caption = video_message.text or video_message.raw_text or ""
        existing_animes = get_existing_animes_list()

        # 1. Qat'iy semantik taqqoslash (Boshqa animega qo'shib yubormaslik kafolati)
        match_res = await match_anime_with_existing(
            video_caption=video_caption,
            dialog_logs=dialog_logs,
            existing_animes=existing_animes
        )

        anime_title = match_res.get("clean_title", "Anime")
        season = match_res.get("season", 1)
        episode_num = match_res.get("episode", 1)
        studio = match_res.get("studio", "UzDub")
        quality = match_res.get("quality", "720p")
        matched_unique_id = match_res.get("matched_unique_id")

        logger.info(f"💎 Semantik Tahlil: '{anime_title}' | {season}-mavsum {episode_num}-qism (Match ID: {matched_unique_id})")

        # 2. File ID olish
        bot_file_id = ""
        try:
            bot_file_id = pack_bot_file_id(video_message.media)
        except Exception:
            pass

        # 3. PostgreSQL bazalariga yozish
        db_ok, db_msg, unique_code = sync_episode_to_bot_database(
            anime_name=anime_title,
            season=season,
            episode_number=episode_num,
            studio=studio,
            video_file_id=bot_file_id or str(video_message.id),
            matched_unique_id=matched_unique_id
        )

        release_obj = AnimeRelease(
            is_anime_release=True,
            anime_name=anime_title,
            season=season,
            episode=episode_num,
            studio=studio,
            quality=quality,
            bot_username=source_bot
        )

        # 4. /admin inline orqali shaxsiy botga joylash
        if dest_bot:
            logger.info(f"🚀 {dest_bot} ga /admin inline orqali qism yuklanmoqda (#{unique_code} - {episode_num}-qism)...")
            await upload_episode_via_admin_flow(
                client=client,
                dest_bot=dest_bot,
                release=release_obj,
                unique_code=unique_code or 1,
                video_message=video_message
            )

        update_status(anime_title, season, episode_num, studio, "COMPLETED", video_message.id)
        return True, f"✅ {anime_title} {episode_num}-qism yuklandi! (Kod: #{unique_code})"

    except Exception as e:
        logger.error(f"process_single_video_message xatosi: {e}", exc_info=True)
        return False, str(e)

async def interact_with_bot_and_grab_all_episodes(release: AnimeRelease) -> Tuple[bool, str]:
    """
    Begona botdan BITTA EMAS, BARCHA MAVJUD QISMLARNI avtomat tarzda tortib oladi.
    """
    bot = release.bot_username
    start_param = release.start_param
    dest_bot = get_current_destination_bot()
    
    logger.info(f"🤖 Begona botga so'rov yuborilmoqda: {bot} -> /start {start_param}")
    
    try:
        start_cmd = f"/start {start_param}" if start_param else "/start"
        await client.send_message(bot, start_cmd)
        
        dialog_logs = [f"Yuborildi: {start_cmd}"]
        clicked_history = set()
        processed_video_ids = set()
        total_grabbed = 0

        for turn in range(1, 10):
            await asyncio.sleep(2.5)
            
            recent_msgs = await client.get_messages(bot, limit=8)
            
            # A) Kelgan barcha yangi videolarni qayta ishlash
            new_videos = []
            for m in recent_msgs:
                if not m.out and (m.video or (m.document and "video" in (m.document.mime_type or ""))):
                    if m.id not in processed_video_ids:
                        new_videos.append(m)
                        processed_video_ids.add(m.id)

            if new_videos:
                logger.info(f"🎉 {len(new_videos)} ta yangi video topildi! (Turn {turn})")
                for v in new_videos:
                    ok, res_str = await process_single_video_message(v, dialog_logs, bot, dest_bot)
                    if ok:
                        total_grabbed += 1
                    await asyncio.sleep(1.5)

            # B) Botning so'nggi xabarini tahlil qilish
            latest_bot_msg = None
            for m in recent_msgs:
                if not m.out and m.reply_markup:
                    latest_bot_msg = m
                    break

            if not latest_bot_msg:
                continue

            bot_text = latest_bot_msg.text or latest_bot_msg.raw_text or ""
            dialog_logs.append(f"Bot xabari: {bot_text}")

            await extract_and_join_required_channels(latest_bot_msg)

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
                    # 1. Barcha qismlar tugmalari bormi tekshirish
                    ep_buttons = await extract_all_episode_buttons_from_menu(buttons_list)
                    
                    if ep_buttons and len(ep_buttons) > 1:
                        logger.info(f"📋 Topilgan qismlar soni: {len(ep_buttons)} ta. Hammasi ketma-ket yuklanadi...")
                        for ep_b in ep_buttons:
                            b_text = ep_b["text"]
                            logger.info(f"👉 Bosilmoqda: '{b_text}'...")
                            try:
                                await latest_bot_msg.click(text=b_text)
                            except Exception:
                                try:
                                    await latest_bot_msg.click(ep_b["index"])
                                except Exception:
                                    pass

                            # Videoni kutish (15s)
                            for _ in range(12):
                                await asyncio.sleep(1.5)
                                ms = await client.get_messages(bot, limit=3)
                                for vm in ms:
                                    if not vm.out and (vm.video or (vm.document and "video" in (vm.document.mime_type or ""))):
                                        if vm.id not in processed_video_ids:
                                            processed_video_ids.add(vm.id)
                                            ok, res_str = await process_single_video_message(vm, dialog_logs, bot, dest_bot)
                                            if ok:
                                                total_grabbed += 1
                                            break
                        break

                    # 2. Agar yakka bosqichli menyu bo'lsa (Fasl/Til/Sifat)
                    decision = await decide_inline_action(
                        target_anime=release.anime_name,
                        target_episode=release.episode,
                        bot_message_text=bot_text,
                        buttons=buttons_list
                    )
                    
                    if decision:
                        chosen_text = decision.get("selected_text")
                        b_idx = decision.get("button_index", 0)
                        
                        btn_key = f"{latest_bot_msg.id}_{chosen_text}"
                        if btn_key in clicked_history and len(buttons_list) > 1:
                            b_idx = (b_idx + 1) % len(buttons_list)
                            chosen_text = buttons_list[b_idx]["text"]

                        clicked_history.add(btn_key)
                        dialog_logs.append(f"Bosildi: {chosen_text}")
                        logger.info(f"🎯 AI Qadami ({turn}): '{chosen_text}' bosilmoqda...")
                        
                        try:
                            await latest_bot_msg.click(text=chosen_text)
                        except Exception as e:
                            try:
                                await latest_bot_msg.click(b_idx)
                            except Exception:
                                pass

        if total_grabbed > 0:
            return True, f"Jami {total_grabbed} ta qism muvaffaqiyatli yuklandi va botga qo'shildi!"
        elif len(processed_video_ids) > 0:
            return True, "Videolar muvaffaqiyatli qabul qilindi va botga uzatildi!"
        else:
            return False, "Botdan video kelmadi yoki qismlar topilmadi"

    except Exception as e:
        logger.error(f"interact_with_bot_and_grab_all_episodes xatosi: {e}", exc_info=True)
        return False, str(e)

async def handle_channel_message(event):
    """Kuzatilayotgan kanallarga yangi post kelganda ishga tushadi."""
    msg = event.message
    
    full_content = extract_all_links_and_entities_from_msg(msg)
    if not full_content:
        return

    chat = await event.get_chat()
    chat_username = getattr(chat, 'username', str(chat.id))
    chat_title = getattr(chat, 'title', 'Kanal')
    
    logger.info(f"📢 Kanalda yangi post aniqlandi: '{chat_title}' (@{chat_username})")

    release = await parse_anime_post(full_content)
    if not release or not release.is_anime_release:
        return

    logger.info(f"🔥 Yangi reliz: {release.anime_name} ({release.studio}) -> Bot: {release.bot_username}")

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
        await interact_with_bot_and_grab_all_episodes(release)

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
            await reply_or_edit("❌ Bot nomini kiriting: `.setbot @NokoriUzBot`")
            return
        bot_name = arg if arg.startswith("@") else f"@{arg}"
        set_setting("destination_bot", bot_name)
        await reply_or_edit(f"✅ **Qabul qiluvchi bot o'zgartirildi!**\n🤖 Joriy bot: `{bot_name}`\nBarcha yangi videolar endi shu botga boradi.")

    elif cmd == ".bot":
        current_bot = get_current_destination_bot()
        await reply_or_edit(f"🤖 **Joriy qabul qiluvchi bot:** `{current_bot or 'Belgilanmagan'}`\nO'zgartirish: `.setbot @YangiBot`")

    elif cmd == ".addchannel":
        if not arg:
            await reply_or_edit("❌ Kanal nomini kiriting: `.addchannel @Uzbekcha_Animelare`")
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
            await reply_or_edit("❌ O'chiriladigan kanalni kiriting: `.delchannel @kanal`")
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
        ch_str = ", ".join(channels) if channels else "yo'q"
        status_text = (
            "📊 **Anime AI Auto-Grabber Holati:**\n\n"
            f"🤖 **Qabul qiluvchi Bot:** `{current_bot or 'Belgilanmagan'}`\n"
            f"📢 **Kuzatuvdagi Kanallar:** `{len(channels)} ta` ({ch_str})\n"
            f"✅ **Bazasiga Yuklangan:** `{stats['completed']} ta qism`\n"
            f"⏳ **Jarayonda:** `{stats['pending']} ta`\n"
            f"❌ **Xatolik:** `{stats['failed']} ta`\n\n"
            "🟢 Tizim 24/7 faol ishlamoqda."
        )
        await reply_or_edit(status_text)

    elif cmd == ".grab":
        if not arg:
            await reply_or_edit("❌ Havolani kiriting: `.grab https://t.me/AniMacUzbot?start=down_11`")
            return
        
        await reply_or_edit(f"⏳ **AI Avtonom Yuklash Boshlandi...**\n🔗 Havola: `{arg}`\n\n🧠 DeepSeek AI barcha qismlarni va inlinelarni tahlil qilmoqda...")
        
        release = await parse_anime_post(f"Anime yuklash: {arg}")
        if release and release.bot_username:
            await reply_or_edit(
                f"⏳ **AI Batch Yuklash Jarayonda:**\n"
                f"🤖 Bot: `{release.bot_username}`\n"
                f"🕹 Barcha qismlar ketma-ket yuklanmoqda va tahlil qilinmoqda..."
            )
            
            success, message = await interact_with_bot_and_grab_all_episodes(release)
            if success:
                await reply_or_edit(
                    f"🎉 **Muvaffaqiyatli Yakunlandi!**\n\n"
                    f"📦 **Natija:** {message}\n"
                    f"🤖 **Yetkazildi:** `{get_current_destination_bot()}`"
                )
            else:
                await reply_or_edit(f"❌ **Yuklashda xatolik:** {message}")
        else:
            await reply_or_edit("❌ Havoladan bot ma'lumotlari aniqlanmadi. Iltimos to'g'ri `t.me/bot?start=xxx` havolasini yuboring.")

    elif cmd == ".help":
        help_text = (
            "🛠 **Anime AI Grabber Telegram Buyruqlari:**\n\n"
            "• `.grab <havola>` — Istalgan bot havolasidagi barcha qismlarni avtonom yuklash va bazaga qo'shish\n"
            "• `.setbot @BotNomi` — Videolar borishi kerak bo'lgan botni o'zgartirish\n"
            "• `.bot` — Joriy qabul qiluvchi botni ko'rish\n"
            "• `.channels` — Kuzatilayotgan kanallar ro'yxati\n"
            "• `.addchannel @Kanal` — Yangi fan-dub kanal qo'shish\n"
            "• `.delchannel @Kanal` — Kanalni ro'yxatdan o'chirish\n"
            "• `.status` — Tizim statistikasi va holati\n"
            "• `.help` — Ushbu yordam oynasi"
        )
        await reply_or_edit(help_text)
EOF
