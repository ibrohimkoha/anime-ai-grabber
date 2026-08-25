# 🎬 Anime AI Auto-Grabber (Telegram MTProto + DeepSeek AI)

Ushbu tizim O'zbekistondagi fan-dub kanallari yangi anime qismini chiqarganda, postni **DeepSeek AI** orqali tahlil qilib, **Telegram Userbot (Telethon)** orqali avtomatik tarzda begona botga kirib, barcha majburiy obuna/zayavkalarni yuborib, videoni sug'urib oladi va to'g'ridan-to'g'ri **O'ZINGIZNING BOTINGIZGA** jo'natadi!

---

## 📱 Telegram Ichidan Boshqarish (Admin Buyruqlari):

Siz serverga kirmasdan, shunchaki telefoningizdagi Telegram orqali (o'zingizga yoki istalgan chatga) quyidagi buyruqlarni yuborib tizimni to'liq boshqara olasiz:

| Buyruq | Tavsif | Misol |
|---|---|---|
| `.setbot @BotNomi` | Videolar tushadigan botni bir zumda o'zgartirish | `.setbot @Tarjima_Animelarrbot` |
| `.bot` | Hozir qaysi botga video tushayotganini ko'rish | `.bot` |
| `.addchannel @Kanal` | Yangi kuzatiladigan fan-dub kanal qo'shish | `.addchannel @amediatarjima` |
| `.delchannel @Kanal` | Kanalni kuzatuvdan o'chirish | `.delchannel @amediatarjima` |
| `.channels` | Barcha kuzatilayotgan kanallar ro'yxati | `.channels` |
| `.status` | Tizim statistikasi (yuklangan qismlar soni) | `.status` |
| `.grab <havola>` | Istalgan bot havolasini qo'lda zudlik bilan yuklash | `.grab https://t.me/bot?start=123` |
| `.help` | Barcha buyruqlar ro'yxati | `.help` |

---

## 🌟 Imkoniyatlari:
1. **To'g'ridan-to'g'ri Botingizga Yuklash:** Video begona botdan olinib, darhol o'zingizning shaxsiy botingizga (`@Tarjima_Animelarrbot` yoki boshqa) jo'natiladi. Botingiz esa videoni qabul qilib, o'z bazasiga saqlab oladi.
2. **Zero-Error Parsing (DeepSeek AI):** Kanallar qanday chalkash yozishidan qat'i nazar (KNY, JJK, qisqartmalar), DeepSeek anime nomi, qismi, fasli, studiyasi va bot havolasini 100% aniqlaydi.
3. **Avto-Obuna & Zayavka (Join Request):** Begona bot majburiy kanal yoki yopiq zayavka kanallarini chiqarsa, userbot ularga avtomatik a'zo bo'ladi va zayavka tashlaydi.
4. **Aqlli Tugma Bosish:** "✅ Obunani tekshirish" yoki sifat tanlash tugmalarini DeepSeek AI orqali aniqlab avtomatik bosadi.
5. **2GB gacha Katta Videolarni Qabul Qilish:** MTProto protokoli orqali 2000 MB gacha bo'lgan videolarni cheklovlarsiz oladi.
6. **Takrorlanishdan Himoya (SQLite Database):** Bir marta yuklangan qism qayta yuklanmaydi.

---

## 🚀 Ishga Tushirish:

1. `.env` fayliga `TELEGRAM_API_ID` va `TELEGRAM_API_HASH` ni kiriting ([my.telegram.org](https://my.telegram.org)).
2. Tizimni ishga tushiring:
```bash
venv/bin/python main.py
```
3. Telegramingizdan `.setbot @Botingiz` deb yozsangiz, barcha videolar avtomatik ravishda o'sha botingizga boradi!
