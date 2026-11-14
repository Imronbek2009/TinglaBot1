import html
import re

TEXT_DEFINITIONS: dict[str, tuple[str, str, str]] = {
    "txt_start": (
        "👋 /start salomlashish matni",
        "{name} - Foydalanuvchi ismi",
        "👋 <b>Assalomu alaykum, {name}!</b>\n\n"
        "🚀 <b>Tingla — Universal Media, Story va Shazam Botga xush kelibsiz!</b>\n\n"
        "✨ <b>Botning asosiy imkoniyatlari:</b>\n"
        "  📸 <b>Instagram va Telegram Story:</b> Link shart emas — shunchaki <code>@username</code> yuboring (yoki Telegram storyni botga ulashing)!\n"
        "  🎵 <b>Shazam (Original qo'shiq topish):</b> Instagram, TikTok yoki YouTube videodagi qo'shiqni Shazam orqali tanib, <b>to'liq original MP3</b> variantini topib beradi!\n"
        "  🎬 <b>2 GB (2000 MB) gacha Video yuklash:</b> YouTube, Instagram, TikTok, Pinterest va boshqa tarmoqlardan suv belgisiz HD videolarni yuklaydi.\n\n"
        "🔗 <b>Boshlash uchun video havolasini (link) yoki <code>@username</code> yuboring!</b>"
    ),
    "txt_force_sub": (
        "🔒 Majburiy obuna xabari",
        "O'zgaruvchilar yo'q",
        "🔒 <b>Botdan to'liq va bepul foydalanish uchun quyidagi rasmiy kanallarimizga obuna bo'ling:</b>\n\n"
        "👇 Kanallarga a'zo bo'lgach, <b>«✅ Obuna bo'ldim»</b> tugmasini bosing:"
    ),
    "txt_sub_confirmed": (
        "🎉 Obuna tasdiqlangandagi xabar",
        "O'zgaruvchilar yo'q",
        "🎉 <b>Obunangiz tasdiqlandi!</b>\nEndi menga video havolasini yoki <code>@username</code> yuborishingiz mumkin."
    ),
    "txt_stories_menu": (
        "📸 Story ko'rish bo'limi matni",
        "O'zgaruvchilar yo'q",
        "📸 <b>USERNAME ORQALI STORY YUKLASH</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Story havolasini qidirib o'tirishingiz shart emas! Shunchaki foydalanuvchining <b>@username</b> nomini yuboring:\n\n"
        "📸 <b>Instagram Story:</b> <code>@username</code> (masalan: <code>@cristiano</code>).\n"
        "✈️ <b>Telegram Story:</b> <code>@username</code> (masalan: <code>@durov</code>) yoki storyni to'g'ridan-to'g'ri botga <b>Share (Forward)</b> qiling!\n\n"
        "👇 <b>Qaysi tarmoqdan Story yuklaymiz? Tanlang:</b>"
    ),
    "txt_ig_story_prompt": (
        "📸 Instagram Story so'rash matni",
        "O'zgaruvchilar yo'q",
        "📸 <b>INSTAGRAM STORY (@USERNAME ORQALI)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Instagram foydalanuvchisining <b>username</b> nomini yozib yuboring:\n"
        "👉 Masalan: <code>@cristiano</code> yoki <code>cristiano</code>"
    ),
    "txt_tg_story_prompt": (
        "✈️ Telegram Story so'rash matni",
        "O'zgaruvchilar yo'q",
        "✈️ <b>TELEGRAM STORY (@USERNAME YOKI FORWARD)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "1️⃣ Telegram kanal yoki foydalanuvchining <b>@username</b> nomini yozing (masalan: <code>@durov</code>);\n"
        "2️⃣ Yoki Telegram ichida istalgan storyni ko'rayotganingizda <b>«Ulashish (Share)»</b> tugmasini bosib, ushbu botga yuboring!"
    ),
    "txt_music_prompt": (
        "🎵 Qo'shiq qidirish bo'limi matni",
        "O'zgaruvchilar yo'q",
        "🎵 <b>QO'SHIQ YOKI KLIP QIDIRISH</b>\n\n"
        "🔎 Ijrochi yoki qo'shiq nomini yozib yuboring (masalan: <i>Konsta - Odamlar nima deydi</i>):"
    ),
    "txt_platforms": (
        "🔥 Platformalar bo'limi matni",
        "O'zgaruvchilar yo'q",
        "🌐 <b>QO'LLAB-QUVVATLANADIGAN PLATFORMALAR VA IMKONIYATLAR</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📸 <b>Instagram:</b> Reels, Postlar + <code>@username</code> orqali Story'lar\n"
        "✈️ <b>Telegram Story:</b> <code>@username</code> yoki Forward orqali Story video va rasmlar\n"
        "🎵 <b>TikTok:</b> Suv belgisiz (No Watermark) HD video va musiqa\n"
        "▶️ <b>YouTube:</b> 2 GB gacha Video, Shorts va MP3 audio\n"
        "🎵 <b>Shazam funksiyasi:</b> Videodagi qo'shiqni tanib, <b>Original to'liq MP3</b> ni topib berish\n"
        "📌 <b>Pinterest, Facebook, X (Twitter), Likee, Threads</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 <i>Maslahat: Chatga shunchaki <code>@username</code> yozsangiz ham Story yuklash tugmalari avtomatik chiqadi!</i>"
    ),
    "txt_profile": (
        "💼 Mening hisobim (Kabinet) matni",
        "{user_id}, {full_name}, {status}, {downloads_count}, {limit_str}, {mode_str}, {joined_at}",
        "💼 <b>SHAXSIY KABINETINGIZ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🆔 <b>ID raqamingiz:</b> <code>{user_id}</code>\n"
        "👤 <b>Ismingiz:</b> {full_name}\n"
        "🌟 <b>Maqomingiz:</b> {status}\n"
        "📥 <b>Jami yuklagan medialaringiz:</b> {downloads_count} ta\n"
        "📊 <b>Bugungi yuklamalar:</b> {limit_str}\n"
        "📦 <b>Maksimal fayl hajmi:</b> 2 GB (2000 MB)\n"
        "⚙️ <b>Yuklash rejimi:</b> {mode_str}\n"
        "📅 <b>Ro'yxatdan o'tgan sana:</b> {joined_at}"
    ),
    "txt_settings": (
        "⚙️ Sozlamalar bo'limi matni",
        "O'zgaruvchilar yo'q",
        "⚙️ <b>YUKLASH REJIMINI SOZLASH</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ <b>Avtomatik rejim:</b> Havola yuborishingiz bilan darhol videoni yuklab beradi va ostida <i>«🎵 Original qo'shiqni topish (Shazam)»</i> tugmasini chiqaradi.\n\n"
        "🎛 <b>Tanlash orqali:</b> Havola yuborganingizda avval video haqida ma'lumot va <i>HD (2GB) / 480p / Shazam / Muqova</i> tugmalarini chiqaradi."
    ),
    "txt_history": (
        "📂 Yuklamalar tarixi matni",
        "O'zgaruvchilar yo'q",
        "📂 <b>OXIRGI 10 TA YUKLAGAN MEDIALARINGIZ:</b>\n"
        "<i>Qayta yuklab olish uchun ustiga bosing (0.5 soniyada keshdan yuboriladi):</i>"
    ),
    "txt_history_empty": (
        "📂 Tarix bo'sh bo'lgandagi matn",
        "O'zgaruvchilar yo'q",
        "📂 <b>Sizda hozircha yuklamalar tarixi mavjud emas.</b>\nBiror video havolasini yuborib ko'ring!"
    ),
    "txt_favorites": (
        "❤️ Saqlanganlar bo'limi matni",
        "O'zgaruvchilar yo'q",
        "❤️ <b>SAQLANGAN SEVIMLI MEDIALARINGIZ:</b>\n"
        "<i>Ko'rish uchun nomiga bosing yoki 🗑 orqali o'chiring:</i>"
    ),
    "txt_favorites_empty": (
        "❤️ Saqlanganlar bo'sh bo'lgandagi matn",
        "O'zgaruvchilar yo'q",
        "❤️ <b>Saqlangan sevimli medialaringiz ro'yxati bo'sh.</b>\n\n"
        "Videolarni yuklab olganingizda ularning ostidagi <b>«❤️ Saqlash»</b> tugmasi orqali shu yerga saqlab qo'yishingiz mumkin!"
    ),
    "txt_help": (
        "ℹ️ Yordam bo'limi matni",
        "O'zgaruvchilar yo'q",
        "ℹ️ <b>BOTDAN FOYDALANISH QO'LLANMASI</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "1️⃣ <b>2 GB gacha Video va Rasm yuklash:</b> Instagram, TikTok, YouTube, Pinterest yoki boshqa tarmoqdan havolani nusxalab, botga yuboring.\n\n"
        "2️⃣ <b>Username orqali Story ko'rish:</b> <b>«📸 Story ko'rish»</b> tugmasini bosing yoki chatning o'ziga <code>@username</code> yozib yuboring!\n\n"
        "3️⃣ <b>Shazam (Original qo'shiqni topish):</b> Video yuklangach, uning pastidagi <b>«🎵 Original qo'shiqni topish (Shazam)»</b> tugmasini bosing — bot videodagi musiqani tanib, uning to'liq original MP3 variantini yuklab beradi! Shuningdek, botga ovozli xabar yuborib ham qo'shiq qidirishingiz mumkin.\n\n"
        "4️⃣ <b>Nomi bo'yicha qo'shiq qidirish:</b> <b>«🎵 Qo'shiq qidirish»</b> tugmasini bosib, qo'shiqchi yoki tarona nomini yozing."
    ),
    "txt_invalid_input": (
        "🔗 Noto'g'ri xabar yuborilgandagi matn",
        "O'zgaruvchilar yo'q",
        "🔗 <b>Iltimos, menga video havolasini (link) yoki Story ko'rish uchun <code>@username</code> yuboring!</b>\n\n"
        "📸 Story ko'rish yoki 🎵 Qo'shiq qidirish uchun pastdagi tugmalardan ham foydalanishingiz mumkin."
    ),
    "txt_downloading": (
        "⏳ Yuklanmoqda (Progress) matni",
        "{icon}, {platform}",
        "{icon} <b>{platform}</b> dan media yuklab olinmoqda...\n"
        "📥 <i>Yuqori sifatli oqim tortilmoqda...</i>\n"
        "<code>[██████░░░░] 65%</code>"
    ),
    "txt_shazam_searching": (
        "🔍 Shazam qidiruv matni",
        "O'zgaruvchilar yo'q",
        "🔍 🎵 <b>Shazam:</b> Videodagi musiqa tinglanmoqda va original qo'shiq qidirilmoqda...\n"
        "<code>[████░░░░░░] 45%</code>"
    ),
    "txt_shazam_not_found": (
        "❌ Shazam topa olmagandagi matn",
        "O'zgaruvchilar yo'q",
        "❌ <b>Kechirasiz, ushbu videodan aniq qo'shiq nomini aniqlab bo'lmadi.</b>\n"
        "Videoning o'z ovozini olish uchun <b>«🔊 Video ovozi (MP3)»</b> tugmasini bosishingiz mumkin."
    ),
    "txt_error_download": (
        "❌ Yuklashda xatolik matni",
        "{error} - Xatolik tafsiloti",
        "❌ <b>Yuklab olishda xatolik yuz berdi!</b>\n\n"
        "🔍 <b>Sabablar bo'lishi mumkin:</b>\n"
        "• Profil yopiq (Private) yoki havola noto'g'ri;\n"
        "• Texnik ma'lumot: <code>{error}</code>"
    ),
    "txt_daily_limit_reached": (
        "⚠️ Kunlik limit tugagandagi matn",
        "{limit} - Kunlik limit soni",
        "⚠️ <b>Siz bugungi bepul yuklash limitiga ({limit} ta) yetdingiz!</b>\n"
        "Ertaga yana davom etishingiz yoki cheklovsiz VIP olish uchun adminga murojaat qilishingiz mumkin."
    ),
    "txt_maintenance": (
        "🛠 Texnik ishlar rejimi matni",
        "O'zgaruvchilar yo'q",
        "🛠 <b>Botda hozir texnik profilaktika ishlari olib borilmoqda!</b>\n\n"
        "⏳ Tez orada yanada tez va sifatli holatda ishga tushamiz. Iltimos, birozdan so'ng urinib ko'ring."
    ),
    "txt_banned": (
        "🚫 Bloklangan foydalanuvchi matni",
        "O'zgaruvchilar yo'q",
        "🚫 <b>Sizning hisobingiz admin tomonidan bloklangan!</b>"
    ),
    "txt_section_disabled": (
        "🔒 Bo'lim o'chirilgandagi matn",
        "O'zgaruvchilar yo'q",
        "⚠️ <b>Ushbu bo'lim hozirda admin tomonidan vaqtincha o'chirilgan!</b>"
    ),
    "watermark": (
        "📝 Video/Audio osti matni (Watermark)",
        "O'zgaruvchilar yo'q",
        "@tingla_officialbot orqali yuklab olindi 📥"
    ),
}


def safe_format_html(template: str, **kwargs) -> str:
    result = template
    for k, v in kwargs.items():
        safe_val = html.escape(str(v if v is not None else ""))
        result = result.replace("{" + k + "}", safe_val)
    return result


def strip_html_tags(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"<[^>]+>", "", text)
    return html.unescape(cleaned)
