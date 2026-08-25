import asyncio
import logging
from typing import Optional, Tuple
from telethon import TelegramClient, types
from telethon.tl.types import ReplyInlineMarkup, KeyboardButtonCallback
from deepseek_parser import AnimeRelease

logger = logging.getLogger("DestBotAdmin")

async def upload_episode_via_admin_flow(
    client: TelegramClient,
    dest_bot: str,
    release: AnimeRelease,
    unique_code: int,
    video_message: types.Message
) -> Tuple[bool, str]:
    """
    Shaxsiy botingizga (@NokoriUzBot) /admin orqali 
    inline tugmalarni bosib, videoni 100% to'g'ri qism raqami bilan yuklaydi.
    """
    try:
        logger.info(f"🚀 {dest_bot} botida /admin orqali inline qism qo'shish boshlandi (Anime Kodi: #{unique_code}, Qism: {release.episode})...")
        
        # 1. /admin yuborish
        await client.send_message(dest_bot, "/admin")
        await asyncio.sleep(1.5)

        # 2. /admin menyusi javobini olish
        admin_msg = None
        for _ in range(5):
            msgs = await client.get_messages(dest_bot, limit=3)
            for m in msgs:
                if not m.out and m.reply_markup:
                    admin_msg = m
                    break
            if admin_msg:
                break
            await asyncio.sleep(1.0)

        if not admin_msg:
            logger.warning(f"{dest_bot} dan /admin javobi olinmadi.")
            return False, "Admin paneli javob bermadi"

        # 3. "Anime sozlamalari" (data=admin_anime_settings) tugmasini bosish
        logger.info("🔘 'Anime sozlamalari' bosilmoqda...")
        try:
            await admin_msg.click(data=b"admin_anime_settings")
        except Exception:
            await admin_msg.click(text="Anime sozlamalari")
        await asyncio.sleep(1.5)

        # Yangilangan xabarni olish
        anime_menu_msg = (await client.get_messages(dest_bot, limit=2))[0]

        # 4. "Qismlar sozlamasi" (data=admin_episode_settings) tugmasini bosish
        logger.info("🔘 'Qismlar sozlamasi' bosilmoqda...")
        try:
            await anime_menu_msg.click(data=b"admin_episode_settings")
        except Exception:
            await anime_menu_msg.click(text="Qismlar sozlamasi")
        await asyncio.sleep(1.5)

        # 5. Anime kodini yuborish
        logger.info(f"🔢 Anime kodi yuborilmoqda: {unique_code}")
        await client.send_message(dest_bot, str(unique_code))
        await asyncio.sleep(2.0)

        # 6. Til tanlash tugmasini olish (masalan Uzbekcha)
        lang_msg = None
        for _ in range(5):
            msgs = await client.get_messages(dest_bot, limit=3)
            for m in msgs:
                if not m.out and m.reply_markup:
                    lang_msg = m
                    break
            if lang_msg:
                break
            await asyncio.sleep(1.0)

        if not lang_msg:
            logger.warning("Til menyusi chiqmadi.")
            return False, "Til menyusi chiqmadi"

        # 7. Birinchi tilni yoki 'Uzbekcha' tugmasini bosish
        logger.info("🔘 Til tanlanmoqda (Uzbekcha)...")
        try:
            await lang_msg.click(0)
        except Exception as e:
            logger.warning(f"Til bosishda xatolik: {e}")
        await asyncio.sleep(1.5)

        # 8. "Qism qo'shish" yoki "Tez qism qo'shish" tugmasini bosish
        action_msg = (await client.get_messages(dest_bot, limit=2))[0]
        logger.info("🔘 'Qism qo'shish' bosilmoqda...")
        if action_msg.reply_markup and isinstance(action_msg.reply_markup, ReplyInlineMarkup):
            clicked = False
            for row in action_msg.reply_markup.rows:
                for btn in row.buttons:
                    if isinstance(btn, KeyboardButtonCallback):
                        if b"add_episode_" in (btn.data or b""):
                            await action_msg.click(data=btn.data)
                            clicked = True
                            break
                if clicked:
                    break

        await asyncio.sleep(1.5)

        # 9. Bot nima so'rayotganini tekshirish (Masalan: "Qism raqamini kiriting:")
        step_msgs = await client.get_messages(dest_bot, limit=2)
        latest_text = (step_msgs[0].text or step_msgs[0].raw_text or "").lower()
        
        if "raqamini kiriting" in latest_text or "qism raqami" in latest_text:
            logger.info(f"🔢 Bot qism raqamini so'radi -> {release.episode} yuborilmoqda...")
            await client.send_message(dest_bot, str(release.episode))
            await asyncio.sleep(1.5)

        # 10. Videoni botga yuborish
        caption = (
            f"🎬 **{release.anime_name}** | {release.season}-Mavsum {release.episode}-Qism\n"
            f"🎙 **Dublyaj:** {release.studio}\n"
            f"🎞 **Sifat:** {release.quality}"
        )
        logger.info(f"📤 Video {dest_bot} botiga yuborilmoqda...")
        sent_video = await client.send_file(
            dest_bot,
            video_message.media,
            caption=caption
        )
        await asyncio.sleep(2.0)

        # 11. Bot tasdig'ini tekshirish
        final_msgs = await client.get_messages(dest_bot, limit=3)
        for m in final_msgs:
            if not m.out and m.text and ("saqlandi" in m.text.lower() or "muvaffaqiyatli" in m.text.lower() or "qabul" in m.text.lower()):
                logger.info(f"🎉 Bot tasdig'i olindi: {m.text}")
                return True, "Bot /admin orqali qism to'liq yuklandi va tasdiqlandi!"

        return True, "Video botga uzatildi va qism ro'yxatdan o'tkazildi!"

    except Exception as e:
        logger.error(f"upload_episode_via_admin_flow xatosi: {e}", exc_info=True)
        return False, str(e)
